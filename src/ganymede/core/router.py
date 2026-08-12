import asyncio
import time
from typing import Any
import structlog
import json
from google.antigravity.types import ToolResult
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
from ganymede.config import AppConfig

logger = structlog.get_logger()

class Router:
    def __init__(self, config: AppConfig, agent_manager: Any = None, activation_check: Any = None, db: Any = None):
        self.config = config
        self.agent_manager = agent_manager
        self.activation_check = activation_check
        self.db = db
        self.adapter = None
        self._locks: dict[ContextKey, asyncio.Lock] = {}
        self._autonomous_msgs: dict[str, dict] = {}
        self._goal_contexts: set[ContextKey] = set()
        self._main_agent_ids: dict[str, str] = {}

    async def global_telemetry_listener(self, data: dict) -> None:
        """Global listener that permanently streams subagent and background goal telemetry into the channel."""
        ganymede_conv_id = data.get("ganymede_conv_id")
        if not ganymede_conv_id:
            return
            
        event = data.get("event")
        payload = data.get("payload", {})
        if isinstance(payload, str):
            payload = {}
            
        tool_call = payload.get("toolCall", {}) if isinstance(payload, dict) else {}
        if isinstance(tool_call, str):
            tool_call = {}

        if event == "Agent Lifecycle Hook" and tool_call:
            if "error" in payload:
                event = "PostToolUse"
            else:
                event = "PreToolUse"

        if event not in ("PreToolUse", "PostToolUse", "Stop"):
            return

        import re
        from ganymede.core import ContextKey
        match = re.search(r"_(\d{17,20})$", ganymede_conv_id)
        if not match:
            return
            
        channel_id = match.group(1)
        context = ContextKey("discord", channel_id, None)
        
        conv_uuid = payload.get("conversationId")
        if not conv_uuid:
            return
            
        main_id = self._main_agent_ids.get(ganymede_conv_id)
        if not main_id:
            # The very first telemetry event establishes the main agent's conversationId
            self._main_agent_ids[ganymede_conv_id] = conv_uuid
            main_id = conv_uuid
            
        is_subagent = (conv_uuid != main_id)
        
        lock = self._locks.get(context)
        is_goal = context in self._goal_contexts
        is_autonomous_main = not is_subagent and (not lock or not lock.locked() or is_goal)
        
        if not is_subagent and not is_autonomous_main:
            # Ephemeral streaming handles the active main agent turn
            return
            
        tool = tool_call.get("name", "tool")
        args = tool_call.get("args", {})
        tool_action = args.get("toolAction", "")
        
        if event == "PreToolUse":
            status = f"⚙️ *{tool_action or f'Calling `{tool}`...'}* — `{tool}`"
        elif event == "PostToolUse":
            err = payload.get("error", "")
            if err:
                status = f"❌ *`{tool}` failed:* `{err[:200]}`"
            else:
                status = f"✅ *{tool_action or f'`{tool}` completed.'}*"
        elif event == "Stop":
            status = f"🏁 *Finished*"
                
        prefix = "🧬 **Subagent** | " if is_subagent else "🎯 **Goal** | "
        
        # Add Discord relative timestamp: <t:TIMESTAMP:T> renders as 12:34 PM
        ts = f"<t:{int(time.time())}:T>"
        line = f"{prefix}`{ts}` {status}"
        
        state = self._autonomous_msgs.setdefault(conv_uuid, {"msg_id": None, "lines": []})
        state["lines"].append(line)
        
        # Keep last 15 lines to avoid hitting 2000 char limits
        if len(state["lines"]) > 15:
            state["lines"] = state["lines"][-15:]
            
        display_lines = list(state["lines"])
        if event != "Stop":
            # Add dynamic timestamp to thinking indicator as well
            ts_thinking = f"<t:{int(time.time())}:T>"
            display_lines.append(f"{prefix}`{ts_thinking}` 💭 *Thinking...*")
            
        text = "\n\n".join(display_lines)
        
        if self.adapter:
            if not state["msg_id"]:
                try:
                    state["msg_id"] = await self.adapter.send_streaming_start(context, initial_text=text, persist_header=f"🚀 **Autonomous Session attached...**")
                except Exception:
                    pass
            else:
                try:
                    await self.adapter.edit_streaming(context, state["msg_id"], text)
                except Exception:
                    pass

    def set_adapter(self, adapter):
        self.adapter = adapter

    async def handle_message(self, message: PlatformMessage) -> None:
        # Check for stop command
        if message.content.strip().lower() in ("/stop", "!stop"):
            logger.info("Received user stop command", context=message.context)
            if self.agent_manager:
                managed_agent = self.agent_manager._agents.get(message.context)
                if managed_agent:
                    await managed_agent.terminate()
                    await self.agent_manager.destroy(message.context)
                    if self.adapter:
                        await self.adapter.send_response(message.context, "🛑 *Active agent execution aborted and session cleared successfully.*", {})
                else:
                    if self.adapter:
                        await self.adapter.send_response(message.context, "❌ *No active agent execution found for this channel.*", {})
            return

        # Step 1: Check activation strategy
        if self.activation_check and not self.activation_check.should_respond(message):
            logger.debug("Message ignored by activation rules", context=message.context)
            return

        # Step 2: Acquire per-context lock        # Serialize messages for this context
        context = message.context
        if context not in self._locks:
            self._locks[context] = asyncio.Lock()
            
        if message.content.startswith("/goal "):
            self._goal_contexts.add(context)
        elif not message.content.startswith("/plan ") and not message.content.startswith("/grill"):
            self._goal_contexts.discard(context)

        async with self._locks[context]:
            if self.agent_manager and self.agent_manager.quota_tracker:
                await self.agent_manager.quota_tracker.throttle(message.context)
            logger.info("Processing message in context", context=message.context, user=message.author_name)
            if self.db:
                try:
                    await self.db.save_message(
                        context=message.context,
                        author_id=message.author_id,
                        role="user",
                        content=message.content,
                        tokens=0
                    )
                except Exception as e:
                    logger.error("Failed to save incoming message to DB", error=str(e))

            try:
                if self.agent_manager:
                    self.agent_manager.set_active_author(message.context, message.author_id, message.author_name)
                    
                    managed_agent = await self.agent_manager.get_or_create(message.context)
                    if self.adapter:
                        msg_id = await self.adapter.send_streaming_start(message.context)
                        start_time = time.time()
                        try:
                            prompt_content = message.content
                            if message.reply_to and self.adapter and hasattr(self.adapter, "get_message"):
                                try:
                                    ref_msg = await self.adapter.get_message(message.context.channel_id, message.reply_to)
                                    # Summarize content if it's very long
                                    ref_content = ref_msg.get('content', '')
                                    if len(ref_content) > 500:
                                        ref_content = ref_content[:500] + "... [truncated]"
                                    if ref_msg.get('attachments'):
                                        ref_content += f"\n[Attachments: {', '.join(ref_msg['attachments'])}]"
                                    prompt_content = f"[In reply to message ID {message.reply_to} from {ref_msg.get('author')}:\n> {ref_content}]\n\n{prompt_content}"
                                except Exception as e:
                                    logger.warning("Failed to fetch reply_to context", error=str(e))
                            
                            if message.attachments:
                                prompt_content += "\n\n[USER PROVIDED ATTACHMENTS]\nThe user has provided the following attachment URLs. You can use the `download_attachment` tool to download these to your workspace for review:\n"
                                for att in message.attachments:
                                    prompt_content += f"- {att}\n"
                            
                            response = await managed_agent.chat(prompt_content)
                            response_text = await self._stream_response_chunks(message.context, msg_id, response, start_time)
                            
                            duration = round(time.time() - start_time, 2)
                            usage = response.usage_metadata
                            tokens_count = usage.total_token_count if usage and usage.total_token_count is not None else 0
                            
                            if self.agent_manager.quota_tracker:
                                await self.agent_manager.quota_tracker.record_usage(message.context, tokens_count)
                            
                            artifact_files = self._extract_artifact_files(response, response_text)
                            
                            metadata = {
                                "tokens": tokens_count, 
                                "duration": duration,
                                "model": self.agent_manager.config.agent.model,
                                "artifacts": getattr(response, "artifacts_count", 0),
                                "artifact_files": artifact_files,
                                "tasks": getattr(response, "tasks_count", 0),
                                "subagents": getattr(response, "subagents_count", 0),
                                "interactive_tools": getattr(response, "interactive_tools", [])
                            }
                            await self.adapter.send_streaming_end(message.context, msg_id, metadata)
                            
                            if self.db:
                                try:
                                    bot_id = "bot"
                                    if self.adapter and hasattr(self.adapter, "user") and self.adapter.user:
                                        bot_id = str(self.adapter.user.id)
                                    await self.db.save_message(
                                        context=message.context,
                                        author_id=bot_id,
                                        role="assistant",
                                        content=response_text,
                                        tokens=tokens_count
                                    )
                                except Exception as e:
                                    logger.error("Failed to save response message to DB", error=str(e))
                        except Exception as e:
                            # End streaming cleanly to prevent stuck UI
                            err_str = str(e)
                            if "denied" in err_str.lower() or "approval" in err_str.lower():
                                try:
                                    denied_status = "\n\n❌ *Tool execution denied by administrator.*"
                                    await self.adapter.edit_streaming(message.context, msg_id, response_text + denied_status)
                                    await self.adapter.send_streaming_end(message.context, msg_id, {"tokens": 0, "duration": round(time.time() - start_time, 2)})
                                except Exception:
                                    pass
                            else:
                                try:
                                    await self.adapter.send_streaming_end(message.context, msg_id, {"tokens": 0, "duration": round(time.time() - start_time, 2)})
                                except Exception:
                                    pass
                                raise
                else:
                    # Temporary mock response
                    if self.adapter:
                        msg_id = await self.adapter.send_streaming_start(message.context)
                        await asyncio.sleep(1.0)
                        await self.adapter.edit_streaming(message.context, msg_id, "🤖 Agent Manager stub received: " + message.content)
                        await self.adapter.send_streaming_end(message.context, msg_id, {"tokens": 10, "duration": 1.0})
            except Exception as e:
                logger.error("Error processing context message", context=message.context, error=str(e))
                if self.agent_manager:
                    if self.agent_manager.quota_tracker:
                        self.agent_manager.quota_tracker.record_blocker(str(e))
                    await self.agent_manager.destroy(message.context)
                if self.adapter:
                    await self.adapter.send_response(message.context, f"⚠️ Error: {str(e)}", {"error": True})

    async def handle_scheduled_prompt(self, context: ContextKey, prompt: str) -> None:
        lock = self._locks.setdefault(context, asyncio.Lock())
        
        if lock.locked():
            logger.warning("Context is busy for scheduled prompt, queueing", context=context)

        async with lock:
            if self.agent_manager and self.agent_manager.quota_tracker:
                await self.agent_manager.quota_tracker.throttle(context)
            logger.info("Processing scheduled prompt in context", context=context)
            if self.db:
                try:
                    await self.db.save_message(
                        context=context,
                        author_id="system",
                        role="user",
                        content=prompt,
                        tokens=0
                    )
                except Exception as e:
                    logger.error("Failed to save scheduled prompt to DB", error=str(e))

            try:
                if self.agent_manager:
                    self.agent_manager.set_active_author(context, "system", "system")
                    managed_agent = await self.agent_manager.get_or_create(context)
                    if self.adapter:
                        persist_header = f"⏰ **Scheduled trigger:** *\"{prompt}\"*"
                        initial_text = f"{persist_header}\n⏳ *Thinking...*"
                        msg_id = await self.adapter.send_streaming_start(context, initial_text=initial_text, persist_header=persist_header)
                        start_time = time.time()
                        try:
                            response = await managed_agent.chat(prompt)
                            response_text = await self._stream_response_chunks(context, msg_id, response, start_time)
                            
                            duration = round(time.time() - start_time, 2)
                            usage = response.usage_metadata
                            tokens_count = usage.total_token_count if usage and usage.total_token_count is not None else 0
                            
                            if self.agent_manager.quota_tracker:
                                await self.agent_manager.quota_tracker.record_usage(context, tokens_count)
                            artifact_files = self._extract_artifact_files(response, response_text)
                            
                            metadata = {
                                "tokens": tokens_count, 
                                "duration": duration,
                                "model": self.agent_manager.config.agent.model,
                                "artifacts": getattr(response, "artifacts_count", 0),
                                "artifact_files": artifact_files,
                                "tasks": getattr(response, "tasks_count", 0),
                                "subagents": getattr(response, "subagents_count", 0),
                                "interactive_tools": getattr(response, "interactive_tools", [])
                            }
                            await self.adapter.send_streaming_end(context, msg_id, metadata)
                            
                            if self.db:
                                try:
                                    bot_id = "bot"
                                    if self.adapter and hasattr(self.adapter, "user") and self.adapter.user:
                                        bot_id = str(self.adapter.user.id)
                                    await self.db.save_message(
                                        context=context,
                                        author_id=bot_id,
                                        role="assistant",
                                        content=response_text,
                                        tokens=tokens_count
                                    )
                                except Exception as e:
                                    logger.error("Failed to save scheduled response message to DB", error=str(e))
                        except Exception as e:
                            # End streaming cleanly to prevent stuck UI
                            err_str = str(e)
                            if "denied" in err_str.lower() or "approval" in err_str.lower():
                                try:
                                    denied_status = "\n\n❌ *Tool execution denied by administrator.*"
                                    await self.adapter.edit_streaming(context, msg_id, response_text + denied_status)
                                    await self.adapter.send_streaming_end(context, msg_id, {"tokens": 0, "duration": round(time.time() - start_time, 2)})
                                except Exception:
                                    pass
                            else:
                                try:
                                    await self.adapter.send_streaming_end(context, msg_id, {"tokens": 0, "duration": round(time.time() - start_time, 2)})
                                except Exception:
                                    pass
                                raise
            except Exception as e:
                logger.error("Error processing scheduled context message", context=context, error=str(e))
                if self.agent_manager:
                    if self.agent_manager.quota_tracker:
                        self.agent_manager.quota_tracker.record_blocker(str(e))
                    await self.agent_manager.destroy(context)
                if self.adapter:
                    await self.adapter.send_response(context, f"⚠️ Error: {str(e)}", {"error": True})

    async def _stream_response_chunks(self, context: ContextKey, msg_id: str, response: Any, start_time: float) -> str:
        if self.agent_manager and self.agent_manager.quota_tracker:
            await self.agent_manager.quota_tracker.record_turn(context)

        verbosity = "normal"
        if self.config.agent and hasattr(self.config.agent, "status_verbosity"):
            verbosity = self.config.agent.status_verbosity

        safe_tools = {"view_file", "grep_search", "list_dir", "search_web", "read_url_content", "finish"}
        response_text = ""
        thought_text = ""
        status_text = ""

        # Live telemetry interceptor to render tool calls while blocking on turn completion.
        # This fires for every intermediate Chalice event, giving us the "hot mic" view
        # of what the agent is doing in real-time.
        last_edit_time = [0.0]  # Throttle: max 1 Discord edit per 2s
        EDIT_THROTTLE_SECS = 2.0

        # Resolve the managed agent's conversation_id for matching against ganymede_conv_id
        managed_agent = self.agent_manager._agents.get(context)
        agent_conv_id = managed_agent.conversation_id if managed_agent else None

        async def on_telemetry(data: dict):
            nonlocal status_text
            
            ganymede_conv_id = data.get("ganymede_conv_id")
            if not ganymede_conv_id or ganymede_conv_id != agent_conv_id:
                return
                
            payload = data.get("payload", {})
            if isinstance(payload, str):
                payload = {}
                
            conv_uuid = payload.get("conversationId")
            main_id = self._main_agent_ids.get(ganymede_conv_id)
            # If main_id is known, and this event belongs to a different conversationId, it's a subagent!
            if main_id and conv_uuid != main_id:
                return
                
            event = data.get("event")
                
            tool_call = payload.get("toolCall", {}) if isinstance(payload, dict) else {}
            if isinstance(tool_call, str):
                tool_call = {}
            
            # Derive event type from Chalice lifecycle hook
            if event == "Agent Lifecycle Hook" and tool_call:
                if "error" in payload:
                    event = "PostToolUse"
                else:
                    event = "PreToolUse"

            if event == "PreToolUse":
                tool = tool_call.get("name", "tool")
                args = tool_call.get("args", {})
                # Prefer human-readable toolAction/toolSummary from the payload
                tool_action = args.get("toolAction", "")
                if tool_action:
                    status_text = f"\n\n⚙️ *{tool_action}* — `{tool}`"
                else:
                    status_text = f"\n\n⚙️ *Calling `{tool}`...*"
            elif event == "PostToolUse":
                tool = tool_call.get("name", "tool")
                err = payload.get("error", "")
                if err:
                    status_text = f"\n\n❌ *`{tool}` failed:* `{err[:200]}`"
                else:
                    args = tool_call.get("args", {})
                    tool_action = args.get("toolAction", "")
                    if tool_action:
                        status_text = f"\n\n✅ *{tool_action}* — `{tool}`"
                    else:
                        status_text = f"\n\n✅ *`{tool}` completed.*"
            else:
                return
            
            # Throttle Discord edits to avoid rate limiting
            now = time.time()
            if (now - last_edit_time[0]) >= EDIT_THROTTLE_SECS:
                last_edit_time[0] = now
                try:
                    await self.adapter.edit_streaming(context, msg_id, response_text + status_text)
                except Exception:
                    pass

        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            dashboard_instance.telemetry_listeners.append(on_telemetry)

        is_running = True
        is_goal = context in self._goal_contexts
        
        async def thinking_loop():
            nonlocal status_text
            dots = 1
            while is_running:
                await asyncio.sleep(2.0)
                if not is_goal and "⚙️" not in status_text and "✅" not in status_text:
                    status_text = f"\n\n💭 *Thinking{'.' * dots}*"
                    dots = (dots % 3) + 1
                    try:
                        await self.adapter.edit_streaming(context, msg_id, response_text + status_text)
                    except Exception:
                        pass

        heartbeat_task = asyncio.create_task(thinking_loop())

        try:
            async for chunk in response.chunks:
                chunk_type = chunk.__class__.__name__
                if chunk_type == "Thought":
                    thought_text += chunk.text
                    if not response_text and verbosity != "none":
                        lines = thought_text.strip().split("\n")
                        if len(lines) > 15:
                            lines = ["..."] + lines[-14:]
                        formatted_thought = "\n".join(f"> {line}" for line in lines)
                        await self.adapter.edit_streaming(context, msg_id, f"💭 *Thinking...*\n{formatted_thought}" + status_text)
                
                elif chunk_type == "Text":
                    response_text += chunk.text
                    await self.adapter.edit_streaming(context, msg_id, response_text + status_text)
                
                elif chunk_type == "ToolCall":
                    base_name = chunk.name.split(":")[-1] if ":" in chunk.name else chunk.name
                    is_safe = base_name in safe_tools
                    if verbosity == "normal":
                        if is_safe:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}`...*"
                        else:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}`...* 🔒 *Awaiting administrator approval...*"
                    elif verbosity == "verbose":
                        args_str = json.dumps(chunk.args)
                        if is_safe:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}` with args: `{args_str[:200]}`...*"
                        else:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}` with args: `{args_str[:200]}`...* 🔒 *Awaiting administrator approval...*"
                    elif verbosity == "minimal" and not is_safe:
                        status_text = f"\n\n⚙️ *Calling unsafe tool `{chunk.name}`...* 🔒 *Awaiting administrator approval...*"
                    else:
                        status_text = ""
                    
                    if status_text:
                        await self.adapter.edit_streaming(context, msg_id, response_text + status_text)
                
                elif isinstance(chunk, ToolResult):
                    if verbosity == "normal":
                        if chunk.error:
                            status_text = f"\n\n❌ *Tool `{chunk.name}` failed: {chunk.error}*"
                        else:
                            status_text = f"\n\n✅ *Tool `{chunk.name}` completed.*"
                    elif verbosity == "verbose":
                        if chunk.error:
                            status_text = f"\n\n❌ *Tool `{chunk.name}` failed: {chunk.error}*"
                        else:
                            res_str = str(chunk.result)
                            status_text = f"\n\n✅ *Tool `{chunk.name}` completed. Result: `{res_str[:150]}`...*"
                    elif verbosity == "minimal" and chunk.name not in safe_tools:
                        if chunk.error:
                            status_text = f"\n\n❌ *Unsafe tool `{chunk.name}` failed: {chunk.error}*"
                        else:
                            status_text = f"\n\n✅ *Unsafe tool `{chunk.name}` completed.*"
                    else:
                        status_text = ""
                    
                    await self.adapter.edit_streaming(context, msg_id, response_text + status_text)

            # Final edit to clear the last status line so it does not pollute the history
            if status_text:
                if not response_text:
                    await self.adapter.edit_streaming(context, msg_id, status_text)
                else:
                    await self.adapter.edit_streaming(context, msg_id, response_text)

        finally:
            is_running = False
            if heartbeat_task:
                heartbeat_task.cancel()
            if dashboard_instance and on_telemetry in dashboard_instance.telemetry_listeners:
                dashboard_instance.telemetry_listeners.remove(on_telemetry)

        return response_text

    def _extract_artifact_files(self, response: Any, response_text: str) -> list[str]:
        import re
        import os
        artifact_files = list(getattr(response, "artifact_files", []))
        file_links = re.findall(r'\[.*?\]\(file://(.*?)\)|`?file://(.*?)`?', response_text)
        for match in file_links:
            path = match[0] or match[1]
            if path and path not in artifact_files and os.path.isabs(path):
                artifact_files.append(path)
        return artifact_files
