# Breakout Scanner

A self-contained, reusable module that scans a ticker universe for stocks that
are **about to break out** (not ones already extended) and ranks them by a
0-100 **Breakout Readiness Score**. Designed to feed a cash-secured-put workflow:
surface high-quality names coiling before a move so you collect rich premium and,
if assigned, own them at a discount.

## Philosophy: leading signals only

No lagging trigger indicators (MACD / SMA-cross / raw RSI level). Every factor is
anticipatory:

| Group | Weight | Signals |
|-------|-------:|---------|
| Options flow + OI accumulation (UW) | 25% | ask-side opening call sweeps, net call premium, call OI build |
| Compression / VCP | 25% | Bollinger bandwidth percentile + squeeze, NR7/inside bars, VCP contraction, volume dry-up |
| Relative strength | 15% | outperformance vs SPY, rising |
| Dark pool + smart money (UW) | 15% | institutional block prints, insider + congress buying |
| Dealer GEX (UW) | 10% | negative dealer gamma (breakouts accelerate) |
| Pivot proximity | 10% | price coiling just under a clean breakout pivot |

Red-flag penalties: earnings inside the CSP window, heavy bearish flow, negative
seasonality.

Raw, unbounded factors are percentile-ranked across the universe; normalized 0..1
structure signals are used directly.

## Usage

```python
from app.modules.breakout_scanner import run_scan, ScannerConfig
from app.modules.breakout_scanner.providers import YahooPriceProvider, UnusualWhalesProvider

result = run_scan(
    tickers=["AAPL", "NVDA", "PLTR", ...],
    config=ScannerConfig(top_n=15, use_unusual_whales=True),
    price_provider=YahooPriceProvider(),
    uw_provider=UnusualWhalesProvider(api_key="..."),  # optional
)
for c in result.candidates:
    print(c.symbol, c.score, c.setup_type, c.iv_rank)
```

If `uw_provider` is omitted (or has no key) the scanner runs on price-structure
signals alone and the UW factor weights are automatically redistributed.

## Architecture

```
types.py            dataclasses (ScannerConfig, ScanCandidate, ScanResult)
signals.py          pure price-structure leading signals (numpy)
uw_signals.py       normalize Unusual Whales responses -> factors
scoring.py          cross-sectional percentile ranking + composite
scanner.py          orchestrator (run_scan)
providers/
  base.py           PriceProvider / SmartMoneyProvider protocols
  yahoo_provider.py default daily OHLCV (yfinance)
  unusual_whales.py UW REST client (httpx)
integration.py      *app-aware* glue (DB settings + Momentum Stocks TradeIdea)
```

## Reusing in another project

Copy the whole `breakout_scanner/` directory **except `integration.py`** (which
depends on this app's SQLAlchemy models). Provide your own `PriceProvider` (or
reuse `YahooPriceProvider`) and optionally a `SmartMoneyProvider`. The only
third-party deps are `numpy`, `yfinance` (default price provider) and `httpx`
(UW provider).

## Removing from this app

Delete `backend/app/modules/breakout_scanner/`, the `breakout_scanner` router
include in `app/api/v1/router.py`, the two models in
`app/models/breakout_scanner.py` (and their registration), the
`BreakoutScannerCard` in the frontend, and `scripts/run_breakout_scan.py`. No
other feature depends on it.
