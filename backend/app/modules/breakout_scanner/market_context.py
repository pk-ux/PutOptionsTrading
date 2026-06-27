"""
Breakout Scanner - market context & regime (fear/greed) layer.

Breakouts succeed far more often when the broad tape is risk-on and fail in
risk-off. This module condenses the market backdrop into a single
``MarketContext`` (a 0-100 fear/greed score, a ``risk_on | neutral | risk_off``
regime label, and a ``regime_scale`` multiplier the scorer applies to every
candidate) so the scanner stops picking names in a vacuum.

Inputs, all optional and individually degrading to neutral:
  - SPY / QQQ trend vs 50/200-DMA and short-term slope (price provider)
  - VIX level + 5-day change (price provider, e.g. ``^VIX``)
  - Internal breadth: % of the scanned universe above its own 50-DMA
  - Unusual Whales market-tide (net market call vs put premium) and SPIKE

Pure-ish: depends only on the injected providers (no app imports), so it travels
with the portable core.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class MarketContext:
    """Condensed market backdrop used to gate/scale candidate scores."""

    regime: str = "neutral"            # risk_on | neutral | risk_off
    fear_greed: float = 50.0           # 0 = extreme fear, 100 = extreme greed
    regime_scale: float = 1.0          # score multiplier applied in scoring
    spy_trend: Optional[float] = None  # 0..1
    qqq_trend: Optional[float] = None  # 0..1
    breadth: Optional[float] = None    # 0..1 (% of universe above 50-DMA)
    vix: Optional[float] = None
    vix_change_5d: Optional[float] = None  # percent
    market_tide: Optional[float] = None    # 0..1 (bullish tape)
    spike: Optional[float] = None
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "regime": self.regime,
            "fear_greed": round(self.fear_greed, 1),
            "regime_scale": round(self.regime_scale, 3),
            "spy_trend": _round(self.spy_trend, 3),
            "qqq_trend": _round(self.qqq_trend, 3),
            "breadth": _round(self.breadth, 3),
            "vix": _round(self.vix, 2),
            "vix_change_5d": _round(self.vix_change_5d, 2),
            "market_tide": _round(self.market_tide, 3),
            "spike": _round(self.spike, 2),
            "notes": self.notes,
        }


def _round(v: Optional[float], digits: int) -> Optional[float]:
    if v is None:
        return None
    try:
        return round(float(v), digits)
    except (TypeError, ValueError):
        return None


def _clip01(x: float) -> float:
    if x != x:
        return 0.0
    return float(max(0.0, min(1.0, x)))


def _index_trend(closes: Optional[np.ndarray]) -> Optional[float]:
    """0..1 trend health for an index from price vs 50/200-DMA + 20d slope."""
    if closes is None or len(closes) < 60:
        return None
    price = float(closes[-1])
    sma50 = float(np.mean(closes[-50:]))
    sma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else sma50
    # Smooth distance terms (not just binary above/below).
    above50 = _clip01(0.5 + (price - sma50) / sma50 * 5.0) if sma50 > 0 else 0.5
    above200 = _clip01(0.5 + (price - sma200) / sma200 * 2.5) if sma200 > 0 else 0.5
    past = float(closes[-21])
    slope = _clip01(0.5 + (price - past) / past * 5.0) if past > 0 else 0.5
    return _clip01(0.4 * above50 + 0.35 * above200 + 0.25 * slope)


def _fetch_closes(price_provider, symbol: str, days: int, log) -> Optional[np.ndarray]:
    try:
        hist = price_provider.get_price_history(symbol, days=days)
        if hist:
            return np.array([p["close"] for p in hist], dtype=float)
    except Exception as e:  # pragma: no cover - network
        log.debug(f"market_context: history failed for {symbol}: {e}")
    return None


def _vix_fear_greed(vix: Optional[float]) -> Optional[float]:
    """Map VIX to a 0..1 greed score (low VIX = greed, high VIX = fear)."""
    if vix is None or vix <= 0:
        return None
    # ~12 -> greed (1.0), ~32 -> fear (0.0)
    return _clip01((32.0 - vix) / (32.0 - 12.0))


def _tide_fear_greed(tide_rows: List[Dict[str, Any]]) -> Optional[float]:
    """Bullish-tape score 0..1 from UW market-tide cumulative premium."""
    if not tide_rows:
        return None
    last = tide_rows[-1]
    try:
        ncp = float(last.get("net_call_premium") or 0.0)
        npp = float(last.get("net_put_premium") or 0.0)
    except (TypeError, ValueError):
        return None
    bullish = ncp - npp  # calls bought (+) and puts sold (npp<0) are both bullish
    return _clip01(0.5 + 0.5 * math.tanh(bullish / 1.0e9))


def _parse_spike(payload: Any) -> Optional[float]:
    """Best-effort SPIKE value extraction (shape varies)."""
    rows: List[Any] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            rows = data
        elif data is not None:
            rows = [data]
        else:
            rows = [payload]
    for row in rows[::-1]:
        if isinstance(row, dict):
            for k in ("spike", "value", "price", "close"):
                v = row.get(k)
                if v is not None:
                    try:
                        return float(v)
                    except (TypeError, ValueError):
                        continue
        else:
            try:
                return float(row)
            except (TypeError, ValueError):
                continue
    return None


def compute_market_context(
    price_provider,
    uw_provider=None,
    index_provider=None,
    spy_closes: Optional[np.ndarray] = None,
    breadth_pct: Optional[float] = None,
    history_days: int = 365,
    logger: Optional[logging.Logger] = None,
) -> MarketContext:
    """Build the market backdrop. Every input degrades to neutral on failure.

    ``index_provider`` (e.g. Yahoo) is used for SPY/QQQ/VIX so the regime can be
    computed even when the universe price provider (e.g. Alpaca) can't supply
    index/^VIX series. Falls back to ``price_provider`` when not given.
    """
    log = logger or logging.getLogger(__name__)
    ctx = MarketContext()

    idx = index_provider or price_provider
    # When a dedicated index provider is supplied, fetch SPY from it rather than
    # reusing the universe provider's SPY series (keeps the index source consistent).
    if index_provider is not None or spy_closes is None:
        spy_closes = _fetch_closes(idx, "SPY", history_days, log)
    qqq_closes = _fetch_closes(idx, "QQQ", history_days, log)

    ctx.spy_trend = _index_trend(spy_closes)
    ctx.qqq_trend = _index_trend(qqq_closes)
    ctx.breadth = _clip01(breadth_pct) if breadth_pct is not None else None

    # VIX (best-effort; some providers can't supply ^VIX -> stays None)
    vix_closes = _fetch_closes(idx, "^VIX", 60, log)
    if vix_closes is not None and len(vix_closes) > 5:
        ctx.vix = float(vix_closes[-1])
        prior = float(vix_closes[-6])
        if prior > 0:
            ctx.vix_change_5d = float((vix_closes[-1] - prior) / prior * 100.0)

    # Unusual Whales market tide + SPIKE
    if uw_provider is not None and getattr(uw_provider, "is_available", lambda: False)():
        tide_fn = getattr(uw_provider, "market_tide", None)
        if callable(tide_fn):
            try:
                ctx.market_tide = _tide_fear_greed(tide_fn())
            except Exception as e:
                log.debug(f"market_context: market_tide failed: {e}")
        spike_fn = getattr(uw_provider, "spike", None)
        if callable(spike_fn):
            try:
                ctx.spike = _parse_spike(spike_fn())
            except Exception as e:
                log.debug(f"market_context: spike failed: {e}")

    # --- Blend available components into a 0..100 fear/greed score ---
    components: List[tuple] = []  # (value 0..1, weight)
    trend_vals = [v for v in (ctx.spy_trend, ctx.qqq_trend) if v is not None]
    if trend_vals:
        components.append((float(np.mean(trend_vals)), 0.30))
    if ctx.breadth is not None:
        components.append((ctx.breadth, 0.20))
    vix_fg = _vix_fear_greed(ctx.vix)
    if vix_fg is not None:
        components.append((vix_fg, 0.25))
    if ctx.market_tide is not None:
        components.append((ctx.market_tide, 0.15))
    spike_fg = _vix_fear_greed(ctx.spike)  # SPIKE behaves like VIX
    if spike_fg is not None:
        components.append((spike_fg, 0.10))

    if components:
        wsum = sum(w for _v, w in components)
        fg = sum(v * w for v, w in components) / wsum if wsum > 0 else 0.5
    else:
        fg = 0.5
        ctx.notes.append("No market-context inputs available; neutral regime assumed.")
    ctx.fear_greed = round(fg * 100.0, 1)

    # --- Regime + score multiplier ---
    if ctx.fear_greed >= 60:
        ctx.regime = "risk_on"
    elif ctx.fear_greed >= 40:
        ctx.regime = "neutral"
    else:
        ctx.regime = "risk_off"

    # Hard override: a clearly broken SPY tape forces risk_off regardless.
    if ctx.spy_trend is not None and ctx.spy_trend < 0.30:
        ctx.regime = "risk_off"
        ctx.notes.append("SPY below trend - risk_off override.")

    # Smooth multiplier in [0.70, 1.10].
    scale = 0.70 + 0.40 * (ctx.fear_greed / 100.0)
    if ctx.regime == "risk_off":
        scale = min(scale, 0.80)
    ctx.regime_scale = float(max(0.70, min(1.10, scale)))
    return ctx
