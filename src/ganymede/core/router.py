import asyncio
import time
from typing import Any
import structlog
import json
from google.antigravity.types import Text, ToolCall, ToolResult, Thought
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

        # Step 2: Acquire per-context lock to avoid parallel chat races on same agent
        lock = self._locks.setdefault(message.context, asyncio.Lock())
        
        async with lock:
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
                            response = await managed_agent.chat(message.content)
                            response_text = await self._stream_response_chunks(message.context, msg_id, response, start_time)
                            
                            duration = round(time.time() - start_time, 2)
                            usage = response.usage_metadata
                            tokens_count = usage.total_token_count if usage and usage.total_token_count is not None else 0
                            
                            if self.agent_manager.quota_tracker:
                                await self.agent_manager.quota_tracker.record_usage(message.context, tokens_count)
                            
                            await self.adapter.send_streaming_end(message.context, msg_id, {"tokens": tokens_count, "duration": duration})
                            
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
                            
                            await self.adapter.send_streaming_end(context, msg_id, {"tokens": tokens_count, "duration": duration})
                            
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

        # Live telemetry interceptor to render tool calls while blocking on --print
        async def on_telemetry(data: dict):
            nonlocal status_text
            ctx_match = context.channel_id in str(data.get("context", ""))
            if not ctx_match: return
            
            event = data.get("event")
            payload = data.get("payload", {})
            if event == "PreToolUse":
                tool = payload.get("tool_name", "tool")
                args = payload.get("tool_args", {})
                try:
                    args_str = json.dumps(args, indent=2)
                except Exception:
                    args_str = str(args)
                status_text = f"\n\n⚙️ *Calling `{tool}`...*\n```json\n{args_str[:400]}\n```"
                await self.adapter.edit_streaming(context, msg_id, response_text + status_text)
            elif event == "PostToolUse":
                tool = payload.get("tool_name", "tool")
                res = payload.get("tool_result", {})
                res_str = str(res.get("output", res))
                status_text = f"\n\n✅ *`{tool}` completed.*\n```\n{res_str[:200]}...\n```"
                await self.adapter.edit_streaming(context, msg_id, response_text + status_text)

        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            dashboard_instance.telemetry_listeners.append(on_telemetry)

        is_running = True
        async def thinking_loop():
            nonlocal status_text
            dots = 1
            while is_running:
                await asyncio.sleep(2.0)
                if "⚙️" not in status_text and "✅" not in status_text:
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
                await self.adapter.edit_streaming(context, msg_id, response_text)

        finally:
            is_running = False
            if heartbeat_task:
                heartbeat_task.cancel()
            if dashboard_instance and on_telemetry in dashboard_instance.telemetry_listeners:
                dashboard_instance.telemetry_listeners.remove(on_telemetry)

        return response_text
