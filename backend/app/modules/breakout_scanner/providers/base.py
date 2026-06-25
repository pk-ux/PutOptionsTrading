"""
Breakout Scanner - provider protocols.

Providers are injected into the scanner so the core stays portable and testable.
A ``PriceProvider`` supplies daily OHLCV; an optional ``SmartMoneyProvider``
supplies Unusual-Whales-style smart-money/flow data.
"""

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class PriceProvider(Protocol):
    """Supplies daily OHLCV history for a symbol."""

    def get_price_history(self, symbol: str, days: int = 365) -> List[Dict[str, Any]]:
        """Return a list of {date, open, high, low, close, volume} oldest-first."""
        ...


@runtime_checkable
class SmartMoneyProvider(Protocol):
    """Supplies options-flow / smart-money data (e.g. Unusual Whales).

    All methods must degrade gracefully (return ``{}``/``[]`` on error) so a
    single failed call never aborts a scan.
    """

    def is_available(self) -> bool: ...

    def stock_screener(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Bulk per-ticker flow/IV metrics keyed by symbol."""
        ...

    def flow_alerts(self, ticker: str) -> List[Dict[str, Any]]: ...

    def greek_exposure(self, ticker: str) -> Dict[str, Any]: ...

    def darkpool(self, ticker: str) -> List[Dict[str, Any]]: ...

    def insider_buy_sells(self, ticker: str) -> Dict[str, Any]: ...

    def congress_trades(self, ticker: str) -> List[Dict[str, Any]]: ...

    def seasonality(self, ticker: str) -> List[Dict[str, Any]]: ...
