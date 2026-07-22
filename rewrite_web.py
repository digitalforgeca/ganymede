import re

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    lines = f.readlines()

new_lines = []
for line in lines:
    if line.startswith("    async def handle_") or line.startswith("    def handle_"):
        break
    new_lines.append(line)

code = "".join(new_lines)
code += """
from ganymede.core.routes.dashboard import handle_index, handle_status, handle_user_info, handle_dashboard_ws, handle_files
from ganymede.core.routes.chats import handle_chats, handle_chat_history, handle_chat_files, handle_chat_merge, handle_chat_fork, handle_chat_settings_get, handle_chat_settings_post, handle_chat_invoke
from ganymede.core.routes.config import handle_config_get, handle_config_post, handle_rules_get, handle_rules_post, handle_rule_delete, handle_bot_conversations
from ganymede.core.routes.telemetry import handle_telemetry_ws, handle_telemetry_post
from ganymede.core.routes.ipc import handle_ipc_request, handle_schedule_cron, handle_status_update, handle_test_invoke

DashboardServer.handle_index = handle_index
DashboardServer.handle_status = handle_status
DashboardServer.handle_user_info = handle_user_info
DashboardServer.handle_dashboard_ws = handle_dashboard_ws
DashboardServer.handle_files = handle_files

DashboardServer.handle_chats = handle_chats
DashboardServer.handle_chat_history = handle_chat_history
DashboardServer.handle_chat_files = handle_chat_files
DashboardServer.handle_chat_merge = handle_chat_merge
DashboardServer.handle_chat_fork = handle_chat_fork
DashboardServer.handle_chat_settings_get = handle_chat_settings_get
DashboardServer.handle_chat_settings_post = handle_chat_settings_post
DashboardServer.handle_chat_invoke = handle_chat_invoke

DashboardServer.handle_config_get = handle_config_get
DashboardServer.handle_config_post = handle_config_post
DashboardServer.handle_rules_get = handle_rules_get
DashboardServer.handle_rules_post = handle_rules_post
DashboardServer.handle_rule_delete = handle_rule_delete
DashboardServer.handle_bot_conversations = handle_bot_conversations

DashboardServer.handle_telemetry_ws = handle_telemetry_ws
DashboardServer.handle_telemetry_post = handle_telemetry_post

DashboardServer.handle_ipc_request = handle_ipc_request
DashboardServer.handle_schedule_cron = handle_schedule_cron
DashboardServer.handle_status_update = handle_status_update
DashboardServer.handle_test_invoke = handle_test_invoke
"""

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'w') as f:
    f.write(code)

