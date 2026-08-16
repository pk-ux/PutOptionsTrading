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

import math
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


def detect_pivot(
    highs: np.ndarray,
    closes: np.ndarray,
    window: int = 40,
    exclude: int = 2,
    tolerance: float = 0.015,
) -> Optional[float]:
    """Identify the nearest overhead breakout pivot.

    Prefers a multi-touch resistance cluster (two swing highs within `tolerance`
    of each other) over a single naked spike high. Falls back to rolling max when
    no cluster is found.
    """
    if len(highs) < window + exclude + 4:
        return None
    region = highs[-window - exclude:-exclude] if exclude > 0 else highs[-window:]
    if len(region) < 5:
        return None

    # Local swing highs: higher than 2 bars on each side
    swing_highs = []
    for i in range(2, len(region) - 2):
        if (region[i] >= region[i - 1] and region[i] >= region[i + 1]
                and region[i] >= region[i - 2] and region[i] >= region[i + 2]):
            swing_highs.append(float(region[i]))

    if len(swing_highs) >= 2:
        sorted_highs = sorted(swing_highs)
        for j in range(len(sorted_highs) - 1):
            lo, hi = sorted_highs[j], sorted_highs[j + 1]
            if lo > 0 and (hi - lo) / lo <= tolerance:
                return float((lo + hi) / 2)

    return float(np.max(region))


def pivot_proximity(
    current_price: float,
    pivot: Optional[float],
    atr_value: Optional[float] = None,
) -> float:
    """Score for price coiling *just below* the pivot (pre-breakout zone).

    Distance is measured in ATR units rather than raw percent: a name with a
    0.8% average range sitting 3% under its pivot needs far more time and
    conviction to get there than a 4% mover at the same percentage, and the two
    should not score alike. Falls back to a percent-based ATR estimate when no
    ATR is supplied.

    The curve is smooth (Gaussian-style decay) so small changes in price never
    produce a discontinuous jump in rank.
    """
    if not pivot or pivot <= 0 or not current_price or current_price <= 0:
        return 0.0

    # Fall back to a 2%-of-price pseudo-ATR so the function still works standalone.
    unit = atr_value if (atr_value and atr_value > 0) else current_price * 0.02
    dist_atr = (pivot - current_price) / unit  # >0 below pivot, <0 above

    # Asymmetric Gaussian peaking just under the pivot. Both branches evaluate
    # to 1.0 at the peak, so the curve is continuous: a name drifting across its
    # pivot never jumps in rank. Decay is faster on the upside because a stock
    # already above the pivot without volume is a failed break, not a setup.
    peak = 0.25          # ATRs below the pivot where readiness is maximal
    below_width = 3.0    # still has room to travel -> gentle decay
    above_width = 1.2    # extending away from the base -> steep decay

    width = below_width if dist_atr >= peak else above_width
    return _clip01(math.exp(-(((dist_atr - peak) / width) ** 2)))


def base_duration(highs: np.ndarray, lows: np.ndarray, max_lookback: int = 120) -> Dict[str, Any]:
    """How many bars the current consolidation has held together.

    Constructive bases take time to build - institutions cannot accumulate a
    position in three days. Walks backwards from the most recent bar counting
    how long price stayed inside a band anchored on the recent range, then
    scores that duration (roughly: 2 weeks -> low, 7+ weeks -> full credit).
    """
    if len(highs) < 20:
        return {"bars": 0, "score": 0.0}

    window = min(len(highs), max_lookback)
    h = highs[-window:]
    l = lows[-window:]

    # Anchor the band on the last 10 bars, then extend back while price stays inside.
    anchor_high = float(np.max(h[-10:]))
    anchor_low = float(np.min(l[-10:]))
    if anchor_high <= 0:
        return {"bars": 0, "score": 0.0}

    mid = (anchor_high + anchor_low) / 2.0
    if mid <= 0:
        return {"bars": 0, "score": 0.0}
    # Allow the base to be up to ~1.6x the anchor range before we call it broken.
    half_band = max((anchor_high - anchor_low) / 2.0, mid * 0.02) * 1.6
    upper, lower = mid + half_band, mid - half_band

    bars = 0
    for i in range(len(h) - 1, -1, -1):
        if h[i] > upper or l[i] < lower:
            break
        bars += 1

    # 10 bars -> 0.0, 35+ bars (~7 weeks) -> 1.0
    score = _clip01((bars - 10) / 25.0)
    return {"bars": int(bars), "score": score}


def up_down_volume_ratio(closes: np.ndarray, volumes: np.ndarray, lookback: int = 50) -> Dict[str, Any]:
    """Institutional accumulation proxy: volume on up days vs down days.

    The classic O'Neil up/down volume ratio. A base being quietly accumulated
    trades heavier on advances than declines even while total volume dries up,
    which plain ``volume_dryup`` cannot distinguish.
    """
    if len(closes) < lookback + 1 or len(volumes) < lookback + 1:
        return {"ratio": None, "score": 0.0}

    c = closes[-lookback - 1:]
    v = volumes[-lookback:]
    changes = np.diff(c)
    up_vol = float(np.sum(v[changes > 0]))
    down_vol = float(np.sum(v[changes < 0]))

    if down_vol <= 0:
        # All-up or no down volume: strong, but avoid a divide-by-zero infinity.
        return {"ratio": 2.0 if up_vol > 0 else None, "score": 1.0 if up_vol > 0 else 0.0}

    ratio = up_vol / down_vol
    # 1.0 (balanced) -> 0.0, 2.0+ (twice the volume on up days) -> 1.0
    return {"ratio": float(ratio), "score": _clip01(ratio - 1.0)}


def tight_closes(closes: np.ndarray, bars: int = 5, threshold: float = 0.02) -> Dict[str, Any]:
    """Minervini-style "tight closes": a run of closes inside a narrow band.

    Consecutive closes clustered within a couple of percent mean supply has
    dried up completely and the stock is ready to move. Measures the spread of
    the last ``bars`` closes relative to their mean.
    """
    if len(closes) < bars:
        return {"spread": None, "tight": False, "score": 0.0}

    seg = closes[-bars:]
    mean = float(np.mean(seg))
    if mean <= 0:
        return {"spread": None, "tight": False, "score": 0.0}

    spread = (float(np.max(seg)) - float(np.min(seg))) / mean
    # 0% spread -> 1.0, at or beyond the threshold -> 0.0
    score = _clip01(1.0 - spread / threshold)
    return {"spread": float(spread * 100.0), "tight": bool(spread <= threshold), "score": score}


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


def adr_pct(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, period: int = 20) -> Optional[float]:
    """Average daily range as a percent of price - a liquidity/tradability gate.

    Stocks that barely move are poor breakout candidates; ones that move too
    violently are noise. Returned as a percent (e.g. 3.5 == 3.5%).
    """
    if len(closes) < period + 1:
        return None
    rng = (highs[-period:] - lows[-period:])
    base = closes[-period:]
    base = np.where(base <= 0, np.nan, base)
    pct = np.nanmean(rng / base) * 100.0
    if pct != pct:  # NaN
        return None
    return float(pct)


def volume_expansion(volumes: np.ndarray, long: int = 50) -> Dict[str, Any]:
    """Is volume expanding vs the base average?

    The opposite of ``volume_dryup``: a real breakout fires on a surge of volume.
    Feeds ``breakout_trigger`` (the pre-breakout exclusion filter) and is shown
    as context in the UI; it is deliberately *not* a scored factor, since volume
    expansion only tells you a move has already started.
    """
    if len(volumes) < long:
        return {"ratio": 1.0, "score": 0.0}
    recent = float(volumes[-1])
    base = float(np.mean(volumes[-long:]))
    if base <= 0:
        return {"ratio": 1.0, "score": 0.0}
    ratio = recent / base
    score = _clip01((ratio - 1.0) / 1.0)  # 1x -> 0, 2x -> 1.0
    return {"ratio": float(ratio), "score": score}


def fifty_two_week(highs: np.ndarray, closes: np.ndarray, lookback: int = 252) -> Dict[str, Any]:
    """Proximity to the 52-week high. The best breakouts emerge near new highs.

    Returns the pct below the 52wk high (smaller is better) and a 0..1 proximity
    score that peaks within ~0-15% of the high and decays beyond.
    """
    if len(highs) < 20:
        return {"pct_from_high": None, "near_high": 0.0}
    window = highs[-lookback:] if len(highs) >= lookback else highs
    high_52 = float(np.max(window))
    price = float(closes[-1])
    if high_52 <= 0:
        return {"pct_from_high": None, "near_high": 0.0}
    pct_from = (high_52 - price) / high_52  # >=0
    if pct_from <= 0.15:
        near = 1.0 - (pct_from / 0.15) * 0.3  # 0% -> 1.0, 15% -> 0.7
    elif pct_from <= 0.35:
        near = _clip01(0.7 - (pct_from - 0.15) / 0.20 * 0.6)
    else:
        near = 0.05
    return {"pct_from_high": float(pct_from * 100.0), "near_high": _clip01(near)}


def base_quality(highs: np.ndarray, lows: np.ndarray, closes: np.ndarray, window: int = 40) -> float:
    """Quality of the consolidation base: shallow, tight bases break out cleaner.

    Rewards a shallow base depth (peak-to-trough range over the window) and price
    sitting in the upper portion of the base (accumulation, not distribution).
    """
    if len(closes) < window:
        return 0.0
    seg_h = highs[-window:]
    seg_l = lows[-window:]
    top = float(np.max(seg_h))
    bottom = float(np.min(seg_l))
    if top <= 0 or top <= bottom:
        return 0.0
    depth = (top - bottom) / top
    depth_score = _clip01(1.0 - depth / 0.35)  # 0% deep -> 1.0, 35%+ -> 0
    price = float(closes[-1])
    pos_in_base = (price - bottom) / (top - bottom)  # 0 bottom, 1 top
    pos_score = _clip01(pos_in_base)
    return _clip01(0.6 * depth_score + 0.4 * pos_score)


def realized_vol(closes: np.ndarray, period: int = 20) -> Optional[float]:
    """Annualized realized volatility (%) from daily log returns."""
    if len(closes) < period + 1:
        return None
    window = closes[-period - 1:]
    rets = np.diff(window) / window[:-1]
    if len(rets) < 2:
        return None
    vol = float(np.std(rets) * np.sqrt(252) * 100.0)
    return vol if vol == vol else None


def breakout_trigger(
    closes: np.ndarray,
    pivot: Optional[float],
    vol_ratio: float,
    vol_mult: float = 1.5,
    max_extension: float = 0.10,
    vol_ratio_confirmed: Optional[float] = None,
) -> bool:
    """Confirmed-breakout trigger: price closed above the pivot on expanding volume.

    Checks both the current bar (closes[-1]) and the prior complete bar
    (closes[-2]) so the scanner works correctly when run intraday — the current
    bar may be partial, but the prior bar is always complete. Pass
    ``vol_ratio_confirmed`` (prior bar's volume ratio) to enable the prior-bar check.
    """
    if not pivot or pivot <= 0 or len(closes) == 0:
        return False

    def _triggered(price: float, vr: float) -> bool:
        if price <= pivot or (price - pivot) / pivot > max_extension:
            return False
        return vr >= vol_mult

    if _triggered(float(closes[-1]), vol_ratio):
        return True
    if vol_ratio_confirmed is not None and len(closes) >= 2:
        if _triggered(float(closes[-2]), vol_ratio_confirmed):
            return True
    return False


def flag_pattern(
    closes: np.ndarray,
    volumes: np.ndarray,
    pole_bars: int = 20,
    flag_bars: int = 10,
    min_advance: float = 0.12,
    max_pullback: float = 0.15,
    max_flag_range: float = 0.12,
) -> Dict[str, Any]:
    """Bull flag continuation: rapid advance (pole) followed by tight low-volume consolidation.

    Detects stocks that already had a breakout run and are coiling in a tight
    flag for the next leg — a continuation signal distinct from a fresh base-breakout.
    """
    needed = pole_bars + flag_bars
    if len(closes) < needed or len(volumes) < needed:
        return {"flag": False, "score": 0.0}

    pole_start = float(closes[-(pole_bars + flag_bars)])
    pole_end = float(closes[-flag_bars])
    if pole_start <= 0 or pole_end <= 0:
        return {"flag": False, "score": 0.0}

    advance = (pole_end - pole_start) / pole_start
    if advance < min_advance:
        return {"flag": False, "score": 0.0}

    flag_seg = closes[-flag_bars:]
    flag_high = float(np.max(flag_seg))
    flag_low = float(np.min(flag_seg))
    pullback = (pole_end - flag_low) / pole_end
    flag_range = (flag_high - flag_low) / pole_end

    if pullback > max_pullback or flag_range > max_flag_range:
        return {"flag": False, "score": 0.0}

    pole_vol = float(np.mean(volumes[-(pole_bars + flag_bars):-flag_bars]))
    flag_vol = float(np.mean(volumes[-flag_bars:]))
    vol_ratio_pf = (flag_vol / pole_vol) if pole_vol > 0 else 1.0

    advance_score = _clip01((advance - min_advance) / 0.20)   # 12% → 0, 32%+ → 1.0
    tightness_score = _clip01(1.0 - flag_range / max_flag_range)
    vol_score = _clip01(1.0 - vol_ratio_pf)                    # lower flag vol → higher

    score = 0.35 * advance_score + 0.45 * tightness_score + 0.20 * vol_score
    return {"flag": True, "score": float(_clip01(score))}


def rs_line_new_high(closes: np.ndarray, spy_closes: Optional[np.ndarray], lookback: int = 60) -> bool:
    """Is the relative-strength line (stock / SPY) making a new high?

    A leading RS line that breaks out *before* price is a hallmark of the
    strongest breakout candidates.
    """
    if spy_closes is None or len(spy_closes) < 20 or len(closes) < 20:
        return False
    n = min(len(closes), len(spy_closes), lookback + 1)
    if n < 10:
        return False
    s = closes[-n:]
    m = spy_closes[-n:]
    m = np.where(m <= 0, np.nan, m)
    rs_line = s / m
    if np.isnan(rs_line).all():
        return False
    return bool(rs_line[-1] >= np.nanmax(rs_line) * 0.999)


def classify_setup(sig: Dict[str, float]) -> str:
    """Human-readable setup label from the computed structure signals.

    Confirmed breakouts never reach this function - the scanner excludes them
    in Stage 1 - so every label here describes a still-coiling setup.
    """
    if sig.get("flag_pattern"):
        return "bull_flag"
    if sig.get("tight_closes", 0) > 0.6 and sig.get("pivot", 0) > 0.6:
        return "tight_at_pivot"
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
    sector_closes: Optional[np.ndarray] = None,
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
    atr_value = atr(highs, lows, closes)
    sma50 = float(np.mean(closes[-50:])) if len(closes) >= 50 else None
    sma200 = float(np.mean(closes[-200:])) if len(closes) >= 200 else None
    vol_exp = volume_expansion(volumes)
    high52 = fifty_two_week(highs, closes)

    # Prior complete bar volume ratio — avoids intraday partial-bar artifacts.
    # volumes[-1] may be mid-session; volumes[-2] is always a full trading day.
    if len(volumes) >= 52:
        avg_vol_base = float(np.mean(volumes[-51:-1]))
    elif len(volumes) >= 2:
        avg_vol_base = float(np.mean(volumes[:-1]))
    else:
        avg_vol_base = None
    vol_ratio_confirmed = (
        float(volumes[-2]) / avg_vol_base
        if (avg_vol_base and avg_vol_base > 0 and len(volumes) >= 2)
        else None
    )

    # Bull flag continuation pattern
    flag = flag_pattern(closes, volumes)

    # Base construction: how mature, how accumulated, how tight
    duration = base_duration(highs, lows)
    updown = up_down_volume_ratio(closes, volumes)
    tight = tight_closes(closes)

    # Sector-relative RS (None when sector ETF unavailable → neutral 0.5 in percentile rank)
    sector_rs_raw = relative_strength(closes, sector_closes) if sector_closes is not None else None

    # Prior uptrend: price is up ≥25% from its 52-week low — Minervini Stage 2 prerequisite.
    # This is the non-redundant part of the uptrend signal (near_52wk_high already
    # handles proximity to the high; this captures that a real advance occurred first).
    lookback_lows = lows[-252:] if len(lows) >= 252 else lows
    low_52 = float(np.min(lookback_lows))
    pct_from_low = (current_price - low_52) / low_52 if low_52 > 0 else 0.0
    prior_uptrend = pct_from_low >= 0.25

    sig: Dict[str, Any] = {
        "compression": comp["compression"],
        "squeeze": comp["squeeze"],
        "nr_tightness": nr_tightness(highs, lows),
        "vcp": vcp_contraction(highs, lows),
        "volume_dryup": volume_dryup(volumes),
        "rs_raw": relative_strength(closes, spy_closes),
        "rs_new_high": rs_line_new_high(closes, spy_closes),
        "pivot": pivot_proximity(current_price, pivot, atr_value),
        # exclusion filter (vol_ratio_confirmed enables prior-bar check for intraday runs)
        "volume_expansion": vol_exp["score"],
        "vol_ratio": vol_exp["ratio"],
        "breakout_trigger": breakout_trigger(
            closes, pivot, vol_exp["ratio"], vol_ratio_confirmed=vol_ratio_confirmed
        ),
        # base / leadership context
        "near_52wk_high": high52["near_high"],
        "pct_from_52wk_high": high52["pct_from_high"],
        "base_quality": base_quality(highs, lows, closes),
        "prior_uptrend": prior_uptrend,
        "pct_from_52wk_low": float(pct_from_low * 100.0) if low_52 > 0 else None,
        # continuation pattern
        "flag_pattern": flag["flag"],
        "flag_score": flag["score"],
        # base construction
        "base_duration_bars": duration["bars"],
        "base_duration": duration["score"],
        "up_down_volume": updown["score"],
        "up_down_volume_ratio": updown["ratio"],
        "tight_closes": tight["score"],
        "tight_closes_pct": tight["spread"],
        # sector-relative RS (None = no sector data)
        "sector_rs_raw": sector_rs_raw,
        # context
        "current_price": current_price,
        "avg_volume": float(np.mean(volumes[-20:])) if len(volumes) >= 20 else float(np.mean(volumes)),
        "avg_volume_50": float(np.mean(volumes[-50:])) if len(volumes) >= 50 else None,
        "pivot_price": pivot,
        "atr": atr_value,
        "adr_pct": adr_pct(highs, lows, closes),
        "realized_vol": realized_vol(closes),
        "above_sma50": (sma50 is not None and current_price > sma50),
        "sma50": sma50,
        "above_sma200": (sma200 is not None and current_price > sma200),
        "sma200": sma200,
    }
    sig["setup_type"] = classify_setup(sig)
    return sig
