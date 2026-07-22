import re
with open('/Users/mcdoolz/dev/ganymede/src/ganymede/cli.py', 'r') as f:
    content = f.read()

target = """    # Dynamically resolve and load active platform provider class
    platform_name = getattr(config, "platform", "discord").lower()
    from ganymede.platforms.base import get_platform_provider_class
    provider_class = get_platform_provider_class(platform_name)
    
    # Factory function to create a Router and its subsystems for a config copy
    def router_factory(inst_config: AppConfig) -> Router:
        quota_tracker = QuotaTracker(inst_config)
        agent_manager = AgentManager(inst_config, quota_tracker, db=db)
        activation = ActivationManager(inst_config)
        router = Router(inst_config, agent_manager, activation, db)
        return router

    # The platform provider class provides the runner instances
    providers = provider_class.create_providers(config, router_factory, db)
    
    # Force-attach the native Web Provider alongside any other configured platform
    from ganymede.platforms.web.provider import WebProvider
    web_provider = WebProvider(config, router_factory(config), db)
    providers.append(web_provider)"""

replacement = """    from ganymede.platforms.base import get_platform_provider_class
    import copy

    # Factory function to create a Router and its subsystems for a config copy
    def router_factory(inst_config: AppConfig) -> Router:
        quota_tracker = QuotaTracker(inst_config)
        agent_manager = AgentManager(inst_config, quota_tracker, db=db)
        activation = ActivationManager(inst_config)
        router = Router(inst_config, agent_manager, activation, db)
        return router

    providers = []
    
    # Iterate through all configured bots
    for bot_id, bot_cfg in config.bots.items():
        try:
            bot_config_copy = copy.copy(config)
            
            # Create a clone of the agent config to override model/identity
            bot_config_copy.agent = copy.copy(config.agent)
            bot_config_copy.bot = copy.copy(config.bot)
            
            if "model" in bot_cfg:
                bot_config_copy.agent.model = bot_cfg["model"]
            if "name" in bot_cfg:
                bot_config_copy.agent.name = bot_cfg["name"]
            if "identity" in bot_cfg:
                bot_config_copy.bot.identity = bot_cfg["identity"]
            if "provider" in bot_cfg:
                bot_config_copy.bot.provider = bot_cfg["provider"]
                
            platform_name = bot_cfg.get("provider", {}).get("type", "discord").lower()
            provider_class = get_platform_provider_class(platform_name)
            
            router = router_factory(bot_config_copy)
            
            # Check if the provider class accepts bot_config in its signature
            import inspect
            sig = inspect.signature(provider_class.__init__)
            if "bot_config" in sig.parameters:
                provider = provider_class(bot_config_copy, router, db, bot_id=bot_id, bot_config=bot_cfg)
            else:
                provider = provider_class(bot_config_copy, router, db)
                provider.bot_id = bot_id
                
            providers.append(provider)
        except Exception as e:
            logger.error("Failed to load provider for bot", bot_id=bot_id, error=str(e))
            
    # Force-attach the native Web Provider if not already present
    has_web = any(p.__class__.__name__ == "WebProvider" for p in providers)
    if not has_web:
        from ganymede.platforms.web.provider import WebProvider
        web_provider = WebProvider(config, router_factory(config), db, bot_id="web-default")
        providers.append(web_provider)"""

if target in content:
    content = content.replace(target, replacement)
    with open('/Users/mcdoolz/dev/ganymede/src/ganymede/cli.py', 'w') as f:
        f.write(content)
    print("Replaced successfully")
else:
    print("Target not found")
