with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    content = f.read()

# Add route bindings
route_setup_target = "self.app.router.add_get('/api/config', self.handle_config_get)"
route_setup_replacement = """self.app.router.add_get('/api/config', self.handle_config_get)
        self.app.router.add_get('/api/providers', self.handle_providers_get)
        self.app.router.add_get('/api/bots', self.handle_bots_get)
        self.app.router.add_post('/api/bots/{bot_id}', self.handle_bot_post)
        self.app.router.add_delete('/api/bots/{bot_id}', self.handle_bot_delete)"""
if route_setup_target in content:
    content = content.replace(route_setup_target, route_setup_replacement)
else:
    print("Failed to find route setup")

# Add imports
import_target = "from ganymede.core.routes.config import handle_config_get, handle_config_post, handle_rules_get, handle_rules_post, handle_rule_delete, handle_bot_conversations"
import_replacement = "from ganymede.core.routes.config import handle_config_get, handle_config_post, handle_rules_get, handle_rules_post, handle_rule_delete, handle_bot_conversations, handle_providers_get, handle_bots_get, handle_bot_post, handle_bot_delete"
if import_target in content:
    content = content.replace(import_target, import_replacement)
else:
    print("Failed to find imports")

# Add bindings
binding_target = "DashboardServer.handle_config_get = handle_config_get"
binding_replacement = """DashboardServer.handle_config_get = handle_config_get
DashboardServer.handle_providers_get = handle_providers_get
DashboardServer.handle_bots_get = handle_bots_get
DashboardServer.handle_bot_post = handle_bot_post
DashboardServer.handle_bot_delete = handle_bot_delete"""
if binding_target in content:
    content = content.replace(binding_target, binding_replacement)
else:
    print("Failed to find bindings")

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'w') as f:
    f.write(content)
print("web.py patched successfully")
