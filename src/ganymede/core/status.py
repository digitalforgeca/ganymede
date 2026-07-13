import random
import re
from typing import Any, Dict

# Map tool names to status emojis
TOOL_EMOJIS: Dict[str, str] = {
    "run_command": "⚙️",
    "list_dir": "📁",
    "view_file": "📄",
    "grep_search": "🔍",
    "write_to_file": "✍️",
    "replace_file_content": "📝",
    "multi_replace_file_content": "🗃️",
    "read_url_content": "🌐",
    "search_web": "🕵️",
    "reply_to_message": "💬",
    "post_message": "✉️",
    "ask_permission": "🔑",
}

# Fun, mythological themed status actions for Antigravity's VPS Greek-mesh environment
FUN_DESCRIPTIONS: Dict[str, list[str]] = {
    "run_command": [
        "Consulting with Hephaestus to execute shell commands...",
        "Forging command processes in the terminal fire...",
        "Whispering low-level instructions to the Linux kernel...",
        "Stoking the forge to run subprocess tasks...",
    ],
    "list_dir": [
        "Mapping out directory labyrinth paths...",
        "Walking folder pathways to inspect layout...",
        "Invading file storage chambers...",
    ],
    "view_file": [
        "Unrolling ancient database scrolls...",
        "Decoding hidden file inscriptions...",
        "Reading target file source text...",
    ],
    "grep_search": [
        "Consulting the Oracle to locate query patterns...",
        "Searching the codebase archives...",
        "Scanning target files for text matches...",
    ],
    "write_to_file": [
        "Engraving new codex entry on disk...",
        "Forging new file contents...",
    ],
    "replace_file_content": [
        "Transmuting lines of code inside file...",
        "Refining file contents with target edits...",
    ],
    "multi_replace_file_content": [
        "Weaving multiple non-contiguous code modifications...",
        "Batch-transmuting the file's archives...",
    ],
    "read_url_content": [
        "Sending Hermes to retrieve public web scrolls...",
        "Harvesting HTML contents from the cloud...",
    ],
    "search_web": [
        "Consulting the universal web oracle...",
        "Seeking universal knowledge across the web...",
    ],
    "ask_permission": [
        "Petitioning Mount Olympus for access privileges...",
        "Requesting admin permission keys...",
    ]
}

def format_tool_status(tool_name: str, args: Dict[str, Any]) -> str:
    """Format tool execution details into a styled status string for the platform streamer.
    
    Args:
        tool_name: Full tool path or name.
        args: Tool call argument dictionary.
    """
    base_name = tool_name.split(":")[-1] if ":" in tool_name else tool_name
    
    emoji = TOOL_EMOJIS.get(base_name, "⚙️")
    
    # Pick a random fun description or fallback to a standard clean one
    fun_list = FUN_DESCRIPTIONS.get(base_name)
    if fun_list:
        action = random.choice(fun_list)
    else:
        action = f"Executing {base_name}..."

    # Extract target details based on arguments to provide context
    target = ""
    if base_name == "run_command" and "CommandLine" in args:
        cmd = str(args["CommandLine"])
        if len(cmd) > 40:
            cmd = cmd[:37] + "..."
        target = f" `{cmd}`"
    elif base_name in ("list_dir", "list_directory") and "DirectoryPath" in args:
        path = str(args["DirectoryPath"])
        parts = path.strip("/").split("/")
        if len(parts) > 2:
            path = ".../" + "/".join(parts[-2:])
        target = f" `{path}/`"
    elif base_name in ("view_file", "write_to_file") and "TargetFile" in args:
        path = str(args["TargetFile"])
        parts = path.strip("/").split("/")
        if len(parts) > 2:
            path = ".../" + "/".join(parts[-2:])
        target = f" `{path}`"
    elif base_name == "view_file" and "AbsolutePath" in args:
        path = str(args["AbsolutePath"])
        parts = path.strip("/").split("/")
        if len(parts) > 2:
            path = ".../" + "/".join(parts[-2:])
        target = f" `{path}`"
    elif base_name in ("replace_file_content", "multi_replace_file_content") and "TargetFile" in args:
        path = str(args["TargetFile"])
        parts = path.strip("/").split("/")
        if len(parts) > 2:
            path = ".../" + "/".join(parts[-2:])
        target = f" `{path}`"
    elif base_name == "grep_search" and "Query" in args:
        target = f" for `\"{args['Query']}\"`"
    elif base_name == "search_web" and "query" in args:
        target = f" for `\"{args['query']}\"`"
    elif base_name == "read_url_content" and "Url" in args:
        target = f" `{args['Url']}`"

    return f"{emoji} *{action}*{target}"
