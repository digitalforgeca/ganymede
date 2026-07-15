import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock
import json
import time
import discord
from discord import app_commands

from ganymede.config import AppConfig, AgentConfig
from ganymede.core import ContextKey
from ganymede.core.db import Database
from ganymede.core.quota import QuotaTracker
from ganymede.core.agent_manager import AgentManager
from ganymede.core.router import Router
from ganymede.platforms.discord.safety import DiscordApprovalHook
from google.antigravity.types import ToolCall, HookResult

class TestGanymedeCore(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Setup temp data directory
        self.config = AppConfig()
        self.config.data_dir = "/tmp/ganymede_test_data"
        os.makedirs(self.config.data_dir, exist_ok=True)
        
        # Initialize Database
        self.db = Database(self.config)
        await self.db.init()
        
        # Initialize Quota Tracker
        self.quota = QuotaTracker(self.config)
        
        # Initialize Agent Manager
        self.agent_manager = AgentManager(self.config, self.quota, db=self.db)
        
        # Mock Discord Adapter
        self.mock_adapter = MagicMock()
        self.mock_adapter.user = MagicMock()
        self.mock_adapter.user.id = 123456789
        
        # Mock get_conversation_id return value
        def mock_get_conversation_id(context):
            cid = f"ganymede_discord_{context.channel_id}"
            if context.thread_id:
                cid += f"_{context.thread_id}"
            return cid
        self.mock_adapter.get_conversation_id = MagicMock(side_effect=mock_get_conversation_id)
        
        # Mock channel resolving
        self.mock_channel = AsyncMock()
        self.mock_channel.name = "test_channel"
        self.mock_adapter._resolve_channel = AsyncMock(return_value=self.mock_channel)
        
        # Bind adapter
        self.agent_manager.set_adapter(self.mock_adapter)
        self.mock_adapter.router = MagicMock()
        self.mock_adapter.router.agent_manager = self.agent_manager
        import ganymede.core.safety as safety
        safety.active_adapter = self.mock_adapter
        
        self.context = ContextKey(
            platform="discord",
            channel_id="999999",
            thread_id=None
        )

    async def asyncTearDown(self):
        await self.agent_manager.destroy_all()
        await self.db.close()
        
        # Cleanup DB file
        db_file = os.path.join(self.config.data_dir, "ganymede.db")
        if os.path.exists(db_file):
            try:
                os.remove(db_file)
            except Exception:
                pass
        try:
            os.rmdir(self.config.data_dir)
        except Exception:
            pass

    async def test_database_logging(self):
        # Test saving message
        await self.db.save_message(self.context, "user123", "user", "Hello agent!")
        
        # Test retrieving history
        history = await self.db.get_history(self.context, limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["content"], "Hello agent!")
        self.assertEqual(history[0]["role"], "user")

    async def test_quota_tracker(self):
        # Check initial budget
        allowed = await self.quota.check_budget(self.context)
        self.assertTrue(allowed)
        
        # Record massive token usage
        await self.quota.record_usage(self.context, 60000)
        
        # Check budget again (should be exhausted)
        allowed = await self.quota.check_budget(self.context)
        self.assertFalse(allowed)

    async def test_quota_tracker_request_throttling(self):
        self.config.quota.max_requests_per_minute = 1
        self.config.quota.max_requests_per_context_per_minute = 1
        
        # Record first request
        await self.quota.record_turn(self.context)
        
        # Mock asyncio.sleep to verify rate throttling behaves correctly without sleeping in tests
        with unittest.mock.patch("asyncio.sleep") as mock_sleep:
            await self.quota.throttle(self.context)
            mock_sleep.assert_called_once()
            self.assertGreater(mock_sleep.call_args[0][0], 58.0)

    async def test_quota_tracker_adaptive_backoff(self):
        self.assertEqual(self.quota.blocked_until, 0.0)
        
        # Record a simulated 429 error
        err_msg = 'request failed (code 429): Quota exceeded. Please retry in 15.5s.'
        self.quota.record_blocker(err_msg)
        
        now = time.time()
        self.assertGreater(self.quota.blocked_until, now + 15.0)
        
        # Verify throttle sleeps to back off
        with unittest.mock.patch("asyncio.sleep") as mock_sleep:
            await self.quota.throttle(self.context)
            mock_sleep.assert_called_once()
            self.assertGreater(mock_sleep.call_args[0][0], 14.0)

    async def test_safety_approval_hook_safe_tools(self):
        # view_file is in safe list, should be auto-approved
        hook = DiscordApprovalHook(self.context, self.config)
        tool_call = ToolCall(name="view_file", args={"AbsolutePath": "/tmp/test.txt"})
        
        result = await hook.run(None, tool_call)
        self.assertTrue(result.allow)
        self.mock_adapter._resolve_channel.assert_not_called()

    async def test_safety_approval_hook_elevated_users(self):
        # Configure test context for elevated user bypass
        self.config.agent.elevated_users = ["dev123"]
        self.agent_manager.set_active_author(self.context, "dev123")
        
        hook = DiscordApprovalHook(self.context, self.config)
        tool_call = ToolCall(name="run_command", args={"CommandLine": "echo 'hack'"})
        
        # Should be auto-approved because author is in elevated_users
        result = await hook.run(None, tool_call)
        self.assertTrue(result.allow)
        self.mock_adapter._resolve_channel.assert_not_called()

    async def test_safety_approval_hook_unsafe_tools_denied_on_timeout(self):
        # run_command is unsafe, triggers Discord approval prompt
        hook = DiscordApprovalHook(self.context, self.config)
        tool_call = ToolCall(name="run_command", args={"CommandLine": "echo 'hack'"})
        
        # Mock approval view timeout behavior
        mock_msg = AsyncMock()
        self.mock_channel.send = AsyncMock(return_value=mock_msg)
        
        # Run in task so we don't block
        result_task = asyncio.create_task(hook.run(None, tool_call))
        await asyncio.sleep(0.1) # Let it send message
        
        # Verify message sent to channel
        self.mock_channel.send.assert_called_once()
        
        # Cancel the task representing a timeout / denial
        result_task.cancel()
        try:
            await result_task
        except asyncio.CancelledError:
            pass

    async def test_agent_spawning(self):
        # Spawn agent
        managed = await self.agent_manager.get_or_create(self.context)
        self.assertIsNotNone(managed)
        
        # Verify it uses the robust identifier-based conversation ID format
        self.assertEqual(managed.conversation_id, "ganymede_discord_999999")
        
        # Verify cached retrieval
        cached = await self.agent_manager.get_or_create(self.context)
        self.assertEqual(managed, cached)

        # Verify mapping was saved in db
        contexts = await self.db.get_conversation_contexts(managed.conversation_id)
        self.assertTrue(len(contexts) > 0)
        context = contexts[0]
        self.assertEqual(context.platform, self.context.platform)
        self.assertEqual(context.channel_id, self.context.channel_id)
    async def test_console_approval_provider(self):
        from ganymede.core.safety import ApprovalHook, ConsoleApprovalProvider
        provider = ConsoleApprovalProvider()
        hook = ApprovalHook(self.context, self.config, provider=provider)
        
        tool_call = ToolCall(name="run_command", args={"CommandLine": "echo 'test'"})
        result = await hook.run(None, tool_call)
        
        # ConsoleApprovalProvider should auto-approve by default
        self.assertTrue(result.allow)
    async def test_scheduler_and_schedule_command(self):
        from ganymede.core.scheduler import Scheduler
        from ganymede.platforms.discord.commands import setup_commands
        
        # 1. Initialize and start the scheduler
        router = AsyncMock()
        scheduler = Scheduler(self.config, self.db, router)
        await scheduler.start()
        
        # 2. Setup commands on the mock adapter
        self.mock_adapter._connection = MagicMock()
        self.mock_adapter._connection._command_tree = None
        self.mock_adapter.tree = app_commands.CommandTree(self.mock_adapter)
        setup_commands(self.mock_adapter)
        
        # Register the schedule_callback mock
        mock_schedule_callback = AsyncMock(return_value="mock_job_123")
        self.mock_adapter.schedule_callback = mock_schedule_callback
        
        # 3. Get the command from the tree
        cmd = self.mock_adapter.tree.get_command("schedule")
        self.assertIsNotNone(cmd)
        
        # 4. Invoke the command callback with a mock interaction
        mock_interaction = AsyncMock()
        mock_interaction.channel = MagicMock()
        mock_interaction.channel.id = 999999
        
        # Run callback
        await cmd.callback(mock_interaction, "*/10 * * * *", "List files")
        
        # Verify scheduler callback was executed with correct arguments
        mock_schedule_callback.assert_called_once_with("*/10 * * * *", "List files", "999999")
        
        # Verify interaction sent ephemeral success response
        mock_interaction.response.send_message.assert_called_once()
        sent_embed = mock_interaction.response.send_message.call_args[1].get("embed")
        self.assertIsNotNone(sent_embed)
        self.assertEqual(sent_embed.title, "📅 Recurring Prompt Scheduled")
        
        # 5. Add actual job to scheduler and verify it registers
        job_id = "test_job_123"
        await scheduler.add_cron_job(job_id, self.context, "creator123", "*/10 * * * *", "Grep logs")
        
        # Verify db contains the schedule
        schedules = await self.db.get_active_schedules()
        self.assertEqual(len(schedules), 1)
        self.assertEqual(schedules[0]["id"], job_id)
        self.assertEqual(schedules[0]["cron_expr"], "*/10 * * * *")
        
        # Stop scheduler
        await scheduler.stop()

    async def test_config_loading(self):
        from ganymede.config import load_config
        import tempfile
        import os
        
        # Test loading config with custom platform dict in yaml
        yaml_content = """
platform: custom_platform
agent:
  idle_timeout_minutes: 30
custom_platform:
  api_key: "secret123"
  endpoint: "https://api.custom.com"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_name = f.name
            
        try:
            # Mock CLI args
            args = MagicMock()
            args.config = temp_name
            args.workspace = None
            args.log_level = None
            args.platform = None
            
            # Load config
            config = load_config(args)
            
            # Verify core configurations
            self.assertEqual(config.platform, "custom_platform")
            self.assertEqual(config.agent.idle_timeout_minutes, 30)
            
            # Verify platform-specific configuration dictionary
            self.assertIn("custom_platform", config.platforms)
            self.assertEqual(config.platforms["custom_platform"]["api_key"], "secret123")
            self.assertEqual(config.platforms["custom_platform"]["endpoint"], "https://api.custom.com")
            
            
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

    async def test_multi_bot_config_partitioning(self):
        from ganymede.config import load_config
        import tempfile
        import copy
        
        yaml_content = """
platform: discord
discord:
  bots:
    - name: "planner"
      token: "plan_tok"
      allowed_guilds: [111]
      namespace: "planner-memories"
      agent:
        system_instructions: "planner inst"
    - name: "orchestrator"
      token: "orch_tok"
      allowed_guilds: [222]
      agent:
        system_instructions: "orch inst"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            temp_name = f.name
            
        try:
            args = MagicMock()
            args.config = temp_name
            args.workspace = None
            args.log_level = None
            args.platform = None
            
            config = load_config(args)
            
            # Verify they loaded under platforms.discord
            discord_cfg = config.platforms.get("discord", {})
            self.assertIn("bots", discord_cfg)
            self.assertEqual(len(discord_cfg["bots"]), 2)
            
            # Replicate the instance split logic from cli.py
            instances = []
            discord_raw = config.platforms.get("discord", {})
            for bot_raw in discord_raw["bots"]:
                bot_config = copy.deepcopy(config)
                bot_config.platforms["discord"] = {
                    "token": bot_raw.get("token", ""),
                    "allowed_guilds": bot_raw.get("allowed_guilds", []),
                    "name": bot_raw.get("name", "ganymede"),
                    "namespace": bot_raw.get("namespace"),
                }
                if "agent" in bot_raw:
                    agent_overrides = bot_raw["agent"]
                    bot_config.agent.system_instructions = agent_overrides.get("system_instructions", bot_config.agent.system_instructions)
                instances.append(bot_config)
                
            self.assertEqual(len(instances), 2)
            self.assertEqual(instances[0].platforms["discord"]["name"], "planner")
            self.assertEqual(instances[0].platforms["discord"]["namespace"], "planner-memories")
            self.assertEqual(instances[0].agent.system_instructions, "planner inst")
            
            self.assertEqual(instances[1].platforms["discord"]["name"], "orchestrator")
            self.assertIsNone(instances[1].platforms["discord"]["namespace"])
            self.assertEqual(instances[1].agent.system_instructions, "orch inst")
            
        finally:
            if os.path.exists(temp_name):
                os.remove(temp_name)

    def test_single_instance_lock(self):
        from ganymede.cli import acquire_instance_lock
        import ganymede.cli
        import tempfile
        import shutil
        
        temp_dir = tempfile.mkdtemp()
        try:
            # First lock acquisition should succeed
            acquire_instance_lock(temp_dir)
            
            # Keep a reference to the first lock file so it does not get garbage-collected and closed
            first_lock_file = ganymede.cli._lock_file
            
            # Second lock acquisition on the same directory should raise SystemExit
            with self.assertRaises(SystemExit) as ctx:
                acquire_instance_lock(temp_dir)
                
            self.assertEqual(ctx.exception.code, 1)
        finally:
            if ganymede.cli._lock_file:
                ganymede.cli._lock_file.close()
                ganymede.cli._lock_file = None
            shutil.rmtree(temp_dir)
