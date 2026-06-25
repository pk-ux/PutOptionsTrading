"""
Breakout Scanner - core data types.

This module is dependency-light on purpose (only stdlib + typing) so the whole
``breakout_scanner`` package can be lifted into other projects unchanged.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


# Default factor-group weights (must sum to ~1.0). Tuned for *pre-breakout*
# detection with a first-class Unusual Whales smart-money layer.
DEFAULT_WEIGHTS: Dict[str, float] = {
    "flow_oi": 0.25,          # UW bullish options flow + OI accumulation
    "compression_vcp": 0.25,  # price-structure compression / VCP / volume dry-up
    "rs": 0.15,               # relative-strength leadership vs SPY
    "darkpool_smart": 0.15,   # UW dark-pool blocks + insider/congress buying
    "gex": 0.10,              # UW dealer gamma exposure regime
    "pivot": 0.10,            # proximity to a clean breakout pivot
}


@dataclass
class ScannerConfig:
    """Tunable configuration for a scan run."""

    top_n: int = 15                     # how many symbols to publish
    deep_dive_n: int = 40               # how many survivors get per-ticker UW calls
    weights: Dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    # Stage-1 pre-filter
    min_price: float = 10.0
    max_price: float = 600.0
    min_avg_volume: int = 500_000
    require_above_sma200: bool = False   # OFF by default (no-lagging rule)

    # Lookbacks
    history_days: int = 365

    # CSP context
    typical_csp_dte: int = 35            # earnings-before-expiry window

    # Toggles
    use_unusual_whales: bool = True

    def normalized_weights(self) -> Dict[str, float]:
        """Return weights renormalized to sum to 1.0 (drops zero/absent groups)."""
        active = {k: float(v) for k, v in self.weights.items() if v and v > 0}
        total = sum(active.values())
        if total <= 0:
            return dict(DEFAULT_WEIGHTS)
        return {k: v / total for k, v in active.items()}


@dataclass
class ScanCandidate:
    """A single scored ticker plus the context needed for CSP decisions."""

    symbol: str
    score: float = 0.0
    rank: int = 0
    setup_type: str = "none"
    pivot_price: Optional[float] = None
    current_price: Optional[float] = None

    # CSP / options context (mostly from Unusual Whales)
    iv_rank: Optional[float] = None
    implied_move: Optional[float] = None
    net_call_premium: Optional[float] = None
    bullish_flow_score: Optional[float] = None
    gex_regime: Optional[str] = None          # "short_gamma" | "long_gamma" | None
    dark_pool_accum: bool = False
    smart_money: bool = False
    next_earnings_date: Optional[str] = None
    earnings_flag: bool = False
    suggested_put_strike: Optional[float] = None

    # Transparency: per-factor 0..1 contributions
    factor_breakdown: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "score": round(self.score, 2),
            "rank": self.rank,
            "setup_type": self.setup_type,
            "pivot_price": self.pivot_price,
            "current_price": self.current_price,
            "iv_rank": self.iv_rank,
            "implied_move": self.implied_move,
            "net_call_premium": self.net_call_premium,
            "bullish_flow_score": self.bullish_flow_score,
            "gex_regime": self.gex_regime,
            "dark_pool_accum": self.dark_pool_accum,
            "smart_money": self.smart_money,
            "next_earnings_date": self.next_earnings_date,
            "earnings_flag": self.earnings_flag,
            "suggested_put_strike": self.suggested_put_strike,
            "factor_breakdown": self.factor_breakdown,
        }


@dataclass
class ScanResult:
    """The full result of a scan run."""

    candidates: List[ScanCandidate] = field(default_factory=list)
    run_at: datetime = field(default_factory=datetime.utcnow)
    universe_size: int = 0
    scanned: int = 0
    used_unusual_whales: bool = False
    warnings: List[str] = field(default_factory=list)

    @property
    def top_symbols(self) -> List[str]:
        return [c.symbol for c in self.candidates]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_at": self.run_at.isoformat(),
            "universe_size": self.universe_size,
            "scanned": self.scanned,
            "used_unusual_whales": self.used_unusual_whales,
            "warnings": self.warnings,
            "candidates": [c.to_dict() for c in self.candidates],
        }
