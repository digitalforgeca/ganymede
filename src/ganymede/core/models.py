from dataclasses import dataclass, field
from typing import Any
from ganymede.core import ContextKey

@dataclass
class PlatformMessage:
    context: ContextKey
    author_id: str
    author_name: str
    content: str
    is_bot: bool
    mentions_us: bool
    attachments: list[str] = field(default_factory=list)
    reply_to: str | None = None
    raw: Any = None  # Original message object from the platform's API
