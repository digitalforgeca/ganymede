import re

with open('/Users/mcdoolz/dev/ganymede/src/ganymede/core/web.py', 'r') as f:
    lines = f.readlines()

def extract_method(method_name):
    start = -1
    end = -1
    for i, line in enumerate(lines):
        if line.startswith(f"    async def {method_name}(") or line.startswith(f"    def {method_name}("):
            start = i
            break
    if start == -1:
        return ""
    
    for i in range(start + 1, len(lines)):
        if lines[i].startswith("    def ") or lines[i].startswith("    async def ") or lines[i].startswith("class "):
            end = i
            break
    if end == -1:
        end = len(lines)
        
    method_lines = lines[start:end]
    # Remove one level of indentation
    out = []
    for line in method_lines:
        if line.startswith("    "):
            out.append(line[4:])
        else:
            out.append(line)
            
    # replace "self" with "server"
    out_text = "".join(out)
    out_text = out_text.replace("def " + method_name + "(self,", "def " + method_name + "(server,")
    out_text = out_text.replace("def " + method_name + "(self)", "def " + method_name + "(server)")
    out_text = re.sub(r'\bself\.', 'server.', out_text)
    return out_text

groups = {
    "dashboard": ["handle_index", "handle_status", "handle_user_info", "handle_dashboard_ws", "handle_files"],
    "chats": ["handle_chats", "handle_chat_history", "handle_chat_files", "handle_chat_merge", "handle_chat_fork", "handle_chat_settings_get", "handle_chat_settings_post", "handle_chat_invoke"],
    "config": ["handle_config_get", "handle_config_post", "handle_rules_get", "handle_rules_post", "handle_rule_delete", "handle_bot_conversations"],
    "telemetry": ["handle_telemetry_ws", "handle_telemetry_post"],
    "ipc": ["handle_ipc_request", "handle_schedule_cron", "handle_status_update", "handle_test_invoke"]
}

imports = """import os
import asyncio
import structlog
import json
import yaml
from aiohttp import web
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()
"""

for group, methods in groups.items():
    code = imports + "\n"
    for m in methods:
        code += extract_method(m) + "\n"
    
    with open(f"/Users/mcdoolz/dev/ganymede/src/ganymede/core/routes/{group}.py", "w") as f:
        f.write(code)

