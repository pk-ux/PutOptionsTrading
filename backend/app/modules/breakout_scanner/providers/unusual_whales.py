"""
Breakout Scanner - Unusual Whales REST provider.

A self-contained smart-money/flow client built on ``httpx`` against the Unusual
Whales public REST API (https://api.unusualwhales.com). The MCP server is a
dev-time convenience only; production uses this client with a bearer token from
the ``UNUSUAL_WHALES_API_KEY`` env var.

Every method degrades gracefully (returns ``{}`` / ``[]`` on any failure) so a
single endpoint hiccup never aborts a scan. A per-instance cache makes repeated
calls within one run cheap, and 429s are retried with backoff.

Endpoints used (all GET):
- /api/screener/stocks                  bulk IV rank, net premium, P/C, earnings
- /api/stock/{t}/flow-alerts            unusual options flow alerts
- /api/stock/{t}/greek-exposure         dealer GEX (gamma/charm/vanna)
- /api/darkpool/{t}                     dark-pool block prints
- /api/stock/{t}/insider-buy-sells      aggregate insider buy/sell notional
- /api/congress/recent-trades           congress trades (ticker filter)
- /api/seasonality/{t}/monthly          monthly seasonality
"""

import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

BASE_URL = "https://api.unusualwhales.com"


class UnusualWhalesProvider:
    """Smart-money / options-flow data from Unusual Whales."""

    def __init__(
        self,
        api_key: Optional[str],
        timeout: float = 20.0,
        max_retries: int = 3,
        min_interval: float = 0.0,
    ):
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        # Minimum seconds between requests to smooth bursts and avoid 429s.
        self.min_interval = max(0.0, min_interval)
        self._last_request_ts = 0.0
        self._cache: Dict[str, Any] = {}
        self._client = None
        if api_key:
            try:
                import httpx

                self._client = httpx.Client(
                    base_url=BASE_URL,
                    timeout=timeout,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Accept": "application/json",
                    },
                )
            except Exception as e:  # pragma: no cover
                logger.warning(f"Could not init Unusual Whales client: {e}")
                self._client = None

    def is_available(self) -> bool:
        return self._client is not None

    def close(self) -> None:
        if self._client is not None:
            try:
                self._client.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Low-level GET with caching + retry/backoff
    # ------------------------------------------------------------------ #
    def _get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Any:
        if self._client is None:
            return None

        params = {k: v for k, v in (params or {}).items() if v is not None}
        cache_key = path + "?" + "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        if cache_key in self._cache:
            return self._cache[cache_key]

        for attempt in range(self.max_retries):
            try:
                self._throttle()
                resp = self._client.get(path, params=params)
                if resp.status_code == 429:
                    wait = self._parse_retry_after(resp.headers.get("Retry-After"), attempt)
                    logger.warning(f"UW rate limited on {path}, retrying in {wait}s")
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                self._cache[cache_key] = payload
                return payload
            except Exception as e:  # pragma: no cover - network
                if attempt == self.max_retries - 1:
                    logger.warning(f"UW GET {path} failed: {e}")
                    return None
                time.sleep(1)
        return None

    def _throttle(self) -> None:
        """Enforce a minimum interval between requests (best-effort, sync)."""
        if self.min_interval <= 0:
            return
        elapsed = time.monotonic() - self._last_request_ts
        if elapsed < self.min_interval:
            time.sleep(self.min_interval - elapsed)
        self._last_request_ts = time.monotonic()

    @staticmethod
    def _parse_retry_after(value: Optional[str], attempt: int) -> float:
        """Honor a Retry-After header (delta seconds) if present, else backoff.

        Falls back to exponential backoff (2**attempt). Caps the wait at 30s so a
        misbehaving header can't stall a scan indefinitely.
        """
        default = float(2 ** attempt)
        if not value:
            return default
        try:
            return min(max(float(value), 0.0), 30.0)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _data(payload: Any) -> List[Dict[str, Any]]:
        """Unwrap the common {"data": [...]} envelope."""
        if payload is None:
            return []
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        return []

    # ------------------------------------------------------------------ #
    # Public endpoints
    # ------------------------------------------------------------------ #
    def stock_screener(self, tickers: List[str]) -> Dict[str, Dict[str, Any]]:
        """Bulk flow/IV metrics for the given tickers, keyed by symbol."""
        if not tickers:
            return {}
        out: Dict[str, Dict[str, Any]] = {}
        # The screener accepts a comma list; chunk to stay well within limits.
        chunk = 100
        for i in range(0, len(tickers), chunk):
            batch = tickers[i:i + chunk]
            payload = self._get(
                "/api/screener/stocks",
                {"ticker": ",".join(batch), "limit": 500},
            )
            for row in self._data(payload):
                sym = (row.get("ticker") or row.get("symbol") or "").upper()
                if sym:
                    out[sym] = row
        return out

    def flow_alerts(self, ticker: str) -> List[Dict[str, Any]]:
        payload = self._get(f"/api/stock/{ticker}/flow-alerts", {"limit": 200})
        return self._data(payload)

    def greek_exposure(self, ticker: str) -> Dict[str, Any]:
        payload = self._get(f"/api/stock/{ticker}/greek-exposure", {"timeframe": "1M"})
        rows = self._data(payload)
        return rows[-1] if rows else {}

    def greek_exposure_by_strike(self, ticker: str) -> List[Dict[str, Any]]:
        """Per-strike dealer gamma exposure (for graded GEX + gamma walls)."""
        payload = self._get(f"/api/stock/{ticker}/greek-exposure/strike")
        return self._data(payload)

    def max_pain(self, ticker: str) -> Any:
        """Max-pain price per expiry for the ticker."""
        return self._get(f"/api/stock/{ticker}/max-pain")

    def net_prem_ticks(self, ticker: str) -> List[Dict[str, Any]]:
        """Intraday cumulative net call/put premium ticks for the latest day."""
        payload = self._get(f"/api/stock/{ticker}/net-prem-ticks")
        return self._data(payload)

    def option_contracts(self, ticker: str) -> List[Dict[str, Any]]:
        """Per-contract list (used for real call open-interest growth)."""
        payload = self._get(f"/api/stock/{ticker}/option-contracts", {"limit": 500})
        return self._data(payload)

    def market_tide(self) -> List[Dict[str, Any]]:
        """Market-wide net options premium (a fear/greed tape proxy)."""
        payload = self._get("/api/market/market-tide")
        return self._data(payload)

    def spike(self) -> Any:
        """Unusual Whales SPIKE intraday volatility index (best-effort)."""
        return self._get("/api/market/spike")

    def economic_calendar(self) -> List[Dict[str, Any]]:
        """Upcoming macro events (used as light market context)."""
        payload = self._get("/api/market/economic-calendar")
        return self._data(payload)

    def darkpool(self, ticker: str) -> List[Dict[str, Any]]:
        payload = self._get(f"/api/darkpool/{ticker}", {"limit": 200})
        return self._data(payload)

    def insider_buy_sells(self, ticker: str) -> Dict[str, Any]:
        payload = self._get(f"/api/stock/{ticker}/insider-buy-sells")
        rows = self._data(payload)
        if rows:
            return rows[0]
        if isinstance(payload, dict):
            return payload
        return {}

    def congress_trades(self, ticker: str) -> List[Dict[str, Any]]:
        payload = self._get("/api/congress/recent-trades", {"ticker": ticker, "limit": 50})
        return self._data(payload)

    def seasonality(self, ticker: str) -> List[Dict[str, Any]]:
        payload = self._get(f"/api/seasonality/{ticker}/monthly")
        return self._data(payload)
