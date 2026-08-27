import asyncio
import time
import os
import re
from typing import Any
import structlog
import json
from google.antigravity.types import ToolResult
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
from ganymede.config import AppConfig
from ganymede.core.model_registry import ModelRegistry

from ganymede.core.constants import (
    DEFAULT_FALLBACK_MODEL,
    DISCORD_THINKING_INTERVAL_SEC,
)
from ganymede.core.transcript import TranscriptParser

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

        # Robust context resolution from ganymede_conv_id
        context = None
        if self.agent_manager:
            for c in self.agent_manager._agents.keys():
                if c.ganymede_conv_id == ganymede_conv_id:
                    context = c
                    break

        if not context:
            parts = ganymede_conv_id.split("_")
            if len(parts) >= 3 and parts[0] == "ganymede":
                platform = parts[1]
                channel_id = "_".join(parts[2:])
                context = ContextKey(platform, channel_id, None)
            else:
                return

        # Only process telemetry for contexts managed by this router's agent_manager
        if not self.agent_manager or context not in self.agent_manager._agents:
            return

        managed_agent = self.agent_manager._agents[context]
        
        conv_uuid = payload.get("conversationId")
        if not conv_uuid:
            return
            
        # If this is an active interactive turn, record the main agent conversation ID
        if getattr(managed_agent, "is_interactive_turn", False):
            managed_agent.active_conversation_id = conv_uuid
            self._main_agent_ids[ganymede_conv_id] = conv_uuid

        main_id = getattr(managed_agent, "active_conversation_id", None) or self._main_agent_ids.get(ganymede_conv_id)
        if not main_id:
            self._main_agent_ids[ganymede_conv_id] = conv_uuid
            managed_agent.active_conversation_id = conv_uuid
            main_id = conv_uuid
            
        is_main_conv = (
            conv_uuid == main_id
            or conv_uuid == getattr(managed_agent, "sdk_conversation_id", None)
            or conv_uuid == getattr(managed_agent, "conversation_id", None)
        )
        is_subagent = not is_main_conv
        is_interactive = getattr(managed_agent, "is_interactive_turn", False)
        is_autonomous_main = is_main_conv and not is_interactive
        
        if not is_subagent and not is_autonomous_main:
            # Ephemeral streaming handles the active main agent turn
            return

        state = self._autonomous_msgs.setdefault(conv_uuid, {"msg_id": None, "lines": [], "start_time": time.time()})
            
        if event == "Stop" and is_autonomous_main:
            # Main agent finished an autonomous turn (e.g. background task completion or timer)
            transcript_path = payload.get("transcriptPath")
            if not transcript_path and self.agent_manager:
                managed_agent = self.agent_manager._agents.get(context)
                if managed_agent:
                    transcript_path = getattr(managed_agent, "_chalice_transcript_path", None)
                    if not transcript_path:
                        transcript_path = os.path.expanduser(
                            f"~/.gemini/antigravity-cli/brain/{managed_agent.sdk_conversation_id}/.system_generated/logs/transcript.jsonl"
                        )

            final_text, artifacts_created, _ = TranscriptParser.parse_transcript(transcript_path) if transcript_path else ("", [], [])

            # Merge any globally captured artifacts from telemetry
            if self.agent_manager:
                managed_agent = self.agent_manager._agents.get(context)
                if managed_agent:
                    captured = getattr(managed_agent, "_artifacts_this_turn", [])
                    for art in captured:
                        if not any(a["file"] == art["file"] for a in artifacts_created):
                            artifacts_created.append(art)
                    managed_agent._artifacts_this_turn = []

            # Sync artifacts to central channel brain dir
            channel_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{context.ganymede_conv_id}")
            TranscriptParser.sync_artifacts(artifacts_created, channel_brain_dir)

            if artifacts_created:
                port = getattr(self.config, "dashboard_port", None) or getattr(self.config.agent, "dashboard_port", 8180)
                review_block = TranscriptParser.format_artifact_review_text(artifacts_created, dashboard_port=port)
                final_text = (final_text + "\n\n" + review_block) if final_text else review_block

            if not final_text:
                final_text = "\n\n".join(state["lines"]) if state["lines"] else "🏁 *Autonomous task finished.*"

            # Extract artifact files for attachment
            artifact_files = self._extract_artifact_files(None, final_text)
            for art in artifacts_created:
                fpath = art["file"]
                if fpath and fpath not in artifact_files and os.path.isabs(fpath) and os.path.isfile(fpath):
                    artifact_files.append(fpath)

            start_ts = state.get("start_time", time.time())
            duration = round(time.time() - start_ts, 2)
            tokens_count = len(final_text) // 4
            managed_agent = self.agent_manager._agents.get(context) if self.agent_manager else None
            if managed_agent and hasattr(managed_agent, "get_current_display_model"):
                model_name = managed_agent.get_current_display_model()
            else:
                model_name = ModelRegistry.to_display_name(getattr(self.config.agent, "model", "gemini-3.7-flash-high"))

            metadata = {
                "tokens": tokens_count,
                "duration": duration,
                "model": model_name,
                "artifacts": len(artifacts_created),
                "artifact_files": artifact_files,
                "tasks": payload.get("activeTasks", 0),
                "subagents": payload.get("activeSubagents", 0),
            }

            if self.adapter:
                if state.get("msg_id"):
                    try:
                        await self.adapter.edit_streaming(context, state["msg_id"], final_text)
                        await self.adapter.send_streaming_end(context, state["msg_id"], metadata)
                    except Exception as e:
                        logger.error("Failed to finalize autonomous streaming message", error=str(e))
                else:
                    try:
                        new_msg_id = await self.adapter.send_streaming_start(
                            context, initial_text=final_text, persist_header=f"🤖 **Background Task Complete**"
                        )
                        await self.adapter.send_streaming_end(context, new_msg_id, metadata)
                    except Exception as e:
                        logger.error("Failed to send autonomous response message", error=str(e))

            if self.db:
                try:
                    bot_id = "bot"
                    if self.adapter and hasattr(self.adapter, "user") and self.adapter.user:
                        bot_id = str(self.adapter.user.id)
                    await self.db.save_message(
                        context=context,
                        author_id=bot_id,
                        role="assistant",
                        content=final_text,
                        tokens=tokens_count
                    )
                except Exception as e:
                    logger.error("Failed to save autonomous response to DB", error=str(e))

            if conv_uuid in self._autonomous_msgs:
                del self._autonomous_msgs[conv_uuid]
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
                
        prefix = "🧬 **Subagent** | " if is_subagent else "🤖 **Task** | "
        line = f"{prefix}{status}"
        
        state["lines"].append(line)
        
        # Keep last 15 lines to avoid hitting 2000 char limits
        if len(state["lines"]) > 15:
            state["lines"] = state["lines"][-15:]
            
        display_lines = list(state["lines"])
        if event != "Stop":
            display_lines.append(f"{prefix}💭 *Thinking...*")
            
        text = "\n\n".join(display_lines)
        
        if self.adapter:
            header = "🧬 **Subagent Session**" if is_subagent else "🚀 **Autonomous Background Task**"
            if not state["msg_id"]:
                try:
                    state["msg_id"] = await self.adapter.send_streaming_start(context, initial_text=text, persist_header=header)
                except Exception:
                    pass
            else:
                try:
                    await self.adapter.edit_streaming(context, state["msg_id"], text)
                except Exception:
                    pass

    def set_adapter(self, adapter):
        self.adapter = adapter

    def cleanup_context(self, context: ContextKey):
        """Cleanup memory leaks for destroyed contexts."""
        if context in self._locks:
            del self._locks[context]
        if context in self._autonomous_msgs:
            del self._autonomous_msgs[context]

    async def handle_message(self, message: PlatformMessage) -> None:
        # Check for stop command
        if message.content.strip().lower() in ("/stop", "!stop"):
            logger.info("Received user stop command", context=message.context)
            if self.agent_manager:
                managed_agent = self.agent_manager._agents.get(message.context)
                if managed_agent:
                    await managed_agent.terminate()
                    await self.agent_manager.destroy(message.context)
                    self.cleanup_context(message.context)
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
                                "model": managed_agent.get_current_display_model() if hasattr(managed_agent, "get_current_display_model") else ModelRegistry.to_display_name(self.agent_manager.config.agent.model),
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
                    self.cleanup_context(message.context)
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
                                "model": managed_agent.get_current_display_model() if hasattr(managed_agent, "get_current_display_model") else ModelRegistry.to_display_name(self.agent_manager.config.agent.model),
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
                    self.cleanup_context(context)
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
        if agent_conv_id:
            self._main_agent_ids[agent_conv_id] = None
        if managed_agent:
            managed_agent.active_conversation_id = None

        async def on_telemetry(data: dict):
            nonlocal status_text
            
            ganymede_conv_id = data.get("ganymede_conv_id")
            if not ganymede_conv_id or ganymede_conv_id != agent_conv_id:
                return
                
            payload = data.get("payload", {})
            if isinstance(payload, str):
                payload = {}
                
            conv_uuid = payload.get("conversationId")
            if not conv_uuid:
                return

            main_id = self._main_agent_ids.get(ganymede_conv_id)
            if not main_id:
                self._main_agent_ids[ganymede_conv_id] = conv_uuid
                if managed_agent:
                    managed_agent.active_conversation_id = conv_uuid
                main_id = conv_uuid

            # If main_id is known, and this event belongs to a different conversationId, it's a subagent!
            if conv_uuid != main_id:
                return
                
            event = data.get("event")
                
            tool_call = payload.get("toolCall", {}) if isinstance(payload, dict) else {}
            if isinstance(tool_call, str):
                tool_call = {}

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
                    await self.adapter.edit_streaming(context, msg_id, get_display_content())
                except Exception:
                    pass

        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            dashboard_instance.telemetry_listeners.append(on_telemetry)

        is_running = True
        
        def get_display_content() -> str:
            if response_text:
                return response_text + status_text
                
            content = ""
            if thought_text and verbosity != "none":
                lines = thought_text.strip().split("\n")
                if len(lines) > 15:
                    lines = ["..."] + lines[-14:]
                formatted_thought = "\n".join(f"> {line}" for line in lines)
                
                if "💭 *Thinking" in status_text:
                    content = f"{status_text.strip()}\n{formatted_thought}"
                else:
                    content = f"💭 *Thinking...*\n{formatted_thought}\n\n{status_text}"
            else:
                content = status_text
            return content
        
        async def thinking_loop():
            nonlocal status_text
            dots = 1
            while is_running:
                await asyncio.sleep(2.0)
                if "⚙️" not in status_text and "✅" not in status_text and "❌" not in status_text:
                    status_text = f"\n\n💭 *Thinking{'.' * dots}*"
                    dots = (dots % 3) + 1
                    try:
                        await self.adapter.edit_streaming(context, msg_id, get_display_content())
                    except Exception:
                        pass

        heartbeat_task = asyncio.create_task(thinking_loop())

        try:
            async for chunk in response.chunks:
                chunk_type = chunk.__class__.__name__
                if chunk_type == "Thought":
                    thought_text += chunk.text
                    await self.adapter.edit_streaming(context, msg_id, get_display_content())
                
                elif chunk_type == "Text":
                    response_text += chunk.text
                    await self.adapter.edit_streaming(context, msg_id, get_display_content())
                
                elif chunk_type == "ToolCall":
                    base_name = chunk.name.split(":")[-1] if ":" in chunk.name else chunk.name
                    is_safe = base_name in safe_tools
                    if verbosity == "normal":
                        if is_safe:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}`...*"
                        else:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}`...*"
                    elif verbosity == "verbose":
                        args_str = json.dumps(chunk.args)
                        if is_safe:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}` with args: `{args_str[:200]}`...*"
                        else:
                            status_text = f"\n\n⚙️ *Calling tool `{chunk.name}` with args: `{args_str[:200]}`...*"
                    elif verbosity == "minimal" and not is_safe:
                        status_text = f"\n\n⚙️ *Calling unsafe tool `{chunk.name}`...*"
                    else:
                        status_text = ""
                    
                    if status_text:
                        await self.adapter.edit_streaming(context, msg_id, get_display_content())
                
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
                    
                    await self.adapter.edit_streaming(context, msg_id, get_display_content())

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
            if dashboard_instance:
                try:
                    dashboard_instance.telemetry_listeners.remove(on_telemetry)
                except ValueError:
                    pass

        return response_text

    def _extract_artifact_files(self, response: Any, response_text: str) -> list[str]:
        return TranscriptParser.extract_artifact_files(response, response_text)
