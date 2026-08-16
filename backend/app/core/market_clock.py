"""
US equity market clock.

Times the app shows to operators (last run, next run, last updated) and
calendar-day math (DTE, earnings windows, auto-scan schedule) follow the NYSE
session, not the server's local timezone or naive UTC.

Alpaca's Trading API ``get_clock`` is the source of truth for "now", open/closed,
and next open/close. ``get_calendar`` supplies session dates so the scheduler can
skip weekends and holidays. If Alpaca is unreachable we fall back to
America/New_York wall-clock time.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import FrozenSet, Optional
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

MARKET_TZ_NAME = "America/New_York"
MARKET_TZ = ZoneInfo(MARKET_TZ_NAME)

_CLOCK_TTL = timedelta(seconds=20)
_CALENDAR_TTL = timedelta(hours=6)

_lock = threading.Lock()
_clock_cache: Optional[tuple[datetime, "MarketClock"]] = None
_calendar_cache: Optional[tuple[datetime, date, date, FrozenSet[str]]] = None
_trading_client = None


@dataclass(frozen=True)
class MarketClock:
    """Snapshot of the US equities session clock."""

    timestamp: datetime  # timezone-aware, America/New_York
    is_open: bool
    next_open: Optional[datetime]
    next_close: Optional[datetime]
    timezone: str
    source: str  # "alpaca" | "fallback"


def to_market_dt(dt: datetime) -> datetime:
    """Convert a datetime to America/New_York. Naive values are treated as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(MARKET_TZ)


def to_market_iso(dt: Optional[datetime]) -> Optional[str]:
    """Serialize a datetime as an ISO-8601 string in America/New_York.

    Naive datetimes are treated as UTC, matching how this app stores timestamps
    (``datetime.utcnow()``). The offset (``-04:00`` / ``-05:00``) is included so
    clients never have to guess the zone.
    """
    if dt is None:
        return None
    return to_market_dt(dt).isoformat()


def _fallback_clock() -> MarketClock:
    now = datetime.now(MARKET_TZ)
    return MarketClock(
        timestamp=now,
        is_open=False,
        next_open=None,
        next_close=None,
        timezone=MARKET_TZ_NAME,
        source="fallback",
    )


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=MARKET_TZ)
    return dt.astimezone(MARKET_TZ)


def _get_trading_client():
    """Lazy singleton so we don't rebuild Alpaca clients on every clock read."""
    global _trading_client
    if _trading_client is not None:
        return _trading_client

    from .config import get_settings

    settings = get_settings()
    if not settings.ALPACA_API_KEY or not settings.ALPACA_SECRET_KEY:
        return None

    from alpaca.trading.client import TradingClient

    _trading_client = TradingClient(
        api_key=settings.ALPACA_API_KEY,
        secret_key=settings.ALPACA_SECRET_KEY,
        paper=True,
    )
    return _trading_client


def _fetch_alpaca_clock() -> Optional[MarketClock]:
    client = _get_trading_client()
    if client is None:
        return None
    raw = client.get_clock()
    ts = _aware(getattr(raw, "timestamp", None))
    if ts is None:
        return None
    return MarketClock(
        timestamp=ts,
        is_open=bool(getattr(raw, "is_open", False)),
        next_open=_aware(getattr(raw, "next_open", None)),
        next_close=_aware(getattr(raw, "next_close", None)),
        timezone=MARKET_TZ_NAME,
        source="alpaca",
    )


def get_market_clock(force_refresh: bool = False) -> MarketClock:
    """Current market clock, cached briefly so the admin UI can poll cheaply."""
    global _clock_cache
    now_utc = datetime.now(timezone.utc)
    with _lock:
        if (
            not force_refresh
            and _clock_cache is not None
            and now_utc - _clock_cache[0] < _CLOCK_TTL
        ):
            return _clock_cache[1]

    clock: Optional[MarketClock] = None
    try:
        clock = _fetch_alpaca_clock()
    except Exception:
        logger.warning("Alpaca market clock fetch failed; using NY wall clock", exc_info=True)

    if clock is None:
        clock = _fallback_clock()

    with _lock:
        _clock_cache = (datetime.now(timezone.utc), clock)
    return clock


def market_now() -> datetime:
    """Current instant in America/New_York, preferably from Alpaca."""
    return get_market_clock().timestamp


def market_now_utc() -> datetime:
    """Current instant as timezone-aware UTC, preferably from Alpaca."""
    return market_now().astimezone(timezone.utc)


def market_today() -> date:
    """Today's US equities calendar date (America/New_York)."""
    return market_now().date()


def _fetch_alpaca_calendar(start: date, end: date) -> Optional[FrozenSet[str]]:
    client = _get_trading_client()
    if client is None:
        return None
    from alpaca.trading.requests import GetCalendarRequest

    rows = client.get_calendar(GetCalendarRequest(start=start, end=end))
    days = set()
    for row in rows or []:
        raw = getattr(row, "date", None)
        if raw is None:
            continue
        if isinstance(raw, datetime):
            raw = raw.date()
        days.add(raw.isoformat() if hasattr(raw, "isoformat") else str(raw)[:10])
    return frozenset(days)


def trading_dates_between(start: date, end: date) -> Optional[FrozenSet[str]]:
    """Alpaca session dates in ``[start, end]``, or None if the calendar is unavailable.

    Callers treat None as "don't extra-filter" so a downed Alpaca never silently
    disables the auto-scan schedule.
    """
    global _calendar_cache
    if end < start:
        start, end = end, start

    now_utc = datetime.now(timezone.utc)
    with _lock:
        cached = _calendar_cache
        if (
            cached is not None
            and now_utc - cached[0] < _CALENDAR_TTL
            and start >= cached[1]
            and end <= cached[2]
        ):
            return frozenset(d for d in cached[3] if start.isoformat() <= d <= end.isoformat())

    window_end = end + timedelta(days=14)
    try:
        dates = _fetch_alpaca_calendar(start, window_end)
    except Exception:
        logger.warning("Alpaca market calendar fetch failed", exc_info=True)
        dates = None

    if dates is None:
        return None

    with _lock:
        _calendar_cache = (datetime.now(timezone.utc), start, window_end, dates)
    return frozenset(d for d in dates if start.isoformat() <= d <= end.isoformat())


def is_trading_day(day: date) -> Optional[bool]:
    """True/False from Alpaca's calendar, or None when the calendar is unknown."""
    dates = trading_dates_between(day, day)
    if dates is None:
        return None
    return day.isoformat() in dates


def clock_to_dict(clock: Optional[MarketClock] = None) -> dict:
    """JSON payload for the market-clock API and admin UI."""
    clock = clock or get_market_clock()
    return {
        "timestamp": clock.timestamp.isoformat(),
        "is_open": clock.is_open,
        "next_open": clock.next_open.isoformat() if clock.next_open else None,
        "next_close": clock.next_close.isoformat() if clock.next_close else None,
        "timezone": clock.timezone,
        "source": clock.source,
    }
