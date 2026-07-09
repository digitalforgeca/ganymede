from dataclasses import dataclass, field

@dataclass
class DiscordConfig:
    token: str = ""
    allowed_guilds: list[str] = field(default_factory=list)
    name: str = "ganymede"
    namespace: str | None = None
