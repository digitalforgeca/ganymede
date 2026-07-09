# 🏛️ Ganymede

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Discord.py-2.4%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py" />
  <img src="https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/MCP-FastMCP-orange?style=for-the-badge&logo=json&logoColor=white" alt="Model Context Protocol" />
  <img src="https://img.shields.io/badge/Platform-Console_/_Discord-green?style=for-the-badge" alt="Platform" />
</p>

**Ganymede** is a production-grade Discord integration and productivity harness for the Google Antigravity Agent. It enables users to converse with, schedule, and delegate background tasks to their Antigravity agent directly inside Discord channels and threads, complete with real-time feedback loops and safety checks.

---

## 🚀 Key Features

*   **Real-time Streaming & Tool Telemetry**: Streams conversational responses token-by-token. Employs chunk-based analysis to display the active tool execution state in real-time.
*   **Safety Approvals**: Audits dangerous tool calls (like running terminal commands or modifying files) and sends an interactive permission request to the Discord channel using Green/Red buttons (admin-gated).
*   **Slash Commands**: Fully registered Discord slash commands:
    *   `/private <prompt>`: Send a direct private query to the agent.
    *   `/task <description>`: Delegate a background task, log status, and receive DM notification upon completion.
    *   `/status [task_id]`: Check on running or past background tasks.
    *   `/session <info|reset>`: Inspect current token quota usage and agent uptime or clear the active context.
    *   `/schedule <cron> <prompt>`: Establish recurring prompts.
    *   `/config <capability> <enabled>`: Toggle safety gates (e.g. `write_tools` or `run_commands`) in real-time (admin-only).
*   **Stdio MCP Server**: Exposes 7 Discord manipulation tools to the Antigravity Agent to let it read, write, and manage Discord channels.
*   **Robust Persistence**: Utilizes SQLite to log historical turn contexts, scheduled jobs, tool audits, background tasks, and quota usage.

---

## 🛠️ Configuration

Ganymede loads a default YAML configuration from `config/default.yaml` and merges environment variables.

### Status Verbosity levels
You can control the level of feedback printed in Discord during agent turns via `status_verbosity` under `agent:` settings:
*   `none`: Silent. Only conversation responses are displayed.
*   `minimal`: Only appends status for dangerous/unsafe tools requiring approval.
*   `normal` *(Default)*: Appends status lines for all tools starting and completing.
*   `verbose`: Appends detailed tool calls with arguments, completion times, and short result previews.

### Environment Variables
*   `DISCORD_TOKEN`: Your Discord Bot Token.
*   *(Note: No Gemini or LLM API keys are required by Ganymede, as all model inference and authentication are managed natively by the Google Antigravity Agent).*

---

## 🏃 Running the Harness

### 1. Install dependencies
```bash
pip install -e .
```

### 2. Start the Discord Bot Sidecar
```bash
DISCORD_TOKEN="your-token" ganymede
```

### 3. Verify Local IPC Server
Once started, the sidecar writes its active dynamic local HTTP port to `rpc_port.txt`. You can verify it is active:
```bash
curl -s http://localhost:<port>/api/ping
```

### 4. Run Stdio MCP Handshake
```bash
python3 -m ganymede.mcp_server
```

---

## 🧪 Testing

Run the unittest suite verifying database, safety hooks, quota tracking, and agent manager lifecycle:
```bash
python3 -m unittest tests/test_ganymede.py
```
