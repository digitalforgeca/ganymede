import os
import asyncio
import structlog
import json
import yaml
from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from ganymede.config import AppConfig
from ganymede.core import ContextKey

logger = structlog.get_logger()

router = APIRouter()

@router.get('/api/chats')
async def handle_chats(request: Request):
    server = request.app.state.server
    # Return all unique contexts from the conversations table by doing a group by
    
    # We need a reference to DB. Let's see if we can get it from the globally injected db or router
    
    # We will just fetch directly from DB if available, else return empty
    # Wait, the DashboardServer doesn't have db injected in __init__ currently.
    # Let's import it or just query the sqlite directly since we have data_dir
    import aiosqlite
    db_path = os.path.join(server.config.data_dir, "ganymede.db")
    
    chats = []
    if os.path.exists(db_path):
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            
            # Fetch Ganymede-native conversations
            async with conn.execute("""
                SELECT context_platform, context_channel, context_thread, MAX(created_at) as last_active, COUNT(id) as msg_count
                FROM conversations 
                GROUP BY context_platform, context_channel, context_thread
                ORDER BY last_active DESC
            """) as cursor:
                rows = await cursor.fetchall()
                for r in rows:
                    conversation_id = f"{r['context_platform']}_{r['context_channel']}"
                    if r['context_thread']:
                        conversation_id += f"_{r['context_thread']}"
                        
                    actual_conv_id = conversation_id
                    try:
                        async with conn.execute(
                            "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                            (r["context_platform"], r["context_channel"], r["context_thread"], r["context_thread"])
                        ) as map_cursor:
                            map_row = await map_cursor.fetchone()
                            if map_row:
                                actual_conv_id = map_row["conversation_id"]
                    except Exception:
                        pass
                        
                    ctx = ContextKey(r['context_platform'], r['context_channel'], r['context_thread'])
                    project_name = ctx.project_name
                        
                    brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}")
                    project_name_path = os.path.join(brain_dir, "project_name.txt")
                    if os.path.exists(project_name_path):
                        try:
                            with open(project_name_path, "r") as f:
                                pname = f.read().strip()
                            if pname:
                                project_name = pname
                        except Exception:
                            pass
                            
                    chats.append({
                        "platform": r["context_platform"],
                        "channel_id": r["context_channel"],
                        "thread_id": r["context_thread"],
                        "last_active": r["last_active"],
                        "msg_count": r["msg_count"],
                        "id": f"{r['context_platform']}_{r['context_channel']}_{r['context_thread'] or 'main'}",
                        "actual_conv_id": actual_conv_id,
                        "project_name": project_name
                    })
                    
    # Merge Antigravity CLI native conversations from brain directory
    brain_dir = os.path.expanduser("~/.gemini/antigravity-cli/brain")
    if os.path.exists(brain_dir):
        ganymede_conv_ids = {c.get("actual_conv_id") for c in chats if c.get("actual_conv_id")}
        try:
            cli_chats = []
            for entry in os.listdir(brain_dir):
                if entry in ganymede_conv_ids or entry == "telemetry.db" or not os.path.isdir(os.path.join(brain_dir, entry)):
                    continue
                    
                # Get modification time of transcript.jsonl if it exists
                transcript_path = os.path.join(brain_dir, entry, ".system_generated", "logs", "transcript.jsonl")
                last_mod = 0
                msg_count = 0
                if os.path.exists(transcript_path):
                    last_mod = os.stat(transcript_path).st_mtime
                    try:
                        with open(transcript_path, 'rb') as f:
                            msg_count = sum(1 for _ in f)
                    except Exception:
                        pass
                else:
                    continue
                    
                pname = f"cli-{entry[:8]}"
                pname_path = os.path.join(brain_dir, entry, "project_name.txt")
                if os.path.exists(pname_path):
                    try:
                        with open(pname_path, "r") as f:
                            pname = f.read().strip() or pname
                    except Exception:
                        pass
                        
                import datetime
                cli_chats.append({
                    "platform": "cli",
                    "channel_id": entry[:8],
                    "thread_id": None,
                    "last_active": datetime.datetime.fromtimestamp(last_mod).strftime('%Y-%m-%d %H:%M:%S'),
                    "msg_count": msg_count,
                    "id": f"cli_{entry}_main",
                    "actual_conv_id": entry,
                    "project_name": pname
                })
            
            cli_chats.sort(key=lambda x: x["last_active"], reverse=True)
            chats.extend(cli_chats[:20])
        except Exception as e:
            print(f"Error fetching brain chats: {e}")
            
    # Re-sort combined list
    chats.sort(key=lambda x: x["last_active"], reverse=True)
    return {"chats": chats}


@router.get('/api/chats/{id}/history')
async def handle_chat_history(request: Request):
    server = request.app.state.server
    context_id = request.path_params.get('id', '')
    parts = context_id.split('_')
    if len(parts) < 3:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    platform = parts[0]
    channel_id = parts[1]
    thread_id = parts[2] if parts[2] != 'main' else None
    
    actual_conv_id = channel_id if platform == "cli" else None
    
    if platform != "cli":
        db_path = os.path.join(server.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                async with conn.execute(
                    "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                    (platform, channel_id, thread_id, thread_id)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        actual_conv_id = row["conversation_id"]

    history = []
    if actual_conv_id:
        transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}/.system_generated/logs/transcript_full.jsonl")
        if not os.path.exists(transcript_path):
            transcript_path = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{actual_conv_id}/.system_generated/logs/transcript.jsonl")
        
        if os.path.exists(transcript_path):
            import json
            try:
                with open(transcript_path, 'r') as f:
                    for line in f:
                        if not line.strip():
                            continue
                        try:
                            data = json.loads(line)
                        except Exception:
                            continue
                        if data.get("type") == "USER_INPUT":
                            history.append({
                                "author_id": "User",
                                "role": "user",
                                "content": data.get("content", ""),
                                "created_at": data.get("created_at", "")
                            })
                        elif data.get("type") == "PLANNER_RESPONSE" or data.get("type") == "TEXT_RESPONSE":
                            content = data.get("content", "")
                            tool_calls = data.get("tool_calls", [])
                            if tool_calls:
                                tool_text = "\n\n*⚒️ Tools Used:*\n"
                                for t in tool_calls:
                                    t_name = t.get('name') or t.get('function', {}).get('name') or 'tool'
                                    args = t.get('args') or t.get('function', {}).get('arguments') or {}
                                    try:
                                        if isinstance(args, str):
                                            args_formatted = json.dumps(json.loads(args), indent=2)
                                        else:
                                            args_formatted = json.dumps(args, indent=2)
                                    except Exception:
                                        args_formatted = str(args)
                                        
                                    tool_text += f"<details><summary><code>{t_name}</code></summary>\n\n```json\n{args_formatted}\n```\n\n</details>\n"
                                
                                content = (content + tool_text) if content else tool_text.strip()
                            
                            if content:
                                history.append({
                                    "author_id": "Antigravity",
                                    "role": "assistant",
                                    "content": content,
                                    "created_at": data.get("created_at", "")
                                })
            except Exception as e:
                print(f"Error reading transcript: {e}")

    # Fallback to database if no transcript history found
    if not history and platform != "cli":
        db_path = os.path.join(server.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            async with aiosqlite.connect(db_path) as conn:
                conn.row_factory = aiosqlite.Row
                query = """
                    SELECT author_id, role, content, tokens, created_at
                    FROM conversations
                    WHERE context_platform = ? AND context_channel = ? AND (context_thread = ? OR (context_thread IS NULL AND ? IS NULL))
                    ORDER BY created_at ASC
                """
                async with conn.execute(query, (platform, channel_id, thread_id, thread_id)) as cursor:
                    rows = await cursor.fetchall()
                    for r in rows:
                        history.append({
                            "author_id": r["author_id"],
                            "role": r["role"],
                            "content": r["content"],
                            "created_at": r["created_at"]
                        })
                        
    return {"messages": history}


@router.get('/api/chats/{id}/files')
async def handle_chat_files(request: Request):
    server = request.app.state.server
    context_id = request.path_params.get('id', '')
    parts = context_id.split('_')
    if len(parts) < 3:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    platform = parts[0]
    channel_id = parts[1]
    thread_id = parts[2] if parts[2] != 'main' else None
    
    db_path = os.path.join(server.config.data_dir, "ganymede.db")
    conversation_id = f"ganymede-{platform}-{channel_id}"
    if thread_id:
        conversation_id += f"-{thread_id}"
        
    # Check mapping table to resolve merged context
    if os.path.exists(db_path):
        import aiosqlite
        async with aiosqlite.connect(db_path) as conn:
            conn.row_factory = aiosqlite.Row
            async with conn.execute(
                "SELECT conversation_id FROM conversation_mappings WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))",
                (platform, channel_id, thread_id, thread_id)
            ) as cursor:
                row = await cursor.fetchone()
                if row and row["conversation_id"]:
                    conversation_id = row["conversation_id"]
                    
    # The default AGY workspace path for artifacts
    # We can also check if there's a local .gemini folder or use the default global
    # Let's check ~/.gemini/antigravity-cli/brain/{conversation_id}
    agy_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
    files_data = []
    
    if os.path.exists(agy_brain_dir):
        for root, dirs, files in os.walk(agy_brain_dir):
            # Optionally exclude logs
            if ".system_generated" in root:
                continue
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, agy_brain_dir)
                size = os.path.getsize(full_path)
                files_data.append({"name": file, "path": rel_path, "size": size})
                
    return {"files": files_data, "workspace": agy_brain_dir}


@router.post('/api/chats/{id}/merge')
async def handle_chat_merge(request: Request):
    server = request.app.state.server
    context_id = request.path_params.get('id', '')
    data = await request.json()
    target_conversation_id = data.get('target_conversation_id')
    
    if not target_conversation_id:
        return JSONResponse({"error": "Missing target_conversation_id"}, status_code=400)
        
    parts = context_id.split('_')
    if len(parts) < 3:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    platform = parts[0]
    channel_id = parts[1]
    thread_id = parts[2] if parts[2] != 'main' else None
    
    db_path = os.path.join(server.config.data_dir, "ganymede.db")
    if os.path.exists(db_path):
        import aiosqlite
        async with aiosqlite.connect(db_path) as conn:
            # Merge logic: We explicitly map this (platform, channel, thread) to the target_conversation_id
            await conn.execute(
                """
                INSERT INTO conversation_mappings (platform, channel_id, thread_id, conversation_id)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(platform, channel_id, thread_id) DO UPDATE SET
                    conversation_id = excluded.conversation_id
                """,
                (platform, channel_id, thread_id, target_conversation_id)
            )
            await conn.commit()
    
    return {"status": "merged", "target_conversation_id": target_conversation_id}


@router.post('/api/chats/{id}/fork')
async def handle_chat_fork(request: Request):
    server = request.app.state.server
    import uuid
    import shutil
    
    context_id = request.path_params.get('id', '')
    conversation_id = await server._resolve_conversation_id(context_id)
    if not conversation_id:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    parts = context_id.split('_')
    platform = parts[0]
    channel_id = parts[1]
    thread_id = parts[2] if parts[2] != 'main' else None
    
    new_thread_id = f"fork-{uuid.uuid4().hex[:8]}"
    new_conversation_id = f"ganymede-{platform}-{channel_id}-{new_thread_id}"
    
    # 1. Copy agy brain dir
    old_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
    new_brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{new_conversation_id}")
    if os.path.exists(old_brain_dir):
        shutil.copytree(old_brain_dir, new_brain_dir)
        
    # 2. Copy DB History
    db_path = os.path.join(server.config.data_dir, "ganymede.db")
    if os.path.exists(db_path):
        import aiosqlite
        async with aiosqlite.connect(db_path) as conn:
            await conn.execute(
                """
                INSERT INTO conversations (context_platform, context_channel, context_thread, author_id, role, content, tokens, created_at)
                SELECT context_platform, context_channel, ?, author_id, role, content, tokens, created_at
                FROM conversations
                WHERE context_platform = ? AND context_channel = ? AND (context_thread = ? OR (context_thread IS NULL AND ? IS NULL))
                """,
                (new_thread_id, platform, channel_id, thread_id, thread_id)
            )
            await conn.commit()
            
    new_context_id = f"{platform}_{channel_id}_{new_thread_id}"
    return {"status": "forked", "new_context_id": new_context_id}


@router.get('/api/chats/{id}/settings')
async def handle_chat_settings_get(request: Request):
    server = request.app.state.server
    context_id = request.path_params.get('id', '')
    conversation_id = await server._resolve_conversation_id(context_id)
    if not conversation_id:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
    
    # Read Model
    model_path = os.path.join(brain_dir, "model.txt")
    model_override = ""
    if os.path.exists(model_path):
        with open(model_path, "r") as f:
            model_override = f.read().strip()
            
    # Read Project Name
    project_name_path = os.path.join(brain_dir, "project_name.txt")
    project_name = ""
    if os.path.exists(project_name_path):
        with open(project_name_path, "r") as f:
            project_name = f.read().strip()
    else:
        # Generate default
        parts = context_id.split('_')
        platform = parts[0]
        channel_id = parts[1]
        thread_id = parts[2] if len(parts) > 2 and parts[2] != 'main' else None
        ctx = ContextKey(platform, channel_id, thread_id)
        project_name = ctx.project_name
            
    # Read Mode
    mode_path = os.path.join(brain_dir, "mode.txt")
    mode = "accept-edits"
    if os.path.exists(mode_path):
        with open(mode_path, "r") as f:
            mode = f.read().strip()
            
    # Read Rules
    rules_path = os.path.join(brain_dir, "sys_instructions.txt")
    rules = ""
    if os.path.exists(rules_path):
        with open(rules_path, "r") as f:
            rules = f.read().strip()

    # Read Skip Permissions
    skip_permissions = False
    skip_permissions_path = os.path.join(brain_dir, "skip_permissions.txt")
    if os.path.exists(skip_permissions_path):
        with open(skip_permissions_path, "r") as f:
            skip_permissions = f.read().strip() == "true"
            
    return {
        "model": model_override, 
        "project_name": project_name,
        "mode": mode,
        "skip_permissions": skip_permissions,
        "rules": rules
    }
    

@router.post('/api/chats/{id}/settings')
async def handle_chat_settings_post(request: Request):
    server = request.app.state.server
    context_id = request.path_params.get('id', '')
    conversation_id = await server._resolve_conversation_id(context_id)
    if not conversation_id:
        return JSONResponse({"error": "Invalid context ID format"}, status_code=400)
        
    data = await request.json()
    model_override = data.get("model", "").strip()
    project_name = data.get("project_name", "").strip()
    
    brain_dir = os.path.expanduser(f"~/.gemini/antigravity-cli/brain/{conversation_id}")
    os.makedirs(brain_dir, exist_ok=True)
    
    model_path = os.path.join(brain_dir, "model.txt")
    if model_override:
        with open(model_path, "w") as f:
            f.write(model_override)
    elif os.path.exists(model_path):
        os.remove(model_path)
        
    project_name_path = os.path.join(brain_dir, "project_name.txt")
    if project_name:
        with open(project_name_path, "w") as f:
            f.write(project_name)
    elif os.path.exists(project_name_path):
        os.remove(project_name_path)
        
    mode = data.get("mode", "")
    mode_path = os.path.join(brain_dir, "mode.txt")
    if mode:
        with open(mode_path, "w") as f:
            f.write(mode)
    elif os.path.exists(mode_path):
        os.remove(mode_path)
        
    skip_permissions = data.get("skip_permissions")
    skip_permissions_path = os.path.join(brain_dir, "skip_permissions.txt")
    if skip_permissions is not None:
        with open(skip_permissions_path, "w") as f:
            f.write("true" if skip_permissions else "false")
    elif os.path.exists(skip_permissions_path):
        os.remove(skip_permissions_path)
        
    rules = data.get("rules")
    rules_path = os.path.join(brain_dir, "sys_instructions.txt")
    if rules is not None:
        if rules.strip() == "":
            if os.path.exists(rules_path):
                os.remove(rules_path)
        else:
            with open(rules_path, "w") as f:
                f.write(rules)
        
    # Log this change directly into the chat history for visibility
    try:
        db_path = os.path.join(server.config.data_dir, "ganymede.db")
        if os.path.exists(db_path):
            import aiosqlite
            parts = context_id.split('_')
            platform = parts[0]
            channel_id = parts[1]
            thread_id = parts[2] if parts[2] != 'main' else None
            async with aiosqlite.connect(db_path) as conn:
                content = "⚙️ *Administrator updated project settings:*"
                if model_override:
                    content += f"\n- **Model**: `{model_override}`"
                if project_name:
                    content += f"\n- **Project Name**: `{project_name}`"
                if not model_override and not project_name:
                    content += "\n- Restored to defaults."
                    
                await conn.execute(
                    """
                    INSERT INTO conversations (context_platform, context_channel, context_thread, author_id, role, content, tokens)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (platform, channel_id, thread_id, "system", "system", content, 0)
                )
                await conn.commit()
    except Exception as e:
        logger.error("Failed to log settings change to db", error=str(e))
        
    return {"status": "saved", "model": model_override, "project_name": project_name}


@router.post('/api/chat/invoke')
async def handle_chat_invoke(request: Request):
    server = request.app.state.server
    if server.web_invoke_callback:
        return await server.web_invoke_callback(request)
    return JSONResponse({"error": "WebProvider not initialized"}, status_code=503)


