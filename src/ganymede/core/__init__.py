from dataclasses import dataclass

@dataclass(frozen=True)
class ContextKey:
    platform: str
    channel_id: str
    thread_id: str | None = None

    @property
    def project_name(self) -> str:
        """Deterministic name for agy projects. Strictly uses provider IDs; no friendly names."""
        if self.thread_id:
            return f"{self.platform}-{self.channel_id}-{self.thread_id}"
        return f"{self.platform}-{self.channel_id}"
        
    @property
    def ganymede_conv_id(self) -> str:
        """Deterministic internal ID for Ganymede to track this context."""
        base = f"ganymede_{self.platform}_{self.channel_id}"
        if self.thread_id:
            return f"{base}_{self.thread_id}"
        return base
