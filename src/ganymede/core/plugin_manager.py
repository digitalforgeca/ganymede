import os
import sys
import json
import importlib
import structlog
from typing import Optional, List, Dict, Any, Type

logger = structlog.get_logger()

class PluginManager:
    """
    Scans for and manages Ganymede plugins dynamically using manifests (plugin.json or provider.json).
    This decouples the core engine from hardcoded plugin knowledge.
    """
    
    def __init__(self):
        self.plugin_dirs = [
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "platforms"), # Built-in platforms
            os.path.expanduser("~/.ganymede/plugins")                              # User plugins
        ]
        self._providers: Dict[str, Type] = {}
        self.scan_plugins()

    def scan_plugins(self):
        """Scan directories for plugin manifests and register them."""
        for p_dir in self.plugin_dirs:
            if not os.path.exists(p_dir):
                continue
            
            # Ensure the plugin directory is in sys.path
            if p_dir not in sys.path:
                sys.path.insert(0, p_dir)

            for entry in os.listdir(p_dir):
                full_path = os.path.join(p_dir, entry)
                if os.path.isdir(full_path):
                    self._check_manifest(full_path, entry)

    def _check_manifest(self, directory: str, fallback_name: str):
        """Check for plugin.json or provider.json in a directory."""
        manifest_path = None
        for name in ("plugin.json", "provider.json"):
            candidate = os.path.join(directory, name)
            if os.path.exists(candidate):
                manifest_path = candidate
                break
                
        if manifest_path:
            try:
                with open(manifest_path, "r") as f:
                    manifest = json.load(f)
                    
                plugin_type = manifest.get("type", "provider")
                plugin_name = manifest.get("name", fallback_name).lower()
                
                if plugin_type == "provider":
                    module_name = manifest.get("module", f"{fallback_name}.provider")
                    class_name = manifest.get("class", None)
                    self._register_provider(plugin_name, module_name, class_name)
                    
            except Exception as e:
                logger.error("Failed to load plugin manifest", path=manifest_path, error=str(e))
        else:
            # Fallback for internal built-in platforms without manifests
            if "platforms" in directory:
                # E.g. discord -> ganymede.platforms.discord.provider
                self._register_provider(fallback_name.lower(), f"ganymede.platforms.{fallback_name}.provider")

    def _register_provider(self, name: str, module_path: str, class_name: Optional[str] = None):
        """Dynamically load and register a provider class."""
        try:
            module = importlib.import_module(module_path)
            
            if class_name:
                obj = getattr(module, class_name)
                self._providers[name] = obj
                return
                
            # If no class specified, look for BasePlatformProvider subclass
            from ganymede.platforms.base import BasePlatformProvider
            for attr_name in dir(module):
                obj = getattr(module, attr_name)
                if isinstance(obj, type) and issubclass(obj, BasePlatformProvider) and obj is not BasePlatformProvider:
                    self._providers[name] = obj
                    return
                    
        except ModuleNotFoundError:
            # Ignore module not found for legacy fallbacks that aren't real modules
            pass
        except Exception as e:
            logger.warning("Error loading provider module", module=module_path, error=str(e))

    def get_provider_class(self, platform_name: str) -> Type:
        """Retrieve the registered provider class for a given platform name."""
        platform_name = platform_name.lower()
        if platform_name in self._providers:
            return self._providers[platform_name]
            
        raise ValueError(f"Platform provider module for '{platform_name}' not found. Are you missing a plugin manifest?")

