"""
Breakout Scanner - Unusual Whales signal normalization.

Turns raw UW REST responses into the leading factors the scorer consumes. All
helpers are defensive about field names/types (UW returns many numerics as
strings) and never raise: missing data yields neutral values.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional


def _clip01(x: float) -> float:
    if x != x:  # NaN
        return 0.0
    return float(max(0.0, min(1.0, x)))


def _f(val: Any) -> Optional[float]:
    """Parse a UW value (often a string) into a float, or None."""
    if val is None:
        return None
    try:
        if isinstance(val, bool):
            return None
        return float(val)
    except (TypeError, ValueError):
        return None


def _get_any(row: Dict[str, Any], *keys: str) -> Any:
    for k in keys:
        if k in row and row[k] is not None:
            return row[k]
    return None


def screener_metrics(row: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract the CSP/flow context fields from a stock-screener row."""
    if not row:
        return {}
    return {
        "iv_rank": _f(_get_any(row, "iv_rank", "iv30d_rank")),
        "implied_move": _f(_get_any(row, "implied_move", "implied_move_perc")),
        "net_call_premium": _f(_get_any(row, "net_call_premium")),
        "net_put_premium": _f(_get_any(row, "net_put_premium")),
        "bullish_premium": _f(_get_any(row, "bullish_premium")),
        "bearish_premium": _f(_get_any(row, "bearish_premium")),
        "put_call_ratio": _f(_get_any(row, "put_call_ratio")),
        "call_oi_change_perc": _f(_get_any(row, "call_oi_change_perc")),
        "total_oi_change_perc": _f(_get_any(row, "total_oi_change_perc")),
        "perc_change": _f(_get_any(row, "perc_change")),
        "marketcap": _f(_get_any(row, "marketcap")),
        "price": _f(_get_any(row, "close", "last", "underlying_price", "stock_price")),
        "next_earnings_date": _get_any(row, "next_earnings_date"),
        "volume": _f(_get_any(row, "volume", "stock_volume")),
    }


def flow_bullishness(alerts: List[Dict[str, Any]]) -> float:
    """Net bullish premium from unusual options flow alerts (raw, can be < 0).

    Rewards opening, ask-side call premium; subtracts bearish (put/ask or
    call/bid) premium. Percentile-ranked across the universe in scoring.
    """
    if not alerts:
        return 0.0
    net = 0.0
    for a in alerts:
        premium = _f(_get_any(a, "total_premium", "premium")) or 0.0
        if premium <= 0:
            continue
        is_call = bool(_get_any(a, "is_call"))
        is_put = bool(_get_any(a, "is_put"))
        side = (_get_any(a, "side") or "").lower()
        is_ask = bool(_get_any(a, "is_ask_side")) or side == "ask"
        is_bid = bool(_get_any(a, "is_bid_side")) or side == "bid"
        # type field fallback
        otype = (_get_any(a, "type", "option_type") or "").lower()
        if not is_call and not is_put and otype:
            is_call = otype == "call"
            is_put = otype == "put"

        weight = 1.0
        if is_ask:
            weight = 1.0
        elif is_bid:
            weight = -1.0

        if is_call:
            net += premium * weight
        elif is_put:
            net -= premium * (1.0 if is_ask else 0.5)
    return float(net)


def oi_accumulation(metrics: Dict[str, Any]) -> float:
    """Call open-interest build (positioning ahead of a move). Raw percent."""
    val = metrics.get("call_oi_change_perc")
    if val is None:
        val = metrics.get("total_oi_change_perc")
    return float(val) if val is not None else 0.0


def oi_accumulation_from_contracts(contracts: List[Dict[str, Any]]) -> Optional[float]:
    """Real call open-interest growth aggregated across a ticker's contracts.

    Replaces the screener-row fallback (which often degrades to 0). Sums prior
    and current call open interest across contracts and returns the net percent
    change. Returns ``None`` if the data is unusable (caller keeps the fallback).
    """
    if not contracts:
        return None
    prev_total = 0.0
    curr_total = 0.0
    for c in contracts:
        otype = (_get_any(c, "option_type", "type") or "").lower()
        if otype and otype != "call":
            continue
        curr = _f(_get_any(c, "open_interest", "oi"))
        prev = _f(_get_any(c, "prev_oi", "previous_oi", "open_interest_change"))
        if curr is None:
            continue
        # If only a change field is present, treat it as the delta directly.
        if prev is None:
            chg = _f(_get_any(c, "oi_change", "open_interest_change"))
            if chg is not None:
                prev = curr - chg
            else:
                continue
        curr_total += curr
        prev_total += prev
    if prev_total <= 0:
        return None
    return float((curr_total - prev_total) / prev_total * 100.0)


def gex_regime(greek: Optional[Dict[str, Any]], current_price: Optional[float]) -> Dict[str, Any]:
    """Dealer gamma regime. Negative net dealer gamma => 'short_gamma' (dealers
    must buy into strength), which fuels breakout acceleration => higher score.
    """
    if not greek:
        return {"regime": None, "score": 0.0}

    call_gamma = _f(_get_any(greek, "call_gamma", "gamma_call"))
    put_gamma = _f(_get_any(greek, "put_gamma", "gamma_put"))
    net = None
    if call_gamma is not None and put_gamma is not None:
        # Dealers are typically short calls / long puts vs customers; a commonly
        # used proxy for dealer gamma is (put_gamma - call_gamma).
        net = put_gamma - call_gamma
    else:
        net = _f(_get_any(greek, "gamma_per_one_percent_move", "gex", "gamma"))

    if net is None:
        return {"regime": None, "score": 0.0}

    if net < 0:
        return {"regime": "short_gamma", "score": 1.0}
    return {"regime": "long_gamma", "score": 0.2}


def gex_profile(strike_rows: List[Dict[str, Any]], current_price: Optional[float]) -> Dict[str, Any]:
    """Graded dealer-gamma regime + overhead gamma-wall detection.

    Uses per-strike greek exposure (``/greek-exposure/strike``). Net dealer gamma
    per strike is ``call_gex + put_gex`` (put gamma is reported negative). A net
    short-gamma book fuels breakout acceleration (dealers chase price), so it
    scores high - but graded by magnitude rather than the old 0/0.2/1.0 step.
    Also locates the nearest large *overhead* gamma wall, which acts as
    resistance just above price.
    """
    out: Dict[str, Any] = {
        "score": 0.0,
        "regime": None,
        "gamma_wall": None,
        "wall_distance": None,
        "wall_pressure": 0.0,
    }
    if not strike_rows:
        return out

    net_total = 0.0
    abs_total = 0.0
    overhead: List[tuple] = []  # (strike, net_gex_at_strike)
    for row in strike_rows:
        strike = _f(_get_any(row, "strike"))
        call_gex = _f(_get_any(row, "call_gex", "call_gamma", "gamma_call")) or 0.0
        put_gex = _f(_get_any(row, "put_gex", "put_gamma", "gamma_put")) or 0.0
        net = call_gex + put_gex  # put_gex already negative
        net_total += net
        abs_total += abs(call_gex) + abs(put_gex)
        if strike is not None and current_price and strike > current_price:
            overhead.append((strike, net))

    if abs_total <= 0:
        return out

    ratio = net_total / abs_total  # [-1, 1]; <0 == net short gamma
    out["regime"] = "short_gamma" if net_total < 0 else "long_gamma"
    out["score"] = _clip01(0.5 - 0.5 * ratio)  # short gamma -> higher

    # Nearest sizable overhead positive-gamma wall (resistance).
    if overhead and current_price:
        walls = [(s, g) for (s, g) in overhead if g > 0]
        if walls:
            wall_strike, _g = max(walls, key=lambda t: t[1])
            dist = (wall_strike - current_price) / current_price
            out["gamma_wall"] = float(wall_strike)
            out["wall_distance"] = float(dist * 100.0)
            # Pressure peaks when a big wall sits 0-5% overhead.
            if 0 < dist <= 0.05:
                out["wall_pressure"] = float(round(1.0 - dist / 0.05, 3))
    return out


def max_pain_context(payload: Any, current_price: Optional[float]) -> Dict[str, Any]:
    """Max-pain price vs spot. Price below max pain implies an upward 'pull'."""
    out: Dict[str, Any] = {"max_pain": None, "distance": None, "pull": 0.5}
    rows: List[Dict[str, Any]] = []
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, list):
            rows = data
        elif isinstance(data, dict):
            rows = [data]
        else:
            rows = [payload]
    if not rows or not current_price:
        return out
    mp = None
    for row in rows:
        if isinstance(row, dict):
            mp = _f(_get_any(row, "max_pain", "max_pain_price", "price", "value"))
        else:
            mp = _f(row)
        if mp is not None:
            break
    if mp is None or mp <= 0:
        return out
    dist = (mp - current_price) / current_price
    out["max_pain"] = float(mp)
    out["distance"] = float(dist * 100.0)
    # Bounded bullish pull when price sits below max pain.
    out["pull"] = float(round(_clip01(0.5 + dist * 4.0), 3))
    return out


def flow_from_ticks(ticks: List[Dict[str, Any]]) -> Optional[float]:
    """Net bullish premium from intraday net-prem ticks (cumulative for the day).

    More robust than a single ``flow-alerts`` snapshot. Uses the last cumulative
    tick: net call premium (call buying, bullish) minus net put premium (negative
    when puts are sold, also bullish). Raw value, percentile-ranked in scoring.
    """
    if not ticks:
        return None
    last = ticks[-1]
    ncp = _f(_get_any(last, "net_call_premium"))
    npp = _f(_get_any(last, "net_put_premium"))
    if ncp is None and npp is None:
        return None
    return float((ncp or 0.0) - (npp or 0.0))


def iv_vs_realized(implied_move: Optional[float], realized_vol: Optional[float]) -> Optional[float]:
    """Ratio of implied to realized vol. >1 == options rich, <1 == options cheap."""
    if implied_move is None or realized_vol is None or realized_vol <= 0:
        return None
    return float(implied_move / realized_vol)


def darkpool_accumulation(trades: List[Dict[str, Any]], current_price: Optional[float]) -> Dict[str, Any]:
    """Institutional block accumulation via dark-pool prints (raw premium)."""
    if not trades:
        return {"premium": 0.0, "accum": False}
    total = 0.0
    for t in trades:
        prem = _f(_get_any(t, "premium"))
        if prem is None:
            size = _f(_get_any(t, "size")) or 0.0
            price = _f(_get_any(t, "price")) or 0.0
            prem = size * price
        if prem and prem > 0:
            total += prem
    accum = total >= 5_000_000  # >= $5M of block prints
    return {"premium": float(total), "accum": bool(accum)}


def smart_money_score(insider: Optional[Dict[str, Any]], congress: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Insider + congress buying corroboration. Raw net-buy signal + bool flag."""
    score = 0.0
    flag = False

    if insider:
        buys = _f(_get_any(insider, "purchases", "buy_value", "total_purchases", "purchases_notional")) or 0.0
        sells = _f(_get_any(insider, "sells", "sell_value", "total_sells", "sells_notional")) or 0.0
        if buys > 0 or sells > 0:
            net = buys - sells
            denom = buys + sells
            if denom > 0:
                score += (net / denom)  # -1..1
            if net > 0:
                flag = True

    # Recent congress BUY activity
    buy_count = 0
    for c in congress:
        txn = (_get_any(c, "transaction", "txn_type", "type") or "").lower()
        if "buy" in txn or "purchase" in txn:
            buy_count += 1
    if buy_count:
        score += min(buy_count / 3.0, 1.0)
        flag = True

    return {"score": float(score), "flag": bool(flag)}


def seasonality_edge(monthly: List[Dict[str, Any]], month: Optional[int] = None) -> float:
    """Average historical return for the upcoming month (raw, can be < 0)."""
    if not monthly:
        return 0.0
    if month is None:
        month = datetime.utcnow().month
    for row in monthly:
        m = _get_any(row, "month")
        try:
            m_int = int(str(m).split("-")[-1]) if m is not None else None
        except (TypeError, ValueError):
            m_int = None
        if m_int == month:
            val = _f(_get_any(row, "avg_change", "median_change", "avg")) or 0.0
            # Normalize to percent (UW may return a fraction like 0.0089)
            if -1.0 < val < 1.0:
                val *= 100.0
            return val
    return 0.0


def earnings_within(next_earnings_date: Any, days: int) -> bool:
    """True if the next earnings date falls within `days` from today."""
    if not next_earnings_date:
        return False
    try:
        dt = datetime.strptime(str(next_earnings_date)[:10], "%Y-%m-%d")
    except (TypeError, ValueError):
        return False
    delta = (dt - datetime.utcnow()).days
    return 0 <= delta <= days
