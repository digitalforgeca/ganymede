from typing import Any
from ganymede.platforms.base import BasePlatformProvider
from ganymede.platforms.console.adapter import ConsoleAdapter

class ConsolePlatformProvider(BasePlatformProvider):
    """Platform provider for Console/Terminal local standard I/O."""
    
    def __init__(self, config: Any, router: Any, db: Any):
        super().__init__(config, router, db)
        self.adapter = ConsoleAdapter(config, router)

    async def start(self) -> None:
        """Start console standard input listening task."""
        self.adapter.register_on_message(self.router.handle_message)
        await self.adapter.start()
        if self.adapter._read_task:
            try:
                await self.adapter._read_task
            except Exception:
                pass

    async def stop(self) -> None:
        """Stop console standard input task."""
        await self.adapter.stop()
