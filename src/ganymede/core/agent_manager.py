"""Manages channel-to-conversation mapping and decoupled CLI execution instances."""

import asyncio
import time
import os
import json
import uuid
import structlog
from typing import Any
from google.antigravity.types import Text
from ganymede.core import ContextKey
from ganymede.config import AppConfig
from ganymede.core.quota import QuotaTracker
from ganymede.core.model_registry import ModelRegistry
from ganymede.core.constants import (
    DEFAULT_FALLBACK_MODEL,
    TMUX_BOOT_MAX_RETRIES,
    TMUX_BOOT_POLL_INTERVAL_SEC,
    WATCHDOG_IDLE_PROMPT_SEC,
    WATCHDOG_COMPLETION_CHECK_SEC,
    QUEUE_POLL_TIMEOUT_SEC,
    AGENT_ACTIVITY_TIMEOUT_SEC,
    AGENT_GRACE_PERIOD_SEC,
    AGENT_HARD_CEILING_SEC,
    IDLE_SWEEPER_INTERVAL_SEC,
    IDLE_SESSION_TTL_SEC,
)
from ganymede.core.tmux import TmuxSession, async_run
from ganymede.core.transcript import TranscriptParser

logger = structlog.get_logger()


class MockUsage:
    def __init__(self):
        self.total_token_count = 0


class Thought:
    def __init__(self, text: str):
        self.text = text


class ToolCall:
    def __init__(self, name: str, args: dict):
        self.name = name
        self.args = args


class ToolResult:
    def __init__(self, name: str, result: Any = None, error: str = None):
        self.name = name
        self.result = result
        self.error = error


class CliResponse:
    """Wrapper around agy subprocess to be compatible with Router chunks interface."""

    def __init__(self, agent_instance, prompt: str, direct_text: str = None):
        self.agent = agent_instance
        self.prompt = prompt
        self.response_text = direct_text or ""
        self.usage_metadata = MockUsage()
        self.artifacts_count = 0
        self.artifact_files: list[str] = []
        self.tasks_count = 0
        self.subagents_count = 0
        self.interactive_tools: list[dict] = []
        if direct_text is not None:
            self._chunks_generator = self._direct_chunks()
        else:
            self._chunks_generator = self._read_chunks()

    async def _direct_chunks(self):
        yield Text(text=self.response_text, step_index=0)

    async def _read_chunks(self):
        try:
            attempts = 0
            max_attempts = 2
            chalice_error = None

            while attempts < max_attempts:
                attempts += 1

                # Only clear on retry attempts (chat() already cleared prior to prompt submission)
                if attempts > 1:
                    while not self.agent.chunk_queue.empty():
                        try:
                            self.agent.chunk_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            break
                    self.agent.turn_completed_event.clear()
                    self.agent.aborted = False

                try:
                    start_wait = time.time()

                    while True:
                        if self.agent.aborted:
                            break
                        if self.agent.turn_completed_event.is_set() and self.agent.chunk_queue.empty():
                            break

                        try:
                            chunk = await asyncio.wait_for(self.agent.chunk_queue.get(), timeout=QUEUE_POLL_TIMEOUT_SEC)
                            if chunk is None:
                                break
                            yield chunk
                            continue
                        except asyncio.TimeoutError:
                            pass

                        if self.agent.aborted:
                            break
                        if self.agent.turn_completed_event.is_set() and self.agent.chunk_queue.empty():
                            break

                        # Periodically verify the tmux session is still alive
                        if self.agent.tmux:
                            if not await self.agent.tmux.is_alive():
                                logger.error("Tmux session died unexpectedly during turn", conversation_id=self.agent.conversation_id)
                                chalice_error = getattr(self.agent, "_chalice_error", None)
                                if chalice_error:
                                    break
                                yield Text(text="⚠️ *The agent process terminated unexpectedly (e.g. quota limit reached or crash).* Check logs.", step_index=0)
                                return

                            res_pane = await self.agent.tmux.capture_pane()
                            if "Verifying your account..." in res_pane and "account eligibility" in res_pane and "? for shortcuts" not in res_pane:
                                logger.error("Agent hit Google account verification hold", conversation_id=self.agent.conversation_id)
                                yield Text(text="⚠️ **Google AI Account Verification Hold:**\nThe `agy` CLI is currently locked because Google is verifying your account eligibility. It refuses to process any prompts. Please wait before trying again.", step_index=0)
                                return

                            # Watchdog checks
                            now_check = time.time()
                            elapsed = now_check - start_wait
                            if elapsed > WATCHDOG_IDLE_PROMPT_SEC:
                                is_idle = "? for shortcuts" in res_pane and "Working..." not in res_pane and "Thinking" not in res_pane and "Generating..." not in res_pane
                                if is_idle:
                                    if not getattr(self, "_kickstarted_prompt", False):
                                        self._kickstarted_prompt = True
                                        logger.info("Watchdog detected idle prompt after paste, sending Enter retry", conversation_id=self.agent.conversation_id)
                                        await self.agent.tmux.send_keys("Enter")
                                    elif elapsed > WATCHDOG_COMPLETION_CHECK_SEC and getattr(self.agent, "_chalice_transcript_path", None):
                                        logger.info("Watchdog detected agy completed turn at prompt", conversation_id=self.agent.conversation_id)
                                        break

                        now = time.time()
                        if now - start_wait > AGENT_HARD_CEILING_SEC:
                            logger.error("Agent hit hard ceiling timeout", conversation_id=self.agent.conversation_id)
                            yield Text(text="[Error: Agent hit hard 2-hour maximum execution limit]", step_index=0)
                            return

                        if now - self.agent.last_active > AGENT_ACTIVITY_TIMEOUT_SEC:
                            if now - self.agent.last_active > (AGENT_ACTIVITY_TIMEOUT_SEC + AGENT_GRACE_PERIOD_SEC):
                                logger.error("Agent failed grace period and timed out", conversation_id=self.agent.conversation_id)
                                yield Text(text="[Error: Agent timed out (no activity detected for 17 minutes)]", step_index=0)
                                return
                            elif not hasattr(self, "_warned_grace_period"):
                                logger.warning("Agent appears inactive, entering 2-minute grace period", conversation_id=self.agent.conversation_id)
                                self._warned_grace_period = True
                except Exception as e:
                    logger.error("Error waiting for agent turn completion", error=str(e), conversation_id=self.agent.conversation_id)
                    yield Text(text="[Error: Internal wait error]", step_index=0)
                    return

                if self.agent.aborted:
                    logger.info("Agent turn aborted by /stop", conversation_id=self.agent.conversation_id)
                    yield Text(text="🛑 *Execution stopped by user.*", step_index=0)
                    return

                chalice_error = self.agent._chalice_error
                self.agent._chalice_error = None

                if chalice_error and "429" in str(chalice_error) and ("RESOURCE_EXHAUSTED" in str(chalice_error) or "quota" in str(chalice_error).lower()) and attempts < max_attempts:
                    yield await self._handle_429_fallback(DEFAULT_FALLBACK_MODEL)
                    continue

                break

            # Turn is complete. Read clean output from transcript
            transcript_path = self.agent._chalice_transcript_path
            if not transcript_path:
                transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.agent.sdk_conversation_id}/.system_generated/logs/transcript.jsonl")

            if not transcript_path or not os.path.exists(transcript_path):
                error_msg = chalice_error or "No transcript available from agent"
                logger.error("No transcript path from Chalice telemetry",
                             conversation_id=self.agent.conversation_id,
                             transcript_path=transcript_path,
                             chalice_error=chalice_error)
                yield Text(text=f"⚠️ {error_msg}", step_index=0)
                return

            final_text, artifacts_created, interactive_tools = TranscriptParser.parse_transcript(transcript_path)
            self.interactive_tools = interactive_tools

            # Merge artifacts globally captured from telemetry
            captured_artifacts = getattr(self.agent, "_artifacts_this_turn", [])
            for art in captured_artifacts:
                if not any(a["file"] == art["file"] for a in artifacts_created):
                    artifacts_created.append(art)

            # Sync artifacts to central channel brain dir
            channel_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.agent.conversation_id}")
            synced_files = TranscriptParser.sync_artifacts(artifacts_created, channel_brain_dir)

            if artifacts_created:
                port = getattr(self.agent.config, "dashboard_port", None) or getattr(getattr(self.agent, "config", None), "port", None) or 8180
                review_block = TranscriptParser.format_artifact_review_text(artifacts_created, dashboard_port=port)
                final_text = (final_text + "\n\n" + review_block) if final_text else review_block

            self.agent._artifacts_this_turn = []
            self.artifacts_count = len(artifacts_created)
            self.artifact_files = synced_files
            self.tasks_count = getattr(self.agent, "_chalice_tasks_count", 0)
            self.subagents_count = getattr(self.agent, "_chalice_subagents_count", 0)

            if not final_text and chalice_error:
                final_text = f"⚠️ {chalice_error}"

            self.response_text = final_text
            yield Text(text=final_text, step_index=0)
            self.usage_metadata.total_token_count = (len(self.prompt) + len(final_text)) // 4
        finally:
            self.agent.is_interactive_turn = False

    async def _handle_429_fallback(self, fallback_model: str) -> Text:
        """Handles 429 quota exhaustion by updating model.txt and restarting the agent."""
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.agent.sdk_conversation_id)
        os.makedirs(sdk_brain_dir, exist_ok=True)
        model_txt_path = os.path.join(sdk_brain_dir, "model.txt")

        current_model = None
        if os.path.exists(model_txt_path):
            with open(model_txt_path, "r") as f:
                current_model = f.read().strip().strip("\"'")

        if current_model != fallback_model:
            logger.warning(f"Detected 429 quota exhaustion. Falling back to {fallback_model}.", conversation_id=self.agent.conversation_id)
            with open(model_txt_path, "w") as f:
                f.write(fallback_model)

            await self.agent.terminate()
            await self.agent.ensure_running()
            await self.agent.tmux.paste_text(self.prompt)

            return Text(text=f"⚠️ *Model quota exhausted! Falling back to `{fallback_model}` and retrying your request...*\n", step_index=0)
        return Text(text="⚠️ *Model quota exhausted, but already using fallback model.*", step_index=0)

    @property
    def chunks(self):
        return self._chunks_generator


class ManagedAgent:
    """Wraps a persistent conversation channel context mapped to an agy CLI session."""

    _settings_lock = asyncio.Lock()

    def __init__(self, context_key: ContextKey, config: AppConfig, conversation_id: str, bot_namespace: str = "ganymede", ipc_port: int | None = None, manager=None, agent_profile: dict[str, Any] | None = None):
        self.manager = manager
        self.context_key = context_key
        self.config = config
        self.last_active = time.time()
        self._lock = asyncio.Lock()
        self.conversation_id = conversation_id
        self.bot_namespace = bot_namespace
        self.ipc_port = ipc_port
        self.sdk_conversation_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, self.conversation_id))
        self.turn_completed_event = asyncio.Event()
        self.chunk_queue = asyncio.Queue()
        self.aborted = False
        self.is_interactive_turn = False
        self.active_model: str | None = None
        self.active_conversation_id: str | None = None
        self._chalice_transcript_path = None
        self._chalice_error = None
        self.tmux = TmuxSession(f"ganymede-{self.sdk_conversation_id}")
        self.tmux_session_name = self.tmux.name
        self.pane_pid: int | None = None

        # Multi-Agent Profile resolution
        if agent_profile is None:
            if hasattr(config, "get_agent_for_context"):
                agent_profile = config.get_agent_for_context(context_key)
            else:
                agent_profile = {}
        self.agent_profile = agent_profile
        self.agent_id = agent_profile.get("id", "default")
        self.agent_name = agent_profile.get("name", getattr(config.agent, "name", "Icarus"))
        self.agent_model = agent_profile.get("model", getattr(config.agent, "model", DEFAULT_FALLBACK_MODEL))
        self.agent_workspace = agent_profile.get("workspace", getattr(config.agent, "workspace", "~/dev"))
        self.agent_mode = agent_profile.get("mode", getattr(config.agent, "mode", "accept-edits"))
        self.agent_identity = agent_profile.get("identity", getattr(config.bot, "identity", ""))
        self.agent_mission = agent_profile.get("mission_statement", getattr(config.agent, "mission_statement", "to be of help"))
        self.skip_permissions = agent_profile.get("skip_permissions", getattr(config.agent, "skip_permissions", True))

    def get_resolved_slug(self) -> str:
        """Resolve the active model slug for spawning agy."""
        if self.active_model:
            return ModelRegistry.to_slug(self.active_model)
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        model_txt = os.path.join(app_data, "brain", self.sdk_conversation_id, "model.txt")
        if os.path.exists(model_txt):
            try:
                with open(model_txt, "r") as f:
                    m = f.read().strip().strip("\"'")
                if m:
                    return ModelRegistry.to_slug(m)
            except Exception:
                pass
        raw_override = getattr(self.config.agent, "raw_model_string", None)
        if raw_override:
            return ModelRegistry.to_slug(raw_override)
        target_model = getattr(self, "agent_model", None) or getattr(self.config.agent, "model", DEFAULT_FALLBACK_MODEL)
        return ModelRegistry.to_slug(target_model)

    def get_current_display_model(self) -> str:
        """Return the user-facing human-readable model name for this agent."""
        if self.active_model:
            return ModelRegistry.to_display_name(self.active_model)
        slug = self.get_resolved_slug()
        return ModelRegistry.to_display_name(slug)

    async def ensure_running(self):
        """Ensure the decoupled agy session is alive in tmux, spawning it if necessary."""
        args = ["agy", "--conversation", self.sdk_conversation_id]
        project_name = self.context_key.project_name

        brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{self.conversation_id}")
        app_data = os.path.expanduser("~/.gemini/antigravity-cli")
        sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
        os.makedirs(brain_dir, exist_ok=True)
        if not os.path.exists(sdk_brain_dir):
            os.symlink(brain_dir, sdk_brain_dir)

        base_workspace = os.path.expanduser(getattr(self, "agent_workspace", None) or getattr(self.config.agent, "workspace", "~/dev"))
        workspace_dir = os.path.join(base_workspace, project_name) if project_name != "default" and not os.path.isabs(project_name) else base_workspace
        os.makedirs(workspace_dir, exist_ok=True)

        if project_name and project_name != "default":
            args.extend(["--project", project_name])

        args.extend(["--mode", getattr(self, "agent_mode", "accept-edits")])

        resolved_model = self.get_resolved_slug()
        self.active_model = resolved_model
        args.extend(["--model", resolved_model])

        if getattr(self, "skip_permissions", True):
            args.append("--dangerously-skip-permissions")

        try:
            if await self.tmux.is_alive():
                logger.info("Found existing decoupled agy session, reattaching", session=self.tmux.name)
                pane_pid = await self.tmux.get_pane_pid()
                if pane_pid:
                    self.pane_pid = pane_pid
                    pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
                    os.makedirs(pid_map_dir, exist_ok=True)
                    with open(os.path.join(pid_map_dir, str(pane_pid)), "w") as f:
                        f.write(self.conversation_id)
                return
        except Exception:
            pass

        subprocess_env = os.environ.copy()
        subprocess_env["SULCUS_NAMESPACE"] = getattr(self, "bot_namespace", "ganymede")
        subprocess_env["NO_COLOR"] = "1"
        subprocess_env["PYTHONUNBUFFERED"] = "1"
        subprocess_env["TERM"] = "dumb"
        subprocess_env["GANYMEDE_PORT"] = str(getattr(self.config.agent, "dashboard_port", 8180))
        if getattr(self, "ipc_port", None):
            subprocess_env["GANYMEDE_IPC_PORT"] = str(self.ipc_port)

        import shlex
        cmd = shlex.join(args)

        logger.info("Spawning decoupled agy in tmux", command=cmd, session=self.tmux.name, model=resolved_model, context=self.context_key)

        # Pre-trust the workspace in settings.json
        settings_path = os.path.expanduser("~/.gemini/antigravity-cli/settings.json")
        async with ManagedAgent._settings_lock:
            try:
                with open(settings_path, "r") as f:
                    settings = json.load(f)
                trusted = settings.get("trustedWorkspaces", [])
                if workspace_dir not in trusted:
                    trusted.append(workspace_dir)
                    settings["trustedWorkspaces"] = trusted
                    with open(settings_path, "w") as f:
                        json.dump(settings, f, indent=4)
                    logger.info("Pre-trusted workspace in settings.json", path=workspace_dir)
            except Exception:
                pass

            await self.tmux.create(cwd=workspace_dir, cmd=cmd, env=subprocess_env)
            pane_pid = await self.tmux.get_pane_pid()
            if not pane_pid:
                raise RuntimeError(f"Failed to start agy: tmux session {self.tmux.name} exited immediately. Command: {cmd}")

            self.pane_pid = pane_pid
            pid_map_dir = os.path.expanduser("~/.ganymede/data/pid_map")
            os.makedirs(pid_map_dir, exist_ok=True)
            with open(os.path.join(pid_map_dir, str(pane_pid)), "w") as f:
                f.write(self.conversation_id)

            # Wait for interactive prompt to appear
            for _ in range(TMUX_BOOT_MAX_RETRIES):
                pane_text = await self.tmux.capture_pane()
                if "Do you trust" in pane_text or "I trust this folder" in pane_text:
                    logger.warning("Trust prompt detected, auto-accepting", session=self.tmux.name)
                    await self.tmux.send_keys("Enter")
                    await asyncio.sleep(1.0)
                    continue

                if "? for shortcuts" in pane_text or "Error" in pane_text:
                    await asyncio.sleep(1.0)
                    break
                await asyncio.sleep(TMUX_BOOT_POLL_INTERVAL_SEC)

    async def chat(self, prompt: str) -> CliResponse:
        """Submits a user prompt to the active agent session and returns a streaming response."""
        self.last_active = time.time()

        async with self._lock:
            prompt_stripped = prompt.strip()

            if prompt_stripped == "/models":
                try:
                    available = ModelRegistry.get_available_models()
                    lines = [f"{slug}\t{disp}" for slug, disp in available]
                    out = "\n".join(lines)
                    return CliResponse(self, prompt, direct_text=f"```\n{out}\n```")
                except Exception as e:
                    return CliResponse(self, prompt, direct_text=f"❌ Error listing models: {e}")

            if prompt_stripped.startswith("/model "):
                model_name = prompt_stripped[7:].strip().strip("\"'")
                slug = ModelRegistry.to_slug(model_name)
                disp = ModelRegistry.to_display_name(model_name)
                self.active_model = slug

                app_data = os.path.expanduser("~/.gemini/antigravity-cli")
                sdk_brain_dir = os.path.join(app_data, "brain", self.sdk_conversation_id)
                os.makedirs(sdk_brain_dir, exist_ok=True)
                with open(os.path.join(sdk_brain_dir, "model.txt"), "w") as f:
                    f.write(slug)

                await self.terminate()
                return CliResponse(self, prompt, direct_text=f"✅ Model successfully switched to `{disp}` for this channel.\n*(It will take effect on your next message)*")

            await self.ensure_running()

            db_dir = os.path.expanduser("~/.gemini/antigravity-cli/conversations")
            is_new = not os.path.exists(os.path.join(db_dir, f"{self.sdk_conversation_id}.db"))

            final_prompt = prompt
            identity_template = getattr(self, "agent_identity", None) or getattr(self.config.bot, "identity", "")
            if is_new and identity_template:
                bot_name = getattr(self, "agent_name", None) or self.bot_namespace
                sys_inst = identity_template.replace("{bot_name}", bot_name)
                sys_inst = sys_inst.replace("{model_name}", self.get_current_display_model())
                mission = getattr(self, "agent_mission", "to be of help")
                sys_inst = sys_inst.replace("{mission_statement}", mission)

                user_name = "user"
                if self.manager:
                    user_name = self.manager.get_active_author_name(self.context_key) or "user"
                sys_inst = sys_inst.replace("{user_name}", user_name)

                from ganymede.core.hooks import hooks
                sys_inst = await hooks.modify("on_agent_system_prompt", sys_inst, context=self.context_key)

                if prompt.startswith("/"):
                    parts = prompt.split(" ", 1)
                    cmd = parts[0]
                    rest = parts[1] if len(parts) > 1 else ""
                    final_prompt = f"{cmd} System Instructions:\n{sys_inst}\n\nUser Request:\n{rest}"
                else:
                    final_prompt = f"System Instructions:\n{sys_inst}\n\nUser Request:\n{prompt}"

            # Flush any stale chunks/events before prompt submission
            while not self.chunk_queue.empty():
                try:
                    self.chunk_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            self.turn_completed_event.clear()
            self.aborted = False
            self._chalice_error = None
            self._chalice_transcript_path = None
            self._artifacts_this_turn = []

            # Submit prompt to tmux
            await self.tmux.paste_text(final_prompt)
            self.is_interactive_turn = True
            return CliResponse(self, prompt)

    async def terminate(self) -> None:
        """Gracefully terminate the active agy CLI subprocess, falling back to force kill."""
        self.aborted = True
        self.turn_completed_event.set()
        try:
            self.chunk_queue.put_nowait(None)
        except Exception:
            pass

        if self.tmux:
            await self.tmux.graceful_terminate()
            if self.pane_pid:
                pid_map_file = os.path.join(
                    os.path.expanduser("~/.ganymede/data/pid_map"),
                    str(self.pane_pid))
                try:
                    os.remove(pid_map_file)
                except FileNotFoundError:
                    pass
            self.pane_pid = None

    async def close(self):
        await self.terminate()


class AgentManager:
    """Manages channel-to-conversation mapping and CLI execution instances."""

    def __init__(self, config: AppConfig, quota_tracker: QuotaTracker = None, db: Any = None):
        self.config = config
        self.quota_tracker = quota_tracker
        self.db = db
        self._agents: dict[ContextKey, ManagedAgent] = {}
        self._active_authors: dict[ContextKey, str] = {}
        self._active_author_names: dict[ContextKey, str] = {}
        self.adapter = None
        self._telemetry_registered = False
        self._sweeper_task = asyncio.create_task(self._idle_sweeper())

    async def _idle_sweeper(self):
        """Background task that reaps idle CLI sessions that haven't shown activity."""
        while True:
            await asyncio.sleep(IDLE_SWEEPER_INTERVAL_SEC)
            now = time.time()
            to_remove = []
            for ctx, agent in self._agents.items():
                if now - agent.last_active > IDLE_SESSION_TTL_SEC:
                    to_remove.append(ctx)
            for ctx in to_remove:
                logger.info("Sweeping idle agent session to free memory/PTY", context=ctx)
                await self.destroy(ctx)

    async def handle_telemetry(self, data: dict):
        """Wake up ManagedAgent when Chalice signals turn completion."""
        valid_events = ("Agent Lifecycle Hook", "PreToolUse", "PostToolUse", "Stop", "AgentLifecycle", "PreInvocation")
        if data.get("event") not in valid_events:
            return

        payload = data.get("payload", {})
        if not isinstance(payload, dict):
            return

        ganymede_conv_id = data.get("ganymede_conv_id")
        if not ganymede_conv_id:
            return

        has_match = any(a.conversation_id == ganymede_conv_id for a in self._agents.values())
        if not has_match:
            if ganymede_conv_id.startswith("ganymede_"):
                expected = [a.conversation_id for a in self._agents.values()]
                logger.debug("Telemetry conv_id not matched for this manager instance",
                             received=ganymede_conv_id,
                             expected=expected)
            return

        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                agent.last_active = time.time()
                m = payload.get("modelName") or payload.get("model")
                if m:
                    agent.active_model = str(m)
                conv_id = payload.get("conversationId")
                if conv_id and (agent.is_interactive_turn or not agent.active_conversation_id):
                    agent.active_conversation_id = str(conv_id)
                logger.debug("Telemetry matched managed agent", telemetry_event=data.get("event"), ganymede_conv_id=ganymede_conv_id, model=agent.active_model)

        tool_call = payload.get("toolCall", {})
        if isinstance(tool_call, str):
            tool_call = {}

        is_interactive_tool = False
        event_type = data.get("event", "")
        if not payload.get("error") and event_type == "PreToolUse":
            tool_name = tool_call.get("name", "")
            if tool_name in ("default_api:ask_question", "default_api:ask_permission", "ask_question", "ask_permission"):
                is_interactive_tool = True

        state = payload.get("state", "")
        is_turn_complete = event_type == "Stop" or payload.get("fullyIdle") or state == "waiting_for_messages" or is_interactive_tool

        if is_turn_complete:
            for agent in self._agents.values():
                if agent.conversation_id == ganymede_conv_id:
                    transcript_path = payload.get("transcriptPath")
                    if transcript_path:
                        agent._chalice_transcript_path = transcript_path
                    error_text = payload.get("error", "")
                    if error_text:
                        agent._chalice_error = error_text

                    agent._chalice_tasks_count = payload.get("activeTasks", payload.get("tasksCount", 0))
                    agent._chalice_subagents_count = payload.get("activeSubagents", payload.get("subagentsCount", 0))
                    logger.info("Chalice signaled turn complete",
                                ganymede_conv_id=ganymede_conv_id,
                                agy_conv_id=payload.get("conversationId"),
                                transcript_path=transcript_path,
                                reason=payload.get("terminationReason"),
                                error=error_text or None)
                    agent.turn_completed_event.set()
                    agent.chunk_queue.put_nowait(None)
                    return

        for agent in self._agents.values():
            if agent.conversation_id == ganymede_conv_id:
                if not hasattr(agent, "_artifacts_this_turn"):
                    agent._artifacts_this_turn = []
                tool_call = payload.get("toolCall")

                if event_type == "PreToolUse":
                    if isinstance(tool_call, dict):
                        t_name = tool_call.get("name", "")
                        t_args = tool_call.get("args", {})
                        if isinstance(t_args, str):
                            try:
                                t_args = json.loads(t_args)
                            except Exception:
                                t_args = {}
                        agent.chunk_queue.put_nowait(ToolCall(t_name, t_args))
                elif event_type == "PostToolUse":
                    if isinstance(tool_call, dict):
                        t_name = tool_call.get("name", "")
                        t_err = payload.get("error")
                        t_res = payload.get("result")
                        agent.chunk_queue.put_nowait(ToolResult(t_name, t_res, t_err))

                if isinstance(tool_call, dict):
                    t_name = tool_call.get("name", "")
                    if t_name in ("write_to_file", "replace_file_content", "multi_replace_file_content"):
                        args = tool_call.get("args", {})
                        if isinstance(args, str):
                            try:
                                args = json.loads(args)
                            except Exception:
                                args = {}
                        if isinstance(args, dict):
                            metadata = args.get("ArtifactMetadata", {})
                            if metadata and (metadata.get("UserFacing") or metadata.get("RequestFeedback")):
                                target_file = args.get("TargetFile")
                                summary = metadata.get("Summary", "")
                                if target_file and not any(a["file"] == target_file for a in agent._artifacts_this_turn):
                                    agent._artifacts_this_turn.append({
                                        "file": target_file,
                                        "summary": summary
                                    })
                return

    def set_active_author(self, context: ContextKey, author_id: str, author_name: str = None) -> None:
        self._active_authors[context] = author_id
        if author_name:
            self._active_author_names[context] = author_name

    def get_active_author(self, context: ContextKey) -> str | None:
        return self._active_authors.get(context)

    def get_active_author_name(self, context: ContextKey) -> str | None:
        return self._active_author_names.get(context)

    def set_adapter(self, adapter) -> None:
        self.adapter = adapter

    def _register_telemetry_listener(self):
        """Lazily register telemetry listener with dashboard."""
        if self._telemetry_registered:
            return
        from ganymede.core.web import dashboard_instance
        if dashboard_instance:
            if not hasattr(dashboard_instance, "telemetry_listeners"):
                dashboard_instance.telemetry_listeners = []
            dashboard_instance.telemetry_listeners.append(self.handle_telemetry)
            self._telemetry_registered = True
            logger.info("Registered Chalice telemetry listener with dashboard")

    async def get_or_create(self, context: ContextKey) -> ManagedAgent:
        self._register_telemetry_listener()

        if context in self._agents:
            managed = self._agents[context]
            managed.last_active = time.time()
            return managed

        # Enforce max_contexts bound via LRU eviction to prevent unbounded memory growth
        max_ctx = getattr(self.config.agent, "max_contexts", 20)
        if len(self._agents) >= max_ctx:
            oldest_ctx, _ = min(self._agents.items(), key=lambda item: item[1].last_active)
            logger.info("Evicting least recently used agent session to preserve memory bounds", evicted_context=oldest_ctx, max_contexts=max_ctx)
            await self.destroy(oldest_ctx)

        if self.quota_tracker:
            allowed = await self.quota_tracker.check_budget(context)
            if not allowed:
                raise RuntimeError("Request blocked due to token/request budget exhaustion.")

        conversation_id = None
        if self.db:
            conversation_id = await self.db.get_conversation_id_by_context(context)

        if not conversation_id:
            if self.adapter:
                conversation_id = self.adapter.get_conversation_id(context)
            else:
                conversation_id = context.ganymede_conv_id

            if self.db:
                await self.db.save_conversation_mapping(conversation_id, context)

        agent_profile = self.config.get_agent_for_context(context) if hasattr(self.config, "get_agent_for_context") else None
        bot_namespace = agent_profile.get("name", "ganymede") if agent_profile else "ganymede"
        ipc_port = None
        if self.adapter:
            if hasattr(self.adapter, "get_bot_namespace") and not agent_profile:
                bot_namespace = self.adapter.get_bot_namespace()
            if hasattr(self.adapter, "ipc_server") and self.adapter.ipc_server and hasattr(self.adapter.ipc_server, "port"):
                ipc_port = self.adapter.ipc_server.port

        managed = ManagedAgent(context, self.config, conversation_id, bot_namespace, ipc_port, manager=self, agent_profile=agent_profile)
        self._agents[context] = managed
        return managed

    async def destroy(self, context: ContextKey) -> None:
        """Terminates an active session gracefully and removes it from the pool."""
        if managed := self._agents.pop(context, None):
            await managed.terminate()
            logger.info("Session destroyed and removed from pool", context=context)

    async def destroy_all(self) -> None:
        """Terminates all active sessions."""
        logger.info("Terminating all active agent sessions")
        keys = list(self._agents.keys())
        for k in keys:
            await self.destroy(k)
