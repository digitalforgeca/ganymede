import asyncio
import sys
import structlog
from typing import Callable, Awaitable, Any
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage
from ganymede.platforms.base import PlatformAdapter

logger = structlog.get_logger()

class ConsoleAdapter(PlatformAdapter):
    """Adapter for running Ganymede in a local terminal console (standard input/output)."""

    def __init__(self, config: Any, router: Any):
        self.config = config
        self.router = router
        self.router.set_adapter(self)
        self._on_message_callback: Callable[[PlatformMessage], Awaitable[None]] | None = None
        self._running = False
        self._read_task = None

    async def start(self) -> None:
        self._running = True
        logger.info("Console Adapter started. Type your message and press Enter (or type '/exit' to quit):")
        # Run input reading loop as a background task
        self._read_task = asyncio.create_task(self._input_loop())

    async def stop(self) -> None:
        self._running = False
        if self._read_task:
            self._read_task.cancel()
        logger.info("Console Adapter stopped.")

    async def send_response(self, context: ContextKey, content: str, metadata: dict[str, Any]) -> None:
        prefix = "🤖 [Response]:"
        if metadata.get("error"):
            prefix = "❌ [Error]:"
        print(f"\n{prefix}\n{content}\n")
        sys.stdout.flush()

    async def send_streaming_start(self, context: ContextKey, initial_text: str | None = None, persist_header: str | None = None) -> str:
        if persist_header:
            print(f"\n{persist_header}")
        if initial_text:
            print(f"⏳ {initial_text}")
        else:
            print("⏳ Thinking...")
        sys.stdout.flush()
        return "console_stream_123"

    async def edit_streaming(self, context: ContextKey, message_id: str, content: str) -> None:
        # Show streamed response output on stdout
        print(f"\r🤖 {content}", end="")
        sys.stdout.flush()

    async def send_streaming_end(self, context: ContextKey, message_id: str, metadata: dict[str, Any]) -> None:
        print("\n✨ Streaming finished.\n")
        sys.stdout.flush()

    async def update_streaming_status(self, context: ContextKey, status_text: str) -> None:
        print(f"⚙️ [Status]: {status_text}")
        sys.stdout.flush()

    def register_on_message(self, callback: Callable[[PlatformMessage], Awaitable[None]]) -> None:
        self._on_message_callback = callback

    def get_bot_namespace(self) -> str:
        # Check if namespace is configured in config
        console_config = self.config.platforms.get("console", {}) if hasattr(self.config, "platforms") else {}
        if isinstance(console_config, dict) and console_config.get("namespace"):
            return console_config["namespace"]
        return "ganymede"

    def get_conversation_id(self, context: ContextKey) -> str:
        """Generate a unique, stable conversation identifier for the given context key."""
        return context.ganymede_conv_id

    async def _input_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                # Read line from stdin in a non-blocking way
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                
                text = line.strip()
                if not text:
                    continue
                    
                if text == "/exit":
                    logger.info("Exiting console loop...")
                    break
                    
                if self._on_message_callback:
                    context = ContextKey("console", "terminal", None)
                    message = PlatformMessage(
                        context=context,
                        author_id="local_user",
                        author_name="user",
                        content=text,
                        is_bot=False,
                        mentions_us=True,
                        raw=line
                    )
                    await self._on_message_callback(message)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error reading console input", error=str(e))
