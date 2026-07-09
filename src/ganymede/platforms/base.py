from typing import Protocol, Callable, Awaitable, Any, runtime_checkable
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage

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


class BasePlatformProvider:
    """Base class for platform provider integrations, encapsulating transport, IPC, and scheduler lifecycles."""
    
    def __init__(self, config: Any, router: Any, db: Any):
        self.config = config
        self.router = router
        self.db = db
        self.adapter: Any = None

    async def start(self) -> None:
        """Start all transport and integration services."""
        raise NotImplementedError()

    async def stop(self) -> None:
        """Gracefully shutdown all transport and integration services."""
        raise NotImplementedError()
