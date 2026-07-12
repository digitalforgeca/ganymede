import structlog
from typing import Any
from apscheduler import AsyncScheduler, ConflictPolicy
from apscheduler.triggers.cron import CronTrigger
from ganymede.core import ContextKey
from ganymede.config import AppConfig

logger = structlog.get_logger()

class Scheduler:
    def __init__(self, config: AppConfig, db: Any, router: Any):
        self.config = config
        self.db = db
        self.router = router
        self.scheduler = AsyncScheduler()

    async def _run_scheduler_task(self):
        import asyncio
        try:
            async with self.scheduler:
                await self.scheduler.run_until_stopped()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("APScheduler task crashed", exc_info=True)

    async def start(self) -> None:
        """Start the scheduler in the background and load active schedules from the DB."""
        import asyncio
        self._scheduler_task = asyncio.create_task(self._run_scheduler_task())
        await asyncio.sleep(0.1) # allow async with block to enter
        logger.info("APScheduler started in background.")

        try:
            schedules = await self.db.get_active_schedules()
            for schedule in schedules:
                trigger = CronTrigger.from_crontab(schedule['cron_expr'])
                context = ContextKey(
                    platform=schedule['context_platform'],
                    channel_id=schedule['context_channel'],
                    thread_id=schedule['context_thread']
                )
                await self.scheduler.add_schedule(
                    self._run_job,
                    trigger,
                    id=schedule['id'],
                    args=[context, schedule['prompt']],
                    conflict_policy=ConflictPolicy.replace
                )
                logger.info("Loaded active schedule from DB", schedule_id=schedule['id'], cron=schedule['cron_expr'])
        except Exception as e:
            logger.error("Failed to load schedules from DB on startup", error=str(e))

    async def add_cron_job(self, schedule_id: str, context: ContextKey, creator_id: str, cron_expr: str, prompt: str) -> None:
        """Save schedule in DB and register with scheduler."""
        await self.db.save_schedule(schedule_id, context, creator_id, cron_expr, prompt)
        
        trigger = CronTrigger.from_crontab(cron_expr)
        await self.scheduler.add_schedule(
            self._run_job,
            trigger,
            id=schedule_id,
            args=[context, prompt],
            conflict_policy=ConflictPolicy.replace
        )
        logger.info("Registered cron job with scheduler", schedule_id=schedule_id, cron=cron_expr)

    async def stop(self) -> None:
        """Stop the scheduler."""
        try:
            await self.scheduler.stop()
        except Exception:
            pass
        if hasattr(self, "_scheduler_task"):
            self._scheduler_task.cancel()
        logger.info("APScheduler stopped.")

    async def _run_job(self, context: ContextKey, prompt: str) -> None:
        """Execute the scheduled prompt."""
        logger.info("Executing scheduled prompt", context=context)
        try:
            schedules = await self.db.get_active_schedules()
            for s in schedules:
                if s['prompt'] == prompt and s['context_channel'] == context.channel_id:
                    await self.db.update_schedule_last_run(s['id'])
                    break
        except Exception as e:
            logger.debug("Failed to update last_run for job", error=str(e))

        await self.router.handle_scheduled_prompt(context, prompt)


# Backwards compatibility alias
DiscordScheduler = Scheduler

