"""Asynchronous Tmux process and session management abstraction."""

import asyncio
import uuid
import structlog
from typing import Any
from ganymede.core.constants import (
    TMUX_PASTE_ABSORB_DELAY_SEC,
    TMUX_TERMINATE_MAX_RETRIES,
    TMUX_TERMINATE_POLL_INTERVAL_SEC,
)

logger = structlog.get_logger()


class TmuxResult:
    def __init__(self, returncode: int, stdout: str | None, stderr: str | None):
        self.returncode = returncode
        self.stdout = stdout or ""
        self.stderr = stderr or ""


async def async_run(*args: str, capture_output: bool = False, text: bool = True, check: bool = False, env: dict | None = None, input: str | None = None) -> TmuxResult:
    """Helper to run a subprocess asynchronously with input/output handling."""
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE if capture_output else None,
        stderr=asyncio.subprocess.PIPE if capture_output else None,
        stdin=asyncio.subprocess.PIPE if input is not None else asyncio.subprocess.DEVNULL,
        env=env
    )
    if input is not None:
        stdout_bytes, stderr_bytes = await proc.communicate(input=input.encode("utf-8") if text else input)
    else:
        stdout_bytes, stderr_bytes = await proc.communicate()

    stdout = stdout_bytes.decode("utf-8") if (text and stdout_bytes is not None) else stdout_bytes
    stderr = stderr_bytes.decode("utf-8") if (text and stderr_bytes is not None) else stderr_bytes

    if check and proc.returncode != 0:
        raise RuntimeError(f"Command {' '.join(args)} failed with return code {proc.returncode}: {stderr}")

    return TmuxResult(proc.returncode, stdout, stderr)


class TmuxSession:
    """Represents and controls a decoupled background Tmux session."""

    def __init__(self, name: str):
        self.name = name

    async def is_alive(self) -> bool:
        """Check if the tmux session currently exists and is active."""
        res = await async_run("tmux", "has-session", "-t", self.name, capture_output=True)
        return res.returncode == 0

    async def create(self, cwd: str, cmd: str, env: dict | None = None) -> None:
        """Create and start a new detached tmux session."""
        await async_run("tmux", "new-session", "-d", "-s", self.name, "-c", cwd, cmd, env=env, check=True)

    async def get_pane_pid(self) -> int | None:
        """Retrieve the process ID of the active shell/CLI pane."""
        res = await async_run("tmux", "display-message", "-p", "-t", self.name, "#{pane_pid}", capture_output=True, text=True, check=False)
        pid_str = res.stdout.strip()
        if pid_str and pid_str.isdigit():
            return int(pid_str)
        return None

    async def capture_pane(self) -> str:
        """Capture the current text rendered in the tmux pane."""
        res = await async_run("tmux", "capture-pane", "-p", "-t", self.name, capture_output=True, text=True)
        return res.stdout

    async def send_keys(self, *keys: str) -> None:
        """Send simulated keystrokes to the active pane."""
        await async_run("tmux", "send-keys", "-t", self.name, *keys)

    async def paste_text(self, text: str) -> None:
        """Atomically paste text into the pane using bracketed paste and submit."""
        buf_name = f"buf-{uuid.uuid4().hex[:8]}"
        try:
            # 1. Clear any dirty/leftover input from the TUI prompt line
            await self.send_keys("C-u")
            # 2. Load text into tmux buffer
            await async_run("tmux", "load-buffer", "-b", buf_name, "-", input=text)
            # 3. Bracketed paste into pane
            await async_run("tmux", "paste-buffer", "-p", "-b", buf_name, "-t", self.name)
            # 4. Wait for bubbletea event loop to absorb buffer
            await asyncio.sleep(TMUX_PASTE_ABSORB_DELAY_SEC)
            # 5. Send Enter to submit
            await self.send_keys("Enter")
        finally:
            # Clean up buffer
            try:
                await async_run("tmux", "delete-buffer", "-b", buf_name)
            except Exception:
                pass

    async def graceful_terminate(self) -> None:
        """Send /exit to cleanly shut down CLI plugins and server, falling back to force kill."""
        logger.info("Gracefully closing decoupled tmux session", session=self.name)
        try:
            await self.send_keys("/exit", "Enter")
            for _ in range(TMUX_TERMINATE_MAX_RETRIES):
                await asyncio.sleep(TMUX_TERMINATE_POLL_INTERVAL_SEC)
                if not await self.is_alive():
                    return
            logger.warning("Tmux session did not exit gracefully, force killing", session=self.name)
            await self.kill()
        except Exception as e:
            logger.error("Error during tmux graceful termination, killing session", error=str(e), session=self.name)
            await self.kill()

    async def kill(self) -> None:
        """Force kill the tmux session."""
        try:
            await async_run("tmux", "kill-session", "-t", self.name, capture_output=True)
        except Exception:
            pass
