import os
import argparse
import yaml
from dataclasses import dataclass, field
from typing import Any
from google.antigravity import CapabilitiesConfig

@dataclass
class DiscordConfig:
    token: str = ""
    allowed_guilds: list[str] = field(default_factory=list)

@dataclass
class AgentConfig:
    system_instructions: str = "You are a helpful coding assistant."
    workspace: str = "~/dev"
    capabilities: dict[str, bool] = field(default_factory=lambda: {
        "read_tools": True,
        "write_tools": False,
    })
    idle_timeout_minutes: int = 60
    max_contexts: int = 20
    status_verbosity: str = "normal"  # "none" | "minimal" | "normal" | "verbose"
    require_approval: bool = True
    elevated_users: list[str] = field(default_factory=list)
    auto_approve_tools: list[str] = field(default_factory=lambda: ["view_file", "grep_search", "list_dir", "search_web", "read_url_content", "finish"])
    mission_statement: str = "developing, auditing, and managing the Sulcus persistent context layer and the Antigravity developer ecosystem"

@dataclass
class QuotaConfig:
    max_tokens_per_context_per_hour: int = 50000
    max_tokens_global_per_hour: int = 200000
    alert_threshold_pct: int = 80
    max_requests_per_minute: int = 4
    max_requests_per_day: int = 18  # Free tier RPD is 20; keep 2 as safety margin

@dataclass
class ActivationConfig:
    default_mode: str = "mention"  # "mention" | "inference" | "always"
    respond_to_bots: bool = False
    trigger_patterns: list[str] = field(default_factory=list)
    per_channel: dict[str, str] = field(default_factory=dict)

@dataclass
class AppConfig:
    platform: str = "discord"
    discord: DiscordConfig = field(default_factory=DiscordConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    quota: QuotaConfig = field(default_factory=QuotaConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    data_dir: str = ""
    log_level: str = "INFO"

def get_default_data_dir() -> str:
    # Resolve $ANTIGRAVITY_EXECUTABLE_DATA_DIR with fallback to ~/.gemini/antigravity-cli/plugins/ganymede/data/
    data_dir = os.environ.get("ANTIGRAVITY_EXECUTABLE_DATA_DIR")
    if not data_dir:
        data_dir = os.path.expanduser("~/.gemini/antigravity-cli/plugins/ganymede/data")
    return os.path.abspath(data_dir)

def load_config(args: argparse.Namespace = None) -> AppConfig:
    config = AppConfig(data_dir=get_default_data_dir())

    # 1. Load default yaml if exists
    default_yaml_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "default.yaml")
    if os.path.exists(default_yaml_path):
        with open(default_yaml_path, "r") as f:
            yaml_data = yaml.safe_load(f) or {}
            _merge_dict_into_config(config, yaml_data)

    # 2. Load specified user config if passed
    if args and getattr(args, "config", None):
        user_config_path = os.path.expanduser(args.config)
        if os.path.exists(user_config_path):
            with open(user_config_path, "r") as f:
                yaml_data = yaml.safe_load(f) or {}
                _merge_dict_into_config(config, yaml_data)

    # 3. Environment overrides (e.g. DISCORD_TOKEN)
    env_platform = os.environ.get("GAN_PLATFORM") or os.environ.get("AGY_PLATFORM")
    if env_platform:
        config.platform = env_platform

    env_token = os.environ.get("DISCORD_TOKEN") or os.environ.get("AGYD_DISCORD_TOKEN")
    if env_token:
        config.discord.token = env_token

    env_log_level = os.environ.get("AGY_DISCORD_LOG_LEVEL") or os.environ.get("AGYD_LOG_LEVEL")
    if env_log_level:
        config.log_level = env_log_level

    # 4. CLI overrides
    if args:
        if getattr(args, "platform", None):
            config.platform = args.platform
        if getattr(args, "workspace", None):
            config.agent.workspace = args.workspace
        if getattr(args, "log_level", None):
            config.log_level = args.log_level

    # Final expansions & setup
    config.agent.workspace = os.path.expanduser(config.agent.workspace)
    os.makedirs(config.data_dir, exist_ok=True)

    return config

def _merge_dict_into_config(config: AppConfig, data: dict[str, Any]):
    if "discord" in data:
        d = data["discord"]
        config.discord.token = d.get("token", config.discord.token)
        config.discord.allowed_guilds = d.get("allowed_guilds", config.discord.allowed_guilds)
    if "agent" in data:
        a = data["agent"]
        config.agent.system_instructions = a.get("system_instructions", config.agent.system_instructions)
        config.agent.workspace = a.get("workspace", config.agent.workspace)
        if "capabilities" in a:
            config.agent.capabilities.update(a["capabilities"])
        config.agent.idle_timeout_minutes = a.get("idle_timeout_minutes", config.agent.idle_timeout_minutes)
        config.agent.max_contexts = a.get("max_contexts", config.agent.max_contexts)
        config.agent.status_verbosity = a.get("status_verbosity", config.agent.status_verbosity)
        config.agent.require_approval = a.get("require_approval", config.agent.require_approval)
        config.agent.elevated_users = a.get("elevated_users", config.agent.elevated_users)
        config.agent.auto_approve_tools = a.get("auto_approve_tools", config.agent.auto_approve_tools)
        config.agent.mission_statement = a.get("mission_statement", config.agent.mission_statement)
    if "quota" in data:
        q = data["quota"]
        config.quota.max_tokens_per_context_per_hour = q.get("max_tokens_per_context_per_hour", config.quota.max_tokens_per_context_per_hour)
        config.quota.max_tokens_global_per_hour = q.get("max_tokens_global_per_hour", config.quota.max_tokens_global_per_hour)
        config.quota.alert_threshold_pct = q.get("alert_threshold_pct", config.quota.alert_threshold_pct)
        config.quota.max_requests_per_minute = q.get("max_requests_per_minute", config.quota.max_requests_per_minute)
        config.quota.max_requests_per_day = q.get("max_requests_per_day", config.quota.max_requests_per_day)
    if "activation" in data:
        ac = data["activation"]
        config.activation.default_mode = ac.get("default_mode", config.activation.default_mode)
        config.activation.respond_to_bots = ac.get("respond_to_bots", config.activation.respond_to_bots)
        config.activation.trigger_patterns = ac.get("trigger_patterns", config.activation.trigger_patterns)
        config.activation.per_channel = ac.get("per_channel", config.activation.per_channel)
    config.log_level = data.get("log_level", config.log_level)
