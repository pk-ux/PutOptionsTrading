"""
Test script to verify Massive.com API key and explore response structure
"""
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Check if API key is set
api_key = os.getenv('MASSIVE_API_KEY')
if not api_key:
    print("ERROR: MASSIVE_API_KEY not found in environment variables")
    print("Please set it in your .env file:")
    print("  MASSIVE_API_KEY=your_api_key_here")
    exit(1)

print(f"API Key found: {api_key[:8]}...{api_key[-4:]}")

try:
    from massive import RESTClient
    print("Massive library imported successfully")
except ImportError:
    print("ERROR: 'massive' library not installed")
    print("Please run: pip install massive")
    exit(1)

# Initialize client
client = RESTClient(api_key=api_key)
print("RESTClient initialized")

# Test 1: Get stock quote (multiple methods)
print("\n" + "="*50)
print("TEST 1: Get Stock Quote for AAPL")
print("="*50)

# Try get_last_quote
print("\n1a. Trying get_last_quote()...")
try:
    quote = client.get_last_quote("AAPL")
    print(f"  Quote object type: {type(quote)}")
    print(f"  Quote: {quote}")
    
    if hasattr(quote, 'bid_price'):
        print(f"  Bid: ${quote.bid_price}")
    if hasattr(quote, 'ask_price'):
        print(f"  Ask: ${quote.ask_price}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try get_last_trade
print("\n1b. Trying get_last_trade()...")
try:
    trade = client.get_last_trade("AAPL")
    print(f"  Trade object type: {type(trade)}")
    print(f"  Trade: {trade}")
    
    if hasattr(trade, 'price'):
        print(f"  Price: ${trade.price}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try get_previous_close
print("\n1c. Trying get_previous_close()...")
try:
    prev = client.get_previous_close("AAPL")
    print(f"  Previous close object type: {type(prev)}")
    print(f"  Previous close: {prev}")
except Exception as e:
    print(f"  ERROR: {e}")

# Try get_daily_open_close
print("\n1d. Trying get_daily_open_close_agg()...")
try:
    from datetime import datetime, timedelta
    yesterday = (datetime.now().date() - timedelta(days=1)).isoformat()
    daily = client.get_daily_open_close_agg("AAPL", yesterday)
    print(f"  Daily agg object type: {type(daily)}")
    print(f"  Daily agg: {daily}")
    if hasattr(daily, 'close'):
        print(f"  Close: ${daily.close}")
except Exception as e:
    print(f"  ERROR: {e}")

# Check underlying_asset in options snapshot
print("\n1e. Stock price from options underlying_asset...")
print("  (Will test this in options chain section)")

# Test 2: Get options chain snapshot with Greeks
print("\n" + "="*50)
print("TEST 2: Get Options Chain Snapshot for AAPL (PUT options)")
print("="*50)
try:
    from datetime import datetime, timedelta
    
    # Calculate date range (15-45 days out)
    today = datetime.now().date()
    min_date = (today + timedelta(days=15)).isoformat()
    max_date = (today + timedelta(days=45)).isoformat()
    
    # Focus on near-the-money options (AAPL ~$260)
    # This should get us options with actual Greeks populated
    strike_min = 240  # Below current price
    strike_max = 270  # Around current price
    
    print(f"Fetching PUT options expiring between {min_date} and {max_date}")
    print(f"Strike range: ${strike_min} - ${strike_max} (near ATM for better data)")
    
    options_count = 0
    sample_options = []
    options_with_greeks = []
    
    for option in client.list_snapshot_options_chain(
        "AAPL",
        params={
            "expiration_date.gte": min_date,
            "expiration_date.lte": max_date,
            "contract_type": "put",
            "strike_price.gte": strike_min,
            "strike_price.lte": strike_max
        }
    ):
        options_count += 1
        
        # Collect options with actual Greeks
        if hasattr(option, 'greeks') and option.greeks and hasattr(option.greeks, 'delta') and option.greeks.delta is not None:
            options_with_greeks.append(option)
        
        if len(sample_options) < 10:
            sample_options.append(option)
        
        # Only count first 200 to avoid long wait
        if options_count >= 200:
            print(f"  (stopped at 200 for testing, more available)")
            break
    
    print(f"\nFound {options_count}+ PUT options")
    print(f"Options with Greeks populated: {len(options_with_greeks)}")
    
    # Examine structure of first option
    if sample_options:
        print("\n--- Sample Option Structure ---")
        opt = sample_options[0]
        print(f"Option object type: {type(opt)}")
        print(f"Option attributes: {dir(opt)}")
        
        # Try to access common attributes
        print("\n--- Option Details ---")
        if hasattr(opt, 'details'):
            details = opt.details
            print(f"  details type: {type(details)}")
            if hasattr(details, 'strike_price'):
                print(f"  Strike: ${details.strike_price}")
            if hasattr(details, 'expiration_date'):
                print(f"  Expiration: {details.expiration_date}")
            if hasattr(details, 'contract_type'):
                print(f"  Type: {details.contract_type}")
            if hasattr(details, 'ticker'):
                print(f"  Ticker: {details.ticker}")
        
        print("\n--- Greeks ---")
        if hasattr(opt, 'greeks'):
            greeks = opt.greeks
            print(f"  greeks type: {type(greeks)}")
            if greeks:
                if hasattr(greeks, 'delta'):
                    print(f"  Delta: {greeks.delta}")
                if hasattr(greeks, 'gamma'):
                    print(f"  Gamma: {greeks.gamma}")
                if hasattr(greeks, 'theta'):
                    print(f"  Theta: {greeks.theta}")
                if hasattr(greeks, 'vega'):
                    print(f"  Vega: {greeks.vega}")
                if hasattr(greeks, 'rho'):
                    print(f"  Rho: {greeks.rho}")
            else:
                print("  Greeks object is None/empty")
        else:
            print("  No 'greeks' attribute found")
        
        print("\n--- Implied Volatility ---")
        if hasattr(opt, 'implied_volatility'):
            print(f"  IV: {opt.implied_volatility}")
        
        print("\n--- Pricing ---")
        if hasattr(opt, 'last_quote'):
            lq = opt.last_quote
            print(f"  last_quote type: {type(lq)}")
            if lq:
                if hasattr(lq, 'bid'):
                    print(f"  Bid: ${lq.bid}")
                if hasattr(lq, 'ask'):
                    print(f"  Ask: ${lq.ask}")
                if hasattr(lq, 'midpoint'):
                    print(f"  Midpoint: ${lq.midpoint}")
        
        if hasattr(opt, 'last_trade'):
            lt = opt.last_trade
            print(f"  last_trade type: {type(lt)}")
            if lt and hasattr(lt, 'price'):
                print(f"  Last Trade Price: ${lt.price}")
        
        print("\n--- Volume/OI ---")
        if hasattr(opt, 'day'):
            day = opt.day
            if day:
                if hasattr(day, 'volume'):
                    print(f"  Volume: {day.volume}")
                if hasattr(day, 'open_interest'):
                    print(f"  Open Interest: {day.open_interest}")
        
        if hasattr(opt, 'open_interest'):
            print(f"  Open Interest (direct): {opt.open_interest}")
        
        print("\n--- Underlying Asset (Stock Price) ---")
        if hasattr(opt, 'underlying_asset'):
            ua = opt.underlying_asset
            print(f"  underlying_asset type: {type(ua)}")
            if ua:
                if hasattr(ua, 'price'):
                    print(f"  Stock Price: ${ua.price}")
                if hasattr(ua, 'change_to_break_even'):
                    print(f"  Change to Break Even: {ua.change_to_break_even}")
                # Print all attributes
                print(f"  Attributes: {[a for a in dir(ua) if not a.startswith('_')]}")
        
        # Print all sample options summary
        print("\n--- Sample Options Summary (first 10) ---")
        for i, opt in enumerate(sample_options):
            strike = getattr(opt.details, 'strike_price', 'N/A') if hasattr(opt, 'details') else 'N/A'
            exp = getattr(opt.details, 'expiration_date', 'N/A') if hasattr(opt, 'details') else 'N/A'
            delta = getattr(opt.greeks, 'delta', 'N/A') if hasattr(opt, 'greeks') and opt.greeks else 'N/A'
            gamma = getattr(opt.greeks, 'gamma', 'N/A') if hasattr(opt, 'greeks') and opt.greeks else 'N/A'
            theta = getattr(opt.greeks, 'theta', 'N/A') if hasattr(opt, 'greeks') and opt.greeks else 'N/A'
            iv = getattr(opt, 'implied_volatility', 'N/A')
            oi = getattr(opt, 'open_interest', 0)
            
            # Get volume from day
            vol = 0
            if hasattr(opt, 'day') and opt.day:
                vol = getattr(opt.day, 'volume', 0) or 0
            
            # Get price
            price = 'N/A'
            if hasattr(opt, 'last_quote') and opt.last_quote:
                if hasattr(opt.last_quote, 'midpoint') and opt.last_quote.midpoint:
                    price = f"${opt.last_quote.midpoint:.2f}"
                elif hasattr(opt.last_quote, 'bid') and hasattr(opt.last_quote, 'ask'):
                    if opt.last_quote.bid and opt.last_quote.ask:
                        price = f"${(opt.last_quote.bid + opt.last_quote.ask) / 2:.2f}"
            
            print(f"  {i+1}. Strike: ${strike}, Exp: {exp}, Delta: {delta}, IV: {iv}, OI: {oi}, Vol: {vol}, Price: {price}")
        
        # Print options WITH Greeks
        if options_with_greeks:
            print("\n--- Options WITH Greeks Populated ---")
            for i, opt in enumerate(options_with_greeks[:5]):
                strike = getattr(opt.details, 'strike_price', 'N/A') if hasattr(opt, 'details') else 'N/A'
                exp = getattr(opt.details, 'expiration_date', 'N/A') if hasattr(opt, 'details') else 'N/A'
                delta = opt.greeks.delta
                gamma = opt.greeks.gamma
                theta = opt.greeks.theta
                vega = opt.greeks.vega
                iv = getattr(opt, 'implied_volatility', 'N/A')
                
                price = 'N/A'
                if hasattr(opt, 'last_quote') and opt.last_quote:
                    if hasattr(opt.last_quote, 'midpoint') and opt.last_quote.midpoint:
                        price = f"${opt.last_quote.midpoint:.2f}"
                
                print(f"  {i+1}. Strike: ${strike}, Exp: {exp}")
                print(f"      Delta: {delta}, Gamma: {gamma}, Theta: {theta}, Vega: {vega}")
                print(f"      IV: {iv}, Price: {price}")

except Exception as e:
    import traceback
    print(f"ERROR getting options chain: {e}")
    traceback.print_exc()

print("\n" + "="*50)
print("TEST COMPLETE")
print("="*50)
