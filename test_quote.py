import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

load_dotenv()

api_key = os.getenv("ALPACA_API_KEY")
api_secret = os.getenv("ALPACA_SECRET_KEY")
paper = os.getenv("ALPACA_PAPER_TRADE", "True").lower() == "true"

print(f"API Key found: {bool(api_key)}")
print(f"API Secret found: {bool(api_secret)}")
print(f"Paper: {paper}")

if not api_key or not api_secret:
    print("Error: Missing Alpaca API credentials.")
    exit(1)

try:
    # We need the data client for quotes
    data_client = StockHistoricalDataClient(api_key, api_secret)
    request_params = StockLatestQuoteRequest(symbol_or_symbols="MU")
    latest_quote = data_client.get_stock_latest_quote(request_params)
    print(f"Quote for MU: {latest_quote['MU']}")
except Exception as e:
    print(f"Error: {e}")


