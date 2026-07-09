import asyncio
import os
import unittest
from unittest.mock import AsyncMock, MagicMock
import json
import time

from ganymede.config import AppConfig, AgentConfig
from ganymede.core import ContextKey
from ganymede.core.db import Database
from ganymede.core.quota import QuotaTracker
from ganymede.core.agent_manager import AgentManager
from ganymede.core.router import Router
from ganymede.core.safety import DiscordApprovalHook
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
        
        # Verify it uses the friendly conversation ID format
        self.assertEqual(managed.conversation_id, "ganymede_discord_test_channel_999999")
        
        # Verify cached retrieval
        cached = await self.agent_manager.get_or_create(self.context)
        self.assertEqual(managed, cached)

        # Verify mapping was saved in db
        context = await self.db.get_conversation_context(managed.conversation_id)
        self.assertIsNotNone(context)
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

if __name__ == '__main__':
    unittest.main()
