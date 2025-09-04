import requests
import os
from datetime import datetime, timedelta
import pandas as pd

class PublicAPIClient:
    def __init__(self):
        self.secret = os.getenv('PUBLIC_ACCESS_TOKEN')  # This is actually the secret
        self.account_id = os.getenv('PUBLIC_ACCOUNT_ID')
        self.base_url = 'https://api.public.com/userapigateway'
        self.auth_url = 'https://api.public.com/userapiauthservice/personal/access-tokens'
        self.access_token = None
        self.token_expires_at = None
        
        if not self.secret or not self.account_id:
            raise ValueError("PUBLIC_ACCESS_TOKEN (secret) and PUBLIC_ACCOUNT_ID must be set in environment variables")
        
        # Generate initial access token
        self._generate_access_token()
    
    def _generate_access_token(self):
        """Generate a new JWT access token using the secret"""
        try:
            headers = {'Content-Type': 'application/json'}
            
            request_body = {
                'validityInMinutes': 60,  # 1 hour validity
                'secret': self.secret
            }
            
            response = requests.post(self.auth_url, headers=headers, json=request_body)
            
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get('accessToken')
                # Set expiry time (59 minutes from now to be safe)
                self.token_expires_at = datetime.now() + timedelta(minutes=59)
                print("Public.com access token generated successfully")
                return True
            else:
                print(f"Failed to generate Public.com access token: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"Error generating Public.com access token: {str(e)}")
            return False
    
    def _ensure_valid_token(self):
        """Ensure we have a valid access token, refresh if needed"""
        if not self.access_token or (self.token_expires_at and datetime.now() >= self.token_expires_at):
            print("Public.com token expired or missing, generating new one...")
            return self._generate_access_token()
        return True
    
    def _get_headers(self):
        """Get headers with current valid token"""
        if not self._ensure_valid_token():
            raise Exception("Failed to get valid access token")
        
        return {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def get_stock_quote(self, symbol):
        """Get real-time stock quote from Public.com"""
        try:
            url = f"{self.base_url}/marketdata/{self.account_id}/quotes"
            
            payload = {
                "instruments": [
                    {
                        "symbol": symbol,
                        "type": "EQUITY"
                    }
                ]
            }
            
            print(f"Fetching real-time quote for {symbol} from Public.com...")
            response = requests.post(url, json=payload, headers=self._get_headers())
            
            if response.status_code == 200:
                data = response.json()
                quotes = data.get('quotes', [])
                
                if quotes and quotes[0].get('outcome') == 'SUCCESS':
                    quote = quotes[0]
                    last_price = float(quote.get('last', 0))
                    bid_price = float(quote.get('bid', 0))
                    ask_price = float(quote.get('ask', 0))
                    
                    # Calculate mid price if available
                    if bid_price > 0 and ask_price > 0:
                        mid_price = (bid_price + ask_price) / 2
                    else:
                        mid_price = last_price
                    
                    print(f"Public.com price for {symbol}: ${mid_price:.2f} (Last: ${last_price:.2f}, Bid: ${bid_price:.2f}, Ask: ${ask_price:.2f})")
                    
                    return {
                        'success': True,
                        'symbol': symbol,
                        'last_price': last_price,
                        'bid_price': bid_price,
                        'ask_price': ask_price,
                        'mid_price': mid_price,
                        'volume': quote.get('volume', 0)
                    }
                else:
                    print(f"ERROR: No valid quote data for {symbol} from Public.com")
                    return {'success': False, 'error': 'No valid quote data'}
            else:
                print(f"ERROR: Public.com API request failed with status {response.status_code}: {response.text}")
                return {'success': False, 'error': f'API request failed: {response.status_code}'}
                
        except Exception as e:
            print(f"ERROR: Exception getting Public.com quote for {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_option_expirations(self, symbol):
        """Get available option expiration dates"""
        try:
            url = f"{self.base_url}/marketdata/{self.account_id}/option-expirations"
            
            payload = {
                "instrument": {
                    "symbol": symbol,
                    "type": "EQUITY"
                }
            }
            
            print(f"Fetching option expirations for {symbol} from Public.com...")
            response = requests.post(url, json=payload, headers=self._get_headers())
            
            if response.status_code == 200:
                data = response.json()
                expirations = data.get('expirations', [])
                print(f"Found {len(expirations)} expiration dates for {symbol}")
                return {'success': True, 'expirations': expirations}
            else:
                print(f"ERROR: Failed to get expirations for {symbol}: {response.status_code}")
                return {'success': False, 'error': f'API request failed: {response.status_code}'}
                
        except Exception as e:
            print(f"ERROR: Exception getting expirations for {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_option_chain(self, symbol, expiration_date):
        """Get option chain for specific expiration date"""
        try:
            url = f"{self.base_url}/marketdata/{self.account_id}/option-chain"
            
            payload = {
                "instrument": {
                    "symbol": symbol,
                    "type": "EQUITY"
                },
                "expirationDate": expiration_date
            }
            
            print(f"Fetching option chain for {symbol} expiring {expiration_date} from Public.com...")
            response = requests.post(url, json=payload, headers=self._get_headers())
            
            if response.status_code == 200:
                data = response.json()
                puts = data.get('puts', [])
                calls = data.get('calls', [])
                
                print(f"Found {len(puts)} puts and {len(calls)} calls for {symbol} {expiration_date}")
                
                # Convert to DataFrame format compatible with existing code
                options_data = []
                
                for put in puts:
                    if put.get('outcome') == 'SUCCESS':
                        # Get real Greeks data for this option
                        option_symbol = put['instrument']['symbol']
                        greeks_result = self.get_option_greeks(option_symbol)
                        
                        if greeks_result.get('success'):
                            delta = greeks_result['delta']
                            implied_vol = greeks_result['impliedVolatility']
                            gamma = greeks_result['gamma']
                            theta = greeks_result['theta']
                            vega = greeks_result['vega']
                            rho = greeks_result['rho']
                        else:
                            # Fallback values if Greeks not available
                            delta = -0.5
                            implied_vol = 0.25
                            gamma = 0.0
                            theta = 0.0
                            vega = 0.0
                            rho = 0.0
                        
                        option_data = {
                            'symbol': symbol,
                            'strike': self._extract_strike_from_symbol(option_symbol),
                            'expiry': expiration_date,
                            'lastPrice': float(put.get('last', 0)),
                            'bid': float(put.get('bid', 0)),
                            'ask': float(put.get('ask', 0)),
                            'volume': put.get('volume', 0),
                            'openInterest': put.get('openInterest', 0),
                            'open_interest': put.get('openInterest', 0),
                            'impliedVolatility': float(implied_vol),
                            'delta': float(delta),
                            'gamma': float(gamma),
                            'theta': float(theta),
                            'vega': float(vega),
                            'rho': float(rho),
                            'option_symbol': option_symbol
                        }
                        options_data.append(option_data)
                
                df = pd.DataFrame(options_data)
                print(f"Processed {len(df)} put options for {symbol}")
                return {'success': True, 'options': df}
            else:
                print(f"ERROR: Failed to get option chain for {symbol}: {response.status_code}")
                return {'success': False, 'error': f'API request failed: {response.status_code}'}
                
        except Exception as e:
            print(f"ERROR: Exception getting option chain for {symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def get_option_greeks(self, option_symbol):
        """Get option greeks for a specific option symbol"""
        try:
            url = f"{self.base_url}/option-details/{self.account_id}/{option_symbol}/greeks"
            
            print(f"Fetching greeks for {option_symbol} from Public.com...")
            response = requests.get(url, headers=self._get_headers())
            
            if response.status_code == 200:
                data = response.json()
                return {
                    'success': True,
                    'delta': float(data.get('delta', 0)),
                    'gamma': float(data.get('gamma', 0)),
                    'theta': float(data.get('theta', 0)),
                    'vega': float(data.get('vega', 0)),
                    'rho': float(data.get('rho', 0)),
                    'impliedVolatility': float(data.get('impliedVolatility', 0))
                }
            else:
                print(f"ERROR: Failed to get greeks for {option_symbol}: {response.status_code}")
                return {'success': False, 'error': f'API request failed: {response.status_code}'}
                
        except Exception as e:
            print(f"ERROR: Exception getting greeks for {option_symbol}: {str(e)}")
            return {'success': False, 'error': str(e)}
    
    def _extract_strike_from_symbol(self, option_symbol):
        """Extract strike price from OSI option symbol"""
        try:
            # OSI format: AAPL230317P00150000 (last 8 digits / 1000 = strike)
            strike_part = option_symbol[-8:]
            strike = float(strike_part) / 1000
            return strike
        except:
            return 0.0

# Create global client instance
try:
    public_client = PublicAPIClient()
    print("Public.com API client initialized successfully")
except Exception as e:
    print(f"Failed to initialize Public.com API client: {str(e)}")
    public_client = None