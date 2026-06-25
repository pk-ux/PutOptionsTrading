"""
Breakout Scanner - orchestrator.

Pipeline:
  1. Bulk Unusual Whales stock-screener over the whole universe (IV rank, net
     premium, P/C, earnings) - one cheap pass.
  2. Per-ticker daily OHLC -> price-structure leading signals + Stage-1 filter.
  3. Rank survivors by a cheap preliminary structure score; the top
     ``deep_dive_n`` get the expensive per-ticker UW calls (flow, GEX, dark pool,
     insider, congress, seasonality).
  4. Cross-sectional composite score -> top N candidates with CSP context.
"""

import logging
from typing import Any, Dict, List, Optional

import numpy as np

from . import signals as S
from . import uw_signals as UW
from .scoring import score_candidates
from .types import ScanCandidate, ScanResult, ScannerConfig


def _preliminary_score(sig: Dict[str, Any]) -> float:
    """Cheap structure-only score to pick deep-dive survivors."""
    return (
        0.4 * float(sig.get("compression") or 0)
        + 0.25 * float(sig.get("vcp") or 0)
        + 0.15 * float(sig.get("nr_tightness") or 0)
        + 0.1 * float(sig.get("volume_dryup") or 0)
        + 0.1 * float(sig.get("pivot") or 0)
        + (0.1 if sig.get("squeeze") else 0)
    )


def _suggested_put_strike(current_price: Optional[float], atr: Optional[float]) -> Optional[float]:
    """A conservative CSP strike near base support (~1.5 ATR below price)."""
    if not current_price:
        return None
    buffer = (atr * 1.5) if atr else current_price * 0.05
    strike = current_price - buffer
    if strike <= 0:
        return None
    # round to a sensible increment
    if strike >= 100:
        return float(round(strike))
    if strike >= 25:
        return float(round(strike * 2) / 2)  # nearest 0.5
    return float(round(strike))


def run_scan(
    tickers: List[str],
    config: Optional[ScannerConfig] = None,
    price_provider=None,
    uw_provider=None,
    logger: Optional[logging.Logger] = None,
) -> ScanResult:
    """Run a breakout scan over ``tickers`` and return a ranked ``ScanResult``."""
    log = logger or logging.getLogger(__name__)
    config = config or ScannerConfig()

    if price_provider is None:
        from .providers.yahoo_provider import YahooPriceProvider
        price_provider = YahooPriceProvider()

    # Normalize universe
    universe = []
    seen = set()
    for t in tickers:
        sym = (t or "").strip().upper()
        if sym and sym not in seen:
            seen.add(sym)
            universe.append(sym)

    result = ScanResult(universe_size=len(universe))
    if not universe:
        result.warnings.append("Empty universe")
        return result

    uw_active = bool(
        config.use_unusual_whales and uw_provider is not None and uw_provider.is_available()
    )
    result.used_unusual_whales = uw_active

    # --- Stage 0: bulk UW screener over whole universe ---
    screener_map: Dict[str, Dict[str, Any]] = {}
    if uw_active:
        try:
            screener_map = uw_provider.stock_screener(universe)
        except Exception as e:
            log.warning(f"UW stock_screener failed: {e}")
            result.warnings.append("Unusual Whales screener unavailable")

    # --- SPY for relative strength ---
    spy_closes = None
    try:
        spy_hist = price_provider.get_price_history("SPY", days=config.history_days)
        if spy_hist:
            spy_closes = np.array([p["close"] for p in spy_hist], dtype=float)
    except Exception as e:
        log.warning(f"Could not fetch SPY history: {e}")

    # --- Stage 1: per-ticker structure + pre-filter ---
    features: List[Dict[str, Any]] = []
    for sym in universe:
        try:
            ohlc = price_provider.get_price_history(sym, days=config.history_days)
        except Exception as e:
            log.warning(f"Price history failed for {sym}: {e}")
            continue
        sig = S.compute_structure_signals(ohlc, spy_closes=spy_closes)
        if not sig:
            continue

        price = sig.get("current_price")
        avg_vol = sig.get("avg_volume") or 0
        if price is None or price < config.min_price or price > config.max_price:
            continue
        if avg_vol < config.min_avg_volume:
            continue
        if config.require_above_sma200 and not sig.get("above_sma200"):
            continue

        metrics = UW.screener_metrics(screener_map.get(sym)) if uw_active else {}

        feat: Dict[str, Any] = {
            "symbol": sym,
            # structure (already 0..1 unless raw)
            "compression": sig.get("compression"),
            "squeeze": sig.get("squeeze"),
            "nr_tightness": sig.get("nr_tightness"),
            "vcp": sig.get("vcp"),
            "volume_dryup": sig.get("volume_dryup"),
            "rs_raw": sig.get("rs_raw"),
            "pivot": sig.get("pivot"),
            # context
            "current_price": price,
            "pivot_price": sig.get("pivot_price"),
            "atr": sig.get("atr"),
            "setup_type": sig.get("setup_type"),
            # UW screener-derived
            "iv_rank": metrics.get("iv_rank"),
            "implied_move": metrics.get("implied_move"),
            "net_call_premium": metrics.get("net_call_premium"),
            "net_put_premium": metrics.get("net_put_premium"),
            "bullish_premium": metrics.get("bullish_premium"),
            "bearish_premium": metrics.get("bearish_premium"),
            "oi_accum": UW.oi_accumulation(metrics) if metrics else 0.0,
            "next_earnings_date": metrics.get("next_earnings_date"),
            # UW deep factors (filled for survivors)
            "flow_bullishness": 0.0,
            "gex_score": 0.0,
            "gex_regime": None,
            "darkpool_premium": 0.0,
            "darkpool_accum": False,
            "smart_money_score": 0.0,
            "smart_money_flag": False,
            "seasonality": None,
            "earnings_flag": UW.earnings_within(metrics.get("next_earnings_date"), config.typical_csp_dte),
            "_prelim": 0.0,
        }
        feat["_prelim"] = _preliminary_score(sig)
        features.append(feat)

    result.scanned = len(features)
    if not features:
        result.warnings.append("No tickers passed the pre-filter")
        return result

    # --- Stage 2: deep-dive UW calls on the strongest structures ---
    if uw_active:
        features.sort(key=lambda f: f["_prelim"], reverse=True)
        deep = features[: max(config.deep_dive_n, config.top_n)]
        for f in deep:
            sym = f["symbol"]
            try:
                alerts = uw_provider.flow_alerts(sym)
                f["flow_bullishness"] = UW.flow_bullishness(alerts)
            except Exception as e:
                log.debug(f"flow_alerts {sym}: {e}")
            try:
                greek = uw_provider.greek_exposure(sym)
                g = UW.gex_regime(greek, f.get("current_price"))
                f["gex_score"] = g["score"]
                f["gex_regime"] = g["regime"]
            except Exception as e:
                log.debug(f"greek_exposure {sym}: {e}")
            try:
                dp = UW.darkpool_accumulation(uw_provider.darkpool(sym), f.get("current_price"))
                f["darkpool_premium"] = dp["premium"]
                f["darkpool_accum"] = dp["accum"]
            except Exception as e:
                log.debug(f"darkpool {sym}: {e}")
            try:
                sm = UW.smart_money_score(
                    uw_provider.insider_buy_sells(sym),
                    uw_provider.congress_trades(sym),
                )
                f["smart_money_score"] = sm["score"]
                f["smart_money_flag"] = sm["flag"]
            except Exception as e:
                log.debug(f"smart_money {sym}: {e}")
            try:
                f["seasonality"] = UW.seasonality_edge(uw_provider.seasonality(sym))
            except Exception as e:
                log.debug(f"seasonality {sym}: {e}")

    # --- Stage 3: composite cross-sectional score ---
    score_candidates(features, weights=config.normalized_weights())
    features.sort(key=lambda f: f.get("score", 0.0), reverse=True)

    top = features[: config.top_n]
    candidates: List[ScanCandidate] = []
    for rank, f in enumerate(top, start=1):
        candidates.append(
            ScanCandidate(
                symbol=f["symbol"],
                score=f.get("score", 0.0),
                rank=rank,
                setup_type=f.get("setup_type", "none"),
                pivot_price=_round(f.get("pivot_price")),
                current_price=_round(f.get("current_price")),
                iv_rank=_round(f.get("iv_rank"), 1),
                implied_move=_round(f.get("implied_move"), 2),
                net_call_premium=_round(f.get("net_call_premium")),
                bullish_flow_score=_round(f.get("flow_bullishness")),
                gex_regime=f.get("gex_regime"),
                dark_pool_accum=bool(f.get("darkpool_accum")),
                smart_money=bool(f.get("smart_money_flag")),
                next_earnings_date=f.get("next_earnings_date"),
                earnings_flag=bool(f.get("earnings_flag")),
                suggested_put_strike=_suggested_put_strike(f.get("current_price"), f.get("atr")),
                factor_breakdown=f.get("factor_breakdown", {}),
            )
        )

    result.candidates = candidates
    return result


def _round(val: Optional[float], digits: int = 2) -> Optional[float]:
    if val is None:
        return None
    try:
        return round(float(val), digits)
    except (TypeError, ValueError):
        return None
