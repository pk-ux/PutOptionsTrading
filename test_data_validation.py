"""
Data Validation Script
Validates the exported data against live API sources to ensure correctness
"""
import pandas as pd
import yfinance as yf
from massive import RESTClient
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize Massive client
MASSIVE_API_KEY = os.getenv('MASSIVE_API_KEY')
massive_client = RESTClient(api_key=MASSIVE_API_KEY)

def validate_exported_data(csv_path):
    """Validate exported data against live sources"""
    
    print("=" * 70)
    print("DATA VALIDATION REPORT")
    print("=" * 70)
    
    # Load exported data
    df = pd.read_csv(csv_path)
    print(f"\nLoaded {len(df)} rows from export")
    print(f"Columns: {list(df.columns)}")
    print()
    
    # Get unique symbol
    symbol = df['Symbol'].iloc[0]
    print(f"Symbol: {symbol}")
    print("-" * 70)
    
    # 1. VALIDATE STOCK PRICE
    print("\n1. STOCK PRICE VALIDATION")
    print("-" * 40)
    
    exported_price = df['Current Price'].iloc[0]
    
    # Get live price from Yahoo
    stock = yf.Ticker(symbol)
    yahoo_price = stock.info.get('regularMarketPrice', stock.info.get('currentPrice'))
    
    print(f"   Exported Price:  ${exported_price:.2f}")
    print(f"   Yahoo Live:      ${yahoo_price:.2f}")
    price_diff = abs(exported_price - yahoo_price)
    price_diff_pct = (price_diff / yahoo_price) * 100
    print(f"   Difference:      ${price_diff:.2f} ({price_diff_pct:.2f}%)")
    
    if price_diff_pct < 2:
        print("   ✅ PASS - Price within 2% tolerance")
    else:
        print("   ⚠️  WARNING - Price difference > 2%")
    
    # 2. VALIDATE OPTIONS DATA FROM MASSIVE
    print("\n2. OPTIONS GREEKS VALIDATION (vs Massive API)")
    print("-" * 40)
    
    # Get a sample option from Massive to compare
    sample_row = df.iloc[0]
    strike = sample_row['Strike Price']
    expiry = sample_row['Expiration Date']
    
    print(f"   Checking: Strike ${strike}, Expiry {expiry}")
    
    # Fetch from Massive
    try:
        for option in massive_client.list_snapshot_options_chain(
            symbol,
            params={
                "expiration_date": expiry,
                "contract_type": "put",
                "strike_price.gte": strike - 0.01,
                "strike_price.lte": strike + 0.01
            }
        ):
            if hasattr(option, 'details') and option.details.strike_price == strike:
                # Compare Greeks
                print(f"\n   Exported vs Massive API:")
                
                # Delta
                exported_delta = sample_row['Delta']
                api_delta = option.greeks.delta if option.greeks else None
                print(f"   Delta:    Exported={exported_delta:.4f}, API={api_delta:.4f if api_delta else 'N/A'}")
                if api_delta and abs(exported_delta - api_delta) < 0.01:
                    print("             ✅ MATCH")
                else:
                    print("             ⚠️  DIFFERENCE (may be timing)")
                
                # Theta (Decay/Contract)
                if 'Decay/Contract' in sample_row:
                    exported_theta = sample_row['Decay/Contract']
                    api_theta = option.greeks.theta if option.greeks else None
                    print(f"   Theta:    Exported={exported_theta:.4f}, API={api_theta:.4f if api_theta else 'N/A'}")
                    if api_theta and abs(exported_theta - api_theta) < 0.01:
                        print("             ✅ MATCH")
                    else:
                        print("             ⚠️  DIFFERENCE (may be timing)")
                
                # IV
                exported_iv = sample_row['IV (%)'] / 100  # Convert from % to decimal
                api_iv = option.implied_volatility if option.implied_volatility else None
                print(f"   IV:       Exported={exported_iv:.4f}, API={api_iv:.4f if api_iv else 'N/A'}")
                if api_iv and abs(exported_iv - api_iv) < 0.02:
                    print("             ✅ MATCH")
                else:
                    print("             ⚠️  DIFFERENCE (may be timing)")
                
                break
    except Exception as e:
        print(f"   Error fetching from Massive: {e}")
    
    # 3. VALIDATE ANNUALIZED RETURN CALCULATION
    print("\n3. ANNUALIZED RETURN CALCULATION VALIDATION")
    print("-" * 40)
    
    print("\n   Formula: (Premium / Strike) * (365 / DTE) * 100")
    print()
    
    all_correct = True
    for idx, row in df.iterrows():
        premium = row['Premium']
        strike = row['Strike Price']
        dte = row['DTE']
        exported_return = row['Annualized Return (%)']
        
        # Calculate expected return
        calculated_return = (premium / strike) * (365 / dte) * 100
        
        diff = abs(exported_return - calculated_return)
        status = "✅" if diff < 0.1 else "❌"
        if diff >= 0.1:
            all_correct = False
        
        print(f"   Row {idx}: Strike ${strike}, Premium ${premium}, DTE {dte}")
        print(f"            Exported: {exported_return:.2f}%, Calculated: {calculated_return:.2f}% {status}")
    
    if all_correct:
        print("\n   ✅ ALL ANNUALIZED RETURNS CORRECT")
    else:
        print("\n   ❌ SOME CALCULATIONS DON'T MATCH")
    
    # 4. VALIDATE OPTION PRICES FROM YAHOO
    print("\n4. OPTION PRICES VALIDATION (vs Yahoo Finance)")
    print("-" * 40)
    
    try:
        # Get Yahoo options chain
        stock = yf.Ticker(symbol)
        
        for idx, row in df.head(3).iterrows():  # Check first 3
            strike = row['Strike Price']
            expiry = row['Expiration Date']
            exported_premium = row['Premium']
            
            try:
                chain = stock.option_chain(expiry)
                puts = chain.puts
                
                # Find matching strike
                match = puts[puts['strike'] == strike]
                if not match.empty:
                    yahoo_price = match['lastPrice'].iloc[0]
                    diff = abs(exported_premium - yahoo_price)
                    diff_pct = (diff / yahoo_price) * 100 if yahoo_price > 0 else 0
                    
                    print(f"   Strike ${strike}, Expiry {expiry}")
                    print(f"   Exported: ${exported_premium:.2f}, Yahoo: ${yahoo_price:.2f}, Diff: {diff_pct:.1f}%")
                    if diff_pct < 10:
                        print("   ✅ PASS")
                    else:
                        print("   ⚠️  DIFFERENCE (timing or bid/ask spread)")
                    print()
            except Exception as e:
                print(f"   Could not fetch {expiry}: {e}")
                
    except Exception as e:
        print(f"   Error: {e}")
    
    print("=" * 70)
    print("VALIDATION COMPLETE")
    print("=" * 70)

if __name__ == "__main__":
    csv_path = "/Users/prashant/Downloads/2026-01-20T06-25_export.csv"
    validate_exported_data(csv_path)
