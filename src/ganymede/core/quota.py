from collections import defaultdict
from typing import Any
import time
import datetime
import structlog
import asyncio
from ganymede.core import ContextKey
from ganymede.config import AppConfig

logger = structlog.get_logger()

# Pacific Time offset in seconds (UTC-7 for PDT, UTC-8 for PST)
# Google resets daily quotas at midnight Pacific Time.
_PACIFIC_UTC_OFFSET_HOURS = -7  # PDT (summer); adjust if needed


def _get_pacific_day_start() -> float:
    """Returns the Unix timestamp of the start of the current day in Pacific Time.
    
    Google's free tier RPD quota resets at midnight Pacific Time.
    """
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    pacific_tz = datetime.timezone(datetime.timedelta(hours=_PACIFIC_UTC_OFFSET_HOURS))
    now_pacific = now_utc.astimezone(pacific_tz)
    midnight_pacific = now_pacific.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight_pacific.timestamp()


class QuotaTracker:
    def __init__(self, config: AppConfig):
        self.config = config
        # Map context key to a list of timestamps and token usage: (timestamp, tokens)
        self._usage_history: dict[ContextKey, list[tuple[float, int]]] = defaultdict(list)
        # List of global token usage: (timestamp, tokens)
        self._global_usage_history: list[tuple[float, int]] = []
        # List of global request timestamps (for RPM sliding window)
        self._global_request_history: list[float] = []
        # List of global request timestamps for daily tracking (RPD)
        self._daily_request_history: list[float] = []
        # Timestamp until which the API is blocked due to 429 backoff
        self.blocked_until: float = 0.0
        # Lock to synchronize rate check and sleep executions across parallel channels
        self._lock = asyncio.Lock()

    def record_blocker(self, error_message: str) -> None:
        """Parse retry duration from 429 error and record blocker."""
        import re
        match = re.search(r"Please retry in (\d+\.?\d*)s", error_message)
        if match:
            retry_seconds = float(match.group(1))
            # Pad with 1 second to ensure the window has fully cleared on Gemini's side
            self.blocked_until = time.time() + retry_seconds + 1.0
            logger.warning("Recorded Gemini API 429 block", duration_seconds=retry_seconds)

    async def record_turn(self, context: ContextKey) -> None:
        """Record a single turn (one user message → model response cycle).
        
        This is called once per chat() invocation, NOT per tool call.
        Each turn may produce multiple internal generate_content calls
        inside the Go harness, but we track at the turn level since
        that's what we control.
        """
        async with self._lock:
            now = time.time()
            self._global_request_history.append(now)
            self._daily_request_history.append(now)
            logger.info(
                "Recorded Gemini API turn",
                context=context,
                daily_turns=self._count_daily_requests(),
                daily_limit=getattr(self.config.quota, "max_requests_per_day", 18),
            )

    def _count_daily_requests(self) -> int:
        """Count requests made since midnight Pacific Time."""
        day_start = _get_pacific_day_start()
        self._daily_request_history = [
            t for t in self._daily_request_history if t >= day_start
        ]
        return len(self._daily_request_history)

    async def throttle(self, context: ContextKey) -> None:
        """Check rate limits and sleep if necessary to stay within limits.
        
        Enforces three dimensions:
        1. RPD (Requests Per Day) - Hard daily cap
        2. RPM (Requests Per Minute) - Sliding window  
        3. 429 backoff blocker - Explicit wait after server rejection
        """
        async with self._lock:
            now = time.time()

            # ── RPD Check (most critical) ──
            daily_limit = getattr(self.config.quota, "max_requests_per_day", 18)
            daily_count = self._count_daily_requests()
            if daily_count >= daily_limit:
                # Calculate time until midnight PT reset
                day_start = _get_pacific_day_start()
                next_midnight = day_start + 86400  # 24 hours later
                wait_until_reset = max(0.0, next_midnight - now)
                logger.error(
                    "DAILY REQUEST QUOTA EXHAUSTED — blocking until midnight PT reset",
                    context=context,
                    daily_count=daily_count,
                    daily_limit=daily_limit,
                    hours_until_reset=round(wait_until_reset / 3600, 1),
                )
                raise RuntimeError(
                    f"Daily API quota exhausted ({daily_count}/{daily_limit} requests today). "
                    f"Resets at midnight Pacific Time (~{round(wait_until_reset / 3600, 1)}h from now)."
                )

            # ── RPM Check (sliding window) ──
            minute_ago = now - 60.0
            self._global_request_history = [
                t for t in self._global_request_history if t >= minute_ago
            ]
            rpm_limit = getattr(self.config.quota, "max_requests_per_minute", 4)
            rpm_sleep = 0.0
            if len(self._global_request_history) >= rpm_limit:
                oldest = self._global_request_history[-rpm_limit]
                rpm_sleep = max(0.0, 60.0 - (now - oldest))

            # ── 429 Blocker Check ──
            block_sleep = 0.0
            if now < self.blocked_until:
                block_sleep = self.blocked_until - now

            sleep_time = max(rpm_sleep, block_sleep)
            if sleep_time > 0.0:
                logger.warning(
                    "Throttling turn to stay within Gemini API rate limits",
                    context=context,
                    sleep_seconds=round(sleep_time, 2),
                    rpm_count=len(self._global_request_history),
                    rpm_limit=rpm_limit,
                    daily_count=daily_count,
                    daily_limit=daily_limit,
                    blocked_until=round(self.blocked_until - now, 2) if self.blocked_until > now else 0,
                )
                await asyncio.sleep(sleep_time)

            # Log remaining daily budget on every turn
            remaining = daily_limit - daily_count
            if remaining <= 5:
                logger.warning(
                    "Daily API budget running low",
                    context=context,
                    remaining_turns=remaining,
                    daily_limit=daily_limit,
                )

    async def record_usage(self, context: ContextKey, tokens: int) -> None:
        now = time.time()
        self._usage_history[context].append((now, tokens))
        self._global_usage_history.append((now, tokens))
        logger.info("Recorded token usage", context=context, tokens=tokens)

    async def check_budget(self, context: ContextKey) -> bool:
        """Returns True if context has remaining budget, False if budget is exhausted."""
        now = time.time()
        hour_ago = now - 3600

        # Clean old context history
        self._usage_history[context] = [
            (t, tok) for t, tok in self._usage_history[context] if t >= hour_ago
        ]
        context_tokens_hour = sum(tok for _, tok in self._usage_history[context])

        # Clean old global history
        self._global_usage_history = [
            (t, tok) for t, tok in self._global_usage_history if t >= hour_ago
        ]
        global_tokens_hour = sum(tok for _, tok in self._global_usage_history)

        # ── Daily request budget check ──
        daily_limit = getattr(self.config.quota, "max_requests_per_day", 18)
        daily_count = self._count_daily_requests()
        if daily_count >= daily_limit:
            logger.warning(
                "Daily request budget exhausted",
                context=context,
                daily_count=daily_count,
                daily_limit=daily_limit,
            )
            return False

        # Enforce context limits
        if context_tokens_hour >= self.config.quota.max_tokens_per_context_per_hour:
            logger.warning(
                "Context token budget exceeded",
                context=context,
                usage=context_tokens_hour,
                limit=self.config.quota.max_tokens_per_context_per_hour
            )
            return False

        # Enforce global limits
        if global_tokens_hour >= self.config.quota.max_tokens_global_per_hour:
            logger.warning(
                "Global token budget exceeded",
                usage=global_tokens_hour,
                limit=self.config.quota.max_tokens_global_per_hour
            )
            return False

        # Check alert threshold
        threshold_tokens = (self.config.quota.max_tokens_global_per_hour * self.config.quota.alert_threshold_pct) // 100
        if global_tokens_hour >= threshold_tokens:
            logger.warning(
                "Global token usage is approaching budget limit",
                usage=global_tokens_hour,
                limit=self.config.quota.max_tokens_global_per_hour,
                pct=self.config.quota.alert_threshold_pct
            )

        return True

    async def get_usage_summary(self, context: ContextKey) -> dict[str, Any]:
        now = time.time()
        hour_ago = now - 3600
        context_tokens = sum(tok for t, tok in self._usage_history[context] if t >= hour_ago)
        global_tokens = sum(tok for t, tok in self._global_usage_history if t >= hour_ago)
        daily_count = self._count_daily_requests()
        daily_limit = getattr(self.config.quota, "max_requests_per_day", 18)
        
        return {
            "context_usage": context_tokens,
            "context_limit": self.config.quota.max_tokens_per_context_per_hour,
            "global_usage": global_tokens,
            "global_limit": self.config.quota.max_tokens_global_per_hour,
            "daily_requests": daily_count,
            "daily_limit": daily_limit,
            "daily_remaining": max(0, daily_limit - daily_count),
        }
