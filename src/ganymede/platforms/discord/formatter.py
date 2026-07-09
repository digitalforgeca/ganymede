import re
from ganymede.formatting.base import Formatter

class DiscordFormatter(Formatter):
    """Formats raw agent outputs into Discord-friendly Markdown and handles message splitting."""

    @property
    def max_message_length(self) -> int:
        return 2000

    def format_text(self, content: str) -> str:
        # Standard cleaning of any unsupported raw HTML tags or double escaping
        clean = re.sub(r"<[^>]+>", "", content)
        return clean

    def format_code_block(self, code: str, language: str) -> str:
        return f"```{language}\n{code}\n```"

    def format_error(self, error: str) -> str:
        return f"❌ **Error Encountered:**\n> {error}"

    def format_task_status(self, task_id: str, status: str, summary: str) -> str:
        emoji = "🔄" if status == "running" else ("✅" if status == "completed" else "❌")
        return f"{emoji} **Task {task_id}**: {status.capitalize()}\n> {summary}"

    def format_approval_request(self, tool_name: str, tool_args: str) -> str:
        return (
            f"🔒 **Security Approval Required**\n"
            f"An agent wants to run a restricted operation:\n"
            f"**Tool:** `{tool_name}`\n"
            f"**Arguments:**\n```json\n{tool_args}\n```\n"
            f"*React with ✅ to approve or ❌ to reject.*"
        )

    def split_message(self, content: str) -> list[str]:
        """Split messages at code block boundaries or paragraphs to stay under 2000 chars."""
        limit = self.max_message_length
        if len(content) <= limit:
            return [content]

        chunks = []
        current_chunk = []
        current_length = 0
        in_code_block = False
        code_block_lang = ""

        # Simple line-by-line chunking keeping code fences balanced
        for line in content.splitlines(keepends=True):
            line_len = len(line)
            
            # Detect code fence
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    code_block_lang = line.strip().replace("```", "")

            # If adding this line exceeds the limit, push the current chunk
            if current_length + line_len + (4 if in_code_block else 0) > limit:
                if in_code_block:
                    # Close the code block in the current chunk
                    current_chunk.append("```\n")
                
                chunks.append("".join(current_chunk))
                
                # Reset for next chunk
                current_chunk = []
                current_length = 0
                if in_code_block:
                    # Reopen the code block in the new chunk
                    current_chunk.append(f"```{code_block_lang}\n")
                    current_length += len(current_chunk[-1])
            
            current_chunk.append(line)
            current_length += line_len

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks
