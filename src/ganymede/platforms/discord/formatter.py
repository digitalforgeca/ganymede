import re
from ganymede.formatting.base import Formatter

class DiscordFormatter(Formatter):
    """Formats raw agent outputs into Discord-friendly Markdown and handles message splitting."""

    @property
    def max_message_length(self) -> int:
        return 2000

    def format_text(self, content: str) -> str:
        """Strip raw HTML tags while preserving Discord mentions and code blocks.
        
        Discord uses angle brackets for mentions (<@id>, <#id>, <:emoji:id>),
        so we cannot blindly strip all <...> sequences. Instead we target
        known HTML tag patterns (alphabetic tag names) and skip anything
        inside fenced code blocks.
        """
        # Split on code fences to avoid mangling code block content
        parts = re.split(r'(```[\s\S]*?```)', content)
        result = []
        for i, part in enumerate(parts):
            if part.startswith('```'):
                # Inside a code block — pass through untouched
                result.append(part)
            else:
                # Convert <details><summary>Title</summary> into Discord collapsible headers (H3)
                clean = re.sub(r'<details>\s*<summary>(.*?)</summary>', r'### \1\n', part, flags=re.IGNORECASE | re.DOTALL)
                clean = re.sub(r'</details>', '\n### \u200B\n', clean, flags=re.IGNORECASE)
                
                # Outside code blocks: strip remaining HTML-style tags
                # but preserve Discord syntax: <@id>, <#id>, <:name:id>, <a:name:id>
                clean = re.sub(r'</?[a-zA-Z][a-zA-Z0-9]*(?:\s[^>]*)?\s*/?>', '', clean)
                result.append(clean)
        return ''.join(result)

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
            # Detect code fence
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                if in_code_block:
                    code_block_lang = line.strip().replace("```", "")

            while line:
                line_len = len(line)
                space_left = limit - current_length - (4 if in_code_block else 0)

                # If the line fits completely, just add it
                if line_len <= space_left:
                    current_chunk.append(line)
                    current_length += line_len
                    break

                # If the chunk already has real content, push it to make room
                has_content = len(current_chunk) > (1 if in_code_block else 0)
                if has_content:
                    if in_code_block:
                        current_chunk.append("```\n")
                    chunks.append("".join(current_chunk))
                    
                    current_chunk = []
                    current_length = 0
                    if in_code_block:
                        prefix = f"```{code_block_lang}\n"
                        current_chunk.append(prefix)
                        current_length = len(prefix)
                    continue

                # If we're here, the chunk has NO real content but the line STILL doesn't fit!
                # This means it's a massive single line > limit chars. We must forcibly split it.
                take_chars = max(1, space_left)
                part = line[:take_chars]
                line = line[take_chars:]
                
                current_chunk.append(part)
                if in_code_block:
                    current_chunk.append("```\n")
                chunks.append("".join(current_chunk))
                
                current_chunk = []
                current_length = 0
                if in_code_block:
                    prefix = f"```{code_block_lang}\n"
                    current_chunk.append(prefix)
                    current_length = len(prefix)

        if current_chunk:
            chunks.append("".join(current_chunk))

        return chunks
