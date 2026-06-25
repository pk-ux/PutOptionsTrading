"""
Breakout Scanner - price-structure LEADING signals.

Pure numpy functions, no app dependencies. Every signal here is anticipatory
(it fires *before* a breakout): volatility compression, NR7/inside-bar tightness,
VCP contraction, volume dry-up, relative-strength leadership and proximity to a
clean pivot. We deliberately avoid lagging trigger indicators (MACD / SMA-cross /
raw RSI level) as breakout signals.

All scores are returned in a 0..1 range unless noted (relative strength is a raw
value that is percentile-ranked across the universe later).
"""

from typing import Any, Dict, List, Optional

import numpy as np


def _clip01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return float(max(0.0, min(1.0, x)))


def _arrays(ohlc: List[Dict[str, Any]]):
    highs = np.array([p["high"] for p in ohlc], dtype=float)
    lows = np.array([p["low"] for p in ohlc], dtype=float)
    closes = np.array([p["close"] for p in ohlc], dtype=float)
    volumes = np.array([p.get("volume", 0) for p in ohlc], dtype=float)
    return highs, lows, closes, volumes


def bollinger_compression(closes: np.ndarray, period: int = 20, lookback: int = 126) -> Dict[str, Any]:
    """Volatility compression via Bollinger bandwidth percentile + squeeze flag.

    A low current bandwidth relative to its own recent history is the classic
    "coiled spring" that precedes expansion.
    """
    if len(closes) < period + 5:
        return {"compression": 0.0, "squeeze": False, "bandwidth": None}

    def bandwidth_at(end: int) -> Optional[float]:
        window = closes[end - period:end]
        if len(window) < period:
            return None
        m = float(np.mean(window))
        s = float(np.std(window))
        if m <= 0:
            return None
        return (2 * 2.0 * s) / m  # (upper-lower)/middle with 2 std

    current_bw = bandwidth_at(len(closes))
    if current_bw is None:
        return {"compression": 0.0, "squeeze": False, "bandwidth": None}

    hist = []
    start = max(period, len(closes) - lookback)
    for end in range(start, len(closes) + 1):
        bw = bandwidth_at(end)
        if bw is not None:
            hist.append(bw)

    if len(hist) < 10:
        return {"compression": 0.0, "squeeze": False, "bandwidth": current_bw}

    hist_arr = np.array(hist)
    # percentile of current bandwidth within its recent range (0 = tightest)
    pctl = float((hist_arr < current_bw).mean())
    compression = 1.0 - pctl  # tighter -> higher score
    squeeze = bool(current_bw < float(np.mean(hist_arr)) * 0.75 or pctl < 0.15)

    return {"compression": _clip01(compression), "squeeze": squeeze, "bandwidth": current_bw}


def nr_tightness(highs: np.ndarray, lows: np.ndarray, lookback: int = 7) -> float:
    """Recent range tightness (NR7 / inside-bar family).

    Compares the average true-ish range of the last `lookback` bars to the prior
    ~30 bars. Tighter recent action => higher score.
    """
    if len(highs) < lookback + 30:
        return 0.0
    rng = highs - lows
    recent = float(np.mean(rng[-lookback:]))
    prior = float(np.mean(rng[-lookback - 30:-lookback]))
    if prior <= 0:
        return 0.0
    ratio = recent / prior
    return _clip01(1.2 - ratio)  # ratio 0.2 -> 1.0, 1.0 -> 0.2


def vcp_contraction(highs: np.ndarray, lows: np.ndarray, segments: int = 4, seg_len: int = 10) -> float:
    """Volatility Contraction Pattern: successively tighter swings into the base.

    Splits the recent window into segments and rewards monotonically shrinking
    ranges (each contraction shallower than the last).
    """
    needed = segments * seg_len
    if len(highs) < needed:
        return 0.0
    ranges = []
    for i in range(segments):
        end = len(highs) - i * seg_len
        seg_h = highs[end - seg_len:end]
        seg_l = lows[end - seg_len:end]
        if len(seg_h) < seg_len:
            return 0.0
        ranges.append(float(np.max(seg_h) - np.min(seg_l)))
    # ranges[0] = most recent. Reward recent < older (monotonic contraction).
    contractions = 0
    for i in range(len(ranges) - 1):
        if ranges[i] < ranges[i + 1]:
            contractions += 1
    base = contractions / (len(ranges) - 1)
    # Bonus if the most recent segment is much tighter than the oldest
    if ranges[-1] > 0:
        tightness = 1.0 - (ranges[0] / ranges[-1])
        base = 0.6 * base + 0.4 * _clip01(tightness)
    return _clip01(base)


def volume_dryup(volumes: np.ndarray, short: int = 5, long: int = 20) -> float:
    """Volume drying up into the base (sellers exhausted) => higher score."""
    if len(volumes) < long:
        return 0.0
    v_short = float(np.mean(volumes[-short:]))
    v_long = float(np.mean(volumes[-long:]))
    if v_long <= 0:
        return 0.0
    ratio = v_short / v_long
    return _clip01(1.2 - ratio)


def relative_strength(closes: np.ndarray, spy_closes: Optional[np.ndarray]) -> float:
    """Raw relative-strength vs SPY (outperformance, with a rising bonus).

    Returned as a raw value (can be negative); percentile-ranked across the
    universe in scoring. If SPY data is missing, falls back to the stock's own
    multi-window momentum so the factor still differentiates names.
    """
    def ret(arr: np.ndarray, n: int) -> Optional[float]:
        if len(arr) <= n or arr[-n - 1] == 0:
            return None
        return (arr[-1] - arr[-n - 1]) / arr[-n - 1]

    windows = [20, 40, 60]
    if spy_closes is not None and len(spy_closes) > 60:
        diffs = []
        for n in windows:
            r_s = ret(closes, n)
            r_m = ret(spy_closes, n)
            if r_s is not None and r_m is not None:
                diffs.append(r_s - r_m)
        if not diffs:
            return 0.0
        rs = float(np.mean(diffs))
        # rising bonus: short-window outperformance stronger than long-window
        short_rs = (ret(closes, 20) or 0) - (ret(spy_closes, 20) or 0)
        long_rs = (ret(closes, 60) or 0) - (ret(spy_closes, 60) or 0)
        if short_rs > long_rs:
            rs += 0.01
        return rs
    # Fallback: own momentum
    vals = [ret(closes, n) for n in windows]
    vals = [v for v in vals if v is not None]
    return float(np.mean(vals)) if vals else 0.0


def detect_pivot(highs: np.ndarray, closes: np.ndarray, window: int = 40, exclude: int = 2) -> Optional[float]:
    """Identify the nearest overhead breakout pivot (recent swing high)."""
    if len(highs) < window + exclude:
        return None
    region = highs[-window - exclude:-exclude] if exclude > 0 else highs[-window:]
    if len(region) == 0:
        return None
    return float(np.max(region))


def pivot_proximity(current_price: float, pivot: Optional[float]) -> float:
    """Score for price coiling *just below* the pivot (pre-breakout zone).

    Highest when price sits within ~0-4% under the pivot. Penalizes names that
    already broke out (we want them *before* the move) or are far below.
    """
    if not pivot or pivot <= 0 or not current_price or current_price <= 0:
        return 0.0
    dist = (pivot - current_price) / pivot  # >0 below pivot, <0 above
    if dist < -0.02:
        return 0.1  # already extended above pivot
    if dist < 0:
        return 0.5  # just poked above (still interesting)
    if dist <= 0.04:
        return 1.0 - (dist / 0.04) * 0.2  # 0% -> 1.0, 4% -> 0.8
    if dist <= 0.12:
        return _clip01(0.8 - (dist - 0.04) / 0.08 * 0.6)
    return 0.1


def atr(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 14) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    hl = highs[1:] - lows[1:]
    hc = np.abs(highs[1:] - closes[:-1])
    lc = np.abs(lows[1:] - closes[:-1])
    tr = np.maximum(hl, np.maximum(hc, lc))
    if len(tr) < period:
        return None
    return float(np.mean(tr[-period:]))


def classify_setup(sig: Dict[str, float]) -> str:
    """Human-readable setup label from the computed structure signals."""
    if sig.get("compression", 0) > 0.6 and sig.get("squeeze"):
        if sig.get("pivot", 0) > 0.6:
            return "squeeze_breakout_setup"
        return "volatility_squeeze"
    if sig.get("vcp", 0) > 0.6:
        return "vcp_base"
    if sig.get("pivot", 0) > 0.6 and sig.get("volume_dryup", 0) > 0.5:
        return "flat_base"
    if sig.get("pivot", 0) > 0.5:
        return "ascending_base"
    return "consolidation"


def compute_structure_signals(
    ohlc: List[Dict[str, Any]],
    spy_closes: Optional[np.ndarray] = None,
) -> Dict[str, Any]:
    """Compute all price-structure leading signals for one ticker.

    Returns a dict of raw factor values plus context (current_price, avg_volume,
    pivot_price, setup_type). Returns ``{}`` if there is not enough data.
    """
    if not ohlc or len(ohlc) < 40:
        return {}

    highs, lows, closes, volumes = _arrays(ohlc)
    current_price = float(closes[-1])

    comp = bollinger_compression(closes)
    pivot = detect_pivot(highs, closes)
    sma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else None

    sig: Dict[str, Any] = {
        "compression": comp["compression"],
        "squeeze": comp["squeeze"],
        "nr_tightness": nr_tightness(highs, lows),
        "vcp": vcp_contraction(highs, lows),
        "volume_dryup": volume_dryup(volumes),
        "rs_raw": relative_strength(closes, spy_closes),
        "pivot": pivot_proximity(current_price, pivot),
        # context
        "current_price": current_price,
        "avg_volume": float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)),
        "pivot_price": pivot,
        "atr": atr(highs, lows, closes),
        "above_sma200": (sma200 is not None and current_price > sma200),
        "sma200": sma200,
    }
    sig["setup_type"] = classify_setup(sig)
    return sig
