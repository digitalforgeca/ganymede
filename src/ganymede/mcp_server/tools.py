import os
import json
import aiohttp
from ganymede.mcp_server import app
from ganymede.config import get_default_data_dir
from ganymede.core.constants import IPC_REQUEST_TIMEOUT_SEC

# Reuse the config fallback logic to resolve rpc_port.txt path
data_dir = get_default_data_dir()
PORT_FILE_PATH = os.path.join(data_dir, "rpc_port.txt")

async def _get_ipc_base_url() -> str:
    """Read the active IPC port file or environment and build localhost base URL."""
    env_port = os.environ.get("GANYMEDE_IPC_PORT")
    if env_port and env_port.isdigit():
        return f"http://localhost:{env_port}"

    if not os.path.exists(PORT_FILE_PATH):
        raise RuntimeError(
            f"Active port file not found at {PORT_FILE_PATH}. "
            "Please ensure the ganymede sidecar bot process is active."
        )
    with open(PORT_FILE_PATH, "r") as f:
        port = f.read().strip()
    if not port.isdigit():
        raise RuntimeError(f"Invalid port content read from file: {port}")
    return f"http://localhost:{port}"

async def _post_ipc(endpoint: str, payload: dict) -> dict:
    """Issue a post request to the sidecar bot local HTTP IPC server."""
    try:
        base_url = await _get_ipc_base_url()
        url = f"{base_url}{endpoint}"
        timeout = aiohttp.ClientTimeout(total=IPC_REQUEST_TIMEOUT_SEC)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(url, json=payload) as response:
                result = await response.json()
                if response.status >= 400:
                    raise RuntimeError(result.get("error", f"HTTP Error {response.status}"))
                return result
    except aiohttp.ClientConnectorError:
        raise RuntimeError(
            "Connection refused to sidecar HTTP IPC server. "
            "Please verify the ganymede bot sidecar is running."
        )

# --- Exposing Tools via FastMCP decorators ---

@app.tool()
async def read_channel_history(channel_id: str, limit: int = 50, platform: str = "discord") -> str:
    """Read recent messages from a specific channel.
    
    Args:
        channel_id: The Discord snowflake ID of the channel.
        limit: Number of messages to retrieve (maximum 100, default 50).
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/channel/history", {"channel_id": channel_id, "limit": limit, "platform": platform})
        messages = result.get("messages", [])
        if not messages:
            return "No recent messages found in this channel."
        
        output = []
        for msg in messages:
            msg_str = f"[{msg['created_at']}] {msg['author']} ({msg['author_id']}): {msg['content']}"
            if msg.get('attachments'):
                msg_str += f"\n  Attachments: {', '.join(msg['attachments'])}"
            output.append(msg_str)
        return "\n".join(output)
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def read_thread_messages(thread_id: str, limit: int = 50, platform: str = "discord") -> str:
    """Read recent messages from a specific active thread.
    
    Args:
        thread_id: The Discord snowflake ID of the target thread.
        limit: Number of messages to retrieve (maximum 100, default 50).
        platform: The platform provider to route to (default 'discord').
    """
    # In Discord, threads are channels too, so we reuse history endpoint
    try:
        result = await _post_ipc("/api/channel/history", {"channel_id": thread_id, "limit": limit, "platform": platform})
        messages = result.get("messages", [])
        if not messages:
            return "No recent messages found in this thread."
        
        output = []
        for msg in messages:
            msg_str = f"[{msg['created_at']}] {msg['author']} ({msg['author_id']}): {msg['content']}"
            if msg.get('attachments'):
                msg_str += f"\n  Attachments: {', '.join(msg['attachments'])}"
            output.append(msg_str)
        return "\n".join(output)
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def get_channel_info(channel_id: str, platform: str = "discord") -> str:
    """Get metadata about a channel (name, type, topic, guild ID).
    
    Args:
        channel_id: The Discord snowflake ID of the target channel.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/channel/info", {"channel_id": channel_id, "platform": platform})
        output = [
            f"Channel ID: {result.get('id')}",
            f"Name: {result.get('name')}",
            f"Type: {result.get('type')}",
            f"Guild ID: {result.get('guild_id', 'DM')}"
        ]
        if "topic" in result:
            output.append(f"Topic: {result['topic']}")
        return "\n".join(output)
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def post_to_channel(channel_id: str, content: str, platform: str = "discord") -> str:
    """Send a message to a specific channel.
    
    Args:
        channel_id: The Discord snowflake ID of the target channel.
        content: The text content of the message to send.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/message/post", {"channel_id": channel_id, "content": content, "platform": platform})
        return f"Message sent successfully. Message ID: {result.get('id')}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def create_thread(channel_id: str, name: str, first_message: str = "", platform: str = "discord") -> str:
    """Create a new thread in a specific text channel.
    
    Args:
        channel_id: The parent Text Channel snowflake ID.
        name: Name of the thread to create.
        first_message: Optional first message to post inside the new thread.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/thread/create", {
            "channel_id": channel_id,
            "name": name,
            "content": first_message,
            "platform": platform
        })
        return f"Thread created successfully. Thread ID: {result.get('id')}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def schedule_cron(cron_expr: str, prompt: str, channel_id: str, platform: str = "discord") -> str:
    """Schedule a recurring prompt execution using cron syntax.
    
    Args:
        cron_expr: Standard 5-field cron expression (e.g. '0 9 * * *' for daily at 9am).
        prompt: The system query prompt to run when cron fires.
        channel_id: Target channel/thread ID where results will be posted.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/schedule/cron", {
            "cron_expr": cron_expr,
            "prompt": prompt,
            "channel_id": channel_id,
            "platform": platform
        })
        return f"Cron job scheduled successfully. Job ID: {result.get('job_id')}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def reply_to_message(channel_id: str, message_id: str, content: str, platform: str = "discord") -> str:
    """Reply directly to a specific message in a channel.
    
    Args:
        channel_id: The Discord snowflake ID of the channel containing the message.
        message_id: The Discord snowflake ID of the message to reply to.
        content: The text content of the reply message.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/message/reply", {"channel_id": channel_id, "message_id": message_id, "content": content, "platform": platform})
        return f"Replied successfully. Message ID: {result.get('id')}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def edit_message(channel_id: str, message_id: str, content: str, platform: str = "discord") -> str:
    """Edit a message previously sent by this agent/bot.
    
    Args:
        channel_id: The Discord snowflake ID of the channel containing the message.
        message_id: The Discord snowflake ID of the message to edit.
        content: The new text content of the message.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        result = await _post_ipc("/api/message/edit", {"channel_id": channel_id, "message_id": message_id, "content": content, "platform": platform})
        return f"Message edited successfully. Message ID: {result.get('id')}"
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def add_reaction(channel_id: str, message_id: str, emoji: str, platform: str = "discord") -> str:
    """Add an emoji reaction to a message.
    
    Args:
        channel_id: The Discord snowflake ID of the channel.
        message_id: The Discord snowflake ID of the message.
        emoji: The emoji character to react with (e.g. '👍' or '✅').
        platform: The platform provider to route to (default 'discord').
    """
    try:
        await _post_ipc("/api/message/react", {"channel_id": channel_id, "message_id": message_id, "emoji": emoji, "platform": platform})
        return f"Added reaction '{emoji}' successfully."
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def get_message_by_id(channel_id: str, message_id: str, platform: str = "discord") -> str:
    """Retrieve details and content of a specific message.
    
    Args:
        channel_id: The Discord snowflake ID of the channel containing the message.
        message_id: The Discord snowflake ID of the message to retrieve.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        msg = await _post_ipc("/api/message/get", {"channel_id": channel_id, "message_id": message_id, "platform": platform})
        msg_str = f"[{msg['created_at']}] {msg['author']} ({msg['author_id']}): {msg['content']}"
        if msg.get('attachments'):
            msg_str += f"\n  Attachments: {', '.join(msg['attachments'])}"
        return msg_str
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def add_folder_to_project(channel_id: str, absolute_path: str, platform: str = "discord") -> str:
    """Add a local directory path to the current project's workspace.
    
    Args:
        channel_id: The target channel ID (used to resolve the active project).
        absolute_path: The absolute path of the local folder to add to the project.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        if not os.path.isabs(absolute_path):
            return "Error: Path must be absolute."
        if not os.path.exists(absolute_path):
            return f"Error: The path '{absolute_path}' does not exist on the host system."
            
        project_name = f"{platform}-{channel_id}"
        projects_file = os.path.expanduser("~/.gemini/projects.json")
        
        data = {"projects": {}}
        if os.path.exists(projects_file):
            try:
                with open(projects_file, "r") as f:
                    data = json.load(f)
            except Exception:
                pass
                
        if "projects" not in data:
            data["projects"] = {}
            
        data["projects"][absolute_path] = project_name
        
        # Ensure the directory exists
        os.makedirs(os.path.dirname(projects_file), exist_ok=True)
        
        with open(projects_file, "w") as f:
            json.dump(data, f, indent=2)
            
        return f"Successfully added '{absolute_path}' to project '{project_name}'."
    except Exception as e:
        return f"Error: {str(e)}"

@app.tool()
async def download_attachment(url: str, absolute_path: str, platform: str = "discord") -> str:
    """Download a file from a URL (e.g. an attachment) to a local absolute path.
    
    Args:
        url: The direct URL of the file to download.
        absolute_path: The local absolute path where the file should be saved.
        platform: The platform provider to route to (default 'discord').
    """
    try:
        if not os.path.isabs(absolute_path):
            return "Error: absolute_path must be an absolute path."
            
        result = await _post_ipc("/api/attachment/download", {
            "url": url,
            "absolute_path": absolute_path,
            "platform": platform
        })
        return f"Successfully downloaded attachment to {absolute_path}"
    except Exception as e:
        return f"Error downloading attachment: {str(e)}"
