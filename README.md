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

## 🏃 Running the Standalone Binary (Quick Start)

If you have downloaded the pre-compiled `ganymede` binary from the [GitHub Releases](https://github.com/digitalforgeca/ganymede/releases), use these instructions. No Python environment is required to run the bin.

### 1. Run in Console Mode (Local Test)
To test the harness locally in your terminal standard input/output without connecting to Discord:
```bash
./ganymede --platform console
```
Type your query and press **Enter** to talk to the agent. Type `/exit` to quit.

### 2. Run in Discord Mode (Sidecar Bridge)
To start the sidecar bot that connects to your Discord server:
```bash
DISCORD_TOKEN="your-discord-bot-token" ./ganymede
```
*(You can also save `DISCORD_TOKEN` in a local `.env` file in the same directory as the executable).*

### 3. Run the Stdio MCP Server
To run the stdio JSON-RPC Model Context Protocol server (for integration into an MCP host like Claude Desktop or Antigravity):
```bash
./ganymede mcp
```

---

## 💻 Development & Compiling from Source

If you want to run Ganymede from source, modify the code, or compile your own standalone executable, use these instructions.

### 1. Setup & Install Dependencies
Ensure you have Python 3.10+ installed. Clone the repository and install the project in editable mode:
```bash
pip install -e .
```

### 2. Run from Source
*   **Discord Mode**:
    ```bash
    DISCORD_TOKEN="your-discord-token" ganymede
    ```
*   **Console Mode**:
    ```bash
    ganymede --platform console
    ```
*   **MCP Server**:
    ```bash
    python3 -m ganymede.mcp_server
    ```

### 3. Compile Standalone Binary
To package the entire Python app, its dependencies, and the interpreter into a single-file executable:
```bash
pip install pyinstaller
pyinstaller --onefile --name ganymede --paths src --add-data "config/default.yaml:config" src/ganymede/cli.py
```
The compiled binary will be written to `dist/ganymede`.

### 4. Running Tests
Run the unittest suite verifying database, safety hooks, quota tracking, and agent manager lifecycle:
```bash
python3 -m unittest tests/test_ganymede.py
```
