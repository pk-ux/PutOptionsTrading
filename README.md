# Put Options Screener

Interactive Streamlit app that scans put option chains for a list of stocks, computes key metrics (delta, annualized return, implied volatility), and highlights candidates that meet your custom filters. Data can come from Alpaca (real-time), Public.com (real-time), or Yahoo Finance (free).

## What this project does
- Loads a configurable list of tickers and option screening rules from `config.json`.
- Pulls quotes/option chains from the selected data source.
- Calculates returns and Greeks, filters on volume/OI/delta/return thresholds, and presents the top candidates in an interactive UI.
- Lets you screen one symbol or many, view a summary table, and adjust settings without editing code.

## Project structure (key files)
- `app.py` – Streamlit UI, state management, and orchestration.
- `options_screener.py` – Data fetching, metrics, filtering, and formatting.
- `alpaca_mcp_client.py` – Thin wrapper around Alpaca APIs for quotes and option contracts.
- `public_api_client.py` – Public.com API client (quotes, chains, Greeks).
- `config.json` – Default symbols and screening parameters you can edit or update via the UI.
- `test_quote.py` – Quick script to verify Alpaca credentials can fetch a quote.

## Prerequisites
- Python 3.11+
- An Alpaca account (for real-time Alpaca data) and/or Public.com credentials if you want those sources. Yahoo Finance works without credentials.

## Setup
1) Clone the repo  
```bash
git clone https://github.com/your-org/PutOptionsTrading.git
cd PutOptionsTrading
```

2) Create and activate a virtual environment  
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

3) Install dependencies  
```bash
pip install -r requirements.txt
# or: pip install -e .  (uses pyproject.toml)
```

4) Add environment variables (create a `.env` in the repo or export in your shell):
```bash
# Alpaca (required for Alpaca source)
ALPACA_API_KEY=your_key
ALPACA_SECRET_KEY=your_secret
ALPACA_PAPER_TRADE=True  # or False if using live

# Public.com (required for Public source)
PUBLIC_ACCESS_TOKEN=your_public_secret_token
PUBLIC_ACCOUNT_ID=your_public_account_id
```
These are loaded automatically via `python-dotenv`.

5) (Optional) Adjust defaults in `config.json`  
- Symbols to screen: `data.symbols`  
- Strategy window: `options_strategy.max_dte`, `min_dte`  
- Liquidity filters: `options_strategy.min_volume`, `min_open_interest`  
- Return/risk filters: `screening_criteria.min_annualized_return`, `min_delta`, `max_delta`  
- Sorting/limits: `output.sort_by`, `sort_order`, `max_results`
You can also change these from the Streamlit UI and click “Save Settings” to persist.

## Running the app
```bash
streamlit run app.py
```
Then open the provided local URL. In the UI:
- Pick your data source (Alpaca, Public.com, or Yahoo).
- Select a symbol or choose “Screen All Stocks”.
- View per-ticker results or the summary table; adjust filters and re-run.

## Command-line usage
You can run the screener without the UI (uses the configured symbols and filters):
```bash
python options_screener.py          # defaults to Alpaca if keys are present
python -c "import options_screener as s; s.main('yahoo')"   # choose source manually
```

## Verifying credentials
- Alpaca: `python test_quote.py` (prints whether keys are found and fetches a quote).  
- Public.com: the Streamlit UI will show a connection error if `PUBLIC_ACCESS_TOKEN` or `PUBLIC_ACCOUNT_ID` are missing.

## Data sources and rate limits
- Alpaca: real-time equities/options via `alpaca_mcp_client.py`. Set `ALPACA_API_KEY/SECRET` and optional `ALPACA_PAPER_TRADE`.
- Public.com: real-time via `public_api_client.py`. Requires `PUBLIC_ACCESS_TOKEN` (secret) and `PUBLIC_ACCOUNT_ID`.
- Yahoo Finance: free fallback; no credentials required.
- Per-source delays can be tuned in the UI and persisted to `config.json` under `api_rate_limits`.

## Notes and precautions
- Keep API keys in environment variables or a local `.env`; do not commit secrets.
- The screener focuses on put contracts; ensure you understand options risk before trading.
- Some data sources may throttle heavy usage; adjust the configured delay if you encounter rate limits.

