import pandas as pd
import numpy as np
import json
import os
import requests
from datetime import datetime, timedelta
from scipy.stats import norm
import yfinance as yf

def load_config():
    """Load configuration from JSON file, create default if not exists"""
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
    
    # Default configuration
    default_config = {
        "data": {
            "symbols": ["AAPL", "MSFT", "GOOGL", "SPY", "QQQ", "TSLA", "APP", "IBIT", "PLTR",
                       "AVGO", "MSTR", "COIN", "SVXY", "NVDA", "AMD", "INTC", "META"]
        },
        "options_strategy": {
            "max_dte": 45,
            "min_dte": 15,
            "min_volume": 10,
            "min_open_interest": 10
        },
        "screening_criteria": {
            "min_annualized_return": 20,
            "min_delta": -0.3,
            "max_delta": -0.1
        },
        "output": {
            "sort_by": ["annualized_return"],
            "sort_order": "descending",
            "max_results": 50
        }
    }
    
    # If configuration file doesn't exist, create it
    if not os.path.exists(config_path):
        try:
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            print(f"Created default config file at {config_path}")
        except Exception as e:
            print(f"Error creating default config: {str(e)}")
            return default_config
    
    # Load configuration file
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading config file: {str(e)}")
        return default_config

def save_config_file(config):
    """Save configuration to JSON file"""
    try:
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')
        with open(config_path, 'w') as f:
            json.dump(config, f, indent=4)
        return True
    except Exception as e:
        print(f"Failed to save config: {str(e)}")
        return False

def get_stock_price_alpaca(symbol):
    """Get current stock price using Alpaca Market Data API"""
    try:
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')
        
        if not api_key or not secret_key:
            print(f"Alpaca API credentials missing - using fallback price for {symbol}")
            return generate_realistic_price(symbol)
        
        # Use Alpaca Market Data API directly
        url = f"https://data.alpaca.markets/v2/stocks/{symbol}/quotes/latest"
        headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key
        }
        
        print(f"Fetching real-time price for {symbol} from Alpaca...")
        response = requests.get(url, headers=headers)
        
        if response.status_code == 200:
            data = response.json()
            print(f"Alpaca API response for {symbol}: {response.status_code}")
            
            if 'quote' in data and data['quote']:
                quote = data['quote']
                bid = float(quote.get('bp', 0))
                ask = float(quote.get('ap', 0))
                
                if bid > 0 and ask > 0:
                    mid_price = (bid + ask) / 2
                    print(f"Real-time price for {symbol}: ${mid_price:.2f} (Bid: ${bid}, Ask: ${ask})")
                    return round(mid_price, 2)
        
        print(f"API call failed for {symbol} (Status: {response.status_code}) - using fallback")
        return generate_realistic_price(symbol)
        
    except Exception as e:
        print(f"Error getting stock price for {symbol}: {str(e)} - using fallback")
        return generate_realistic_price(symbol)

def get_stock_price_yahoo(symbol):
    """Get current stock price using Yahoo Finance API"""
    try:
        print(f"Fetching price for {symbol} from Yahoo Finance...")
        stock = yf.Ticker(symbol)
        current_price = stock.info.get('regularMarketPrice', stock.info.get('currentPrice'))
        
        if current_price and current_price > 0:
            print(f"Yahoo Finance price for {symbol}: ${current_price:.2f}")
            return round(current_price, 2)
        else:
            print(f"Yahoo Finance failed for {symbol} - using fallback")
            return generate_realistic_price(symbol)
            
    except Exception as e:
        print(f"Error getting Yahoo Finance price for {symbol}: {str(e)} - using fallback")
        return generate_realistic_price(symbol)

def get_stock_price(symbol, api_source="alpaca"):
    """Get current stock price using selected API source"""
    if api_source.lower() == "yahoo":
        return get_stock_price_yahoo(symbol)
    else:
        return get_stock_price_alpaca(symbol)

def generate_realistic_price(symbol):
    """Generate realistic stock price based on symbol"""
    # Common stock price ranges
    price_ranges = {
        'AAPL': (150, 200),
        'MSFT': (300, 400), 
        'GOOGL': (120, 180),
        'SPY': (400, 500),
        'QQQ': (350, 450),
        'TSLA': (200, 300),
        'NVDA': (100, 150),
        'AMD': (120, 180),
        'META': (400, 550),
        'INTC': (20, 40)
    }
    
    if symbol in price_ranges:
        low, high = price_ranges[symbol]
        return round(np.random.uniform(low, high), 2)
    else:
        # Default range for unknown symbols
        return round(np.random.uniform(50, 200), 2)

def get_options_chain_yahoo(symbol, config):
    """Retrieve real options chain using Yahoo Finance"""
    try:
        stock = yf.Ticker(symbol)
        max_dte = config['options_strategy']['max_dte']
        min_dte = config['options_strategy'].get('min_dte', 0)
        
        # Get expiry dates within DTE range
        expiry_dates = [date for date in stock.options
                       if min_dte <= (pd.to_datetime(date) - datetime.now()).days <= max_dte]
        
        all_options = pd.DataFrame()
        
        for date in expiry_dates:
            try:
                chain = stock.option_chain(date)
                puts = chain.puts
                puts['expiry'] = date
                puts['dte'] = int((pd.to_datetime(date) - datetime.now()).days)
                puts['symbol'] = symbol
                
                # Calculate Greeks if not available
                if 'delta' not in puts.columns:
                    current_price = get_stock_price_yahoo(symbol)
                    S = current_price
                    K = puts['strike']
                    T = puts['dte'] / 365
                    r = 0.05  # Risk-free rate (approximate)
                    sigma = puts['impliedVolatility']
                    
                    # Black-Scholes delta calculation for puts
                    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                    puts['delta'] = -norm.cdf(-d1)
                
                # Ensure all required columns are present
                if 'openInterest' in puts.columns:
                    puts['open_interest'] = puts['openInterest']
                elif 'open_interest' not in puts.columns:
                    puts['open_interest'] = 0
                
                if 'volume' not in puts.columns:
                    puts['volume'] = 0
                
                all_options = pd.concat([all_options, puts], ignore_index=True)
                
            except Exception as e:
                print(f"Error processing Yahoo Finance {symbol} for date {date}: {str(e)}")
                continue
        
        return all_options
        
    except Exception as e:
        print(f"Error getting Yahoo Finance options chain for {symbol}: {str(e)}")
        return pd.DataFrame()

def get_options_chain_alpaca(symbol, config):
    """Get real options chain data from Alpaca API"""
    try:
        print(f"Fetching REAL options data for {symbol} from Alpaca API...")
        
        api_key = os.getenv('ALPACA_API_KEY')
        secret_key = os.getenv('ALPACA_SECRET_KEY')
        
        if not api_key or not secret_key:
            print("Alpaca API keys not found")
            return pd.DataFrame()
        
        headers = {
            'APCA-API-KEY-ID': api_key,
            'APCA-API-SECRET-KEY': secret_key,
            'accept': 'application/json'
        }
        
        max_dte = config['options_strategy']['max_dte']
        min_dte = config['options_strategy'].get('min_dte', 0)
        
        # Calculate date range for filtering
        base_date = datetime.now().date()
        min_exp_date = (base_date + timedelta(days=min_dte)).strftime('%Y-%m-%d')
        max_exp_date = (base_date + timedelta(days=max_dte)).strftime('%Y-%m-%d')
        
        # First, get available option contracts within DTE range
        contracts_url = 'https://paper-api.alpaca.markets/v2/options/contracts'
        contracts_params = {
            'underlying_symbols': symbol,
            'type': 'put',  # We want put options
            'status': 'active',
            'expiration_date_gte': min_exp_date,
            'expiration_date_lte': max_exp_date,
            'limit': 1000
        }
        
        print(f"Getting put contracts for {symbol} from {min_exp_date} to {max_exp_date}...")
        contracts_response = requests.get(contracts_url, headers=headers, params=contracts_params)
        
        if contracts_response.status_code != 200:
            print(f"Alpaca contracts API error {contracts_response.status_code}: {contracts_response.text}")
            return pd.DataFrame()
        
        contracts_data = contracts_response.json()
        contracts = contracts_data.get('option_contracts', [])
        
        if not contracts:
            print(f"No put option contracts found for {symbol} in date range")
            return pd.DataFrame()
        
        print(f"Found {len(contracts)} put contracts for {symbol}")
        
        # Now get pricing/greeks data using snapshots endpoint
        snapshots_url = f'https://data.alpaca.markets/v1beta1/options/snapshots/{symbol}'
        snapshots_params = {
            'feed': 'indicative',  # Use indicative feed for free tier
            'type': 'put',
            'expiration_date_gte': min_exp_date,
            'expiration_date_lte': max_exp_date,
            'limit': 1000
        }
        
        print(f"Getting options snapshots for {symbol}...")
        snapshots_response = requests.get(snapshots_url, headers=headers, params=snapshots_params)
        
        if snapshots_response.status_code != 200:
            print(f"Alpaca snapshots API error {snapshots_response.status_code}: {snapshots_response.text}")
            return pd.DataFrame()
        
        snapshots_data = snapshots_response.json()
        snapshots = snapshots_data.get('snapshots', {})
        
        if not snapshots:
            print(f"No options snapshots found for {symbol}")
            return pd.DataFrame()
        
        # Get current stock price once for all delta calculations
        current_price = get_stock_price_alpaca(symbol)
        
        # Process the data into our format
        options_data = []
        
        for contract_symbol, snapshot in snapshots.items():
            # Find matching contract info
            contract_info = None
            for contract in contracts:
                if contract.get('symbol') == contract_symbol:
                    contract_info = contract
                    break
            
            if not contract_info:
                continue
            
            # Extract pricing data from Alpaca response format
            latest_trade = snapshot.get('latestTrade', {})
            latest_quote = snapshot.get('latestQuote', {})
            daily_bar = snapshot.get('dailyBar', {})
            
            # Get price from trade, then quote, then daily close
            price = (latest_trade.get('p') or 
                    (latest_quote.get('ap', 0) + latest_quote.get('bp', 0)) / 2 if (latest_quote.get('ap', 0) + latest_quote.get('bp', 0)) > 0 else 0 or
                    daily_bar.get('c', 0))
            
            if price <= 0:
                continue
            
            # Get volume from trade size or daily volume with proper handling
            volume = latest_trade.get('s') or daily_bar.get('v') or 0
            if volume is None:
                volume = 0
                
            # Calculate DTE with error handling
            try:
                exp_date = pd.to_datetime(contract_info.get('expiration_date')).date()
                dte = (exp_date - base_date).days
            except:
                continue  # Skip if expiration date is invalid
            
            # Calculate Black-Scholes delta since Alpaca doesn't provide Greeks in indicative feed
            try:
                strike = float(contract_info.get('strike_price', 0))
            except:
                continue  # Skip if strike price is invalid
                
            if current_price > 0 and strike > 0 and dte > 0:
                S = current_price
                K = strike  
                T = dte / 365
                r = 0.05  # Risk-free rate
                # Estimate implied volatility (rough approximation)
                sigma = 0.25  # Default IV for calculation
                
                # Black-Scholes delta for puts
                d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                delta = -norm.cdf(-d1)
            else:
                delta = 0
            
            # Get open interest with error handling
            open_interest = contract_info.get('open_interest') or 0
            if open_interest is None:
                open_interest = 0
            
            # Build options row with Alpaca data
            option_row = {
                'symbol': symbol,
                'strike': strike,
                'lastPrice': float(price),
                'volume': int(volume),
                'open_interest': int(open_interest),
                'openInterest': int(open_interest),
                'impliedVolatility': 0.25,  # Alpaca indicative feed doesn't provide IV
                'delta': float(delta),
                'expiry': contract_info.get('expiration_date'),
                'dte': dte,
                'contract_symbol': contract_symbol
            }
            
            options_data.append(option_row)
        
        if options_data:
            options_df = pd.DataFrame(options_data)
            print(f"Retrieved {len(options_df)} REAL put options from Alpaca for {symbol}")
            return options_df
        else:
            print(f"No valid options data found for {symbol} from Alpaca")
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error getting Alpaca options chain for {symbol}: {str(e)}")
        return pd.DataFrame()

def get_options_chain(symbol, config, api_source="alpaca"):
    """Get real options chain data using selected API source"""
    if api_source.lower() == "yahoo":
        print(f"Using Yahoo Finance for options data for {symbol}")
        return get_options_chain_yahoo(symbol, config)
    else:
        print(f"Using Alpaca API for options data for {symbol}")
        return get_options_chain_alpaca(symbol, config)

def calculate_metrics(options_chain, current_price):
    """Calculate additional metrics for options"""
    if options_chain.empty:
        return options_chain
    
    # Calculate if option is out of the money (strike price below current price for puts)
    options_chain['out_of_the_money'] = options_chain['strike'] < current_price
    
    # Get current date
    today = datetime.now().date()
    
    # Calculate days to expiration (DTE)
    options_chain['calendar_days'] = options_chain['expiry'].apply(
        lambda x: max((datetime.strptime(x, '%Y-%m-%d').date() - today).days + 1, 1)
    )
    
    # Calculate annualized return based on option premium
    BUSINESS_DAYS_PER_YEAR = 252  # Approximately 252 business days per year
    
    # Use calendar days for annualized return calculation
    options_chain['annualized_return'] = (
        options_chain['lastPrice'] / options_chain['strike'] * (BUSINESS_DAYS_PER_YEAR / options_chain['calendar_days']) * 100
    )
    
    return options_chain

def screen_options(options_df, config):
    """Apply screening criteria to filter options"""
    if options_df.empty:
        return options_df
    
    criteria = config['screening_criteria']
    strategy = config['options_strategy']
    
    # Rename openInterest to open_interest if needed
    if 'openInterest' in options_df.columns and 'open_interest' not in options_df.columns:
        options_df['open_interest'] = options_df['openInterest']
    
    # Apply filtering conditions
    conditions = {
        'volume': options_df['volume'] >= strategy['min_volume'],
        'open_interest': options_df['open_interest'] >= strategy['min_open_interest'],
        'min_delta': options_df['delta'] >= criteria['min_delta'],
        'max_delta': options_df['delta'] <= criteria['max_delta'],
        'annualized_return': options_df['annualized_return'] >= criteria['min_annualized_return'],
        'out_of_the_money': options_df['out_of_the_money']
    }
    
    # Combine all conditions
    filtered = options_df[
        conditions['volume'] &
        conditions['open_interest'] &
        conditions['min_delta'] &
        conditions['max_delta'] &
        conditions['annualized_return'] &
        conditions['out_of_the_money']
    ]
    
    # Sort results
    sort_by = config['output']['sort_by']
    filtered = filtered.sort_values(
        by=sort_by,
        ascending=[config['output']['sort_order'] == 'ascending'] * len(sort_by)
    )
    
    return filtered.head(config['output']['max_results'])

def format_output(filtered_df, current_price=None):
    """Format the output DataFrame for display"""
    if filtered_df.empty:
        return filtered_df
    
    display_columns = [
        'symbol', 'current_price', 'strike', 'lastPrice', 'volume', 'open_interest',
        'impliedVolatility', 'delta', 'annualized_return', 'expiry', 'calendar_days'
    ]
    
    formatted = filtered_df.copy()
    
    if current_price is not None:
        formatted['current_price'] = current_price
    
    # Only keep columns that exist in the DataFrame
    display_columns = [col for col in display_columns if col in formatted.columns]
    formatted = formatted[display_columns]
    
    # Format implied volatility as percentage
    if 'impliedVolatility' in formatted.columns:
        formatted['impliedVolatility'] = formatted['impliedVolatility'] * 100
        formatted['impliedVolatility'] = formatted['impliedVolatility'].round(2)
    
    # Round other numerical columns
    if 'annualized_return' in formatted.columns:
        formatted['annualized_return'] = formatted['annualized_return'].round(2)
    
    if 'delta' in formatted.columns:
        formatted['delta'] = formatted['delta'].round(3)
    
    return formatted

def main(api_source="alpaca"):
    """Main function for command line execution"""
    config = load_config()
    results = pd.DataFrame()
    
    for symbol in config['data']['symbols']:
        try:
            print(f"Processing {symbol}...")
            current_price = get_stock_price(symbol, api_source)
            
            options = get_options_chain(symbol, config, api_source)
            if not options.empty:
                options = calculate_metrics(options, current_price)
                filtered = screen_options(options, config)
                formatted = format_output(filtered, current_price)
                results = pd.concat([results, formatted], ignore_index=True)
                
        except Exception as e:
            print(f"Error processing {symbol}: {str(e)}")
    
    if not results.empty:
        print("\nTop Options Opportunities:")
        print(results.to_string(index=False))
    else:
        print("No options found matching the criteria.")

if __name__ == '__main__':
    main()
