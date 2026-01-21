"""
Simple script to get stock price using Massive.com API
"""
from massive import RESTClient
from datetime import datetime, timedelta

# Initialize client with API key
API_KEY = "FEqqzDBrV0ZMOmoHR51NNPLHNC1LPrxo"
client = RESTClient(api_key=API_KEY)

symbol = "AAPL"

print(f"Getting price for {symbol}...")

# Try last few days to find a trading day (skip weekends/holidays)
for days_back in range(1, 7):
    date_str = (datetime.now().date() - timedelta(days=days_back)).isoformat()
    try:
        daily = client.get_daily_open_close_agg(symbol, date_str)
        print(f"\nDate: {daily.from_}")
        print(f"Open: ${daily.open}")
        print(f"High: ${daily.high}")
        print(f"Low: ${daily.low}")
        print(f"Close: ${daily.close}")
        print(f"Volume: {daily.volume:,.0f}")
        break
    except Exception as e:
        print(f"  No data for {date_str} (likely weekend/holiday)")
