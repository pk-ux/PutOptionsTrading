"""
Breakout Scanner module.

A self-contained, reusable pre-breakout stock scanner. It ranks a ticker
universe by a 0-100 Breakout Readiness Score built entirely from *leading*
signals - price-structure compression (VCP, Bollinger squeeze, NR7, volume
dry-up), relative-strength leadership, proximity to a clean pivot, and a
first-class Unusual Whales smart-money layer (bullish options flow, OI
accumulation, dealer GEX, dark-pool blocks, insider/congress buying, native IV
rank).

Public API:
    from app.modules.breakout_scanner import run_scan, ScannerConfig
    result = run_scan(tickers, ScannerConfig(top_n=15), price_provider, uw_provider)

The core (signals, scoring, scanner, types, providers) has no app dependencies
and can be copied into other projects. ``integration.py`` is the only app-aware
glue (DB + TradeIdea) and is intentionally separate.
"""

from .scanner import run_scan
from .types import (
    DEFAULT_WEIGHTS,
    ScanCandidate,
    ScanResult,
    ScannerConfig,
)

__all__ = [
    "run_scan",
    "ScannerConfig",
    "ScanCandidate",
    "ScanResult",
    "DEFAULT_WEIGHTS",
]
