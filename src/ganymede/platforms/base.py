from typing import Protocol, Callable, Awaitable, Any, runtime_checkable
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage

import importlib

# Static imports for PyInstaller analysis to ensure bundling in single-file binary
try:
    import ganymede.platforms.discord.provider  # noqa: F401
    import ganymede.platforms.console.provider  # noqa: F401
except ImportError:
    pass

@runtime_checkable
class PlatformAdapter(Protocol):
    """Transport layer — receives messages and sends formatted responses."""
    
    async def start(self) -> None:
        """Start the connection to the platform (e.g. Discord bot login)."""
        ...
        
    async def stop(self) -> None:
        """Gracefully disconnect from the platform."""
        ...
        
    async def send_response(self, context: ContextKey, content: str, metadata: dict[str, Any]) -> None:
        """Send a standard text/embed response message to the context."""
        ...
        
    async def send_streaming_start(self, context: ContextKey, initial_text: str | None = None, persist_header: str | None = None) -> str:
        """Send a temporary 'Thinking' message and return its message ID."""
        ...
        
    async def edit_streaming(self, context: ContextKey, message_id: str, content: str) -> None:
        """Update an active streaming message with new token content."""
        ...
        
    async def send_streaming_end(self, context: ContextKey, message_id: str, metadata: dict[str, Any]) -> None:
        """Mark streaming complete, update stats footer, and clean up."""
        ...

    async def update_streaming_status(self, context: ContextKey, status_text: str) -> None:
        """Update the active streaming message with the current tool execution status."""
        ...
        
    def register_on_message(self, callback: Callable[[PlatformMessage], Awaitable[None]]) -> None:
        """Register the router callback for processing inbound messages."""
        ...

    def register_status_callback(self, callback: Callable[[str, bool], None]) -> None:
        """Register a callback to emit connection state changes."""
        ...

    def get_conversation_id(self, context: ContextKey) -> str:
        """Generate a unique, stable conversation identifier for the given context key."""
        ...

    def get_system_instructions(self) -> str | None:
        """Return platform-specific system instructions to append to the bot identity."""
        return None

    # --- Standard Capability Methods for SSE Tools ---

    async def get_channel_history(self, channel_id: str, limit: int) -> list[dict[str, Any]]:
        """Retrieve recent message history from a channel."""
        ...

    async def get_channel_info(self, channel_id: str) -> dict[str, Any]:
        """Retrieve metadata about a channel."""
        ...

    async def post_message(self, channel_id: str, content: str) -> dict[str, Any]:
        """Send a standard text message to a channel."""
        ...

    async def reply_message(self, channel_id: str, message_id: str, content: str) -> dict[str, Any]:
        """Reply to a specific message."""
        ...

    async def edit_message(self, channel_id: str, message_id: str, content: str) -> dict[str, Any]:
        """Edit a previously sent message."""
        ...

    async def react_message(self, channel_id: str, message_id: str, emoji: str) -> dict[str, Any]:
        """Add an emoji reaction to a message."""
        ...

    async def get_message(self, channel_id: str, message_id: str) -> dict[str, Any]:
        """Retrieve a specific message by its ID."""
        ...

    async def create_thread(self, channel_id: str, name: str, content: str | None = None) -> dict[str, Any]:
        """Create a new thread in a channel."""
        ...


class BasePlatformProvider:
    """Base class for platform provider integrations, encapsulating transport, IPC, and scheduler lifecycles."""
    
    def __init__(self, config: Any, router: Any, db: Any, bot_id: str = "default"):
        self.config = config
        self.router = router
        self.db = db
        self.bot_id = bot_id
        self.adapter: Any = None

    @classmethod
    def get_config_schema(cls) -> dict[str, Any]:
        """Return the JSON schema defining the provider's specific configuration fields."""
        return {}

    @classmethod
    def create_providers(cls, config: Any, router_factory: Callable[[Any], Any], db: Any) -> list['BasePlatformProvider']:
        """Factory method to instantiate one or more provider instances based on the configuration."""
        router = router_factory(config)
        provider = cls(config, router, db)
        return [provider]

    async def start(self) -> None:
        """Start all transport and integration services."""
        raise NotImplementedError()

    async def stop(self) -> None:
        """Gracefully shutdown all transport and integration services."""
        raise NotImplementedError()



