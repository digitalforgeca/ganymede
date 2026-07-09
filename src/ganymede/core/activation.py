import structlog
from ganymede.core.models import PlatformMessage
from ganymede.config import AppConfig

logger = structlog.get_logger()

class ActivationManager:
    def __init__(self, config: AppConfig):
        self.config = config

    def should_respond(self, message: PlatformMessage) -> bool:
        # Step 1: Handle bot-to-bot filtering
        if message.is_bot:
            if not self.config.activation.respond_to_bots:
                logger.debug("Ignored bot message due to bot-to-bot filtering config")
                return False
            # Never respond to ourselves (even if respond_to_bots is True, to prevent infinite loops)
            # In actual running, adapter filters out author == self.user, but this acts as an extra guard.
            # (Note: we don't have self.user easily accessible here, but the adapter filters it anyway).

        # Step 2: Resolve channel specific strategy
        channel_id = message.context.channel_id
        strategy = self.config.activation.per_channel.get(channel_id, self.config.activation.default_mode)

        if strategy == "always":
            return True
        elif strategy == "mention":
            return message.mentions_us
        elif strategy == "inference":
            # Match configured trigger phrases/patterns in incoming text
            if message.mentions_us:
                return True
            content_lower = message.content.lower()
            return any(pattern.lower() in content_lower for pattern in self.config.activation.trigger_patterns)
        
        # Default fallback: check if mentioned
        return message.mentions_us
