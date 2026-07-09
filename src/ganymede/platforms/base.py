from typing import Protocol, Callable, Awaitable, Any, runtime_checkable
from ganymede.core import ContextKey
from ganymede.core.models import PlatformMessage

import importlib

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


def get_platform_provider_class(platform_name: str) -> type[BasePlatformProvider]:
    """Dynamically import and retrieve the BasePlatformProvider subclass for a given platform name."""
    platform_name = platform_name.lower()
    try:
        module_path = f"ganymede.platforms.{platform_name}.provider"
        module = importlib.import_module(module_path)
        for name in dir(module):
            obj = getattr(module, name)
            if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                return obj
        raise ValueError(f"No BasePlatformProvider subclass found in {module_path}")
    except ModuleNotFoundError as e:
        raise ValueError(f"Platform provider module for '{platform_name}' not found: {str(e)}")
