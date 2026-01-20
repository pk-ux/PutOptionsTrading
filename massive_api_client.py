"""
Massive.com API Client - Wrapper for options screener integration

Hybrid approach:
- Stock prices: Yahoo Finance (real-time)
- Options data + Greeks: Massive.com API (no local calculation needed)
"""

import os
import pandas as pd
import yfinance as yf
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class MassiveAPIClient:
    """
    Massive.com API client wrapper for options screening.
    
    Uses a hybrid approach:
    - Stock prices from Yahoo Finance (real-time)
    - Options Greeks from Massive.com API (delta, gamma, theta, vega, IV)
    """
    
    def __init__(self):
        self.api_key = os.getenv('MASSIVE_API_KEY')
        
        if not self.api_key:
            raise ValueError(
                "MASSIVE_API_KEY not found in environment variables. "
                "Please set it in your .env file."
            )
        
        # Import and initialize the Massive REST client
        try:
            from massive import RESTClient
            self.client = RESTClient(api_key=self.api_key)
            print("Massive.com API client initialized successfully")
        except ImportError:
            raise ImportError(
                "Massive library not installed. "
                "Please run: pip install massive"
            )
    
    def get_stock_price(self, symbol: str) -> Optional[float]:
        """
        Get current stock price using Yahoo Finance (real-time).
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            
        Returns:
            Stock price as float, or None if unavailable
        """
        try:
            print(f"Fetching price for {symbol} from Yahoo Finance (for Massive mode)...")
            stock = yf.Ticker(symbol)
            current_price = stock.info.get('regularMarketPrice', stock.info.get('currentPrice'))
            
            if current_price and current_price > 0:
                print(f"Yahoo Finance price for {symbol}: ${current_price:.2f}")
                return round(current_price, 2)
            else:
                print(f"WARNING: Could not get price for {symbol}")
                return None
                
        except Exception as e:
            print(f"ERROR getting Yahoo price for {symbol}: {str(e)}")
            return None
    
    def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """
        Get stock quote in format compatible with existing code.
        
        Args:
            symbol: Stock ticker symbol
            
        Returns:
            Dictionary with success status and price data
        """
        price = self.get_stock_price(symbol)
        
        if price is not None:
            return {
                'success': True,
                'symbol': symbol,
                'mid_price': price,
                'last_price': price,
                'source': 'yahoo_finance'
            }
        else:
            return {
                'success': False,
                'error': f'Could not get price for {symbol}'
            }
    
    def _get_yahoo_option_prices(self, symbol: str, expirations: list) -> Dict[str, float]:
        """
        Get option prices from Yahoo Finance for given expirations.
        
        Returns a dict mapping (strike, expiry) -> lastPrice
        """
        price_map = {}
        
        try:
            stock = yf.Ticker(symbol)
            
            for exp_date in expirations:
                try:
                    chain = stock.option_chain(exp_date)
                    puts = chain.puts
                    
                    for _, row in puts.iterrows():
                        key = (float(row['strike']), exp_date)
                        price = row.get('lastPrice', 0)
                        if price and price > 0:
                            price_map[key] = float(price)
                except Exception as e:
                    # Skip expirations that fail
                    continue
                    
        except Exception as e:
            print(f"  Warning: Could not get Yahoo prices for {symbol}: {e}")
        
        return price_map
    
    def get_options_chain(self, symbol: str, config: Dict[str, Any]) -> pd.DataFrame:
        """
        Get options chain with Greeks from Massive.com API.
        
        Hybrid approach:
        - Greeks (delta, gamma, theta, vega, IV) from Massive.com API - NO local calculation!
        - Option prices from Yahoo Finance (since Massive basic plan doesn't include quotes)
        
        Args:
            symbol: Stock ticker symbol
            config: Configuration dictionary with options_strategy settings
            
        Returns:
            DataFrame with options data including API-provided Greeks
        """
        try:
            print(f"Fetching options chain for {symbol} from Massive.com (with API Greeks)...")
            
            # Extract DTE range from config
            max_dte = config['options_strategy']['max_dte']
            min_dte = config['options_strategy'].get('min_dte', 0)
            
            # Calculate date range for expiration filtering
            today = datetime.now().date()
            min_exp_date = (today + timedelta(days=min_dte)).isoformat()
            max_exp_date = (today + timedelta(days=max_dte)).isoformat()
            
            print(f"  Expiration range: {min_exp_date} to {max_exp_date} (DTE: {min_dte}-{max_dte})")
            
            # Build request parameters with server-side filtering
            params = {
                "expiration_date.gte": min_exp_date,
                "expiration_date.lte": max_exp_date,
                "contract_type": "put"  # Only get PUT options
            }
            
            # Fetch options chain from Massive - gets Greeks without calculation!
            options_data = []
            options_count = 0
            skipped_no_greeks = 0
            expirations_seen = set()
            
            for option in self.client.list_snapshot_options_chain(symbol, params=params):
                options_count += 1
                
                # Extract option details
                details = option.details if hasattr(option, 'details') else None
                if not details:
                    continue
                
                strike = getattr(details, 'strike_price', None)
                expiration = getattr(details, 'expiration_date', None)
                ticker = getattr(details, 'ticker', '')
                
                if strike is None or expiration is None:
                    continue
                
                # Track expirations for Yahoo price lookup
                expirations_seen.add(str(expiration))
                
                # Calculate DTE
                try:
                    exp_date = datetime.strptime(str(expiration), '%Y-%m-%d').date()
                    dte = (exp_date - today).days
                except:
                    continue
                
                # Extract Greeks directly from API (NO CALCULATION!)
                greeks = option.greeks if hasattr(option, 'greeks') else None
                if not greeks or getattr(greeks, 'delta', None) is None:
                    skipped_no_greeks += 1
                    continue  # Skip options without Greeks
                
                delta = float(greeks.delta)
                gamma = float(greeks.gamma) if greeks.gamma else 0
                theta = float(greeks.theta) if greeks.theta else 0
                vega = float(greeks.vega) if greeks.vega else 0
                rho = float(greeks.rho) if getattr(greeks, 'rho', None) else 0
                
                # Get implied volatility from API
                iv = getattr(option, 'implied_volatility', None)
                if iv is None:
                    continue  # Need IV for screening
                iv = float(iv)
                
                # Get volume and open interest from Massive
                open_interest = getattr(option, 'open_interest', 0) or 0
                
                volume = 0
                if hasattr(option, 'day') and option.day:
                    volume = getattr(option.day, 'volume', 0) or 0
                
                # Build option row (price will be added later from Yahoo)
                option_row = {
                    'symbol': symbol,
                    'strike': float(strike),
                    'expiry': str(expiration),
                    'dte': dte,
                    'volume': int(volume),
                    'open_interest': int(open_interest),
                    'openInterest': int(open_interest),
                    'impliedVolatility': iv,  # From Massive API
                    'delta': delta,            # From Massive API - NOT calculated!
                    'gamma': gamma,            # From Massive API
                    'theta': theta,            # From Massive API
                    'vega': vega,              # From Massive API
                    'rho': rho,                # From Massive API
                    'contract_symbol': ticker
                }
                
                options_data.append(option_row)
            
            if not options_data:
                print(f"No valid options data found for {symbol}")
                return pd.DataFrame()
            
            print(f"  Got {len(options_data)} options with Greeks from Massive")
            print(f"  (Scanned: {options_count}, Skipped without Greeks: {skipped_no_greeks})")
            
            # Now get option prices from Yahoo Finance
            print(f"  Fetching option prices from Yahoo Finance...")
            yahoo_prices = self._get_yahoo_option_prices(symbol, sorted(expirations_seen))
            print(f"  Got prices for {len(yahoo_prices)} options from Yahoo")
            
            # Merge prices into options data
            final_options = []
            matched_count = 0
            
            for opt in options_data:
                key = (opt['strike'], opt['expiry'])
                if key in yahoo_prices:
                    opt['lastPrice'] = yahoo_prices[key]
                    matched_count += 1
                    final_options.append(opt)
                # Skip options without prices (can't calculate returns)
            
            if final_options:
                df = pd.DataFrame(final_options)
                print(f"Retrieved {len(df)} PUT options (Greeks from Massive, prices from Yahoo)")
                return df
            else:
                print(f"No options with matching prices found for {symbol}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"ERROR getting Massive.com options chain for {symbol}: {str(e)}")
            import traceback
            traceback.print_exc()
            return pd.DataFrame()


    def get_ticker_news(self, symbol, limit=10, max_age_days=7):
        """
        Fetch latest news for a ticker from Massive.com API.
        
        Args:
            symbol: Stock ticker symbol (e.g., 'AAPL')
            limit: Number of news items to fetch (default: 10)
            max_age_days: Only include news from last N days (default: 7)
            
        Returns:
            List of news items with title, url, published date, and source
        """
        if not self.client:
            return []
        
        try:
            from datetime import datetime, timedelta, timezone
            cutoff_date = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            
            news_items = []
            for news in self.client.list_ticker_news(symbol, order="desc", limit=limit * 2):  # Fetch more to filter
                # Parse the published date
                published_str = news.published_utc
                try:
                    # Handle ISO format with Z or timezone
                    if isinstance(published_str, str):
                        published_str = published_str.replace('Z', '+00:00')
                        published_date = datetime.fromisoformat(published_str)
                    else:
                        published_date = published_str
                    
                    # Skip news older than max_age_days
                    if published_date < cutoff_date:
                        continue
                    
                    # Format date for display (e.g., "Jan 20")
                    date_display = published_date.strftime("%b %d")
                except:
                    date_display = ""
                
                news_items.append({
                    'title': news.title,
                    'url': news.article_url,
                    'published': news.published_utc,
                    'date_display': date_display,
                    'source': getattr(news.publisher, 'name', '') if hasattr(news, 'publisher') and news.publisher else ''
                })
                
                if len(news_items) >= limit:
                    break
                    
            return news_items
        except Exception as e:
            print(f"Error fetching news for {symbol}: {str(e)}")
            return []


# Global instance for easy import
try:
    massive_client = MassiveAPIClient()
except Exception as e:
    print(f"Failed to initialize Massive.com API client: {str(e)}")
    massive_client = None
