"""
Breakout Scanner - default price provider backed by Yahoo Finance (yfinance).

Self-contained (only yfinance) so the module stays portable. Includes a small
in-process cache for SPY to avoid refetching it for every symbol in a run.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class YahooPriceProvider:
    """Daily OHLCV via yfinance."""

    def __init__(self) -> None:
        self._cache: Dict[str, List[Dict[str, Any]]] = {}

    def get_price_history(self, symbol: str, days: int = 365) -> List[Dict[str, Any]]:
        cache_key = f"{symbol}:{days}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            hist = ticker.history(period=f"{days}d")
            if hist is None or hist.empty:
                return []

            data: List[Dict[str, Any]] = []
            for idx, row in hist.iterrows():
                data.append(
                    {
                        "date": idx.strftime("%Y-%m-%d"),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]),
                    }
                )
            self._cache[cache_key] = data
            return data
        except Exception as e:  # pragma: no cover - network/availability
            logger.warning(f"YahooPriceProvider failed for {symbol}: {e}")
            return []
