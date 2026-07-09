from typing import Protocol, runtime_checkable

@runtime_checkable
class Formatter(Protocol):
    """Formats raw agent outputs into platform-compliant UI representations."""

    def format_text(self, content: str) -> str:
        """Sanitize and format generic markdown into platform-specific format."""
        ...

    def format_code_block(self, code: str, language: str) -> str:
        """Format source code snippet appropriately."""
        ...

    def format_error(self, error: str) -> str:
        """Format system/agent errors (usually red highlight/embed)."""
        ...

    def format_task_status(self, task_id: str, status: str, summary: str) -> str:
        """Format background execution status trackers."""
        ...

    def format_approval_request(self, tool_name: str, tool_args: str) -> str:
        """Format a human-in-the-loop tool execution approval dialog."""
        ...

    def split_message(self, content: str) -> list[str]:
        """Split text that exceeds maximum message boundaries securely."""
        ...

    @property
    def max_message_length(self) -> int:
        """The maximum character capacity allowed for a single message."""
        ...
