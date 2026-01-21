#!/usr/bin/env python3
"""
Validate the CSP screener results against live API data
"""

import yfinance as yf
from massive_api_client import massive_client
from datetime import datetime

# Data from the screenshot
results = [
    {"symbol": "APP", "price": 559.78, "strike": 460, "premium": 9.33, "delta": -0.147, "return_pct": 41.1, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "PLTR", "price": 169.01, "strike": 140, "premium": 2.15, "delta": -0.131, "return_pct": 31.1, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "MSTR", "price": 160.16, "strike": 135, "premium": 2.00, "delta": -0.145, "return_pct": 30.0, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "CRWV", "price": 97.22, "strike": 75, "premium": 1.65, "delta": -0.129, "return_pct": 44.6, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "NBIS", "price": 101.54, "strike": 80, "premium": 1.58, "delta": -0.125, "return_pct": 40.0, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "IREN", "price": 54.71, "strike": 42, "premium": 1.30, "delta": -0.143, "return_pct": 62.8, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "APLD", "price": 34.00, "strike": 25, "premium": 0.44, "delta": -0.091, "return_pct": 35.7, "dte": 18, "expiry": "2026-02-06"},
    {"symbol": "BMNR", "price": 28.60, "strike": 22, "premium": 0.47, "delta": -0.136, "return_pct": 31.2, "dte": 25, "expiry": "2026-02-13"},
]

print("=" * 80)
print("VALIDATING CSP SCREENER RESULTS")
print("=" * 80)

# 1. Validate stock prices against Yahoo Finance
print("\n1. STOCK PRICE VALIDATION (vs Yahoo Finance)")
print("-" * 60)
for r in results:
    symbol = r["symbol"]
    try:
        ticker = yf.Ticker(symbol)
        live_price = ticker.info.get('regularMarketPrice') or ticker.info.get('currentPrice')
        if live_price:
            diff_pct = abs(live_price - r["price"]) / r["price"] * 100
            status = "✓" if diff_pct < 5 else "⚠️"
            print(f"{symbol}: App=${r['price']:.2f}, Yahoo=${live_price:.2f}, Diff={diff_pct:.1f}% {status}")
        else:
            print(f"{symbol}: Could not get Yahoo price")
    except Exception as e:
        print(f"{symbol}: Error - {e}")

# 2. Validate annualized return calculation
print("\n2. ANNUALIZED RETURN CALCULATION VALIDATION")
print("-" * 60)
print("Formula: (Premium / Strike) * (365 / DTE) * 100")
for r in results:
    calculated_return = (r["premium"] / r["strike"]) * (365 / r["dte"]) * 100
    diff = abs(calculated_return - r["return_pct"])
    status = "✓" if diff < 0.5 else "⚠️"
    print(f"{r['symbol']}: App={r['return_pct']:.1f}%, Calculated={calculated_return:.1f}%, Diff={diff:.2f}% {status}")

# 3. Validate Greeks from Massive API (sample a few)
print("\n3. GREEKS VALIDATION (vs Massive API)")
print("-" * 60)
test_symbols = ["PLTR", "IREN", "APP"]
for r in results:
    if r["symbol"] not in test_symbols:
        continue
    symbol = r["symbol"]
    try:
        # Get options chain from Massive
        options = massive_client.get_options_chain_with_greeks(
            symbol, 
            min_dte=r["dte"]-2, 
            max_dte=r["dte"]+2
        )
        
        # Find matching option
        for opt in options:
            if opt.get('strike') == r["strike"] and opt.get('type', '').upper() == 'PUT':
                api_delta = opt.get('delta', 'N/A')
                if api_delta != 'N/A':
                    diff = abs(api_delta - r["delta"])
                    status = "✓" if diff < 0.02 else "⚠️"
                    print(f"{symbol} ${r['strike']}P: App Delta={r['delta']:.3f}, API Delta={api_delta:.3f}, Diff={diff:.3f} {status}")
                break
        else:
            print(f"{symbol} ${r['strike']}P: Option not found in API")
    except Exception as e:
        print(f"{symbol}: Error - {e}")

# 4. Validate option premiums from Yahoo
print("\n4. OPTION PREMIUM VALIDATION (vs Yahoo Finance)")
print("-" * 60)
for r in results[:4]:  # Test first 4
    symbol = r["symbol"]
    try:
        ticker = yf.Ticker(symbol)
        expiry_date = r["expiry"]
        
        # Get options chain
        opts = ticker.option_chain(expiry_date)
        puts = opts.puts
        
        # Find matching strike
        matching = puts[puts['strike'] == r["strike"]]
        if not matching.empty:
            yahoo_premium = matching.iloc[0]['lastPrice']
            diff_pct = abs(yahoo_premium - r["premium"]) / r["premium"] * 100 if r["premium"] > 0 else 0
            status = "✓" if diff_pct < 20 else "⚠️"  # 20% tolerance for price changes
            print(f"{symbol} ${r['strike']}P: App=${r['premium']:.2f}, Yahoo=${yahoo_premium:.2f}, Diff={diff_pct:.1f}% {status}")
        else:
            print(f"{symbol} ${r['strike']}P: Strike not found in Yahoo")
    except Exception as e:
        print(f"{symbol}: Error - {e}")

print("\n" + "=" * 80)
print("VALIDATION COMPLETE")
print("=" * 80)
print("\nNote: Small differences in prices are expected due to:")
print("- Market movement between when data was captured")
print("- Bid/ask spread differences")
print("- Different data feed timestamps")
