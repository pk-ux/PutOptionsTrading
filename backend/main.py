"""
Put Options Screener - FastAPI Backend
=======================================
Provides REST API for the options screener with:
- Clerk JWT authentication
- Stripe billing integration
- Usage limits for free tier
- PostgreSQL database for user management
"""

import os
import sys
import hashlib
import secrets
from datetime import datetime, date, timedelta
from typing import Optional, List
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import jwt
import stripe
import httpx
from dotenv import load_dotenv

# Add parent directory to path to import screener modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, Column, String, Integer, Float, Date, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session, relationship
import uuid
import json

# Load environment variables
load_dotenv()

# Load default config from config.json
def load_default_config():
    """Load default settings from config.json"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.json')
    try:
        with open(config_path, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Could not load config.json: {e}")
        return None

DEFAULT_CONFIG = load_default_config()

# =============================================================================
# Configuration
# =============================================================================

DATABASE_URL = os.getenv("DATABASE_URL", "")
CLERK_SECRET_KEY = os.getenv("CLERK_SECRET_KEY", "")
CLERK_PUBLISHABLE_KEY = os.getenv("CLERK_PUBLISHABLE_KEY", "")
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID = os.getenv("STRIPE_PRICE_ID", "")
MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")

# Initialize Stripe
if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

# Free tier limits
FREE_SCREENS_PER_DAY = 5
FREE_MAX_SYMBOLS = 5
PRO_MAX_SYMBOLS = 50

# =============================================================================
# Database Setup
# =============================================================================

Base = declarative_base()

class User(Base):
    """User model for database"""
    __tablename__ = "users"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    clerk_user_id = Column(String(255), unique=True, nullable=False)
    email = Column(String(255), unique=True)
    password_hash = Column(String(255))  # For simple email/password auth
    subscription_status = Column(String(20), default="free")  # free, pro, cancelled
    stripe_customer_id = Column(String(255))
    screens_today = Column(Integer, default=0)
    last_screen_date = Column(Date)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationship to settings
    settings = relationship("UserSettings", back_populates="user", uselist=False)


class UserSettings(Base):
    """User settings model for database"""
    __tablename__ = "user_settings"
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(36), ForeignKey("users.id"), unique=True, nullable=False)
    
    # Watchlist
    symbols = Column(Text, default="AAPL,MSFT,GOOGL,SPY,QQQ")  # Comma-separated
    
    # Options strategy
    max_dte = Column(Integer, default=45)
    min_dte = Column(Integer, default=15)
    min_volume = Column(Integer, default=10)
    min_open_interest = Column(Integer, default=10)
    
    # Screening criteria
    min_annualized_return = Column(Float, default=20.0)
    max_assignment_probability = Column(Integer, default=20)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationship to user
    user = relationship("User", back_populates="settings")


# Database session management
engine = None
SessionLocal = None

def get_db():
    """Get database session"""
    if SessionLocal is None:
        raise HTTPException(status_code=503, detail="Database not configured")
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Initialize database connection and create tables"""
    global engine, SessionLocal
    
    if not DATABASE_URL:
        print("WARNING: DATABASE_URL not set. Database features disabled.")
        return False
    
    try:
        # Handle Railway's postgres:// vs postgresql://
        db_url = DATABASE_URL
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        
        # SQLite needs check_same_thread=False for FastAPI
        if db_url.startswith("sqlite"):
            engine = create_engine(db_url, connect_args={"check_same_thread": False})
        else:
            engine = create_engine(db_url)
        
        SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
        
        # Create tables
        Base.metadata.create_all(bind=engine)
        print(f"Database initialized successfully: {db_url.split('@')[-1] if '@' in db_url else db_url}")
        return True
    except Exception as e:
        print(f"Database initialization failed: {e}")
        return False


# =============================================================================
# Pydantic Models (Request/Response)
# =============================================================================

class ScreenRequest(BaseModel):
    """Request model for screening options"""
    symbols: List[str]
    max_dte: int = 45
    min_dte: int = 15
    min_volume: int = 10
    min_open_interest: int = 10
    min_annualized_return: float = 20.0
    max_assignment_probability: int = 20


class ScreenResult(BaseModel):
    """Single option result"""
    symbol: str
    current_price: float
    strike: float
    premium: float
    volume: int
    open_interest: int
    implied_volatility: float
    delta: float
    annualized_return: float
    expiry: str
    dte: int


class ScreenResponse(BaseModel):
    """Response model for screening"""
    success: bool
    results: dict  # symbol -> list of options
    screens_remaining: Optional[int] = None
    used_yahoo_fallback: bool = False
    message: str = ""


class CheckoutRequest(BaseModel):
    """Request for Stripe checkout"""
    success_url: str
    cancel_url: str


class CheckoutResponse(BaseModel):
    """Response with Stripe checkout URL"""
    checkout_url: str


class UserInfo(BaseModel):
    """User information response"""
    email: str
    subscription_status: str
    screens_today: int
    screens_remaining: int
    settings: Optional["UserSettingsModel"] = None


class UserSettingsModel(BaseModel):
    """User settings model"""
    symbols: List[str] = ["AAPL", "MSFT", "GOOGL", "SPY", "QQQ"]
    max_dte: int = 45
    min_dte: int = 15
    min_volume: int = 10
    min_open_interest: int = 10
    min_annualized_return: float = 20.0
    max_assignment_probability: int = 20


class UserSettingsUpdate(BaseModel):
    """Request to update user settings"""
    symbols: Optional[List[str]] = None
    max_dte: Optional[int] = None
    min_dte: Optional[int] = None
    min_volume: Optional[int] = None
    min_open_interest: Optional[int] = None
    min_annualized_return: Optional[float] = None
    max_assignment_probability: Optional[int] = None


class AuthRequest(BaseModel):
    """Login/Signup request"""
    email: str
    password: str


class AuthResponse(BaseModel):
    """Login/Signup response"""
    token: str
    email: str
    subscription_status: str


# JWT Secret for our own tokens (fallback when Clerk not used)
JWT_SECRET = os.getenv("JWT_SECRET", secrets.token_hex(32))


def hash_password(password: str) -> str:
    """Hash password with SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()


def create_jwt_token(user_id: str, email: str) -> str:
    """Create a JWT token for the user"""
    payload = {
        "sub": user_id,
        "email": email,
        "exp": datetime.utcnow() + timedelta(days=30),
        "iat": datetime.utcnow()
    }
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def verify_jwt_token(token: str) -> Optional[dict]:
    """Verify and decode a JWT token"""
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


# =============================================================================
# Authentication (Clerk JWT + Simple Auth)
# =============================================================================

# Cache for Clerk JWKS
_clerk_jwks_cache = None
_clerk_jwks_cache_time = None

async def get_clerk_jwks():
    """Fetch Clerk's JWKS for JWT verification"""
    global _clerk_jwks_cache, _clerk_jwks_cache_time
    
    # Cache JWKS for 1 hour
    if _clerk_jwks_cache and _clerk_jwks_cache_time:
        if (datetime.utcnow() - _clerk_jwks_cache_time).seconds < 3600:
            return _clerk_jwks_cache
    
    if not CLERK_PUBLISHABLE_KEY:
        return None
    
    # Extract instance ID from publishable key (pk_live_xxx or pk_test_xxx)
    try:
        # Clerk JWKS endpoint
        async with httpx.AsyncClient() as client:
            # The frontend domain is derived from the publishable key
            resp = await client.get(
                "https://api.clerk.com/v1/jwks",
                headers={"Authorization": f"Bearer {CLERK_SECRET_KEY}"}
            )
            if resp.status_code == 200:
                _clerk_jwks_cache = resp.json()
                _clerk_jwks_cache_time = datetime.utcnow()
                return _clerk_jwks_cache
    except Exception as e:
        print(f"Failed to fetch Clerk JWKS: {e}")
    
    return None


async def verify_clerk_token(authorization: str = Header(None)) -> dict:
    """
    Verify JWT token (our own or Clerk) and return user info.
    Returns dict with 'sub' (user_id) and 'email'.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")
    
    token = authorization.replace("Bearer ", "")
    
    # For development/testing without Clerk
    if not CLERK_SECRET_KEY and token == "dev_token":
        return {"sub": "dev_user_123", "email": "dev@example.com"}
    
    # First, try to verify as our own JWT token (simple email/password auth)
    own_token = verify_jwt_token(token)
    if own_token:
        return {"sub": own_token.get("sub"), "email": own_token.get("email")}
    
    # If not our token, try Clerk JWT verification
    if CLERK_SECRET_KEY:
        try:
            jwks = await get_clerk_jwks()
            if not jwks:
                raise HTTPException(status_code=503, detail="Auth service unavailable")
            
            # Decode without verification first to get the key ID
            unverified = jwt.decode(token, options={"verify_signature": False})
            
            # Find the matching key
            header = jwt.get_unverified_header(token)
            key_id = header.get("kid")
            
            rsa_key = None
            for key in jwks.get("keys", []):
                if key.get("kid") == key_id:
                    rsa_key = jwt.algorithms.RSAAlgorithm.from_jwk(key)
                    break
            
            if not rsa_key:
                raise HTTPException(status_code=401, detail="Invalid token key")
            
            # Verify and decode
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=["RS256"],
                options={"verify_aud": False}
            )
            
            return {
                "sub": payload.get("sub"),
                "email": payload.get("email", payload.get("email_addresses", [{}])[0].get("email_address"))
            }
            
        except jwt.ExpiredSignatureError:
            raise HTTPException(status_code=401, detail="Token expired")
        except jwt.InvalidTokenError as e:
            raise HTTPException(status_code=401, detail=f"Invalid token: {str(e)}")
    
    raise HTTPException(status_code=401, detail="Invalid token")


def get_or_create_user(db: Session, clerk_user_id: str, email: str = None) -> User:
    """Get existing user or create new one"""
    user = db.query(User).filter(User.clerk_user_id == clerk_user_id).first()
    
    if not user:
        user = User(
            clerk_user_id=clerk_user_id,
            email=email,
            subscription_status="free",
            screens_today=0,
            last_screen_date=date.today()
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        
        # Create default settings for new user from config.json
        if DEFAULT_CONFIG:
            symbols = ",".join(DEFAULT_CONFIG.get('data', {}).get('symbols', ['AAPL', 'MSFT', 'GOOGL', 'SPY', 'QQQ']))
            opts = DEFAULT_CONFIG.get('options_strategy', {})
            criteria = DEFAULT_CONFIG.get('screening_criteria', {})
            settings = UserSettings(
                user_id=user.id,
                symbols=symbols,
                max_dte=opts.get('max_dte', 45),
                min_dte=opts.get('min_dte', 15),
                min_volume=opts.get('min_volume', 10),
                min_open_interest=opts.get('min_open_interest', 10),
                min_annualized_return=criteria.get('min_annualized_return', 20.0),
                max_assignment_probability=criteria.get('max_assignment_probability', 20)
            )
        else:
            settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(user)
    elif email and user.email != email:
        user.email = email
        db.commit()
    
    # Ensure settings exist for existing users
    if not user.settings:
        if DEFAULT_CONFIG:
            symbols = ",".join(DEFAULT_CONFIG.get('data', {}).get('symbols', ['AAPL', 'MSFT', 'GOOGL', 'SPY', 'QQQ']))
            opts = DEFAULT_CONFIG.get('options_strategy', {})
            criteria = DEFAULT_CONFIG.get('screening_criteria', {})
            settings = UserSettings(
                user_id=user.id,
                symbols=symbols,
                max_dte=opts.get('max_dte', 45),
                min_dte=opts.get('min_dte', 15),
                min_volume=opts.get('min_volume', 10),
                min_open_interest=opts.get('min_open_interest', 10),
                min_annualized_return=criteria.get('min_annualized_return', 20.0),
                max_assignment_probability=criteria.get('max_assignment_probability', 20)
            )
        else:
            settings = UserSettings(user_id=user.id)
        db.add(settings)
        db.commit()
        db.refresh(user)
    
    return user


def get_user_settings_model(user: User) -> UserSettingsModel:
    """Convert database settings to Pydantic model"""
    if not user.settings:
        return UserSettingsModel()
    
    s = user.settings
    symbols = [sym.strip() for sym in s.symbols.split(",") if sym.strip()] if s.symbols else []
    
    return UserSettingsModel(
        symbols=symbols,
        max_dte=s.max_dte,
        min_dte=s.min_dte,
        min_volume=s.min_volume,
        min_open_interest=s.min_open_interest,
        min_annualized_return=s.min_annualized_return,
        max_assignment_probability=s.max_assignment_probability
    )


def check_and_increment_usage(db: Session, user: User) -> int:
    """
    Check usage limits and increment counter.
    Returns remaining screens or raises HTTPException if limit exceeded.
    """
    today = date.today()
    
    # Reset counter if new day
    if user.last_screen_date != today:
        user.screens_today = 0
        user.last_screen_date = today
    
    # Check limits for free tier
    if user.subscription_status == "free":
        if user.screens_today >= FREE_SCREENS_PER_DAY:
            raise HTTPException(
                status_code=429,
                detail=f"Daily limit reached. Upgrade to Pro for unlimited screens."
            )
        remaining = FREE_SCREENS_PER_DAY - user.screens_today - 1
    else:
        remaining = -1  # Unlimited for pro
    
    # Increment usage
    user.screens_today += 1
    db.commit()
    
    return remaining


# =============================================================================
# FastAPI App
# =============================================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize resources on startup"""
    init_db()
    yield


app = FastAPI(
    title="Put Options Screener API",
    description="API for screening put options with real-time market data",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =============================================================================
# API Endpoints
# =============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "database": "connected" if engine else "not configured",
        "massive_api": "configured" if MASSIVE_API_KEY else "not configured"
    }


# =============================================================================
# Simple Email/Password Authentication Endpoints
# =============================================================================

@app.post("/auth/signup", response_model=AuthResponse)
async def signup(auth_req: AuthRequest, db: Session = Depends(get_db)):
    """Create a new user account"""
    # Check if email already exists
    existing = db.query(User).filter(User.email == auth_req.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    
    # Create new user
    user_id = str(uuid.uuid4())
    password_hash = hash_password(auth_req.password)
    
    user = User(
        id=user_id,
        clerk_user_id=f"email_{user_id}",  # Use email-based ID
        email=auth_req.email,
        password_hash=password_hash,
        subscription_status="free",
        screens_today=0,
        last_screen_date=date.today()
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    
    # Create default settings from config.json
    if DEFAULT_CONFIG:
        symbols = ",".join(DEFAULT_CONFIG.get('data', {}).get('symbols', ['AAPL', 'MSFT', 'GOOGL', 'SPY', 'QQQ']))
        opts = DEFAULT_CONFIG.get('options_strategy', {})
        criteria = DEFAULT_CONFIG.get('screening_criteria', {})
        settings = UserSettings(
            user_id=user.id,
            symbols=symbols,
            max_dte=opts.get('max_dte', 45),
            min_dte=opts.get('min_dte', 15),
            min_volume=opts.get('min_volume', 10),
            min_open_interest=opts.get('min_open_interest', 10),
            min_annualized_return=criteria.get('min_annualized_return', 20.0),
            max_assignment_probability=criteria.get('max_assignment_probability', 20)
        )
    else:
        settings = UserSettings(user_id=user.id)
    
    db.add(settings)
    db.commit()
    
    # Generate JWT token
    token = create_jwt_token(user.id, user.email)
    
    return AuthResponse(
        token=token,
        email=user.email,
        subscription_status=user.subscription_status
    )


@app.post("/auth/login", response_model=AuthResponse)
async def login(auth_req: AuthRequest, db: Session = Depends(get_db)):
    """Login with email and password"""
    # Find user by email
    user = db.query(User).filter(User.email == auth_req.email).first()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Check password
    password_hash = hash_password(auth_req.password)
    if user.password_hash != password_hash:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    
    # Generate JWT token
    token = create_jwt_token(user.id, user.email)
    
    return AuthResponse(
        token=token,
        email=user.email,
        subscription_status=user.subscription_status
    )


@app.get("/api/v1/test-screen")
async def test_screen(symbol: str = "AAPL"):
    """
    Test endpoint - no auth required.
    Quick way to verify the screener logic works.
    """
    try:
        from options_screener import (
            get_options_chain_massive,
            get_options_chain_yahoo,
            get_stock_price_massive,
            get_stock_price_yahoo,
            calculate_metrics,
            screen_options as filter_options,
            format_output
        )
    except ImportError as e:
        return {"error": f"Screener module error: {e}"}
    
    config = {
        'options_strategy': {'max_dte': 45, 'min_dte': 15, 'min_volume': 10, 'min_open_interest': 10},
        'screening_criteria': {'min_annualized_return': 20.0, 'max_assignment_probability': 20},
        'output': {'sort_by': ['annualized_return'], 'sort_order': 'descending', 'max_results': 5}
    }
    
    # Get price
    current_price = get_stock_price_massive(symbol)
    price_source = "massive"
    if current_price is None:
        current_price = get_stock_price_yahoo(symbol)
        price_source = "yahoo"
    
    if current_price is None:
        return {"error": f"Could not get price for {symbol}"}
    
    # Get options
    options = get_options_chain_massive(symbol, config)
    options_source = "massive"
    if options.empty:
        options = get_options_chain_yahoo(symbol, config)
        options_source = "yahoo"
    
    if options.empty:
        return {"error": f"No options data for {symbol}"}
    
    # Process
    options = calculate_metrics(options, current_price)
    filtered = filter_options(options, config)
    formatted = format_output(filtered, current_price)
    
    return {
        "symbol": symbol,
        "current_price": current_price,
        "price_source": price_source,
        "options_source": options_source,
        "results_count": len(formatted),
        "top_results": formatted.head(5).to_dict(orient='records') if not formatted.empty else []
    }


@app.get("/api/v1/news/{symbol}")
async def get_ticker_news(symbol: str, limit: int = 10, max_age_days: int = 7):
    """Get recent news for a ticker symbol"""
    try:
        from massive_api_client import massive_client
        if not massive_client:
            return {"news": [], "error": "Massive client not available"}
        
        news_items = massive_client.get_ticker_news(symbol, limit=limit, max_age_days=max_age_days)
        return {"symbol": symbol, "news": news_items}
    except Exception as e:
        return {"news": [], "error": str(e)}


@app.get("/api/v1/me", response_model=UserInfo)
async def get_current_user(
    user_info: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """Get current user information including settings"""
    user = get_or_create_user(db, user_info["sub"], user_info.get("email"))
    
    today = date.today()
    screens_today = user.screens_today if user.last_screen_date == today else 0
    
    if user.subscription_status == "free":
        remaining = max(0, FREE_SCREENS_PER_DAY - screens_today)
    else:
        remaining = -1  # Unlimited
    
    return UserInfo(
        email=user.email or "",
        subscription_status=user.subscription_status,
        screens_today=screens_today,
        screens_remaining=remaining,
        settings=get_user_settings_model(user)
    )


@app.get("/api/v1/settings", response_model=UserSettingsModel)
async def get_settings(
    user_info: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """Get current user's settings"""
    user = get_or_create_user(db, user_info["sub"], user_info.get("email"))
    return get_user_settings_model(user)


@app.put("/api/v1/settings", response_model=UserSettingsModel)
async def update_settings(
    settings_update: UserSettingsUpdate,
    user_info: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """Update current user's settings"""
    user = get_or_create_user(db, user_info["sub"], user_info.get("email"))
    
    settings = user.settings
    if not settings:
        settings = UserSettings(user_id=user.id)
        db.add(settings)
    
    # Update only provided fields
    if settings_update.symbols is not None:
        settings.symbols = ",".join(settings_update.symbols)
    if settings_update.max_dte is not None:
        settings.max_dte = settings_update.max_dte
    if settings_update.min_dte is not None:
        settings.min_dte = settings_update.min_dte
    if settings_update.min_volume is not None:
        settings.min_volume = settings_update.min_volume
    if settings_update.min_open_interest is not None:
        settings.min_open_interest = settings_update.min_open_interest
    if settings_update.min_annualized_return is not None:
        settings.min_annualized_return = settings_update.min_annualized_return
    if settings_update.max_assignment_probability is not None:
        settings.max_assignment_probability = settings_update.max_assignment_probability
    
    db.commit()
    db.refresh(user)
    
    return get_user_settings_model(user)


@app.post("/api/v1/screen", response_model=ScreenResponse)
async def screen_options(
    request: ScreenRequest,
    user_info: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """
    Screen options based on criteria.
    Enforces usage limits for free tier users.
    """
    user = get_or_create_user(db, user_info["sub"], user_info.get("email"))
    
    # Check symbol limits
    max_symbols = PRO_MAX_SYMBOLS if user.subscription_status == "pro" else FREE_MAX_SYMBOLS
    if len(request.symbols) > max_symbols:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {max_symbols} symbols allowed. Upgrade to Pro for more."
        )
    
    # Check and increment usage
    screens_remaining = check_and_increment_usage(db, user)
    
    # Import screener logic
    try:
        from options_screener import (
            get_options_chain_massive,
            get_options_chain_yahoo,
            get_stock_price_massive,
            get_stock_price_yahoo,
            calculate_metrics,
            screen_options as filter_options,
            format_output
        )
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Screener module error: {e}")
    
    # Build config for screener
    config = {
        'options_strategy': {
            'max_dte': request.max_dte,
            'min_dte': request.min_dte,
            'min_volume': request.min_volume,
            'min_open_interest': request.min_open_interest
        },
        'screening_criteria': {
            'min_annualized_return': request.min_annualized_return,
            'max_assignment_probability': request.max_assignment_probability
        },
        'output': {
            'sort_by': ['annualized_return'],
            'sort_order': 'descending',
            'max_results': 50
        }
    }
    
    results = {}
    used_yahoo = False
    
    for symbol in request.symbols:
        try:
            # Get price (Massive first, Yahoo fallback)
            current_price = get_stock_price_massive(symbol)
            if current_price is None:
                current_price = get_stock_price_yahoo(symbol)
                used_yahoo = True
            
            if current_price is None:
                continue
            
            # Get options chain (Massive first, Yahoo fallback)
            options = get_options_chain_massive(symbol, config)
            if options.empty:
                options = get_options_chain_yahoo(symbol, config)
                if not options.empty:
                    used_yahoo = True
            
            if options.empty:
                continue
            
            # Calculate metrics and filter
            options = calculate_metrics(options, current_price)
            filtered = filter_options(options, config)
            formatted = format_output(filtered, current_price)
            
            if not formatted.empty:
                # Convert DataFrame to list of dicts for JSON response
                results[symbol] = formatted.to_dict(orient='records')
                
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
    
    return ScreenResponse(
        success=True,
        results=results,
        screens_remaining=screens_remaining if screens_remaining >= 0 else None,
        used_yahoo_fallback=used_yahoo,
        message=f"Screened {len(results)} symbols successfully"
    )


@app.post("/api/v1/checkout", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    user_info: dict = Depends(verify_clerk_token),
    db: Session = Depends(get_db)
):
    """Create Stripe checkout session for Pro upgrade"""
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(status_code=503, detail="Billing not configured")
    
    user = get_or_create_user(db, user_info["sub"], user_info.get("email"))
    
    try:
        # Create or get Stripe customer
        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                metadata={"clerk_user_id": user.clerk_user_id}
            )
            user.stripe_customer_id = customer.id
            db.commit()
        
        # Create checkout session
        session = stripe.checkout.Session.create(
            customer=user.stripe_customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": STRIPE_PRICE_ID,
                "quantity": 1
            }],
            mode="subscription",
            success_url=request.success_url,
            cancel_url=request.cancel_url,
            metadata={"clerk_user_id": user.clerk_user_id}
        )
        
        return CheckoutResponse(checkout_url=session.url)
        
    except stripe.error.StripeError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/webhooks/stripe")
async def stripe_webhook(request: Request):
    """Handle Stripe webhook events for subscription changes"""
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured")
    
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    
    # Handle subscription events
    if event["type"] in ["customer.subscription.created", "customer.subscription.updated"]:
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        status = subscription["status"]
        
        # Update user subscription status
        if SessionLocal:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
                if user:
                    if status in ["active", "trialing"]:
                        user.subscription_status = "pro"
                    elif status in ["canceled", "unpaid", "past_due"]:
                        user.subscription_status = "cancelled"
                    db.commit()
            finally:
                db.close()
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        customer_id = subscription["customer"]
        
        if SessionLocal:
            db = SessionLocal()
            try:
                user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
                if user:
                    user.subscription_status = "free"
                    db.commit()
            finally:
                db.close()
    
    return {"status": "ok"}


# =============================================================================
# Run with: uvicorn main:app --reload
# =============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
