import asyncio
import time
import discord
import structlog
from ganymede.platforms.discord.formatter import DiscordFormatter

logger = structlog.get_logger()

class DiscordStreamer:
    """Manages rate-limited token streaming and message updates on Discord."""
    
    EDIT_INTERVAL = 1.5  # seconds (Discord rate limit safety boundary)

    def __init__(self, channel: discord.abc.Messageable, initial_text: str | None = None, persist_header: str | None = None):
        self.channel = channel
        self.formatter = DiscordFormatter()
        self.message: discord.Message | None = None
        self.buffer = ""
        self.last_edit_time = 0.0
        self.is_finished = False
        self.initial_text = initial_text or "⏳ *Thinking...*"
        self.persist_header = persist_header or ""

    async def start(self) -> None:
        """Send the initial placeholder message to indicate thinking state."""
        self.message = await self.channel.send(self.initial_text)
        self.last_edit_time = time.time()

    async def push_tokens(self, tokens: str) -> None:
        """Push raw token updates, editing the message if interval elapsed."""
        if self.is_finished:
            return
        
        self.buffer += tokens
        now = time.time()

        if now - self.last_edit_time >= self.EDIT_INTERVAL:
            await self._update_message()

    async def set_content(self, content: str) -> None:
        """Overwrite the current buffer with the exact content specified."""
        if self.is_finished:
            return
        
        self.buffer = content
        now = time.time()

        if now - self.last_edit_time >= self.EDIT_INTERVAL:
            await self._update_message()

    async def finish(self, metadata: dict | None = None) -> None:
        """Flushes remaining buffer, appends execution metadata, and closes streaming."""
        if self.is_finished:
            return
        self.is_finished = True
        
        # Final flush
        await self._update_message(final=True, metadata=metadata)
        try:
            if self.message:
                reaction = metadata.get("reaction_emoji", "✅") if metadata else "✅"
                await self.message.add_reaction(reaction)
        except Exception as e:
            logger.warning("Failed to add completion reaction", error=str(e))

    async def _update_message(self, final: bool = False, metadata: dict | None = None) -> None:
        if not self.message:
            return

        content = self.buffer.strip()
        if not content:
            content = "..."

        if self.persist_header:
            content = f"{self.persist_header}\n{content}"

        # Handle formatting metadata (e.g. tokens, execution duration) on final edit
        if final and metadata:
            stats = f"\n\n*⚡ {metadata.get('tokens', '?')} tokens · ⏱ {metadata.get('duration', '?')}s*"
            content += stats

        # Ensure code blocks are balanced
        content = self._balance_code_fences(content)

        # Split content if it exceeds the limit
        chunks = self.formatter.split_message(content)
        
        try:
            # We edit the initial message with the first chunk
            first_chunk = chunks[0] if chunks else "..."
            await self.message.edit(content=first_chunk)
            self.last_edit_time = time.time()

            # If there are subsequent chunks, send them as new follow-up messages
            # Note: For simplicity, we just send subsequent chunks. In actual production,
            # we would track them, but since streaming completes, sending them is sufficient.
            if len(chunks) > 1:
                for extra_chunk in chunks[1:]:
                    self.message = await self.channel.send(self._balance_code_fences(extra_chunk))
        except discord.errors.HTTPException as e:
            logger.error("HTTP error during message update", error=str(e))

    def _balance_code_fences(self, text: str) -> str:
        """Close open code blocks to keep rendering valid on partial edits."""
        # Simple count of ``` occurrences
        fences = text.count("```")
        if fences % 2 != 0:
            # Close the open fence
            return text + "\n```"
        return text

    async def set_status(self, status_text: str) -> None:
        """Update the status placeholder if we haven't started streaming content yet."""
        if self.is_finished:
            return
            
        # Only update if the buffer is empty (still thinking/planning)
        if not self.buffer.strip() or self.buffer.strip() == "...":
            content = f"{self.initial_text}\n⚙️ *Running:* `{status_text}`"
            if self.persist_header:
                content = f"{self.persist_header}\n{content}"
            
            try:
                if self.message:
                    await self.message.edit(content=content)
            except Exception as e:
                logger.error("Failed to edit streaming status", error=str(e))
