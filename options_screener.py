import pandas as pd
import numpy as np
import json
import os
import requests
from datetime import datetime, timedelta
from scipy.stats import norm
import yfinance as yf
from alpaca_mcp_client import alpaca_mcp_client
from public_api_client import public_client

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
    """Get current stock price using Alpaca MCP Client"""
    try:
        print(f"Fetching real-time price for {symbol} from Alpaca MCP...")
        quote = alpaca_mcp_client.get_stock_quote(symbol)
        
        if quote.get('success') and quote.get('mid_price', 0) > 0:
            mid_price = quote['mid_price']
            bid = quote.get('bid_price', 0)
            ask = quote.get('ask_price', 0)
            print(f"Real-time price for {symbol}: ${mid_price:.2f} (Bid: ${bid:.2f}, Ask: ${ask:.2f})")
            return round(mid_price, 2)
        else:
            error_msg = quote.get('error', 'Unknown error')
            print(f"ERROR: Failed to get real price for {symbol}: {error_msg}")
            return None  # Return None instead of synthetic data
        
    except Exception as e:
        print(f"ERROR: Exception getting stock price for {symbol}: {str(e)}")
        return None  # Return None instead of synthetic data

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

def get_stock_price_public(symbol):
    """Get current stock price using Public.com API"""
    try:
        if not public_client:
            print(f"Public.com client not available for {symbol}")
            return None
            
        quote = public_client.get_stock_quote(symbol)
        
        if quote.get('success') and quote.get('mid_price', 0) > 0:
            return round(quote['mid_price'], 2)
        else:
            error_msg = quote.get('error', 'Unknown error')
            print(f"ERROR: Failed to get Public.com price for {symbol}: {error_msg}")
            return None
        
    except Exception as e:
        print(f"ERROR: Exception getting Public.com price for {symbol}: {str(e)}")
        return None

def get_stock_price(symbol, api_source="alpaca"):
    """Get current stock price using selected API source"""
    if api_source.lower() == "yahoo":
        return get_stock_price_yahoo(symbol)
    elif api_source.lower() == "public":
        return get_stock_price_public(symbol)
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
    """Get real options chain data using Alpaca MCP Client"""
    try:
        print(f"Fetching REAL options data for {symbol} from Alpaca MCP...")
        
        max_dte = config['options_strategy']['max_dte']
        min_dte = config['options_strategy'].get('min_dte', 0)
        
        # Calculate date range for filtering
        base_date = datetime.now().date()
        min_exp_date = (base_date + timedelta(days=min_dte)).strftime('%Y-%m-%d')
        max_exp_date = (base_date + timedelta(days=max_dte)).strftime('%Y-%m-%d')
        
        # Get option contracts using MCP client
        print(f"Getting put contracts for {symbol} from {min_exp_date} to {max_exp_date}...")
        contracts = alpaca_mcp_client.get_option_contracts(symbol, min_exp_date, max_exp_date)
        
        if not contracts:
            print(f"No put option contracts found for {symbol} in date range")
            return pd.DataFrame()
        
        print(f"Found {len(contracts)} put contracts for {symbol}")
        
        # Extract contract symbols for pricing lookup
        contract_symbols = [contract['symbol'] for contract in contracts]
        
        # Get option quotes using MCP client
        print(f"Getting options pricing for {len(contract_symbols)} contracts...")
        quotes_response = alpaca_mcp_client.get_option_quotes(contract_symbols)
        
        if not quotes_response.get('success') or not quotes_response.get('quotes'):
            print(f"No options quotes found for {symbol}")
            return pd.DataFrame()
        
        quotes = quotes_response['quotes']
        
        # Get current stock price for calculations
        current_price = get_stock_price_alpaca(symbol)
        if current_price is None:
            print(f"ERROR: Cannot get stock price for {symbol} - skipping options chain")
            return pd.DataFrame()
        
        # Process the data into our format
        options_data = []
        
        for contract in contracts:
            contract_symbol = contract['symbol']
            quote = quotes.get(contract_symbol, {})
            
            if not quote:
                continue
                
            # Extract pricing data
            price = quote.get('mid_price', 0)
            if price <= 0:
                continue
            
            # Calculate DTE
            try:
                exp_date = pd.to_datetime(contract['expiration_date']).date()
                dte = (exp_date - base_date).days
            except:
                continue  # Skip if expiration date is invalid
            
            # Get strike price
            try:
                strike = float(contract['strike_price'])
            except:
                continue  # Skip if strike price is invalid
                
            # Calculate implied volatility and delta using Black-Scholes
            if current_price > 0 and strike > 0 and dte > 0 and price > 0:
                S = current_price
                K = strike  
                T = dte / 365
                r = 0.05  # Risk-free rate
                
                # Calculate implied volatility using Newton-Raphson method
                def black_scholes_put(S, K, T, r, sigma):
                    if sigma <= 0 or T <= 0:
                        return 0
                    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                    d2 = d1 - sigma*np.sqrt(T)
                    put_price = K * np.exp(-r*T) * norm.cdf(-d2) - S * norm.cdf(-d1)
                    return max(put_price, 0)
                
                def vega(S, K, T, r, sigma):
                    if sigma <= 0 or T <= 0:
                        return 0
                    d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                    return S * np.sqrt(T) * norm.pdf(d1)
                
                # Newton-Raphson to find implied volatility
                sigma = 0.3  # Initial guess
                for i in range(20):  # Max iterations
                    bs_price = black_scholes_put(S, K, T, r, sigma)
                    price_diff = bs_price - price
                    if abs(price_diff) < 0.001:
                        break
                    vega_val = vega(S, K, T, r, sigma)
                    if vega_val == 0:
                        break
                    sigma = sigma - price_diff / vega_val
                    sigma = max(0.01, min(sigma, 5.0))  # Keep IV reasonable
                
                # Calculate delta using the calculated IV
                d1 = (np.log(S/K) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                delta = -norm.cdf(-d1)
                
                implied_vol = sigma
            else:
                delta = 0
                implied_vol = 0
            
            # Build options row with MCP data
            option_row = {
                'symbol': symbol,
                'strike': strike,
                'lastPrice': float(price),
                'volume': int(quote.get('volume', 0)),
                'open_interest': int(contract.get('open_interest', 0)),
                'openInterest': int(contract.get('open_interest', 0)),
                'impliedVolatility': float(implied_vol),  # Calculated real IV from option prices
                'delta': float(delta),
                'expiry': contract['expiration_date'],
                'dte': dte,
                'contract_symbol': contract_symbol
            }
            
            options_data.append(option_row)
        
        if options_data:
            options_df = pd.DataFrame(options_data)
            print(f"Retrieved {len(options_df)} REAL put options from Alpaca MCP for {symbol}")
            return options_df
        else:
            print(f"No valid options data found for {symbol} from Alpaca MCP")
            return pd.DataFrame()
            
    except Exception as e:
        print(f"Error getting Alpaca MCP options chain for {symbol}: {str(e)}")
        return pd.DataFrame()

def get_options_chain_public(symbol, config):
    """Get real options chain data using Public.com API"""
    try:
        if not public_client:
            print(f"Public.com client not available for {symbol}")
            return pd.DataFrame()
            
        print(f"Fetching REAL options data for {symbol} from Public.com...")
        
        max_dte = config['options_strategy']['max_dte']
        min_dte = config['options_strategy'].get('min_dte', 0)
        
        # Get available expiration dates
        exp_result = public_client.get_option_expirations(symbol)
        if not exp_result.get('success'):
            print(f"Failed to get expirations for {symbol}: {exp_result.get('error')}")
            return pd.DataFrame()
        
        # Filter expirations by DTE range
        expirations = exp_result['expirations']
        today = datetime.now().date()
        
        valid_expirations = []
        for exp_date_str in expirations:
            exp_date = datetime.strptime(exp_date_str, '%Y-%m-%d').date()
            dte = (exp_date - today).days
            if min_dte <= dte <= max_dte:
                valid_expirations.append(exp_date_str)
        
        print(f"Found {len(valid_expirations)} valid expirations for {symbol} (DTE: {min_dte}-{max_dte})")
        
        if not valid_expirations:
            print(f"No expirations found for {symbol} in DTE range {min_dte}-{max_dte}")
            return pd.DataFrame()
        
        # Get option chains for each valid expiration
        all_options = pd.DataFrame()
        
        for exp_date in valid_expirations:
            try:
                chain_result = public_client.get_option_chain(symbol, exp_date)
                
                if chain_result.get('success') and not chain_result['options'].empty:
                    options_df = chain_result['options']
                    
                    # Calculate DTE
                    exp_date_dt = datetime.strptime(exp_date, '%Y-%m-%d').date()
                    options_df['calendar_days'] = (exp_date_dt - today).days
                    
                    all_options = pd.concat([all_options, options_df], ignore_index=True)
                    print(f"Retrieved {len(options_df)} put options for {symbol} {exp_date}")
                else:
                    print(f"No options data for {symbol} {exp_date}")
                    
            except Exception as e:
                print(f"Error processing {symbol} for date {exp_date}: {str(e)}")
                continue
        
        if not all_options.empty:
            print(f"Retrieved {len(all_options)} REAL put options from Public.com for {symbol}")
        else:
            print(f"No options data found for {symbol}")
            
        return all_options
        
    except Exception as e:
        print(f"Error getting Public.com options chain for {symbol}: {str(e)}")
        return pd.DataFrame()

def get_options_chain(symbol, config, api_source="alpaca"):
    """Get real options chain data using selected API source"""
    if api_source.lower() == "yahoo":
        print(f"Using Yahoo Finance for options data for {symbol}")
        return get_options_chain_yahoo(symbol, config)
    elif api_source.lower() == "public":
        print(f"Using Public.com for options data for {symbol}")
        return get_options_chain_public(symbol, config)
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
