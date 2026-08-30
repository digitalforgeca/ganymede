import random
from typing import Any, Dict
from ganymede.core.constants import STATUS_COMMAND_TRUNCATE_LEN

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
        if len(cmd) > STATUS_COMMAND_TRUNCATE_LEN:
            cmd = cmd[:STATUS_COMMAND_TRUNCATE_LEN - 3] + "..."
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
    return f"{emoji} *{action}*{target}"


def get_agent_live_summary(managed_agent: Any) -> Dict[str, Any]:
    """Extracts a rich real-time summary of the agent's active execution, last tool, and recent thoughts."""
    if not managed_agent or not getattr(managed_agent, "tmux", None):
        return {"status": "offline", "message": "No active agent session found."}

    import os
    import json
    import time

    model_display = managed_agent.get_current_display_model() if hasattr(managed_agent, "get_current_display_model") else getattr(managed_agent, "active_model", "Unknown")
    is_running = getattr(managed_agent, "is_interactive_turn", False)

    app_data = os.path.expanduser("~/.gemini/antigravity-cli")
    transcript_path = getattr(managed_agent, "_chalice_transcript_path", None)
    if not transcript_path and hasattr(managed_agent, "sdk_conversation_id"):
        transcript_path = os.path.join(app_data, "brain", managed_agent.sdk_conversation_id, ".system_generated", "logs", "transcript.jsonl")

    steps_count = 0
    last_tool = None
    last_action = None
    last_thought = None

    if transcript_path and os.path.exists(transcript_path):
        try:
            with open(transcript_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
                steps_count = len(lines)
                for line in reversed(lines):
                    try:
                        data = json.loads(line)
                        if not last_thought and data.get("thinking"):
                            last_thought = data.get("thinking").strip()
                        if not last_thought and data.get("content") and data.get("type") == "PLANNER_RESPONSE":
                            last_thought = data.get("content").strip()
                        if not last_tool and data.get("tool_calls"):
                            tc = data["tool_calls"][0]
                            last_tool = tc.get("name")
                            args = tc.get("args", {})
                            if isinstance(args, str):
                                try:
                                    args = json.loads(args)
                                except Exception:
                                    args = {}
                            last_action = args.get("toolAction") or args.get("toolSummary")
                    except Exception:
                        continue
        except Exception:
            pass

    return {
        "status": "busy" if is_running else "idle",
        "model": model_display,
        "steps_count": steps_count,
        "last_tool": last_tool,
        "last_action": last_action,
        "last_thought": last_thought,
        "last_active": getattr(managed_agent, "last_active", time.time()),
    }
