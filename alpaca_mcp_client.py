"""
Alpaca MCP Client - Simplified wrapper for Streamlit integration
Extracts key functionality from the official Alpaca MCP server for our options screener
"""

import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
from typing import Dict, Any, List, Optional, Union
from dotenv import load_dotenv

# Import Alpaca libraries
from alpaca.data.enums import DataFeed, OptionsFeed
from alpaca.data.historical.option import OptionHistoricalDataClient
from alpaca.data.historical.stock import StockHistoricalDataClient
from alpaca.trading.client import TradingClient
from alpaca.data.requests import (
    OptionLatestQuoteRequest,
    OptionSnapshotRequest,
    StockLatestQuoteRequest,
    StockSnapshotRequest,
    OptionChainRequest,
)
from alpaca.trading.requests import GetOptionContractsRequest
from alpaca.trading.enums import ContractType, AssetStatus
from scipy.stats import norm

# Load environment variables
load_dotenv()

class AlpacaMCPClient:
    """
    Simplified MCP client wrapper for Alpaca API integration
    Provides structured access to Alpaca's trading and market data APIs
    """
    
    def __init__(self):
        self.api_key = os.getenv('ALPACA_API_KEY')
        self.secret_key = os.getenv('ALPACA_SECRET_KEY')
        self.paper_trade = os.getenv('ALPACA_PAPER_TRADE', 'True').lower() == 'true'
        
        if not self.api_key or not self.secret_key:
            raise ValueError("Alpaca API credentials not found in environment variables.")
        
        # Initialize clients
        self.trading_client = TradingClient(
            self.api_key, 
            self.secret_key, 
            paper=self.paper_trade
        )
        self.stock_data_client = StockHistoricalDataClient(
            self.api_key, 
            self.secret_key
        )
        self.option_data_client = OptionHistoricalDataClient(
            api_key=self.api_key, 
            secret_key=self.secret_key
        )
        
    def get_account_info(self) -> Dict[str, Any]:
        """Get account information"""
        try:
            account = self.trading_client.get_account()
            return {
                'account_id': str(getattr(account, 'id', 'Unknown')),
                'status': str(getattr(account, 'status', 'Unknown')),
                'currency': str(getattr(account, 'currency', 'USD')),
                'buying_power': float(getattr(account, 'buying_power', 0)),
                'cash': float(getattr(account, 'cash', 0)),
                'portfolio_value': float(getattr(account, 'portfolio_value', 0)),
                'equity': float(getattr(account, 'equity', 0)),
                'paper_trading': self.paper_trade
            }
        except Exception as e:
            return {'error': str(e)}
    
    def get_stock_quote(self, symbol: str) -> Dict[str, Any]:
        """Get latest stock quote using MCP server approach"""
        try:
            request_params = StockLatestQuoteRequest(symbol_or_symbols=symbol)
            quotes = self.stock_data_client.get_stock_latest_quote(request_params)
            
            if symbol in quotes:
                quote = quotes[symbol]
                bid = float(quote.bid_price) if quote.bid_price else 0
                ask = float(quote.ask_price) if quote.ask_price else 0
                mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
                
                return {
                    'symbol': symbol,
                    'bid_price': bid,
                    'ask_price': ask,
                    'mid_price': mid_price,
                    'bid_size': quote.bid_size or 0,
                    'ask_size': quote.ask_size or 0,
                    'timestamp': quote.timestamp,
                    'success': True
                }
            else:
                return {'error': f'No quote data found for {symbol}', 'success': False}
        except Exception as e:
            return {'error': str(e), 'success': False}
    
    def get_option_contracts(self, symbol: str, expiry_start: str, expiry_end: str) -> List[Dict[str, Any]]:
        """Get available PUT option contracts within date range with pagination"""
        try:
            contract_list = []
            page_token = None
            
            # Implement pagination loop to get ALL contracts
            while True:
                request = GetOptionContractsRequest(
                    underlying_symbols=[symbol],  # Pass as list
                    expiration_date_gte=date.fromisoformat(expiry_start),
                    expiration_date_lte=date.fromisoformat(expiry_end),
                    status=AssetStatus.ACTIVE,  # Use enum
                    contract_type=ContractType.PUT,  # Server-side PUT filtering
                    page_token=page_token,  # For pagination
                    limit=1000  # Max per request
                )
                
                contracts_response = self.trading_client.get_option_contracts(request)
                
                contracts = getattr(contracts_response, 'option_contracts', []) or []
                
                for contract in contracts:
                    contract_symbol = getattr(contract, 'symbol', '')
                    if not contract_symbol:
                        continue
                        
                    # Handle multiplier safely
                    multiplier_val = getattr(contract, 'multiplier', 100)
                    if multiplier_val is None:
                        multiplier_val = 100
                    
                    # Handle open interest safely  
                    open_interest_val = getattr(contract, 'open_interest', 0)
                    if open_interest_val is None:
                        open_interest_val = 0
                    
                    # Handle expiration date safely
                    exp_date = getattr(contract, 'expiration_date', date.today())
                    if hasattr(exp_date, 'isoformat'):
                        exp_date_str = exp_date.isoformat()
                    else:
                        exp_date_str = str(exp_date)
                    
                    contract_list.append({
                        'symbol': contract_symbol,
                        'underlying_symbol': getattr(contract, 'underlying_symbol', symbol),
                        'strike_price': float(getattr(contract, 'strike_price', 0)),
                        'contract_type': 'PUT',
                        'expiration_date': exp_date_str,
                        'multiplier': int(multiplier_val),
                        'tradable': getattr(contract, 'tradable', True),
                        'open_interest': int(open_interest_val)
                    })
                
                # Check if there are more pages
                next_page_token = getattr(contracts_response, 'next_page_token', None)
                if not next_page_token:
                    break
                page_token = next_page_token
                print(f"Fetching next page of contracts... (current total: {len(contract_list)})")
            
            print(f"Retrieved {len(contract_list)} PUT contracts total for {symbol}")
            return contract_list
            
        except Exception as e:
            print(f"Error getting option contracts: {str(e)}")
            return []
    
    def get_option_quotes(self, symbols: List[str]) -> Dict[str, Any]:
        """Get option quotes for multiple symbols"""
        try:
            request = OptionLatestQuoteRequest(symbol_or_symbols=symbols)
            quotes_response = self.option_data_client.get_option_latest_quote(request)
            
            quote_data = {}
            # Handle the quotes response which is likely a dict-like object
            quotes = getattr(quotes_response, 'quotes', quotes_response) if hasattr(quotes_response, 'quotes') else quotes_response
            
            if isinstance(quotes, dict):
                for symbol in symbols:
                    if symbol in quotes:
                        quote = quotes[symbol]
                        # Handle the quote object safely
                        bid = float(getattr(quote, 'bid_price', 0) or 0)
                        ask = float(getattr(quote, 'ask_price', 0) or 0)
                        mid_price = (bid + ask) / 2 if bid > 0 and ask > 0 else 0
                        
                        quote_data[symbol] = {
                            'bid_price': bid,
                            'ask_price': ask,
                            'mid_price': mid_price,
                            'bid_size': getattr(quote, 'bid_size', 0) or 0,
                            'ask_size': getattr(quote, 'ask_size', 0) or 0,
                            'timestamp': getattr(quote, 'timestamp', None),
                            'volume': getattr(quote, 'volume', 0) or 0  # Add volume if available
                        }
            
            return {
                'success': len(quote_data) > 0,
                'quotes': quote_data,
                'total_quotes': len(quote_data)
            }
        except Exception as e:
            print(f"Error getting option quotes: {str(e)}")
            return {'success': False, 'error': str(e), 'quotes': {}}
    
    def get_options_chain_data(self, symbol: str, config: Dict[str, Any]) -> pd.DataFrame:
        """
        Get comprehensive options chain data using MCP server approach
        This replaces our manual API calls with structured MCP server functionality
        """
        try:
            print(f"Fetching options data for {symbol} using Alpaca MCP client...")
            
            max_dte = config['options_strategy']['max_dte']
            min_dte = config['options_strategy'].get('min_dte', 0)
            
            # Calculate date range
            base_date = datetime.now().date()
            min_exp_date = (base_date + timedelta(days=min_dte)).isoformat()
            max_exp_date = (base_date + timedelta(days=max_dte)).isoformat()
            
            # Step 1: Get available contracts
            contracts = self.get_option_contracts(symbol, min_exp_date, max_exp_date)
            
            if not contracts:
                print(f"No option contracts found for {symbol}")
                return pd.DataFrame()
            
            print(f"Found {len(contracts)} option contracts for {symbol}")
            
            # Step 2: Get current stock price
            stock_quote = self.get_stock_quote(symbol)
            if not stock_quote.get('success'):
                print(f"Could not get stock price for {symbol}")
                return pd.DataFrame()
            
            current_price = stock_quote['mid_price']
            
            # Step 3: Get option quotes for all contracts
            contract_symbols = [contract['symbol'] for contract in contracts]
            option_quotes = self.get_option_quotes(contract_symbols)
            
            # Step 4: Build options dataframe
            options_data = []
            
            for contract in contracts:
                contract_symbol = contract['symbol']
                
                # Get quote data
                if contract_symbol not in option_quotes:
                    continue
                
                quote = option_quotes[contract_symbol]
                option_price = quote['mid_price']
                
                if option_price <= 0:
                    continue
                
                # Calculate DTE
                exp_date = datetime.fromisoformat(contract['expiration_date']).date()
                dte = (exp_date - base_date).days
                
                if dte <= 0:
                    continue
                
                # Calculate Greeks using Black-Scholes
                strike = contract['strike_price']
                T = dte / 365
                r = 0.05  # Risk-free rate
                
                # Calculate implied volatility using Newton-Raphson
                sigma = self._calculate_implied_volatility(
                    current_price, strike, T, r, option_price, is_put=True
                )
                
                # Calculate delta
                if sigma > 0 and T > 0:
                    d1 = (np.log(current_price/strike) + (r + sigma**2/2)*T) / (sigma*np.sqrt(T))
                    delta = -norm.cdf(-d1)  # Put delta
                else:
                    delta = 0
                
                # Build option data row
                option_row = {
                    'symbol': symbol,
                    'contract_symbol': contract_symbol,
                    'strike': strike,
                    'lastPrice': option_price,
                    'bid': quote['bid_price'],
                    'ask': quote['ask_price'],
                    'volume': 0,  # Not available in basic quotes
                    'open_interest': contract['open_interest'],
                    'openInterest': contract['open_interest'],
                    'impliedVolatility': sigma,
                    'delta': delta,
                    'expiry': contract['expiration_date'],
                    'dte': dte
                }
                
                options_data.append(option_row)
            
            if options_data:
                options_df = pd.DataFrame(options_data)
                print(f"Retrieved {len(options_df)} option contracts with pricing from Alpaca MCP")
                return options_df
            else:
                print(f"No valid options data found for {symbol}")
                return pd.DataFrame()
                
        except Exception as e:
            print(f"Error getting options chain for {symbol}: {str(e)}")
            return pd.DataFrame()
    
    def _calculate_implied_volatility(self, S: float, K: float, T: float, r: float, 
                                    market_price: float, is_put: bool = True) -> float:
        """Calculate implied volatility using Newton-Raphson method"""
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
            price_diff = bs_price - market_price
            if abs(price_diff) < 0.001:
                break
            vega_val = vega(S, K, T, r, sigma)
            if vega_val == 0:
                break
            sigma = sigma - price_diff / vega_val
            sigma = max(0.01, min(sigma, 5.0))  # Keep IV reasonable
        
        return sigma

# Global instance for easy import
alpaca_mcp_client = AlpacaMCPClient()