# Ganymede System — Agent Reference Guide

**Context File for Future Agents**  
*Purpose*: This file serves as a persistent memory and technical orientation guide for any autonomous agent or developer working on the Ganymede gateway.

## 1. System Overview
**Ganymede** is the standalone communication gateway and router for the Antigravity ecosystem. It serves as a persistent, long-running daemon (primarily bridging platforms like Discord to Antigravity agents). 

**Critical Architectural Note**: Ganymede is **not** an Antigravity plugin. Historically, it was scaffolded as a plugin (Phase 0), but it has since been pivoted into a dedicated, standalone executable. Do not attempt to load or configure it via the Antigravity plugin lifecycle (`plugin.json`, `sidecars/`, etc. have been intentionally removed).

## 2. Core Directories & Structure
*   `src/ganymede/` — Main Python package.
*   `src/ganymede/cli.py` — The core application entrypoint. It initializes configuration, structural logging, single-instance file locks, database connections, and platform providers.
*   `src/ganymede/core/web.py` — The embedded `aiohttp` web server that hosts the lightweight monitoring dashboard and telemetry endpoints (`/api/status`).
*   `src/ganymede/web/` — The frontend static files (`index.html`, `style.css`, `app.js`). It uses a vanilla glassmorphism aesthetic; avoid pulling in heavy frameworks like React or Tailwind unless explicitly authorized by the user.
*   `scripts/` — Deployment pipeline utilities (`bump_tag.sh`, `deploy.sh`).
*   `tests/` — Automated test suite verifying End-to-End operations (Database, Router, Quotables, Web, Locks). 

## 3. Configuration Hierarchy
Ganymede operates using a singular, consistent user configuration file.
*   **User Config Location**: `~/.ganymede/config.yaml`
*   **Fallback Logic**: If the user config does not exist at boot, `src/ganymede/config.py` intercepts the load sequence, extracts the internal `default.yaml` shipped in the Python wheel, and safely copies it into `~/.ganymede/` as a template for the user.
*   **Data Directory**: By default, SQLite databases and execution lock files are stored in `~/.ganymede/data/`.

## 4. Single-Instance Daemon Lock
To prevent parallel execution and port conflicts (particularly with Discord Gateway and local HTTP socket binding), `cli.py` implements an exclusive non-blocking instance lock using Unix `fcntl.flock`.
*   The lock file is `ganymede.lock` stored in the user data directory.
*   **Agent Rule**: Do not delete this lockfile manually in shutdown hooks. Kernel-managed `flock` releases gracefully when the process terminates. Deleting it introduces race conditions.

## 5. Deployment & Release Pipeline
Releases are handled automatically by the scripts in `scripts/`:
1.  **Testing**: Always run `.venv/bin/python -m unittest discover -s tests` before building.
2.  **Versioning**: `scripts/bump_tag.sh` accepts semantic nudges (`patch`, `minor`, `major`). It handles `pyproject.toml` string replacement and executes Git tagging.
3.  **Deployment**: `scripts/deploy.sh` connects these pieces: it runs tests, builds the `sdist`/`wheel`, bumps the tag, and pushes to remote (`origin`).

## 6. Development Rules & Guidelines
*   **Code Stability**: Changes to platform adapters (Discord) or the internal Router must be audited with unit tests.
*   **Aesthetics**: Any extensions to the web dashboard must maintain the established "Airy Olympus" theme (high contrast obsidian text on alabaster/marble backgrounds with classical serif typography) using vanilla HTML/CSS. Do not use glassmorphism.
*   **Direct Pushing**: Never use `--force` or push without vetting against unit tests.
*   **Subprocesses**: Avoid using terminal subshells (e.g. `cat` or `sed`) to manage Python configurations; prioritize programmatic AST or regex replacements within python scripts.
*   **CRITICAL OPERATIONAL RULE**: Always validate, never assume. Do not ever assume. Always validate. Always legwork the solve, parameters, CLI flags, and configurations. Never assume a parameter or path exists without running the `help` menu, using `grep`, or reading the file first.
