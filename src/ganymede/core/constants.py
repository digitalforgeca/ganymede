"""Centralized system constants, timeouts, intervals, and default settings for Ganymede."""

import re

# Regex for stripping terminal ANSI escapes
ANSI_ESCAPE_PATTERN = re.compile(r'\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\)|\([A-Z0-9])')

# Default Models
DEFAULT_FALLBACK_MODEL = "gemini-3.7-flash-high"

# Tmux & PTY Interaction Timings
TMUX_PASTE_ABSORB_DELAY_SEC = 0.15
TMUX_BOOT_MAX_RETRIES = 40
TMUX_BOOT_POLL_INTERVAL_SEC = 0.5
TMUX_TERMINATE_MAX_RETRIES = 10
TMUX_TERMINATE_POLL_INTERVAL_SEC = 0.5

# Watchdog & Execution Timeouts
WATCHDOG_IDLE_PROMPT_SEC = 3.0
WATCHDOG_COMPLETION_CHECK_SEC = 6.0
QUEUE_POLL_TIMEOUT_SEC = 1.0

# Turn Activity & Lifecycle Timeouts
AGENT_ACTIVITY_TIMEOUT_SEC = 900       # 15 minutes without telemetry
AGENT_GRACE_PERIOD_SEC = 120           # 2 minutes grace period
AGENT_HARD_CEILING_SEC = 7200          # 2 hours absolute hard cap

# Idle Sweeper Settings
IDLE_SWEEPER_INTERVAL_SEC = 600        # Check every 10 minutes
IDLE_SESSION_TTL_SEC = 1800            # Reap after 30 minutes of complete silence

# Discord Platform Constants
DISCORD_STREAM_EDIT_INTERVAL_SEC = 1.5
DISCORD_THINKING_INTERVAL_SEC = 2.0
DISCORD_MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB Discord attachment ceiling
DISCORD_API_TIMEOUT_SEC = 10.0
