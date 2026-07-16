import os
import aiosqlite
import structlog
from typing import Any, List, Dict
from ganymede.core import ContextKey
from ganymede.config import AppConfig

logger = structlog.get_logger()

class Database:
    def __init__(self, config: AppConfig):
        self.config = config
        self.db_path = os.path.join(config.data_dir, "ganymede.db")
        self._conn = None

    async def init(self) -> None:
        """Initialize database connection and run schema DDL statements."""
        os.makedirs(self.config.data_dir, exist_ok=True)
        self._conn = await aiosqlite.connect(self.db_path)
        self._conn.row_factory = aiosqlite.Row

        # Conversations Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_platform TEXT NOT NULL,
                context_channel TEXT NOT NULL,
                context_thread TEXT,
                author_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tokens INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Schedules Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS schedules (
                id TEXT PRIMARY KEY,
                context_platform TEXT NOT NULL,
                context_channel TEXT NOT NULL,
                context_thread TEXT,
                creator_id TEXT NOT NULL,
                cron_expr TEXT NOT NULL,
                prompt TEXT NOT NULL,
                active BOOLEAN DEFAULT 1,
                last_run TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Tasks Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                context_platform TEXT NOT NULL,
                context_channel TEXT NOT NULL,
                context_thread TEXT,
                creator_id TEXT NOT NULL,
                description TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                result TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)

        # Tool Calls Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS tool_calls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_platform TEXT NOT NULL,
                context_channel TEXT NOT NULL,
                context_thread TEXT,
                tool_name TEXT NOT NULL,
                tool_args TEXT NOT NULL,
                result TEXT,
                approved_by TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Quota Usage Table
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS quota_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                context_platform TEXT NOT NULL,
                context_channel TEXT NOT NULL,
                context_thread TEXT,
                tokens_used INTEGER NOT NULL,
                recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Conversation Mappings Table (Many-to-One network contexts to one Antigravity conversation)
        await self._conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_mappings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                platform TEXT NOT NULL,
                channel_id TEXT NOT NULL,
                thread_id TEXT,
                conversation_id TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(platform, channel_id, thread_id)
            )
        """)

        await self._conn.commit()
        logger.info("Database initialized successfully", path=self.db_path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def save_message(self, context: ContextKey, author_id: str, role: str, content: str, tokens: int = 0) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        await self._conn.execute(
            """
            INSERT INTO conversations (context_platform, context_channel, context_thread, author_id, role, content, tokens)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (context.platform, context.channel_id, context.thread_id, author_id, role, content, tokens)
        )
        await self._conn.commit()
        logger.debug("Message saved to database", context=context, role=role)

    async def get_history(self, context: ContextKey, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        async with self._conn.execute(
            """
            SELECT author_id, role, content, tokens, created_at
            FROM conversations
            WHERE context_platform = ? AND context_channel = ? AND (context_thread = ? OR (context_thread IS NULL AND ? IS NULL))
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (context.platform, context.channel_id, context.thread_id, context.thread_id, limit)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in reversed(rows)]

    async def save_schedule(self, schedule_id: str, context: ContextKey, creator_id: str, cron_expr: str, prompt: str) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        await self._conn.execute(
            """
            INSERT INTO schedules (id, context_platform, context_channel, context_thread, creator_id, cron_expr, prompt, active)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
            ON CONFLICT(id) DO UPDATE SET
                cron_expr = excluded.cron_expr,
                prompt = excluded.prompt,
                active = 1
            """,
            (schedule_id, context.platform, context.channel_id, context.thread_id, creator_id, cron_expr, prompt)
        )
        await self._conn.commit()
        logger.info("Schedule saved to database", schedule_id=schedule_id, cron=cron_expr)

    async def get_active_schedules(self) -> List[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        async with self._conn.execute(
            """
            SELECT id, context_platform, context_channel, context_thread, creator_id, cron_expr, prompt, active, last_run, created_at
            FROM schedules
            WHERE active = 1
            """
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def delete_schedule(self, schedule_id: str) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        await self._conn.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))
        await self._conn.commit()
        logger.info("Schedule deleted from database", schedule_id=schedule_id)

    async def toggle_schedule(self, schedule_id: str, active: bool) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        await self._conn.execute(
            "UPDATE schedules SET active = ? WHERE id = ?",
            (1 if active else 0, schedule_id)
        )
        await self._conn.commit()
        logger.info("Schedule toggle updated in database", schedule_id=schedule_id, active=active)

    async def update_schedule_last_run(self, schedule_id: str) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        
        from datetime import datetime
        await self._conn.execute(
            "UPDATE schedules SET last_run = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), schedule_id)
        )
        await self._conn.commit()

    async def save_task(self, task_id: str, context: ContextKey, creator_id: str, description: str, status: str = 'running') -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        await self._conn.execute(
            """
            INSERT INTO tasks (id, context_platform, context_channel, context_thread, creator_id, description, status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (task_id, context.platform, context.channel_id, context.thread_id, creator_id, description, status)
        )
        await self._conn.commit()
        logger.info("Task saved to database", task_id=task_id, status=status)

    async def update_task(self, task_id: str, status: str, result: str = None) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        from datetime import datetime
        completed_at = datetime.utcnow().isoformat() if status in ('completed', 'failed') else None
        await self._conn.execute(
            """
            UPDATE tasks
            SET status = ?, result = ?, completed_at = ?
            WHERE id = ?
            """,
            (status, result, completed_at, task_id)
        )
        await self._conn.commit()
        logger.info("Task updated in database", task_id=task_id, status=status)

    async def get_task(self, task_id: str) -> Dict[str, Any] | None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        async with self._conn.execute(
            "SELECT * FROM tasks WHERE id = ?", (task_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

    async def get_recent_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        async with self._conn.execute(
            "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def save_conversation_mapping(self, conversation_id: str, context: ContextKey) -> None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        await self._conn.execute(
            """
            INSERT INTO conversation_mappings (conversation_id, platform, channel_id, thread_id)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(platform, channel_id, thread_id) DO UPDATE SET
                conversation_id = excluded.conversation_id
            """,
            (conversation_id, context.platform, context.channel_id, context.thread_id)
        )
        await self._conn.commit()
        logger.debug("Conversation mapping saved", conversation_id=conversation_id, context=context)

    async def get_conversation_contexts(self, conversation_id: str) -> List[ContextKey]:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        async with self._conn.execute(
            "SELECT platform, channel_id, thread_id FROM conversation_mappings WHERE conversation_id = ?",
            (conversation_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [ContextKey(platform=row["platform"], channel_id=row["channel_id"], thread_id=row["thread_id"]) for row in rows]

    async def get_conversation_id_by_context(self, context: ContextKey) -> str | None:
        if not self._conn:
            raise RuntimeError("Database not initialized. Call init() first.")
        async with self._conn.execute(
            """
            SELECT conversation_id 
            FROM conversation_mappings 
            WHERE platform = ? AND channel_id = ? AND (thread_id = ? OR (thread_id IS NULL AND ? IS NULL))
            """,
            (context.platform, context.channel_id, context.thread_id, context.thread_id)
        ) as cursor:
            row = await cursor.fetchone()
            return row["conversation_id"] if row else None
