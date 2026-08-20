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
    model: str = "Gemini 3.7 Flash (High)"
    raw_model_string: str = None
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
    mission_statement: str = "to be of help"
    mcp_auth_token: str = "default_secure_token_123"

@dataclass
class QuotaConfig:
    max_tokens_per_context_per_hour: int = 50000
    max_tokens_global_per_hour: int = 200000
    alert_threshold_pct: int = 80
    max_requests_per_minute: int = 15
    max_requests_per_day: int = 1450  # Free tier RPD is 1500; keep 50 as safety margin
    max_concurrent_sessions: int = 3  # Max simultaneous agy turns globally — prevents RPM exhaustion from subagent swarms


@dataclass
class AuthConfig:
    enabled: bool = False
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: list[str] = field(default_factory=list)

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
    identity: str = "You are {bot_name}, a helpful AI assistant. Always begin your response by thinking out loud and explicitly explaining what you are going to do before calling any tools. This ensures the user is kept abreast of your activity. Your mission is {mission_statement}. Additional context about your current channel or project may be provided below — use it to orient your responses."

@dataclass
class AppConfig:
    bot: BotConfig = field(default_factory=BotConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    quota: QuotaConfig = field(default_factory=QuotaConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    activation: ActivationConfig = field(default_factory=ActivationConfig)
    data_dir: str = ""
    log_level: str = "INFO"
    dashboard_port: int = 8180
    platforms: dict[str, Any] = field(default_factory=dict)

    bots: dict[str, Any] = field(default_factory=dict)
    agents: dict[str, Any] = field(default_factory=dict)
    channel_mappings: dict[str, str] = field(default_factory=dict)
    theme: str = "default"

    def __post_init__(self):
        self.platforms = SyncedPlatformsDict(self, self.platforms)
        p_type = self.bot.provider.get("type", "discord")
        self.platforms[p_type] = self.bot.provider
        
        # Populate default agent if none exists
        if "default" not in self.agents:
            self.agents["default"] = {
                "id": "default",
                "name": self.agent.name,
                "model": self.agent.model,
                "workspace": self.agent.workspace,
                "mode": self.agent.mode,
                "skip_permissions": self.agent.skip_permissions,
                "identity": self.bot.identity,
                "mission_statement": self.agent.mission_statement,
                "bindings": [{"provider": p_type, "channels": ["*"]}]
            }
        
        # Populate default bots if none exist for legacy backwards-compat
        if not self.bots:
            self.bots = {
                "default": {
                    "name": self.agent.name,
                    "model": self.agent.model,
                    "identity": self.bot.identity,
                    "provider": self.bot.provider
                }
            }

    def get_agent_profile(self, agent_id: str = "default") -> dict[str, Any]:
        """Retrieve full agent profile dict with fallbacks to global defaults."""
        profile = self.agents.get(agent_id) or self.agents.get("default") or {}
        return {
            "id": profile.get("id", agent_id),
            "name": profile.get("name", self.agent.name),
            "model": profile.get("model", self.agent.model),
            "workspace": profile.get("workspace", self.agent.workspace),
            "mode": profile.get("mode", self.agent.mode),
            "skip_permissions": profile.get("skip_permissions", self.agent.skip_permissions),
            "identity": profile.get("identity", self.bot.identity),
            "mission_statement": profile.get("mission_statement", self.agent.mission_statement),
            "bindings": profile.get("bindings", []),
            "provider_config": profile.get("provider_config", {})
        }

    def get_agent_for_context(self, context: Any) -> dict[str, Any]:
        """Resolve which agent profile governs a given context (e.g. Discord channel)."""
        if not context:
            return self.get_agent_profile("default")
        
        platform = getattr(context, "platform", "discord")
        channel_id = str(getattr(context, "channel_id", "") or "")

        # 1. Direct explicit channel mapping (e.g. "discord:1539870389780348977" -> "rotor")
        direct_key = f"{platform}:{channel_id}"
        if direct_key in self.channel_mappings:
            agent_id = self.channel_mappings[direct_key]
            if agent_id in self.agents:
                return self.get_agent_profile(agent_id)

        # 2. Check each agent's bindings list
        for aid, a_data in self.agents.items():
            if isinstance(a_data, dict) and "bindings" in a_data:
                for b in a_data.get("bindings", []):
                    if isinstance(b, dict) and b.get("provider", "").lower() == platform.lower():
                        channels = [str(c) for c in b.get("channels", [])]
                        if channel_id in channels or "*" in channels:
                            return self.get_agent_profile(aid)

        # 3. Check wildcard platform mapping (e.g. "discord:*" -> "default")
        wildcard_key = f"{platform}:*"
        if wildcard_key in self.channel_mappings:
            agent_id = self.channel_mappings[wildcard_key]
            if agent_id in self.agents:
                return self.get_agent_profile(agent_id)

        # 4. Fallback to default
        return self.get_agent_profile("default")

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

    env_port = os.environ.get("GANYMEDE_PORT")
    if env_port:
        try:
            config.dashboard_port = int(env_port)
        except ValueError:
            pass

    # 4. CLI overrides
    if args:
        if getattr(args, "platform", None):
            config.platform = args.platform
        if getattr(args, "workspace", None):
            config.agent.workspace = args.workspace
        if getattr(args, "log_level", None):
            config.log_level = args.log_level
        if getattr(args, "model", None):
            config.agent.raw_model_string = args.model

    # Final expansions & setup
    config.agent.workspace = os.path.expanduser(config.agent.workspace)
    os.makedirs(config.data_dir, exist_ok=True)

    return config

def _merge_dict_into_config(config: AppConfig, data: dict[str, Any]):
    if "platform" in data:
        config.platform = data["platform"]

    if "theme" in data:
        config.theme = data["theme"]

    if "bots" in data:
        config.bots.update(data["bots"])

    if "bot" in data:
        b = data["bot"]
        if isinstance(b, dict):
            if "provider" in b:
                config.bot.provider.update(b["provider"])
            config.bot.identity = b.get("identity", config.bot.identity)

    # For backwards compatibility with legacy YAML structures:
    # If the YAML defines `discord:` directly at top-level, merge its keys into bot.provider
    if "discord" in data and isinstance(data["discord"], dict):
        d = data["discord"]
        config.bot.provider.update(d)
        config.bot.provider["type"] = "discord"

    if "agents" in data and isinstance(data["agents"], dict):
        config.agents.update(data["agents"])

    if "channel_mappings" in data and isinstance(data["channel_mappings"], dict):
        config.channel_mappings.update(data["channel_mappings"])

    if "providers" in data and isinstance(data["providers"], dict):
        for p_name, p_cfg in data["providers"].items():
            if isinstance(p_cfg, dict):
                if p_name in config.platforms and isinstance(config.platforms[p_name], dict):
                    config.platforms[p_name].update(p_cfg)
                else:
                    config.platforms[p_name] = p_cfg
                if p_name == config.platform:
                    config.bot.provider.update(p_cfg)

    # Merge platform-specific config keys into config.platforms dict
    core_keys = {"agent", "agents", "channel_mappings", "providers", "quota", "activation", "log_level", "platform", "bot", "bots", "discord", "auth", "theme", "dashboard_port"}
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
    if "auth" in data:
        au = data["auth"]
        config.auth.enabled = au.get("enabled", config.auth.enabled)
        config.auth.google_client_id = au.get("google_client_id", config.auth.google_client_id)
        config.auth.google_client_secret = au.get("google_client_secret", config.auth.google_client_secret)
        config.auth.allowed_emails = au.get("allowed_emails", config.auth.allowed_emails)
    config.log_level = data.get("log_level", config.log_level)
    config.dashboard_port = data.get("dashboard_port", config.dashboard_port)
