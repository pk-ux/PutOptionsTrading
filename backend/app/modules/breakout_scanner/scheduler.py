"""
Breakout Scanner - automatic scan scheduler.

Runs the scan once per configured day at a configured local wall-clock time,
inside the web process. The app has no job queue and deploys as a single uvicorn
process, so an asyncio loop is the whole mechanism: no new infrastructure, and
the schedule lives in the same settings row as the rest of the scanner config so
admins can change it from the UI without a redeploy.

Design notes
------------
- **Wall-clock, not interval.** The useful moment to scan is "30 minutes after
  the close", which is a local time in a specific timezone, not "every 24h".
  Storing ``HH:MM`` + IANA zone keeps that stable across DST.
- **Blocking work is offloaded.** ``run_and_publish`` is synchronous and can take
  minutes; it is dispatched with ``asyncio.to_thread`` so the event loop (and
  therefore the whole API) keeps serving requests.
- **Once per day, claimed atomically.** ``last_auto_run_date`` is written with a
  conditional UPDATE and the run only proceeds if that UPDATE matched a row. A
  restart mid-day, a slow tick, or a second process can therefore never double-fire.
- **Catch-up window.** If the process was down at the scheduled minute it still
  runs when it comes back, but only within ``CATCHUP_WINDOW``; past that the slot
  is skipped rather than producing a surprise scan at midnight.
- **Manual runs always win.** A tick that finds a scan already running skips and
  retries on the next tick, so the scheduler never interrupts or duplicates a
  manual run triggered from the admin UI.
- **"Now" is market time.** Ticks use Alpaca's clock (America/New_York) rather
  than the server's local timezone, so a 16:30 ET schedule fires at 16:30 ET
  even if the host is in UTC or Pacific.
- **Closed sessions are skipped.** Alpaca's market calendar drops weekends and
  NYSE holidays from ``is_due`` / ``next_run_at`` when the calendar is available.
  If Alpaca is unreachable the weekday mask still applies and holidays are not
  extra-filtered (same as before).
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, FrozenSet, Optional, Tuple
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text

from ...core.database import SessionLocal
from ...core.market_clock import market_now_utc, trading_dates_between
from ...models.breakout_scanner import (
    DEFAULT_AUTO_SCAN_TIME,
    DEFAULT_AUTO_SCAN_TIMEZONE,
    BreakoutScannerSettings,
    parse_weekday_csv,
)
from .integration import get_or_create_settings, reset_if_stale, run_and_publish

logger = logging.getLogger(__name__)

# How often the loop wakes to check whether the scheduled time has arrived.
# This bounds how *late* a run starts, never whether it happens: any tick inside
# CATCHUP_WINDOW fires the scan, so the interval is purely a promptness knob.
# A daily post-close scan does not need minute-level accuracy.
TICK_SECONDS = 30 * 60

# Let startup (DB init, cache warmup) settle before the first check.
STARTUP_DELAY_SECONDS = 20

# How long after the scheduled time a missed run is still worth executing.
CATCHUP_WINDOW = timedelta(hours=4)


# --------------------------------------------------------------------------- #
# Pure schedule math (no DB, no I/O - unit tested directly)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class SchedulePlan:
    """An immutable snapshot of the schedule, resolved from the settings row."""

    enabled: bool  # master scanner switch
    auto_enabled: bool  # auto-scan switch
    at: time
    tz: ZoneInfo
    tz_name: str
    days: Tuple[int, ...]  # Python weekday() numbers, Mon=0
    last_run_date: Optional[str]  # "YYYY-MM-DD" in `tz`

    @property
    def active(self) -> bool:
        """A scan only ever fires when both switches are on and a day is selected."""
        return self.enabled and self.auto_enabled and bool(self.days)

    def fire_time_on(self, day: date) -> datetime:
        """The timezone-aware moment the scan should start on `day`."""
        return datetime.combine(day, self.at).replace(tzinfo=self.tz)


def parse_time_of_day(value: Optional[str], fallback: str = DEFAULT_AUTO_SCAN_TIME) -> time:
    """Parse "HH:MM" (or "HH:MM:SS") into a `time`, falling back on bad input."""
    for candidate in (value, fallback):
        if not candidate:
            continue
        parts = str(candidate).strip().split(":")
        if len(parts) < 2:
            continue
        try:
            hour, minute = int(parts[0]), int(parts[1])
        except (TypeError, ValueError):
            continue
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour=hour, minute=minute)
    return time(hour=16, minute=30)


def resolve_timezone(name: Optional[str]) -> ZoneInfo:
    """Resolve an IANA zone name, falling back to the market default."""
    for candidate in (name, DEFAULT_AUTO_SCAN_TIMEZONE):
        if not candidate:
            continue
        try:
            return ZoneInfo(str(candidate).strip())
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            logger.warning(f"Unknown auto-scan timezone {candidate!r}; falling back")
    return ZoneInfo("UTC")


def plan_from_settings(settings: BreakoutScannerSettings) -> SchedulePlan:
    tz_name = settings.auto_scan_timezone or DEFAULT_AUTO_SCAN_TIMEZONE
    return SchedulePlan(
        enabled=bool(settings.enabled),
        auto_enabled=bool(settings.auto_scan_enabled),
        at=parse_time_of_day(settings.auto_scan_time),
        tz=resolve_timezone(tz_name),
        tz_name=tz_name,
        days=tuple(parse_weekday_csv(settings.auto_scan_days)),
        last_run_date=settings.last_auto_run_date,
    )


def is_due(
    plan: SchedulePlan,
    now_utc: datetime,
    trading_dates: Optional[FrozenSet[str]] = None,
) -> bool:
    """True when a scan should start right now.

    Due means: today is a selected weekday, the scheduled minute has passed, we
    are still inside the catch-up window, and today's slot has not been claimed.
    When ``trading_dates`` is provided (Alpaca calendar), closed sessions are
    skipped even if the weekday is selected.
    """
    if not plan.active:
        return False
    now_local = now_utc.astimezone(plan.tz)
    today = now_local.date()
    if today.weekday() not in plan.days:
        return False
    if trading_dates is not None and today.isoformat() not in trading_dates:
        return False
    if plan.last_run_date == today.isoformat():
        return False
    fire = plan.fire_time_on(today)
    return fire <= now_local < fire + CATCHUP_WINDOW


def next_run_at(
    plan: SchedulePlan,
    now_utc: datetime,
    trading_dates: Optional[FrozenSet[str]] = None,
) -> Optional[datetime]:
    """The next UTC moment the scan will fire, or None if it never will.

    Used for the "Next run" readout in the admin UI, so it has to agree with
    `is_due`: it skips days already run, slots whose catch-up window closed,
    and (when ``trading_dates`` is provided) closed market sessions.
    """
    if not plan.active:
        return None
    now_local = now_utc.astimezone(plan.tz)
    # 16 days covers a full week plus a long holiday stretch (Thanksgiving).
    for offset in range(16):
        day = now_local.date() + timedelta(days=offset)
        if day.weekday() not in plan.days:
            continue
        if trading_dates is not None and day.isoformat() not in trading_dates:
            continue
        if plan.last_run_date == day.isoformat():
            continue
        fire = plan.fire_time_on(day)
        if now_local >= fire + CATCHUP_WINDOW:
            continue  # window closed; try the next selected day
        return fire.astimezone(timezone.utc)
    return None


def describe_schedule(plan: SchedulePlan) -> str:
    """Human-readable summary for status messages and logs."""
    if not plan.active:
        return "Automatic scan is off"
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    days = ",".join(names[d] for d in plan.days)
    return f"{plan.at.strftime('%H:%M')} {plan.tz_name} on {days}"


# --------------------------------------------------------------------------- #
# Atomic once-per-day claim
# --------------------------------------------------------------------------- #
def claim_day(db, day_key: str) -> bool:
    """Reserve today's slot. Returns True only for the caller that won it.

    The conditional UPDATE is the concurrency control: whichever tick (or worker)
    flips `last_auto_run_date` first gets rowcount 1, everyone else gets 0. This
    is what makes the schedule exactly-once per day rather than best-effort.
    """
    result = db.execute(
        text(
            "UPDATE breakout_scanner_settings "
            "SET last_auto_run_date = :day, last_auto_run_at = :ts "
            "WHERE id = 1 AND (last_auto_run_date IS NULL OR last_auto_run_date <> :day)"
        ),
        {"day": day_key, "ts": datetime.utcnow()},
    )
    db.commit()
    return (result.rowcount or 0) == 1


# --------------------------------------------------------------------------- #
# The loop
# --------------------------------------------------------------------------- #
class AutoScanScheduler:
    """Background asyncio task that fires the scan on schedule."""

    def __init__(
        self,
        runner: Optional[Callable[[], object]] = None,
        tick_seconds: int = TICK_SECONDS,
        startup_delay: int = STARTUP_DELAY_SECONDS,
    ):
        self._runner = runner or run_and_publish
        self._tick_seconds = tick_seconds
        self._startup_delay = startup_delay
        self._task: Optional[asyncio.Task] = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if self.running:
            return
        self._task = asyncio.create_task(self._loop(), name="breakout-auto-scan")
        logger.info("Breakout auto-scan scheduler started")

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            logger.info("Breakout auto-scan scheduler stopped")

    async def _loop(self) -> None:
        await asyncio.sleep(self._startup_delay)
        while True:
            try:
                await self.tick(market_now_utc())
            except asyncio.CancelledError:
                raise
            except Exception:  # never let one bad tick kill the schedule
                logger.exception("Breakout auto-scan tick failed")
            await asyncio.sleep(self._tick_seconds)

    async def tick(self, now_utc: datetime) -> bool:
        """Run one scheduling check. Returns True if a scan was executed."""
        day_key = await asyncio.to_thread(self._claim_if_due, now_utc)
        if day_key is None:
            return False
        logger.info(f"Breakout auto-scan firing for {day_key}")
        # Offloaded: run_and_publish blocks for minutes on network I/O.
        await asyncio.to_thread(self._runner)
        return True

    def _claim_if_due(self, now_utc: datetime) -> Optional[str]:
        """Decide and claim, in one short transaction. Returns the claimed day key."""
        db = SessionLocal()
        try:
            settings = get_or_create_settings(db)
            plan = plan_from_settings(settings)
            today = now_utc.astimezone(plan.tz).date()
            trading_dates = trading_dates_between(today, today)
            if not is_due(plan, now_utc, trading_dates):
                return None

            # A manual run in flight owns the scanner; retry on the next tick
            # rather than claiming (and therefore burning) today's slot.
            reset_if_stale(db, settings)
            if settings.last_run_status == "running":
                logger.info("Breakout auto-scan deferred: a scan is already running")
                return None

            day_key = now_utc.astimezone(plan.tz).date().isoformat()
            if not claim_day(db, day_key):
                return None

            # Reflect the queued state immediately so the admin UI shows it
            # before the (slow) scan actually starts.
            settings.last_run_status = "running"
            settings.last_run_message = f"Scheduled scan queued ({describe_schedule(plan)})"
            db.commit()
            return day_key
        finally:
            db.close()


_scheduler: Optional[AutoScanScheduler] = None


def get_scheduler() -> AutoScanScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AutoScanScheduler()
    return _scheduler


def start_scheduler() -> None:
    get_scheduler().start()


async def stop_scheduler() -> None:
    if _scheduler is not None:
        await _scheduler.stop()
