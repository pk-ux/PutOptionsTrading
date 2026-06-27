"""
Breakout Scanner - cross-sectional scoring.

Combines per-ticker leading factors into a 0-100 Breakout Readiness Score.
Raw, unbounded factors (relative strength, flow premium, OI change, dark-pool
premium) are percentile-ranked *across the universe* so no single factor with a
large scale dominates. Already-normalized 0..1 structure signals are used
directly. Red-flag penalties (earnings, bearish flow, negative seasonality) are
subtracted at the end.
"""

from typing import Any, Dict, List, Optional

from .types import DEFAULT_WEIGHTS

# Penalty magnitudes (subtracted from the final 0..1 score)
EARNINGS_PENALTY = 0.10
BEARISH_PENALTY = 0.10
SEASONALITY_PENALTY_MAX = 0.05
GAMMA_WALL_PENALTY_MAX = 0.05


def percentile_rank(values: List[Optional[float]], missing: float = 0.5) -> List[float]:
    """Return a 0..1 percentile rank for each value.

    Missing values map to ``missing`` (default 0.5, neutral) rather than 0.0 so
    that names simply lacking a data point are not unfairly ranked dead-last.
    """
    present = [(i, v) for i, v in enumerate(values) if v is not None]
    out = [missing] * len(values)
    if not present:
        return out
    if len(present) == 1:
        out[present[0][0]] = 1.0
        return out
    ordered = sorted(present, key=lambda t: t[1])
    n = len(ordered)
    for rank, (idx, _) in enumerate(ordered):
        out[idx] = rank / (n - 1)
    return out


def _col(features: List[Dict[str, Any]], key: str) -> List[Optional[float]]:
    return [f.get(key) for f in features]


def score_candidates(
    features: List[Dict[str, Any]],
    weights: Optional[Dict[str, float]] = None,
    regime_scale: float = 1.0,
) -> None:
    """Compute composite scores in-place: sets ``score`` (0..100) and
    ``factor_breakdown`` on each feature dict.

    ``regime_scale`` (from the market-context layer) multiplies the final 0..1
    score so the same setup ranks lower in a risk-off tape than a risk-on one.
    """
    if not features:
        return
    weights = weights or dict(DEFAULT_WEIGHTS)
    try:
        regime_scale = float(regime_scale)
    except (TypeError, ValueError):
        regime_scale = 1.0

    # Percentile-ranked raw factors (missing -> neutral 0.5)
    rs_pct = percentile_rank(_col(features, "rs_raw"))
    flow_pct = percentile_rank(_col(features, "flow_bullishness"))
    oi_pct = percentile_rank(_col(features, "oi_accum"))
    dp_pct = percentile_rank(_col(features, "darkpool_premium"))
    sm_pct = percentile_rank(_col(features, "smart_money_score"))

    for i, f in enumerate(features):
        # --- group: compression / VCP / base (already 0..1 signals) ---
        compression = float(f.get("compression") or 0.0)
        vcp = float(f.get("vcp") or 0.0)
        nr = float(f.get("nr_tightness") or 0.0)
        vdu = float(f.get("volume_dryup") or 0.0)
        base_q = float(f.get("base_quality") or 0.0)
        squeeze_bonus = 0.08 if f.get("squeeze") else 0.0
        compression_vcp = min(
            1.0,
            0.35 * compression + 0.25 * vcp + 0.12 * nr + 0.12 * vdu
            + 0.16 * base_q + squeeze_bonus,
        )

        # --- group: flow + OI accumulation (UW) ---
        flow_oi = 0.6 * flow_pct[i] + 0.4 * oi_pct[i]

        # --- group: leadership (relative strength + 52wk-high proximity) ---
        near_high = float(f.get("near_52wk_high") or 0.0)
        rs_high_bonus = 0.05 if f.get("rs_new_high") else 0.0
        leadership = min(1.0, 0.6 * rs_pct[i] + 0.4 * near_high + rs_high_bonus)

        # --- group: breakout confirmation (volume expansion + trigger) ---
        vol_exp = float(f.get("volume_expansion") or 0.0)
        trigger = 1.0 if f.get("breakout_trigger") else 0.0
        confirmation = min(1.0, 0.6 * vol_exp + 0.4 * trigger)

        # --- group: dark pool + smart money (UW) ---
        dp_bonus = 0.10 if f.get("darkpool_accum") else 0.0
        sm_bonus = 0.10 if f.get("smart_money_flag") else 0.0
        darkpool_smart = min(1.0, 0.5 * dp_pct[i] + 0.5 * sm_pct[i] + dp_bonus + sm_bonus)

        # --- group: dealer GEX (UW, already 0..1, graded) ---
        gex = float(f.get("gex_score") or 0.0)

        # --- group: pivot proximity (already 0..1) ---
        pivot = float(f.get("pivot") or 0.0)

        groups = {
            "flow_oi": flow_oi,
            "compression_vcp": compression_vcp,
            "leadership": leadership,
            "confirmation": confirmation,
            "darkpool_smart": darkpool_smart,
            "gex": gex,
            "pivot": pivot,
        }

        base = sum(groups[g] * weights.get(g, 0.0) for g in groups)

        # --- penalties ---
        penalty = 0.0
        if f.get("earnings_flag"):
            penalty += EARNINGS_PENALTY
        if _is_bearish(f):
            penalty += BEARISH_PENALTY
        seasonality = f.get("seasonality")
        if seasonality is not None and seasonality < 0:
            penalty += min(SEASONALITY_PENALTY_MAX, abs(seasonality) / 100.0)
        wall_pressure = float(f.get("gamma_wall_pressure") or 0.0)
        if wall_pressure > 0:
            penalty += min(GAMMA_WALL_PENALTY_MAX, wall_pressure * GAMMA_WALL_PENALTY_MAX)

        final = max(0.0, min(1.0, base - penalty))
        final = max(0.0, min(1.0, final * regime_scale))
        f["score"] = round(final * 100.0, 2)
        f["factor_breakdown"] = {
            **{g: round(v, 3) for g, v in groups.items()},
            "penalty": round(penalty, 3),
            "regime_scale": round(regime_scale, 3),
        }


def _is_bearish(f: Dict[str, Any]) -> bool:
    """Heavy bearish positioning => avoid (we sell puts on names likely to rise)."""
    ncp = f.get("net_call_premium")
    npp = f.get("net_put_premium")
    if ncp is not None and npp is not None and npp > 0 and npp > ncp * 1.5 and ncp <= 0:
        return True
    bull = f.get("bullish_premium")
    bear = f.get("bearish_premium")
    if bull is not None and bear is not None and bear > bull * 1.5 and bear > 0:
        return True
    return False
