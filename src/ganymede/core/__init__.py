from dataclasses import dataclass

@dataclass(frozen=True)
class ContextKey:
    platform: str
    channel_id: str
    thread_id: str | None = None
