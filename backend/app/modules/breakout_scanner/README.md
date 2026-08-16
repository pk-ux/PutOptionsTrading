# Breakout Scanner

A self-contained, reusable module that scans a ticker universe for stocks that
are **about to break out** and ranks them by a 0-100 **Breakout Readiness Score**.
Designed to feed a cash-secured-put workflow: surface high-quality names coiling
before a move so you collect rich premium and, if assigned, own them at a discount.

## Philosophy: leading signals only

No lagging trigger indicators (MACD / SMA-cross / raw RSI level). Every factor is
anticipatory, and names that have **already** broken out are excluded up front so
the results answer "what is about to move?" rather than "what just moved?".

| Group | Weight | Signals |
|-------|-------:|---------|
| Compression / VCP | 20% | Bollinger bandwidth percentile + squeeze, NR7/inside bars, VCP contraction, volume dry-up, base quality |
| Options flow + OI accumulation (UW) | 20% | ask-side opening call sweeps, net call premium, real call OI build |
| Leadership | 16% | relative strength vs SPY and sector ETF, 52-week-high proximity, RS-line new high, prior uptrend |
| Pivot proximity | 14% | ATR-normalized distance to a clean multi-touch breakout pivot |
| Dark pool + smart money (UW) | 12% | institutional block prints, insider + congress buying |
| Base construction | 10% | base duration, up/down volume accumulation, tight closes |
| Dealer GEX (UW) | 8% | negative dealer gamma (breakouts accelerate) |

Red-flag penalties: earnings inside the CSP window, heavy bearish flow, negative
seasonality, and an overhead gamma wall.

A market-regime layer scales every score by 0.70-1.10 based on a 0-100 fear/greed
reading, so the same setup ranks lower in a risk-off tape.

Raw, unbounded factors are percentile-ranked across the universe (ties share a
rank; missing data maps to a neutral 0.5 rather than dead-last). Normalized 0..1
structure signals are used directly.

## Usage

```python
from app.modules.breakout_scanner import run_scan, ScannerConfig
from app.modules.breakout_scanner.providers import YahooPriceProvider, UnusualWhalesProvider

result = run_scan(
    tickers=["AAPL", "NVDA", "PLTR"],
    config=ScannerConfig(top_n=15, use_unusual_whales=True),
    price_provider=YahooPriceProvider(),
    uw_provider=UnusualWhalesProvider(api_key="..."),  # optional
)
for c in result.candidates:
    print(c.rank, c.symbol, c.score, c.setup_type, c.pct_to_pivot)
```

If `uw_provider` is omitted (or has no key) the scanner runs on price-structure
signals alone and the UW factor weights are automatically redistributed.

Auto-universe mode needs no curated list — `integration.py` pulls the top
optionable US equities from the UW screener:

```python
config = ScannerConfig(universe_mode="auto", auto_universe_size=300)
```

## Running it in the app

Three entry points, all landing on `integration.run_and_publish()`:

| How | Trigger |
|---|---|
| Manual | Admin → Breakout Scanner → **Run Scan** (always available) |
| Automatic | Built-in scheduler, configured in the same admin card |
| External | `python -m scripts.run_breakout_scan` from cron (optional) |

The automatic schedule is off by default and defaults to **16:30
America/New_York, Mon–Fri** — 30 minutes after the US close, once the daily bar
has settled. Time, timezone, and weekdays are all editable from the admin UI; no
redeploy or cron entry is needed. It runs once per day at most, catches up if the
process was down at the scheduled minute (within 4 hours), and never collides
with a manual run. See `ARCHITECTURE.md` §6.1.

## Architecture

```
types.py            dataclasses (ScannerConfig, ScanCandidate, ScanResult)
signals.py          pure price-structure leading signals (numpy)
uw_signals.py       normalize Unusual Whales responses -> factors
market_context.py   market regime / fear-greed -> score multiplier
scoring.py          cross-sectional percentile ranking + composite
scanner.py          orchestrator (run_scan)
providers/
  base.py             PriceProvider / SmartMoneyProvider protocols
  yahoo_provider.py   daily OHLCV (yfinance)
  alpaca_provider.py  daily OHLCV (alpaca-py)
  unusual_whales.py   UW REST client (httpx)
integration.py      *app-aware* glue (DB settings + Momentum Stocks TradeIdea)
scheduler.py        *app-aware* automatic scan schedule (asyncio loop)
```

See `ARCHITECTURE.md` for the full algorithm, pipeline diagrams, and the
playbook for adding new signals.

## Testing

```
cd backend && python -m pytest tests/test_breakout_scanner.py
```

The suite runs entirely against fake providers, so it needs no API keys or
network access.

## Reusing in another project

Copy the whole `breakout_scanner/` directory **except `integration.py` and
`scheduler.py`** (which depend on this app's SQLAlchemy models). Provide your own
`PriceProvider` (or reuse `YahooPriceProvider`) and optionally a
`SmartMoneyProvider`. The only third-party deps are `numpy`, `yfinance` (default
price provider) and `httpx` (UW provider).

## Removing from this app

Delete `backend/app/modules/breakout_scanner/`, the `breakout_scanner` router
include in `app/api/v1/router.py`, the two models in
`app/models/breakout_scanner.py` (and their registration), the scheduler
start/stop calls in `app/main.py`'s lifespan, the `BreakoutScannerCard` in the
frontend, `backend/tests/test_breakout_scanner.py`, and
`scripts/run_breakout_scan.py`. No other feature depends on it.
