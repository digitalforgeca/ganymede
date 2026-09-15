import re
import urllib.parse
from ganymede.formatting.base import Formatter
from ganymede.core.constants import DISCORD_MAX_MESSAGE_LENGTH

class DiscordFormatter(Formatter):
    """Formats raw agent outputs into Discord-friendly Markdown and handles message splitting."""

    @property
    def max_message_length(self) -> int:
        return DISCORD_MAX_MESSAGE_LENGTH

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

                # Sanitize raw LaTeX math notation (e.g. $< 0.18\text{s}$, $\rightarrow$) into clean text/Unicode
                clean = self._clean_latex(clean)

                # Cap deep Markdown headings (Discord only supports H1-H3: #, ##, ###)
                clean = re.sub(r'^(#{4,})\s+', '### ', clean, flags=re.MULTILINE)

                # Unwrap backticks inside web markdown links so Discord renders them properly
                clean = re.sub(r'\[`+([^`\]]+)`+\]\((https?://[^\)]+)\)', r'[\1](\2)', clean)

                # Convert unclickable file:/// links into clean inline code references
                clean = self._clean_file_links(clean)

                result.append(clean)
        return ''.join(result)

    def _clean_file_links(self, text: str) -> str:
        """Transform local file:/// markdown links into clean inline code references.

        Discord markdown restricts clickable hyperlinks to http:// and https:// schemes.
        Local file:/// links render as broken, noisy raw text and expose local paths.
        This helper parses file links and renders them cleanly (e.g. `file.py`, `func()` (`file.py:10-20`)).
        """
        def replace_file_link(match):
            raw_label = match.group(1).strip()
            url = match.group(2).strip()
            had_backticks = raw_label.startswith('`') and raw_label.endswith('`')
            label = re.sub(r'^`+|`+$', '', raw_label).strip()

            fragment = ""
            if '#' in url:
                url_base, fragment = url.split('#', 1)
            else:
                url_base = url

            path = re.sub(r'^file:///?', '', url_base)
            path = path.split('?')[0]
            filename = urllib.parse.unquote(path.rstrip('/').split('/')[-1]) if path else ""

            line_ref = ""
            if fragment:
                line_match = re.match(r'^L?(\d+)(?:-L?(\d+))?$', fragment)
                if line_match:
                    start = line_match.group(1)
                    end = line_match.group(2)
                    line_ref = f"{start}-{end}" if end else start
                else:
                    line_ref = fragment.lstrip('L')

            if not label:
                label = filename

            # If label is a full path, reduce it to filename
            if label.startswith('file://') or label.startswith('/'):
                label = urllib.parse.unquote(label.rstrip('/').split('/')[-1])

            clean_label_base = re.sub(r'[:#]L?\d+(?:-L?\d+)?$', '', label)
            label_is_file = (clean_label_base == filename or clean_label_base.endswith('/' + filename))

            if label_is_file:
                target = clean_label_base or filename
                return f"`{target}:{line_ref}`" if line_ref else f"`{target}`"
            else:
                formatted_label = f"`{label}`" if (had_backticks or (' ' not in label)) else label
                file_loc = f"{filename}:{line_ref}" if line_ref else filename
                if file_loc:
                    return f"{formatted_label} (`{file_loc}`)"
                else:
                    return formatted_label

        pattern = r'\[([^\]]*)\]\((file://[^\)]+)\)'
        return re.sub(pattern, replace_file_link, text)

    def _clean_latex(self, text: str) -> str:
        """Convert LaTeX math notation and symbols into clean Discord-friendly text and Unicode."""
        replacements = [
            (r'\\rightarrow|\\to', '→'),
            (r'\\leftarrow', '←'),
            (r'\\leftrightarrow', '↔'),
            (r'\\Rightarrow|\\implies', '⇒'),
            (r'\\Leftarrow', '⇐'),
            (r'\\Leftrightarrow|\\iff', '⇔'),
            (r'\\ge\b|\\geq\b', '≥'),
            (r'\\le\b|\\leq\b', '≤'),
            (r'\\ne\b|\\neq\b', '≠'),
            (r'\\approx\b', '≈'),
            (r'\\pm\b', '±'),
            (r'\\times\b', '×'),
            (r'\\cdot\b', '·'),
            (r'\\degree\b|\\circ\b', '°'),
            (r'\\infty\b', '∞'),
            (r'\\quad|\\qquad', ' '),
        ]
        for pattern, repl in replacements:
            text = re.sub(pattern, repl, text)

        # Unwrap text formatting macros: \text{...}, \mathrm{...}, etc.
        text = re.sub(r'\\(?:text|mathrm|mathbf|mathit|textsf|texttt)\{([^}]*)\}', r'\1', text)
        # Convert fractions \frac{a}{b} -> a/b
        text = re.sub(r'\\frac\{([^}]*)\}\{([^}]*)\}', r'\1/\2', text)
        # Block math $$...$$ -> ...
        text = re.sub(r'\$\$(.*?)\$\$', r'\1', text, flags=re.DOTALL)

        # Clean inline math $...$ while preserving standard currency amounts (e.g. "$50" or "$10.99")
        def clean_inline_math(match):
            content = match.group(1)
            if re.match(r'^\d+(?:\.\d+)?$', content.strip()):
                return match.group(0)
            return content

        text = re.sub(r'(?<![\w\\])\$(?!\s)([^\$\n]+?)(?<!\s)\$(?!\d)', clean_inline_math, text)
        return text

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
            is_fence = line.strip().startswith("```")
            fence_lang = line.strip().replace("```", "") if is_fence else ""

            while line:
                line_len = len(line)
                will_open_block = is_fence and not in_code_block
                reserve_chars = 4 if (in_code_block or will_open_block) else 0
                space_left = limit - current_length - reserve_chars

                # If the line fits completely, just add it
                if line_len <= space_left:
                    current_chunk.append(line)
                    current_length += line_len
                    if is_fence:
                        in_code_block = not in_code_block
                        if in_code_block:
                            code_block_lang = fence_lang
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
