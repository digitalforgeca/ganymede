<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="src/ganymede/web/ganymede-logo-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="src/ganymede/web/ganymede-logo-light.png">
    <img alt="Ganymede Logo" src="src/ganymede/web/ganymede-logo-light.png" width="400">
  </picture>
</p>

<p align="left">
  <img src="https://img.shields.io/badge/Python-3.10%2B-blue?style=for-the-badge&logo=python&logoColor=white" alt="Python" />
  <img src="https://img.shields.io/badge/Discord.py-2.4%2B-5865F2?style=for-the-badge&logo=discord&logoColor=white" alt="Discord.py" />
  <img src="https://img.shields.io/badge/Aiohttp-Web_Server-purple?style=for-the-badge&logo=aiohttp&logoColor=white" alt="Aiohttp" />
  <img src="https://img.shields.io/badge/SQLite-3-003B57?style=for-the-badge&logo=sqlite&logoColor=white" alt="SQLite" />
  <img src="https://img.shields.io/badge/Homebrew-Formula-F2B50F?style=for-the-badge&logo=homebrew&logoColor=black" alt="Homebrew" />
  <img src="https://img.shields.io/badge/Hatch-Build_System-4B32C3?style=for-the-badge&logo=python&logoColor=white" alt="Hatchling" />
  <img src="https://img.shields.io/badge/MCP-FastMCP-orange?style=for-the-badge&logo=json&logoColor=white" alt="Model Context Protocol" />
</p>

**Ganymede** is a standalone, production-grade communication gateway and productivity harness for the Google Antigravity ecosystem. It connects platforms like Discord to your local autonomous agents, enabling you to converse with, schedule, and delegate background tasks seamlessly, complete with real-time feedback loops and safety checks.

Ganymede also features a built-in lightweight web dashboard (glassmorphic aesthetic) running natively on port `8080` to monitor telemetry, configurations, and agent statuses.

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
    *   `/plan <prompt>`: Request the agent to produce a step-by-step plan before execution.
    *   `/goal <prompt>`: Assign a long-running goal to the agent to execute autonomously.
    *   `/grill [prompt]`: Trigger an interactive plan alignment interview.
    *   `/learn <prompt>`: Persist a behavioral pattern or solution for future tasks.
    *   `/teamwork-preview [prompt]`: Preview teamwork options with a team of autonomous subagents.
    *   `/stop`: Abruptly terminate the active agent execution in this channel.
    *   `/about`: Display metadata about the bot, active workspace, and credits.
*   **Stdio MCP Server**: Exposes 7 Discord manipulation tools to the Antigravity Agent to let it read, write, and manage Discord channels.
*   **Robust Persistence**: Utilizes SQLite to log historical turn contexts, scheduled jobs, tool audits, background tasks, and quota usage.

---

## 🛠️ Configuration

Ganymede uses a singular, consistent user configuration file stored at `~/.ganymede/config.yaml`.
If this file does not exist on your first run, Ganymede will automatically safely copy a default template to this location.

---

## 🍷 The Chalice Plugin (Full-Circle Architecture)

While Ganymede operates outside the Antigravity CLI lifecycle as a robust standalone daemon, it maintains a two-way real-time telemetry and feedback loop directly with the active Antigravity instances using the **Chalice** plugin. 

Found in `plugins/chalice`, this Antigravity-native sidecar lives inside the agent instance. It establishes a persistent WebSocket conduit (`conduit.py`) to the Ganymede gateway's port `8080` interface. This allows Ganymede to receive real-time streams of agent execution events and dispatch direct feedback on demand, bridging the standalone gateway seamlessly with the agent lifecycle.

To install the Chalice plugin into your Antigravity environment:
```bash
ln -s $(pwd)/plugins/chalice ~/.gemini/config/plugins/chalice
```

---

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

## 💻 Installation

We provide streamlined installation processes tailored to your operating system. Because Ganymede is a standalone executable gateway, it manages its own Python virtual environment safely outside of your system paths.

### macOS (Homebrew)
You can install Ganymede natively using Homebrew by building our included formula from source. This sets up a virtual environment in `libexec` and symlinks the binary:
```bash
brew install --build-from-source brew/ganymede.rb
```

### Linux (Systemd)
Run our provided bash script (requires `sudo`) to install Ganymede into `/opt/ganymede`, link it to `/usr/local/bin`, and register a persistent `systemd` service for automatic startup:
```bash
sudo ./scripts/install_linux.sh
```

### Windows (PowerShell)
Execute our PowerShell script. It isolates the build in your `LOCALAPPDATA` directory and places a convenient `Start-Ganymede.bat` launcher right on your desktop:
```powershell
.\scripts\install_windows.ps1
```

---

## 🏃 Running the Gateway

Once installed, simply start the daemon:
```bash
# Terminal execution
ganymede run
```
You can access the real-time telemetry dashboard at `http://localhost:8080`.

To run the stdio JSON-RPC Model Context Protocol server (for integration into an MCP host like Claude Desktop or Antigravity):
```bash
ganymede mcp
```
----

## 💻 Development & Compiling from Source

If you want to run Ganymede from source, modify the code, or compile your own standalone executable, use these instructions.

### 1. Setup & Install Dependencies
Ensure you have Python 3.10+ installed. Clone the repository and install the project in editable mode:
```bash
pip install -e .
```

### 2. Run from Source
*   **Discord Platform**:
    ```bash
    DISCORD_TOKEN="your-discord-token" ganymede
    ```
*   **Console Platform**:
    ```bash
    ganymede --platform console
    ```
*   **Stdio MCP Server**:
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

---

## 🗺️ Roadmap & Future Developments

- **Auto-Detect Local Models**: Intelligently auto-detect the available models defined in the `~/.gemini/models` folder and populate them in the UI for the user to work with seamlessly.
- **Enhanced Multi-Bot Provisioning**: Formalize full multi-bot orchestration directly within the Ganymede UI to allow spanning multiple identity gateways concurrently.
- **Plugin Registry Integration**: Seamless UI-driven installations of community Antigravity plugins.
