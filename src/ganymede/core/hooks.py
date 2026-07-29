import asyncio
from typing import Callable, Any, Dict, List
import structlog

logger = structlog.get_logger()

class HookManager:
    """
    A lightweight, decoupled event hook system.
    Plugins can register callbacks to hook into core engine lifecycles.
    """
    def __init__(self):
        self._hooks: Dict[str, List[Callable]] = {}

    def register(self, hook_name: str, callback: Callable):
        """Register a callback function for a specific hook."""
        if hook_name not in self._hooks:
            self._hooks[hook_name] = []
        self._hooks[hook_name].append(callback)
        logger.debug("Registered plugin hook", hook=hook_name)

    async def execute(self, hook_name: str, *args, **kwargs) -> List[Any]:
        """Fire a hook and return a list of all callback results."""
        if hook_name not in self._hooks:
            return []
            
        results = []
        for cb in self._hooks[hook_name]:
            try:
                if asyncio.iscoroutinefunction(cb):
                    res = await cb(*args, **kwargs)
                else:
                    res = cb(*args, **kwargs)
                results.append(res)
            except Exception as e:
                logger.error(f"Error executing hook {hook_name}", error=str(e))
        return results
        
    async def modify(self, hook_name: str, value: Any, *args, **kwargs) -> Any:
        """
        Passes a value sequentially through a chain of hook callbacks.
        Each callback receives the current value and should return the modified value.
        """
        if hook_name not in self._hooks:
            return value
            
        current_value = value
        for cb in self._hooks[hook_name]:
            try:
                if asyncio.iscoroutinefunction(cb):
                    current_value = await cb(current_value, *args, **kwargs)
                else:
                    current_value = cb(current_value, *args, **kwargs)
            except Exception as e:
                logger.error(f"Error executing modifier hook {hook_name}", error=str(e))
        return current_value

# Global singleton hook manager
hooks = HookManager()
