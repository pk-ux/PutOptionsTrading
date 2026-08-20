"""
Tests for the Flow & Positioning direction score.

Fixtures are trimmed real Unusual Whales payloads (NBIS, 2026-08-19) so the
scoring math is exercised without network access.
"""

from app.services.direction import (
    DIRECTION_WEIGHTS,
    _signal_dark_pool,
    _signal_flow,
    _signal_gamma,
    _signal_insider,
    score_direction,
)


def _future(days: int) -> str:
    from datetime import timedelta

    from app.core.market_clock import market_today

    return (market_today() + timedelta(days=days)).isoformat()


FLOW_ROWS = [
    {
        "expiry": _future(16),
        "call_premium_ask_side": "32049509.00",
        "call_premium_bid_side": "22830412.00",
        "put_premium_ask_side": "23935508.00",
        "put_premium_bid_side": "20622274.00",
    },
    {
        "expiry": _future(30),
        "call_premium_ask_side": "8410219.00",
        "call_premium_bid_side": "26870591.00",
        "put_premium_ask_side": "8760976.00",
        "put_premium_bid_side": "8023326.00",
    },
]

GREEK_ROWS = [
    {"call_delta": "47585187", "put_delta": "-6475763", "call_gamma": "199667", "put_gamma": "-87926"},
    {"call_delta": "47211578", "put_delta": "-7107367", "call_gamma": "214167", "put_gamma": "-106712"},
    {"call_delta": "39798612", "put_delta": "-11870531", "call_gamma": "241539", "put_gamma": "-182434"},
    {"call_delta": "40100000", "put_delta": "-11000000", "call_gamma": "230000", "put_gamma": "-170000"},
    {"call_delta": "41000000", "put_delta": "-10500000", "call_gamma": "225000", "put_gamma": "-160000"},
]

DARK_POOL = {
    "data": [
        {"price": "216", "dark_pool_volume": "1259478"},
        {"price": "224", "dark_pool_volume": "1699228"},
        {"price": "232", "dark_pool_volume": "389601"},
    ]
}

MAX_PAIN = {"data": [{"expiry": _future(16), "max_pain": "222.5", "close": "223.9"}]}

INSIDER_ROWS = [
    # Real NBIS shape: a large sale that is entirely a pre-scheduled 10b5-1 plan.
    {"date": _future(-5), "premium": "-14102691.84", "premium_10b5": "-14102691.84"},
    {"date": _future(-78), "premium": "-416785.8", "premium_10b5": "0"},
]


def _bundle(**overrides):
    base = {
        "symbol": "NBIS",
        "flow_per_expiry": FLOW_ROWS,
        "greek_series": GREEK_ROWS,
        "dark_pool_levels": DARK_POOL,
        "insider_flow": INSIDER_ROWS,
        "max_pain": MAX_PAIN,
    }
    base.update(overrides)
    return base


class TestSignals:
    def test_flow_uses_ask_bid_aggressor_convention(self):
        """Ask-side calls + bid-side puts are bullish; the mirror is bearish."""
        # Near expiry alone: bull 32.0M + 20.6M vs bear 23.9M + 22.8M -> bullish
        score, detail = _signal_flow([FLOW_ROWS[0]], dte_target=16)
        assert 0 < score < 1
        assert "bullish" in detail

        # Flip every side and the sign must flip with it.
        flipped = [{
            "expiry": FLOW_ROWS[0]["expiry"],
            "call_premium_ask_side": FLOW_ROWS[0]["call_premium_bid_side"],
            "call_premium_bid_side": FLOW_ROWS[0]["call_premium_ask_side"],
            "put_premium_ask_side": FLOW_ROWS[0]["put_premium_bid_side"],
            "put_premium_bid_side": FLOW_ROWS[0]["put_premium_ask_side"],
        }]
        flipped_score, _ = _signal_flow(flipped, dte_target=16)
        assert flipped_score == -score

    def test_flow_weights_expiries_near_the_target_dte(self):
        """The 30-day expiry is heavily bid-side calls, so it drags the read down."""
        near_only, _ = _signal_flow([FLOW_ROWS[0]], dte_target=16)
        both, _ = _signal_flow(FLOW_ROWS, dte_target=16)
        assert both < near_only

    def test_flow_needs_minimum_premium(self):
        tiny = [dict(FLOW_ROWS[0], call_premium_ask_side="10", call_premium_bid_side="10",
                     put_premium_ask_side="10", put_premium_bid_side="10")]
        assert _signal_flow(tiny, dte_target=16) is None

    def test_gamma_net_is_call_plus_put(self):
        # call_gamma 241539 + put_gamma -182434 > 0 -> dealers long gamma
        score, _, regime = _signal_gamma(GREEK_ROWS[:3])
        assert score > 0
        assert regime == "long_gamma"

    def test_gamma_short_when_puts_dominate(self):
        rows = [{"call_gamma": "100000", "put_gamma": "-250000"}]
        score, _, regime = _signal_gamma(rows)
        assert score < 0
        assert regime == "short_gamma"

    def test_dark_pool_above_vwap_is_bullish(self):
        score, _, vwap, poc = _signal_dark_pool(DARK_POOL, spot=228.0)
        assert score > 0
        assert 216 < vwap < 232
        assert poc == 224.0  # heaviest volume level

    def test_insider_ignores_10b5_planned_sales(self):
        """A large fully-planned 10b5-1 sale must not read as bearish."""
        rows = [{"date": _future(-5), "premium": "-14102691.84", "premium_10b5": "-14102691.84"}]
        score, detail = _signal_insider(rows)
        assert score == 0.0
        assert "10b5-1" in detail

    def test_insider_scales_by_materiality(self):
        """A small discretionary sale is a weak signal, not a maximal one."""
        small = [{"date": _future(-5), "premium": "-416785", "premium_10b5": "0"}]
        large = [{"date": _future(-5), "premium": "-20000000", "premium_10b5": "0"}]
        small_score, _ = _signal_insider(small)
        large_score, _ = _signal_insider(large)
        assert -0.2 < small_score < 0
        assert large_score == -1.0

    def test_insider_ignores_stale_rows(self):
        old = [{"date": _future(-400), "premium": "-20000000", "premium_10b5": "0"}]
        score, _ = _signal_insider(old)
        assert score == 0.0


class TestComposite:
    def test_full_coverage_and_weighted_mean(self):
        result = score_direction(_bundle(), spot=228.39, expiry=_future(16), strike=185.0)
        assert result["coverage"] == 1.0
        assert result["direction"] in ("BULLISH", "NEUTRAL", "BEARISH")
        available = {s["key"]: s["score"] for s in result["signals"] if s["available"]}
        expected = sum(DIRECTION_WEIGHTS[k] * v for k, v in available.items())
        assert abs(result["score"] / 100.0 - expected) < 0.01

    def test_degrades_when_a_signal_is_missing(self):
        full = score_direction(_bundle(), spot=228.39)
        partial = score_direction(_bundle(dark_pool_levels=None), spot=228.39)
        assert partial["coverage"] < full["coverage"]
        missing = [s for s in partial["signals"] if s["key"] == "dark_pool"][0]
        assert missing["available"] is False
        assert missing["score"] is None

    def test_confidence_never_exceeds_coverage(self):
        """Missing data caps how much the read can be trusted."""
        for bundle in (_bundle(), _bundle(dark_pool_levels=None, insider_flow=None),
                       _bundle(flow_per_expiry=None, greek_series=None)):
            result = score_direction(bundle, spot=228.39)
            assert result["confidence"] <= result["coverage"] + 1e-9

    def test_no_data_yields_zero_coverage(self):
        result = score_direction({"symbol": "ZZZZ"}, spot=None)
        assert result["coverage"] == 0.0
        assert result["confidence"] == 0.0
        assert result["direction"] == "NEUTRAL"

    def test_disagreement_lowers_confidence(self):
        """Same magnitude of score, but conflicting signals should be trusted less."""
        agree = score_direction(
            {"symbol": "T", "greek_series": [{"call_gamma": "300000", "put_gamma": "-100000"}],
             "max_pain": {"data": [{"expiry": _future(20), "max_pain": "120"}]}},
            spot=100.0,
        )
        conflict = score_direction(
            {"symbol": "T", "greek_series": [{"call_gamma": "300000", "put_gamma": "-100000"}],
             "max_pain": {"data": [{"expiry": _future(20), "max_pain": "80"}]}},
            spot=100.0,
        )
        assert agree["confidence"] > conflict["confidence"]

    def test_all_signal_keys_always_reported(self):
        result = score_direction({"symbol": "X"}, spot=None)
        assert [s["key"] for s in result["signals"]] == list(DIRECTION_WEIGHTS)

    def test_put_seller_note_mentions_strike(self):
        result = score_direction(_bundle(), spot=228.39, expiry=_future(16), strike=185.0)
        assert "185" in result["put_seller_note"]
