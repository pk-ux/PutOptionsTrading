"""
Breakout Scanner - Alpaca daily-OHLCV price provider.

A more reliable alternative to ``YahooPriceProvider`` for the price-structure
signals. Depends only on ``alpaca-py`` (constructs its own data client from API
keys) so the portable-core boundary is preserved - the app wires keys in via
``integration.py`` and falls back to Yahoo when keys are absent.

Returns split/dividend-adjusted daily bars, oldest-first, in the same shape the
rest of the scanner expects: ``{date, open, high, low, close, volume}``.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class AlpacaPriceProvider:
    """Daily OHLCV via Alpaca's market-data API."""

    def __init__(self, api_key: Optional[str], secret_key: Optional[str]):
        self.api_key = api_key
        self.secret_key = secret_key
        self._cache: Dict[str, List[Dict[str, Any]]] = {}
        self._client = None
        if api_key and secret_key:
            try:
                from alpaca.data.historical import StockHistoricalDataClient

                self._client = StockHistoricalDataClient(
                    api_key=api_key, secret_key=secret_key
                )
            except Exception as e:  # pragma: no cover - import/availability
                logger.warning(f"Could not init Alpaca price client: {e}")
                self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def get_price_history(self, symbol: str, days: int = 365) -> List[Dict[str, Any]]:
        if self._client is None:
            return []
        cache_key = f"{symbol}:{days}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        try:
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from alpaca.data.enums import Adjustment

            # Alpaca caps the most recent bar window for free feeds; request a
            # generous calendar window to net the requested number of sessions.
            start = datetime.now(timezone.utc) - timedelta(days=int(days * 1.6) + 5)
            req = StockBarsRequest(
                symbol_or_symbols=symbol,
                timeframe=TimeFrame.Day,
                start=start,
                adjustment=Adjustment.ALL,
            )
            barset = self._client.get_stock_bars(req)
            bars = barset.data.get(symbol) if hasattr(barset, "data") else None
            if not bars:
                return []

            data: List[Dict[str, Any]] = []
            for b in bars:
                ts = getattr(b, "timestamp", None)
                data.append(
                    {
                        "date": ts.strftime("%Y-%m-%d") if ts else "",
                        "open": float(b.open),
                        "high": float(b.high),
                        "low": float(b.low),
                        "close": float(b.close),
                        "volume": int(b.volume or 0),
                    }
                )
            data.sort(key=lambda r: r["date"])  # oldest-first
            self._cache[cache_key] = data
            return data
        except Exception as e:  # pragma: no cover - network/availability
            logger.warning(f"AlpacaPriceProvider failed for {symbol}: {e}")
            return []
