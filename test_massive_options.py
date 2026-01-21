"""
Simple script to test Massive.com Options API
"""
from massive import RESTClient
from datetime import datetime, timedelta

# Initialize client
API_KEY = "FEqqzDBrV0ZMOmoHR51NNPLHNC1LPrxo"
client = RESTClient(api_key=API_KEY)

symbol = "AAPL"

# Calculate date range (15-45 days out)
today = datetime.now().date()
min_date = (today + timedelta(days=15)).isoformat()
max_date = (today + timedelta(days=45)).isoformat()

print(f"Fetching PUT options for {symbol}")
print(f"Expiration range: {min_date} to {max_date}")
print(f"Strike range: $250 - $270 (near ATM)")
print("-" * 60)

count = 0
for option in client.list_snapshot_options_chain(
    symbol,
    params={
        "expiration_date.gte": min_date,
        "expiration_date.lte": max_date,
        "contract_type": "put",
        "strike_price.gte": 250,
        "strike_price.lte": 270
    }
):
    count += 1
    
    # Extract data
    strike = option.details.strike_price
    exp = option.details.expiration_date
    
    # Greeks from API
    delta = option.greeks.delta if option.greeks else None
    gamma = option.greeks.gamma if option.greeks else None
    theta = option.greeks.theta if option.greeks else None
    vega = option.greeks.vega if option.greeks else None
    
    # IV
    iv = option.implied_volatility
    
    # Volume/OI
    oi = option.open_interest or 0
    vol = option.day.volume if option.day else 0
    
    # Price (may be None on basic plan)
    price = None
    if option.last_quote:
        if option.last_quote.midpoint:
            price = option.last_quote.midpoint
        elif option.last_quote.bid and option.last_quote.ask:
            price = (option.last_quote.bid + option.last_quote.ask) / 2
    
    print(f"Strike: ${strike:>6} | Exp: {exp} | Delta: {delta:>7.4f} | IV: {iv:.2%} | OI: {oi:>5} | Vol: {vol:>4} | Price: {'$'+f'{price:.2f}' if price else 'N/A':>6}")

print("-" * 60)
print(f"Total options found: {count}")
