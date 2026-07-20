import asyncio
import time
import discord
import structlog
from ganymede.platforms.discord.formatter import DiscordFormatter

logger = structlog.get_logger()

class DiscordStreamer:
    """Manages rate-limited token streaming and message updates on Discord."""
    def __init__(self, channel: discord.abc.Messageable, initial_text: str | None = None, persist_header: str | None = None, edit_interval: float = 1.5):
        self.channel = channel
        self.formatter = DiscordFormatter()
        self.messages: list[discord.Message] = []
        self.buffer = ""
        self.last_edit_time = 0.0
        self.is_finished = False
        self.initial_text = initial_text or "⏳ *Thinking...*"
        self.persist_header = persist_header or ""
        self.edit_interval = edit_interval
        self._flush_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Send the initial placeholder message to indicate thinking state."""
        try:
            msg = await asyncio.wait_for(self.channel.send(self.initial_text), timeout=10.0)
            self.messages.append(msg)
            self.last_edit_time = time.time()
        except asyncio.TimeoutError:
            logger.warning("Timeout creating initial discord stream message")

    def _schedule_flush(self):
        if self._flush_task and not self._flush_task.done():
            return
        
        async def flush():
            delay = max(0.0, self.edit_interval - (time.time() - self.last_edit_time))
            if delay > 0:
                await asyncio.sleep(delay)
            if not self.is_finished:
                await self._update_message()
                
        self._flush_task = asyncio.create_task(flush())

    async def push_tokens(self, tokens: str) -> None:
        """Push raw token updates, editing the message if interval elapsed."""
        if self.is_finished:
            return
        
        self.buffer += tokens
        now = time.time()

        if now - self.last_edit_time >= self.edit_interval:
            await self._update_message()
        else:
            self._schedule_flush()

    async def set_content(self, content: str) -> None:
        """Overwrite the current buffer with the exact content specified."""
        if self.is_finished:
            return
        
        self.buffer = content
        now = time.time()

        if now - self.last_edit_time >= self.edit_interval:
            await self._update_message()
        else:
            self._schedule_flush()

    async def finish(self, metadata: dict | None = None) -> None:
        """Flushes remaining buffer, appends execution metadata, and closes streaming."""
        if self.is_finished:
            return
        self.is_finished = True
        
        # Final flush
        await self._update_message(final=True, metadata=metadata)
        try:
            if self.messages:
                reaction = metadata.get("reaction_emoji", "✅") if metadata else "✅"
                await asyncio.wait_for(self.messages[-1].add_reaction(reaction), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout while adding completion reaction")
        except Exception as e:
            logger.warning("Failed to add completion reaction", error=str(e))

    async def _update_message(self, final: bool = False, metadata: dict | None = None) -> None:
        if not self.messages:
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

        # Sanitize any stray HTML tags before sending to Discord
        content = self.formatter.format_text(content)

        # Split content if it exceeds the limit
        chunks = self.formatter.split_message(content)
        if not chunks:
            chunks = ["..."]
        
        try:
            for i, chunk in enumerate(chunks):
                if i < len(self.messages):
                    await asyncio.wait_for(self.messages[i].edit(content=chunk), timeout=10.0)
                else:
                    new_msg = await asyncio.wait_for(self.channel.send(self._balance_code_fences(chunk)), timeout=10.0)
                    self.messages.append(new_msg)
            self.last_edit_time = time.time()
        except asyncio.TimeoutError:
            logger.warning("Timeout while updating message on Discord")
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
                if self.messages:
                    await asyncio.wait_for(self.messages[-1].edit(content=content), timeout=10.0)
                    self.last_edit_time = time.time()
            except asyncio.TimeoutError:
                logger.warning("Timeout while setting status on Discord message")
            except discord.HTTPException as e:
                logger.warning("Failed to edit Discord message status", error=str(e))
