import os
import subprocess
import time
from typing import Dict, List, Tuple

class ModelRegistry:
    """Dynamic model catalog and resolution registry for Antigravity (agy).
    
    Dynamically queries `agy models` for available models and their human-readable
    names, caching the bidirectional mappings so slug <-> display conversions are
    always accurate, fresh, and never hardcoded.
    """
    _slug_to_display: Dict[str, str] = {}
    _display_to_slug: Dict[str, str] = {}
    _last_refresh: float = 0.0
    _CACHE_TTL: float = 300.0  # 5 minutes

    # Robust baseline fallback map in case agy binary is unreachable during cold boot
    _DEFAULT_MAP: Dict[str, str] = {
        "gemini-3.7-flash-high": "Gemini 3.7 Flash (High)",
        "gemini-3.7-flash-medium": "Gemini 3.7 Flash (Medium)",
        "gemini-3.7-flash-low": "Gemini 3.7 Flash (Low)",
        "gemini-3.6-flash-high": "Gemini 3.6 Flash (High)",
        "gemini-3.6-flash-medium": "Gemini 3.6 Flash (Medium)",
        "gemini-3.6-flash-low": "Gemini 3.6 Flash (Low)",
        "gemini-3.5-flash-high": "Gemini 3.5 Flash (High)",
        "gemini-3.5-flash-medium": "Gemini 3.5 Flash (Medium)",
        "gemini-3.5-flash-low": "Gemini 3.5 Flash (Low)",
        "gemini-3.1-pro-high": "Gemini 3.1 Pro (High)",
        "gemini-3.1-pro-low": "Gemini 3.1 Pro (Low)",
        "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
        "claude-opus-4-6-thinking": "Claude Opus 4.6 (Thinking)",
        "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
    }

    _LEGACY_ALIASES: Dict[str, str] = {
        "gemini-pro-agent": "gemini-3.1-pro-high",
        "gemini-flash-agent": "gemini-3.1-pro-low",
        "gemini-pro": "gemini-3.1-pro-high",
        "gemini-flash": "gemini-3.7-flash-high",
    }

    @classmethod
    def refresh(cls, force: bool = False) -> None:
        now = time.time()
        if not force and cls._slug_to_display and (now - cls._last_refresh < cls._CACHE_TTL):
            return

        cls._slug_to_display = dict(cls._DEFAULT_MAP)
        cls._display_to_slug = {}
        # Populate canonical mappings first
        for slug, disp in cls._DEFAULT_MAP.items():
            cls._display_to_slug[disp.lower()] = slug
            cls._display_to_slug[slug.lower()] = slug

        # Map legacy aliases
        for alias, target_slug in cls._LEGACY_ALIASES.items():
            cls._display_to_slug[alias.lower()] = target_slug
            if target_slug in cls._DEFAULT_MAP:
                cls._slug_to_display[alias] = cls._DEFAULT_MAP[target_slug]

        try:
            # Query agy models directly with DEVNULL stdin to avoid hangs
            proc = subprocess.run(
                ["agy", "models"],
                capture_output=True,
                text=True,
                stdin=subprocess.DEVNULL,
                timeout=5.0
            )
            if proc.returncode == 0 and proc.stdout.strip():
                for line in proc.stdout.splitlines():
                    line = line.strip()
                    if not line or line.startswith("Available") or line.startswith("==") or line.startswith("Fetching"):
                        continue
                    if "\t" in line:
                        parts = line.split("\t", 1)
                        slug = parts[0].strip()
                        disp = parts[1].strip()
                        cls._slug_to_display[slug] = disp
                        cls._display_to_slug[disp.lower()] = slug
                        cls._display_to_slug[slug.lower()] = slug
                    elif "  " in line:
                        parts = [p.strip() for p in line.split("  ") if p.strip()]
                        if len(parts) >= 2:
                            slug, disp = parts[0], parts[1]
                            cls._slug_to_display[slug] = disp
                            cls._display_to_slug[disp.lower()] = slug
                            cls._display_to_slug[slug.lower()] = slug
                        elif len(parts) == 1:
                            cls._slug_to_display[parts[0]] = parts[0]
                            cls._display_to_slug[parts[0].lower()] = parts[0]
                    else:
                        cls._slug_to_display[line] = line
                        cls._display_to_slug[line.lower()] = line
            cls._last_refresh = now
        except Exception:
            cls._last_refresh = now

    @classmethod
    def to_slug(cls, name_or_slug: str) -> str:
        """Resolve any model display name, alias, or slug into the exact agy CLI model slug."""
        if not name_or_slug:
            return "gemini-3.7-flash-high"
        cls.refresh()
        cleaned = name_or_slug.strip().strip("\"'")
        lower = cleaned.lower()
        if lower in cls._display_to_slug:
            return cls._display_to_slug[lower]
        if cleaned in cls._slug_to_display:
            return cleaned
        # Fuzzy alias checks for common user shorthand
        if "3.7" in lower and "flash" in lower:
            if "low" in lower:
                return "gemini-3.7-flash-low"
            elif "medium" in lower:
                return "gemini-3.7-flash-medium"
            return "gemini-3.7-flash-high"
        if "3.1" in lower and "pro" in lower:
            if "low" in lower:
                return "gemini-3.1-pro-low"
            return "gemini-3.1-pro-high"
        if "flash" in lower and "3.5" in lower:
            return "gemini-3.5-flash-high"
        if "sonnet" in lower:
            return "claude-sonnet-4-6"
        if "opus" in lower:
            return "claude-opus-4-6-thinking"
        return cleaned

    @classmethod
    def to_display_name(cls, slug_or_name: str) -> str:
        """Resolve any model slug or raw string into a clean, human-readable display name."""
        if not slug_or_name:
            return "Gemini 3.7 Flash (High)"
        cls.refresh()
        cleaned = slug_or_name.strip().strip("\"'")
        if cleaned in cls._slug_to_display:
            return cls._slug_to_display[cleaned]
        lower = cleaned.lower()
        if lower in cls._display_to_slug:
            slug = cls._display_to_slug[lower]
            return cls._slug_to_display.get(slug, cleaned)
        return cleaned

    @classmethod
    def get_available_models(cls) -> List[Tuple[str, str]]:
        """Return list of (slug, display_name) for all registered models."""
        cls.refresh()
        return [(slug, disp) for slug, disp in cls._slug_to_display.items()]
