"""
Breakout Scanner tests.

Covers the portable core (signals, scoring, config) plus an end-to-end
``run_scan`` against fake providers. Everything here is deterministic: the
synthetic price series are constructed so each signal has an unambiguous
expected direction.
"""

import asyncio
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pytest

from app.models.breakout_scanner import (
    DEFAULT_AUTO_SCAN_DAYS,
    DEFAULT_AUTO_SCAN_TIME,
    DEFAULT_AUTO_SCAN_TIMEZONE,
    parse_weekday_csv,
)
from app.modules.breakout_scanner import run_scan
from app.modules.breakout_scanner import scheduler as SCH
from app.modules.breakout_scanner import signals as S
from app.modules.breakout_scanner import uw_signals as UW
from app.modules.breakout_scanner.scoring import NEUTRAL, percentile_rank, score_candidates
from app.modules.breakout_scanner.types import DEFAULT_WEIGHTS, ScannerConfig


# --------------------------------------------------------------------------- #
# Synthetic price series helpers
# --------------------------------------------------------------------------- #
def make_ohlc(closes, volumes=None, spread=0.01):
    """Build an OHLC list from a close series with a fixed intrabar spread."""
    closes = np.asarray(closes, dtype=float)
    if volumes is None:
        volumes = np.full(len(closes), 1_000_000.0)
    return [
        {
            "date": f"2025-01-{i % 28 + 1:02d}",
            "open": float(c),
            "high": float(c * (1 + spread)),
            "low": float(c * (1 - spread)),
            "close": float(c),
            "volume": float(v),
        }
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


def coiling_series(n_trend=220, n_base=80, base_price=100.0, noise=0.5, seed=7):
    """An advance followed by a tight consolidation just under the highs."""
    rng = np.random.default_rng(seed)
    trend = np.linspace(base_price * 0.5, base_price, n_trend)
    base = base_price + rng.normal(0, noise, n_base)
    closes = np.concatenate([trend, base])
    volumes = np.concatenate([
        rng.normal(2_000_000, 100_000, n_trend),
        rng.normal(900_000, 50_000, n_base),
    ])
    return closes, np.abs(volumes)


# --------------------------------------------------------------------------- #
# percentile_rank
# --------------------------------------------------------------------------- #
class TestPercentileRank:
    def test_missing_values_map_to_neutral(self):
        """A missing data point must not rank below a real low value."""
        ranks = percentile_rank([10.0, None, 20.0, 30.0])
        assert ranks[1] == NEUTRAL
        assert ranks[0] == 0.0
        assert ranks[3] == 1.0

    def test_all_missing_is_all_neutral(self):
        assert percentile_rank([None, None, None]) == [NEUTRAL] * 3

    def test_single_present_value_ranks_top(self):
        ranks = percentile_rank([None, 5.0, None])
        assert ranks[1] == 1.0
        assert ranks[0] == NEUTRAL

    def test_ordering_is_monotonic(self):
        ranks = percentile_rank([3.0, 1.0, 2.0])
        assert ranks[1] < ranks[2] < ranks[0]

    def test_ties_share_a_rank(self):
        """Equal inputs must score equally regardless of list position."""
        assert percentile_rank([5.0, 5.0]) == [NEUTRAL, NEUTRAL]
        assert percentile_rank([5.0, 5.0, 5.0]) == [NEUTRAL] * 3

    def test_partial_ties_average_their_span(self):
        ranks = percentile_rank([1.0, 2.0, 2.0, 3.0])
        assert ranks[1] == ranks[2]
        assert ranks[0] < ranks[1] < ranks[3]

    def test_rank_is_independent_of_input_order(self):
        forward = percentile_rank([1.0, 7.0, 7.0, 9.0])
        backward = list(reversed(percentile_rank([9.0, 7.0, 7.0, 1.0])))
        assert forward == backward


# --------------------------------------------------------------------------- #
# Weight configuration
# --------------------------------------------------------------------------- #
class TestWeights:
    def test_defaults_sum_to_one(self):
        assert sum(DEFAULT_WEIGHTS.values()) == pytest.approx(1.0)

    def test_confirmation_group_is_gone(self):
        """Pre-breakout scanner must not carry a post-breakout factor group."""
        assert "confirmation" not in DEFAULT_WEIGHTS

    def test_normalized_weights_renormalize_after_partial_override(self):
        config = ScannerConfig(weights={"pivot": 0.5, "leadership": 0.25})
        weights = config.normalized_weights()
        assert sum(weights.values()) == pytest.approx(1.0)
        assert weights["pivot"] == pytest.approx(2 / 3)

    def test_zero_weights_are_dropped(self):
        config = ScannerConfig(weights={**DEFAULT_WEIGHTS, "gex": 0.0})
        assert "gex" not in config.normalized_weights()

    def test_empty_weights_fall_back_to_defaults(self):
        assert ScannerConfig(weights={}).normalized_weights() == DEFAULT_WEIGHTS


# --------------------------------------------------------------------------- #
# Price-structure signals
# --------------------------------------------------------------------------- #
class TestStructureSignals:
    def test_insufficient_history_returns_empty(self):
        assert S.compute_structure_signals(make_ohlc(np.linspace(10, 20, 30))) == {}

    def test_coiling_base_scores_high_compression_and_pivot(self):
        closes, volumes = coiling_series()
        sig = S.compute_structure_signals(make_ohlc(closes, volumes))
        assert sig["compression"] > 0.5
        assert sig["pivot"] > 0.8
        assert sig["breakout_trigger"] is False
        assert sig["prior_uptrend"] is True

    def test_pivot_proximity_is_atr_normalized(self):
        """The same percent gap should score lower for a low-volatility name."""
        price, pivot = 100.0, 103.0
        wide = S.pivot_proximity(price, pivot, atr_value=3.0)
        tight = S.pivot_proximity(price, pivot, atr_value=0.5)
        assert wide > tight

    def test_pivot_proximity_peaks_near_the_pivot(self):
        at_pivot = S.pivot_proximity(100.0, 100.0, atr_value=2.0)
        far_below = S.pivot_proximity(100.0, 110.0, atr_value=2.0)
        far_above = S.pivot_proximity(100.0, 94.0, atr_value=2.0)
        assert at_pivot > far_below
        assert at_pivot > far_above
        assert at_pivot > 0.95

    def test_pivot_proximity_decays_faster_above_than_below(self):
        """A failed break above the pivot is worth less than the same gap below."""
        one_atr_below = S.pivot_proximity(100.0, 102.0, atr_value=2.0)
        one_atr_above = S.pivot_proximity(100.0, 98.0, atr_value=2.0)
        assert one_atr_below > one_atr_above

    def test_pivot_proximity_is_continuous(self):
        """No discontinuous jumps as price creeps toward the pivot."""
        atr_value = 2.0
        scores = [S.pivot_proximity(p, 100.0, atr_value) for p in np.arange(90.0, 101.0, 0.25)]
        deltas = np.abs(np.diff(scores))
        assert deltas.max() < 0.1

    def test_pivot_proximity_handles_missing_inputs(self):
        assert S.pivot_proximity(100.0, None) == 0.0
        assert S.pivot_proximity(0.0, 100.0) == 0.0

    def test_base_duration_rewards_long_consolidation(self):
        rng = np.random.default_rng(3)
        long_base = np.concatenate([np.linspace(50, 100, 100), 100 + rng.normal(0, 0.4, 60)])
        short_base = np.concatenate([np.linspace(50, 100, 155), 100 + rng.normal(0, 0.4, 5)])
        long_score = S.base_duration(long_base * 1.01, long_base * 0.99)
        short_score = S.base_duration(short_base * 1.01, short_base * 0.99)
        assert long_score["bars"] > short_score["bars"]
        assert long_score["score"] > short_score["score"]

    def test_base_duration_handles_short_history(self):
        assert S.base_duration(np.arange(5.0), np.arange(5.0))["score"] == 0.0

    def test_up_down_volume_detects_accumulation(self):
        """Heavy volume on up days, light on down days => accumulation."""
        closes = np.array([100 + (1 if i % 2 == 0 else -1) * 0.5 for i in range(60)])
        changes = np.diff(closes)
        volumes = np.concatenate([[1e6], np.where(changes > 0, 3e6, 1e6)])
        accumulating = S.up_down_volume_ratio(closes, volumes)
        distributing = S.up_down_volume_ratio(closes, np.concatenate([[1e6], np.where(changes > 0, 1e6, 3e6)]))
        assert accumulating["score"] > distributing["score"]
        assert accumulating["ratio"] > 1.0
        assert distributing["ratio"] < 1.0

    def test_up_down_volume_handles_no_down_days(self):
        closes = np.linspace(100, 130, 60)
        out = S.up_down_volume_ratio(closes, np.full(60, 1e6))
        assert out["score"] == 1.0

    def test_tight_closes_rewards_narrow_range(self):
        tight = S.tight_closes(np.array([100.0, 100.1, 99.95, 100.05, 100.0]))
        loose = S.tight_closes(np.array([100.0, 104.0, 97.0, 102.0, 99.0]))
        assert tight["tight"] is True
        assert tight["score"] > loose["score"]
        assert loose["score"] == 0.0

    def test_breakout_trigger_requires_volume(self):
        closes = np.array([95.0, 96.0, 101.0])
        assert S.breakout_trigger(closes, pivot=100.0, vol_ratio=2.0) is True
        assert S.breakout_trigger(closes, pivot=100.0, vol_ratio=1.0) is False

    def test_breakout_trigger_rejects_overextension(self):
        closes = np.array([95.0, 96.0, 130.0])
        assert S.breakout_trigger(closes, pivot=100.0, vol_ratio=3.0) is False

    def test_breakout_trigger_uses_prior_complete_bar(self):
        """Mid-session partial bars must not suppress a real confirmed move."""
        closes = np.array([95.0, 101.0, 101.5])
        assert S.breakout_trigger(closes, 100.0, vol_ratio=0.3, vol_ratio_confirmed=2.0) is True

    def test_classify_setup_never_returns_confirmed_breakout(self):
        closes, volumes = coiling_series()
        sig = S.compute_structure_signals(make_ohlc(closes, volumes))
        assert sig["setup_type"] != "confirmed_breakout"


# --------------------------------------------------------------------------- #
# Unusual Whales normalizers
# --------------------------------------------------------------------------- #
class TestUwSignals:
    def test_oi_accumulation_missing_returns_none(self):
        """Missing OI data is not the same as zero OI growth."""
        assert UW.oi_accumulation({}) is None

    def test_oi_accumulation_reads_real_value(self):
        assert UW.oi_accumulation({"call_oi_change_perc": 12.5}) == 12.5

    def test_oi_accumulation_zero_is_preserved(self):
        assert UW.oi_accumulation({"call_oi_change_perc": 0.0}) == 0.0

    def test_screener_metrics_tolerates_string_numerics(self):
        metrics = UW.screener_metrics({"iv_rank": "42.5", "net_call_premium": "1000"})
        assert metrics["iv_rank"] == 42.5
        assert metrics["net_call_premium"] == 1000.0

    def test_screener_metrics_on_empty_row(self):
        assert UW.screener_metrics(None) == {}

    def test_earnings_within_window(self):
        from datetime import datetime, timedelta

        soon = (datetime.utcnow() + timedelta(days=5)).strftime("%Y-%m-%d")
        far = (datetime.utcnow() + timedelta(days=90)).strftime("%Y-%m-%d")
        assert UW.earnings_within(soon, 35) is True
        assert UW.earnings_within(far, 35) is False
        assert UW.earnings_within(None, 35) is False


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #
def base_feature(**overrides):
    feat = {
        "symbol": "TEST",
        "compression": 0.5,
        "vcp": 0.5,
        "nr_tightness": 0.5,
        "volume_dryup": 0.5,
        "base_quality": 0.5,
        "base_duration": 0.5,
        "up_down_volume": 0.5,
        "tight_closes": 0.5,
        "pivot": 0.5,
        "near_52wk_high": 0.5,
        "rs_raw": 0.1,
        "sector_rs_raw": 0.1,
        "flow_bullishness": 1000.0,
        "oi_accum": 10.0,
        "darkpool_premium": 1e6,
        "smart_money_score": 0.5,
        "gex_score": 0.5,
    }
    feat.update(overrides)
    return feat


class TestScoring:
    def test_score_is_bounded_and_explained(self):
        feats = [base_feature(symbol="A"), base_feature(symbol="B", compression=0.9)]
        score_candidates(feats, weights=DEFAULT_WEIGHTS)
        for f in feats:
            assert 0.0 <= f["score"] <= 100.0
            assert set(DEFAULT_WEIGHTS).issubset(f["factor_breakdown"])
            assert "penalty" in f["factor_breakdown"]
            assert "regime_scale" in f["factor_breakdown"]

    def test_missing_gex_scores_neutral_not_zero(self):
        """A failed UW call must not rank below a genuine long-gamma book."""
        missing = base_feature(symbol="MISSING", gex_score=None)
        worst = base_feature(symbol="WORST", gex_score=0.0)
        score_candidates([missing, worst], weights=DEFAULT_WEIGHTS)
        assert missing["score"] > worst["score"]
        assert missing["factor_breakdown"]["gex"] == NEUTRAL

    def test_missing_oi_ranks_neutral(self):
        missing = base_feature(symbol="MISSING", oi_accum=None)
        low = base_feature(symbol="LOW", oi_accum=-50.0)
        high = base_feature(symbol="HIGH", oi_accum=90.0)
        score_candidates([missing, low, high], weights=DEFAULT_WEIGHTS)
        assert low["score"] < missing["score"] < high["score"]

    def test_earnings_penalty_lowers_score(self):
        clean = base_feature(symbol="CLEAN")
        flagged = base_feature(symbol="FLAGGED", earnings_flag=True)
        score_candidates([clean, flagged], weights=DEFAULT_WEIGHTS)
        assert flagged["score"] < clean["score"]
        assert flagged["factor_breakdown"]["penalty"] == pytest.approx(0.10)

    def test_bearish_flow_penalty(self):
        clean = base_feature(symbol="CLEAN")
        bearish = base_feature(
            symbol="BEARISH", bullish_premium=1_000.0, bearish_premium=100_000.0
        )
        score_candidates([clean, bearish], weights=DEFAULT_WEIGHTS)
        assert bearish["factor_breakdown"]["penalty"] >= 0.10

    def test_regime_scale_multiplies_score(self):
        risk_on = [base_feature(symbol="A"), base_feature(symbol="B", compression=0.9)]
        risk_off = [base_feature(symbol="A"), base_feature(symbol="B", compression=0.9)]
        score_candidates(risk_on, weights=DEFAULT_WEIGHTS, regime_scale=1.0)
        score_candidates(risk_off, weights=DEFAULT_WEIGHTS, regime_scale=0.75)
        assert risk_off[0]["score"] == pytest.approx(risk_on[0]["score"] * 0.75, rel=1e-3)

    def test_base_construction_contributes(self):
        weak = base_feature(symbol="WEAK", base_duration=0.0, up_down_volume=0.0, tight_closes=0.0)
        strong = base_feature(symbol="STRONG", base_duration=1.0, up_down_volume=1.0, tight_closes=1.0)
        score_candidates([weak, strong], weights=DEFAULT_WEIGHTS)
        assert strong["score"] > weak["score"]
        assert strong["factor_breakdown"]["base_construction"] == pytest.approx(1.0)

    def test_empty_feature_list_is_a_noop(self):
        score_candidates([], weights=DEFAULT_WEIGHTS)  # must not raise


# --------------------------------------------------------------------------- #
# Fake providers + end-to-end run_scan
# --------------------------------------------------------------------------- #
class FakePriceProvider:
    """Serves deterministic synthetic history for any symbol."""

    def __init__(self, series_by_symbol=None, default=None):
        self.series_by_symbol = series_by_symbol or {}
        self.default = default if default is not None else coiling_series()
        self.calls = []

    def get_price_history(self, symbol, days=365):
        self.calls.append(symbol)
        closes, volumes = self.series_by_symbol.get(symbol, self.default)
        return make_ohlc(closes, volumes)


class FakeUwProvider:
    """Minimal SmartMoneyProvider that returns empty/neutral payloads."""

    def __init__(self, available=True, screener=None):
        self.available = available
        self.screener = screener or {}

    def is_available(self):
        return self.available

    def stock_screener(self, tickers):
        return {t: self.screener.get(t, {}) for t in tickers}

    def flow_alerts(self, ticker):
        return []

    def greek_exposure(self, ticker):
        return {}

    def darkpool(self, ticker):
        return []

    def insider_buy_sells(self, ticker):
        return {}

    def congress_trades(self, ticker):
        return []

    def seasonality(self, ticker):
        return []

    def close(self):
        pass


class TestRunScan:
    def test_empty_universe_returns_warning(self):
        result = run_scan([], price_provider=FakePriceProvider())
        assert result.candidates == []
        assert "Empty universe" in result.warnings

    def test_ranks_and_limits_to_top_n(self):
        provider = FakePriceProvider()
        result = run_scan(
            ["AAA", "BBB", "CCC", "DDD"],
            config=ScannerConfig(top_n=2, use_unusual_whales=False),
            price_provider=provider,
        )
        assert len(result.candidates) == 2
        assert [c.rank for c in result.candidates] == [1, 2]
        assert result.candidates[0].score >= result.candidates[1].score

    def test_runs_without_unusual_whales(self):
        result = run_scan(
            ["AAA", "BBB"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=FakePriceProvider(),
        )
        assert result.used_unusual_whales is False
        assert len(result.candidates) == 2

    def test_universe_is_normalized_and_deduped(self):
        result = run_scan(
            [" aaa ", "AAA", "bbb", ""],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=FakePriceProvider(),
        )
        assert result.universe_size == 2

    def test_already_broken_out_names_are_excluded(self):
        """The scanner answers 'what is about to break out', never 'what did'."""
        rng = np.random.default_rng(11)
        # A clean base that then gaps decisively above the pivot on huge volume.
        base = np.concatenate([np.linspace(50, 100, 220), 100 + rng.normal(0, 0.3, 75)])
        broken = np.concatenate([base, [104.0, 105.0, 106.0]])
        volumes = np.concatenate([np.full(len(base), 1e6), [9e6, 9e6, 9e6]])

        provider = FakePriceProvider(
            series_by_symbol={"BROKE": (broken, volumes), "COIL": coiling_series()}
        )
        result = run_scan(
            ["BROKE", "COIL"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=provider,
        )
        assert "BROKE" not in result.top_symbols
        assert "COIL" in result.top_symbols

    def test_price_filters_drop_out_of_band_names(self):
        cheap = (np.full(300, 2.0), np.full(300, 1e6))
        provider = FakePriceProvider(series_by_symbol={"CHEAP": cheap})
        result = run_scan(
            ["CHEAP", "GOOD"],
            config=ScannerConfig(min_price=10.0, use_unusual_whales=False),
            price_provider=provider,
        )
        assert "CHEAP" not in result.top_symbols

    def test_illiquid_names_are_dropped(self):
        thin = (coiling_series()[0], np.full(300, 1_000.0))
        provider = FakePriceProvider(series_by_symbol={"THIN": thin})
        result = run_scan(
            ["THIN", "GOOD"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=provider,
        )
        assert "THIN" not in result.top_symbols

    def test_provider_errors_do_not_abort_the_scan(self):
        class FlakyProvider(FakePriceProvider):
            def get_price_history(self, symbol, days=365):
                if symbol == "BOOM":
                    raise RuntimeError("upstream exploded")
                return super().get_price_history(symbol, days)

        result = run_scan(
            ["BOOM", "GOOD"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=FlakyProvider(),
        )
        assert result.top_symbols == ["GOOD"]

    def test_uw_provider_is_used_when_available(self):
        uw = FakeUwProvider(screener={"AAA": {"iv_rank": "55", "call_oi_change_perc": "20"}})
        result = run_scan(
            ["AAA", "BBB"],
            config=ScannerConfig(use_unusual_whales=True),
            price_provider=FakePriceProvider(),
            uw_provider=uw,
        )
        assert result.used_unusual_whales is True
        by_symbol = {c.symbol: c for c in result.candidates}
        assert by_symbol["AAA"].iv_rank == 55.0

    def test_unavailable_uw_degrades_gracefully(self):
        result = run_scan(
            ["AAA", "BBB"],
            config=ScannerConfig(use_unusual_whales=True),
            price_provider=FakePriceProvider(),
            uw_provider=FakeUwProvider(available=False),
        )
        assert result.used_unusual_whales is False
        assert len(result.candidates) == 2

    def test_candidate_carries_pivot_context(self):
        result = run_scan(
            ["AAA"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=FakePriceProvider(),
        )
        candidate = result.candidates[0]
        assert candidate.pivot_price is not None
        assert candidate.pct_to_pivot is not None
        assert candidate.suggested_put_strike < candidate.current_price

    def test_result_serializes(self):
        result = run_scan(
            ["AAA"],
            config=ScannerConfig(use_unusual_whales=False),
            price_provider=FakePriceProvider(),
        )
        payload = result.to_dict()
        assert payload["candidates"][0]["symbol"] == "AAA"
        assert "factor_breakdown" in payload["candidates"][0]
        assert "pct_to_pivot" in payload["candidates"][0]


# --------------------------------------------------------------------------- #
# Auto-scan scheduler
# --------------------------------------------------------------------------- #
class FakeScheduleSettings:
    """Stand-in for the BreakoutScannerSettings row (schedule fields only)."""

    def __init__(self, **kwargs):
        self.enabled = kwargs.get("enabled", True)
        self.auto_scan_enabled = kwargs.get("auto_scan_enabled", True)
        self.auto_scan_time = kwargs.get("auto_scan_time", "16:30")
        self.auto_scan_timezone = kwargs.get("auto_scan_timezone", "America/New_York")
        self.auto_scan_days = kwargs.get("auto_scan_days", "0,1,2,3,4")
        self.last_auto_run_date = kwargs.get("last_auto_run_date", None)


def et(year, month, day, hour, minute=0):
    """A UTC instant expressed via New York wall-clock time."""
    local = datetime(year, month, day, hour, minute, tzinfo=ZoneInfo("America/New_York"))
    return local.astimezone(timezone.utc)


def plan(**kwargs):
    return SCH.plan_from_settings(FakeScheduleSettings(**kwargs))


class TestScheduleParsing:
    def test_defaults_are_30_minutes_after_the_close(self):
        assert SCH.parse_time_of_day(DEFAULT_AUTO_SCAN_TIME) == time(16, 30)
        assert DEFAULT_AUTO_SCAN_TIMEZONE == "America/New_York"
        assert parse_weekday_csv(DEFAULT_AUTO_SCAN_DAYS) == [0, 1, 2, 3, 4]

    @pytest.mark.parametrize("bad", ["", None, "nonsense", "25:00", "16:99"])
    def test_bad_time_falls_back_to_default(self, bad):
        assert SCH.parse_time_of_day(bad) == time(16, 30)

    def test_unknown_timezone_falls_back_to_market_zone(self):
        assert SCH.resolve_timezone("Mars/Olympus") == ZoneInfo(DEFAULT_AUTO_SCAN_TIMEZONE)

    def test_weekday_csv_dedupes_sorts_and_rejects_out_of_range(self):
        assert parse_weekday_csv("4,0,0,9,-1,2") == [0, 2, 4]

    def test_empty_weekday_csv_falls_back_rather_than_disabling(self):
        assert parse_weekday_csv("") == [0, 1, 2, 3, 4]


class TestIsDue:
    def test_not_due_before_the_scheduled_minute(self):
        # Monday 16:29 ET
        assert SCH.is_due(plan(), et(2026, 8, 17, 16, 29)) is False

    def test_due_at_the_scheduled_minute(self):
        assert SCH.is_due(plan(), et(2026, 8, 17, 16, 30)) is True

    def test_still_due_inside_the_catchup_window(self):
        # Process was down at 16:30 and came back at 19:00 the same day
        assert SCH.is_due(plan(), et(2026, 8, 17, 19, 0)) is True

    def test_not_due_once_the_catchup_window_closes(self):
        # 4h window means 20:30 ET is past the edge
        assert SCH.is_due(plan(), et(2026, 8, 17, 21, 0)) is False

    def test_not_due_on_an_unselected_weekday(self):
        # Saturday
        assert SCH.is_due(plan(), et(2026, 8, 22, 17, 0)) is False

    def test_not_due_twice_on_the_same_day(self):
        already = plan(last_auto_run_date="2026-08-17")
        assert SCH.is_due(already, et(2026, 8, 17, 17, 0)) is False

    def test_yesterdays_marker_does_not_block_today(self):
        stale = plan(last_auto_run_date="2026-08-14")
        assert SCH.is_due(stale, et(2026, 8, 17, 17, 0)) is True

    def test_auto_disabled_is_never_due(self):
        assert SCH.is_due(plan(auto_scan_enabled=False), et(2026, 8, 17, 17, 0)) is False

    def test_master_switch_off_is_never_due(self):
        assert SCH.is_due(plan(enabled=False), et(2026, 8, 17, 17, 0)) is False


class TestNextRunAt:
    def test_next_run_is_todays_slot_when_still_ahead(self):
        nxt = SCH.next_run_at(plan(), et(2026, 8, 17, 9, 0))
        assert nxt == et(2026, 8, 17, 16, 30)

    def test_next_run_rolls_to_monday_from_a_weekend(self):
        # Saturday -> Monday
        nxt = SCH.next_run_at(plan(), et(2026, 8, 22, 12, 0))
        assert nxt == et(2026, 8, 24, 16, 30)

    def test_next_run_skips_today_once_it_has_run(self):
        nxt = SCH.next_run_at(plan(last_auto_run_date="2026-08-17"), et(2026, 8, 17, 17, 0))
        assert nxt == et(2026, 8, 18, 16, 30)

    def test_next_run_skips_today_after_the_catchup_window_closed(self):
        nxt = SCH.next_run_at(plan(), et(2026, 8, 17, 23, 0))
        assert nxt == et(2026, 8, 18, 16, 30)

    def test_next_run_is_none_when_auto_scan_is_off(self):
        assert SCH.next_run_at(plan(auto_scan_enabled=False), et(2026, 8, 17, 9, 0)) is None

    def test_next_run_survives_a_dst_boundary(self):
        # US DST ends Sun 2026-11-01; the slot stays at 16:30 local either side.
        before = SCH.next_run_at(plan(), et(2026, 10, 30, 9, 0))
        after = SCH.next_run_at(plan(), et(2026, 11, 2, 9, 0))
        for moment in (before, after):
            local = moment.astimezone(ZoneInfo("America/New_York"))
            assert (local.hour, local.minute) == (16, 30)
        # ...even though the UTC offset shifted by an hour across the boundary.
        assert before.hour != after.hour

    def test_next_run_agrees_with_is_due(self):
        """next_run_at must never report a future slot while is_due says 'now'."""
        now = et(2026, 8, 17, 17, 0)
        assert SCH.is_due(plan(), now) is True
        assert SCH.next_run_at(plan(), now) <= now


class TestScheduleSummary:
    def test_summary_names_time_zone_and_days(self):
        assert SCH.describe_schedule(plan()) == (
            "16:30 America/New_York on Mon,Tue,Wed,Thu,Fri"
        )

    def test_summary_reports_off_state(self):
        assert SCH.describe_schedule(plan(auto_scan_enabled=False)) == "Automatic scan is off"


class TestSchedulerLoop:
    """The async loop: dispatch happens only when the claim succeeds."""

    def test_tick_runs_the_scan_when_the_claim_is_won(self):
        calls = []
        sched = SCH.AutoScanScheduler(runner=lambda: calls.append("ran"))
        sched._claim_if_due = lambda now: "2026-08-17"
        assert asyncio.run(sched.tick(et(2026, 8, 17, 16, 30))) is True
        assert calls == ["ran"]

    def test_tick_is_a_noop_when_not_due(self):
        calls = []
        sched = SCH.AutoScanScheduler(runner=lambda: calls.append("ran"))
        sched._claim_if_due = lambda now: None
        assert asyncio.run(sched.tick(et(2026, 8, 17, 10, 0))) is False
        assert calls == []
