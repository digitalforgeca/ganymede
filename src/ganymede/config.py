import os
import argparse
import yaml
from dataclasses import dataclass, field
from typing import Any

class SyncedPlatformsDict(dict):
    def __init__(self, config_inst, *args, **kwargs):
        self._config = config_inst
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if hasattr(self, "_config") and self._config is not None:
            if hasattr(self._config, "bot") and self._config.bot is not None:
                if key == self._config.platform:
                    if isinstance(value, dict):
                        # Save current platform type to preserve it across dict re-assignments
                        p_type = self._config.bot.provider.get("type", "discord")
                        self._config.bot.provider.clear()
                        self._config.bot.provider.update(value)
                        self._config.bot.provider["type"] = p_type

@dataclass
class AgentConfig:
    name: str = "Agent"
    system_instructions: str = "You are {bot_name}, a helpful AI assistant. Always begin your response by thinking out loud and explicitly explaining what you are going to do before calling any tools. This ensures the user is kept abreast of your activity. Your mission is {mission_statement}."
    workspace: str = "~/dev"
    capabilities: dict[str, bool] = field(default_factory=lambda: {
        "read_tools": True,
        "write_tools": False,
    })
    idle_timeout_minutes: int = 60
    max_contexts: int = 20
    status_verbosity: str = "normal"  # "none" | "minimal" | "normal" | "verbose"
    require_approval: bool = True
    skip_permissions: bool = True
    mode: str = "accept-edits"
    elevated_users: list[str] = field(default_factory=list)
    auto_approve_tools: list[str] = field(default_factory=lambda: ["view_file", "grep_search", "list_dir", "search_web", "read_url_content", "finish"])
    mission_statement: str = "developing, auditing, and managing the Sulcus persistent context layer and the Antigravity developer ecosystem"

@dataclass
class QuotaConfig:
    max_tokens_per_context_per_hour: int = 50000
    max_tokens_global_per_hour: int = 200000
    alert_threshold_pct: int = 80
    max_requests_per_minute: int = 15
    max_requests_per_day: int = 1450  # Free tier RPD is 1500; keep 50 as safety margin

@dataclass
class ActivationConfig:
    default_mode: str = "mention"  # "mention" | "inference" | "always"
    respond_to_bots: bool = False
    trigger_patterns: list[str] = field(default_factory=list)
    per_channel: dict[str, str] = field(default_factory=dict)

@dataclass
class BotConfig:
    provider: dict[str, Any] = field(default_factory=lambda: {
        "type": "discord",
        "token": "",
        "allowed_guilds": [],
        "name": "ganymede",
        "namespace": None
    })

@dataclass
class AppConfig:
    bot: BotConfig = field(default_factory=BotConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    quota: QuotaConfig = field(default_factory=QuotaConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    data_dir: str = ""
    log_level: str = "INFO"
    platforms: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.platforms = SyncedPlatformsDict(self, self.platforms)
        p_type = self.bot.provider.get("type", "discord")
        self.platforms[p_type] = self.bot.provider

    @property
    def platform(self) -> str:
        return self.bot.provider.get("type", "discord")

    @platform.setter
    def platform(self, val: str):
        self.bot.provider["type"] = val

def get_default_data_dir() -> str:
    # Resolve $GANYMEDE_DATA_DIR with fallback to ~/.ganymede/data/
    data_dir = os.environ.get("GANYMEDE_DATA_DIR")
    if not data_dir:
        data_dir = os.path.expanduser("~/.ganymede/data")
    return os.path.abspath(data_dir)

def load_config(args: argparse.Namespace = None) -> AppConfig:
    config = AppConfig(data_dir=get_default_data_dir())

    # 1. Determine singular user config file path
    user_config_path = os.path.expanduser(args.config) if (args and getattr(args, "config", None)) else os.path.expanduser("~/.ganymede/config.yaml")

    # 2. If it doesn't exist, try to seed it from the default yaml shipped with the package
    if not os.path.exists(user_config_path):
        os.makedirs(os.path.dirname(user_config_path), exist_ok=True)
        # Check adjacent directory for local development, or package data
        possible_defaults = [
            os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "config", "default.yaml"), # Dev root
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "default.yaml"), # Packaged via hatchling
        ]
        for def_path in possible_defaults:
            if os.path.exists(def_path):
                import shutil
                shutil.copy(def_path, user_config_path)
                break

    # 3. Load the singular user config file
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
        config.bot.provider["token"] = env_token

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
    if "platform" in data:
        config.platform = data["platform"]

    if "bot" in data:
        b = data["bot"]
        if isinstance(b, dict) and "provider" in b:
            config.bot.provider.update(b["provider"])

    # For backwards compatibility with legacy YAML structures:
    # If the YAML defines `discord:` directly at top-level, merge its keys into bot.provider
    if "discord" in data and isinstance(data["discord"], dict):
        d = data["discord"]
        config.bot.provider.update(d)
        config.bot.provider["type"] = "discord"

    # Merge platform-specific config keys into config.platforms dict
    core_keys = {"agent", "quota", "activation", "log_level", "platform", "bot", "discord"}
    for k, v in data.items():
        if k not in core_keys:
            if isinstance(v, dict) and k in config.platforms and isinstance(config.platforms[k], dict):
                config.platforms[k].update(v)
            else:
                config.platforms[k] = v

    if "agent" in data:
        a = data["agent"]
        config.agent.name = a.get("name", config.agent.name)
        if "model" in a:
            config.agent.model = a["model"]
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
