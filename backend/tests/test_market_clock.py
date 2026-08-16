"""
Tests for US equities market clock (Alpaca) and ET timestamp serialization.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core import market_clock as MC


ET = ZoneInfo("America/New_York")


@pytest.fixture(autouse=True)
def _reset_market_clock_cache():
    MC._clock_cache = None
    MC._calendar_cache = None
    yield
    MC._clock_cache = None
    MC._calendar_cache = None


class TestToMarketIso:
    def test_none_passthrough(self):
        assert MC.to_market_iso(None) is None

    def test_naive_utc_in_summer_is_edt(self):
        # 21:50 UTC on 15 Aug 2026 is 17:50 EDT (UTC-4)
        naive = datetime(2026, 8, 15, 21, 50, 54)
        iso = MC.to_market_iso(naive)
        assert iso is not None
        assert iso.startswith("2026-08-15T17:50:54")
        assert iso.endswith("-04:00")

    def test_naive_utc_in_winter_is_est(self):
        # 21:50 UTC on 15 Jan 2026 is 16:50 EST (UTC-5)
        naive = datetime(2026, 1, 15, 21, 50, 54)
        iso = MC.to_market_iso(naive)
        assert iso is not None
        assert iso.startswith("2026-01-15T16:50:54")
        assert iso.endswith("-05:00")

    def test_aware_utc_converts_to_et(self):
        aware = datetime(2026, 8, 15, 21, 50, 54, tzinfo=timezone.utc)
        iso = MC.to_market_iso(aware)
        assert iso is not None
        assert "-04:00" in iso
        assert "17:50:54" in iso

    def test_already_et_keeps_wall_clock(self):
        local = datetime(2026, 8, 15, 16, 30, tzinfo=ET)
        iso = MC.to_market_iso(local)
        assert iso is not None
        assert iso.startswith("2026-08-15T16:30:00")
        assert iso.endswith("-04:00")


class TestFallbackClock:
    def test_missing_alpaca_keys_use_ny_wall_clock(self, monkeypatch):
        monkeypatch.setattr(MC, "_fetch_alpaca_clock", lambda: None)
        clock = MC.get_market_clock(force_refresh=True)
        assert clock.source == "fallback"
        assert clock.timezone == "America/New_York"
        assert clock.timestamp.tzinfo is not None
        assert str(clock.timestamp.tzinfo) in ("America/New_York", "EDT", "EST") or (
            clock.timestamp.utcoffset() is not None
        )

    def test_clock_to_dict_includes_offset(self, monkeypatch):
        frozen = MC.MarketClock(
            timestamp=datetime(2026, 8, 15, 17, 50, tzinfo=ET),
            is_open=False,
            next_open=datetime(2026, 8, 17, 9, 30, tzinfo=ET),
            next_close=datetime(2026, 8, 17, 16, 0, tzinfo=ET),
            timezone="America/New_York",
            source="alpaca",
        )
        monkeypatch.setattr(MC, "get_market_clock", lambda force_refresh=False: frozen)
        payload = MC.clock_to_dict(frozen)
        assert payload["timestamp"].endswith("-04:00")
        assert payload["is_open"] is False
        assert payload["next_open"].startswith("2026-08-17T09:30:00")
        assert payload["source"] == "alpaca"


class TestTradingDates:
    def test_unknown_calendar_returns_none(self, monkeypatch):
        monkeypatch.setattr(MC, "_fetch_alpaca_calendar", lambda start, end: None)
        assert MC.trading_dates_between(
            datetime(2026, 8, 15).date(), datetime(2026, 8, 17).date()
        ) is None

    def test_is_trading_day_none_when_calendar_unknown(self, monkeypatch):
        monkeypatch.setattr(MC, "trading_dates_between", lambda start, end: None)
        assert MC.is_trading_day(datetime(2026, 8, 17).date()) is None

    def test_is_trading_day_false_on_holiday(self, monkeypatch):
        monkeypatch.setattr(MC, "trading_dates_between", lambda start, end: frozenset())
        assert MC.is_trading_day(datetime(2026, 9, 7).date()) is False
