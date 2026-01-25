# Put Options Screener

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-green.svg)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61dafb.svg)](https://reactjs.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.0+-3178c6.svg)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Interactive web application that scans put option chains for a list of stocks, computes key metrics (delta, annualized return, implied volatility), and highlights candidates that meet your custom filters. Ideal for options traders looking for high-probability, cash-secured put opportunities.

## Features

- **Professional-grade Greeks**: Delta, gamma, theta, vega directly from Massive.com API
- **Automatic fallback**: Uses Yahoo Finance when Massive.com data is unavailable
- **User authentication**: Sign in with Google, Apple, or email via Clerk
- **Settings persistence**: Your watchlist and filters are saved to your account
- **Real-time progress**: See each symbol being screened with live progress bar
- **Responsive UI**: Works on desktop and mobile browsers
- **Real-time news**: Latest news headlines for screened tickers
- **Configurable filters**: DTE, volume, open interest, return %, assignment probability

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Project Structure](#project-structure)
- [Quick Start](#quick-start)
- [Deployment](#deployment)
- [API Reference](#api-reference)
- [Configuration](#configuration)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)
- [License](#license)

---

## System Architecture

### High-Level Overview

```mermaid
flowchart TB
    subgraph frontend [Frontend - React/Vite]
        UI[Dashboard UI]
        Store[Zustand Store]
        APIClient[API Client]
    end
    
    subgraph backend [Backend - FastAPI]
        Routes[API Routes]
        Services[Business Logic]
        Models[SQLAlchemy Models]
    end
    
    subgraph external [External Services]
        Clerk[Clerk Auth]
        Massive[Massive.com API]
        Yahoo[Yahoo Finance]
    end
    
    subgraph data [Data Layer]
        DB[(PostgreSQL/SQLite)]
    end
    
    UI --> Store
    Store --> APIClient
    APIClient --> Routes
    Routes --> Services
    Services --> Models
    Models --> DB
    Services --> Massive
    Services --> Yahoo
    frontend --> Clerk
    backend --> Clerk
```

### Authentication Flow

```mermaid
sequenceDiagram
    participant User
    participant Frontend
    participant Clerk
    participant Backend
    participant DB
    
    User->>Frontend: Visit app
    Frontend->>Clerk: Check auth status
    Clerk-->>Frontend: Not signed in
    Frontend->>User: Redirect to /sign-in
    User->>Clerk: Sign in via Google/Apple/Email
    Clerk-->>Frontend: JWT Token
    Frontend->>Backend: API request + Bearer token
    Backend->>Backend: Verify JWT claims
    Backend->>DB: Get or create user
    Backend-->>Frontend: Response + user data
```

### Options Screening Data Flow

```mermaid
flowchart LR
    A[User clicks Screen] --> B[Frontend sends symbols]
    B --> C[Backend receives request]
    C --> D[Fetch from Massive.com]
    D --> E{Has Greeks?}
    E -->|Yes| F[Use Massive data]
    E -->|No| G[Yahoo Finance fallback]
    G --> H[Calculate Greeks via Black-Scholes]
    F --> I[Apply screening filters]
    H --> I
    I --> J[Return filtered results]
    J --> K[Display in results table]
```

### Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| Frontend | React 18 + TypeScript | UI components and routing |
| Build Tool | Vite | Fast development and bundling |
| State Management | Zustand | Client-side state |
| Server State | TanStack Query | API caching and mutations |
| Styling | Tailwind CSS | Utility-first CSS |
| Backend | FastAPI | REST API server |
| ORM | SQLAlchemy | Database abstraction |
| Database | PostgreSQL / SQLite | Data persistence |
| Authentication | Clerk | User auth (OAuth + Email) |
| Options Data | Massive.com | Professional Greeks |
| Fallback Data | Yahoo Finance | Free options data |

---

## Project Structure

```
PutOptionsTrading/
├── frontend/                    # React + TypeScript + Vite
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts       # Axios API client with auth
│   │   ├── components/
│   │   │   ├── NewsSection.tsx      # Ticker news display
│   │   │   ├── ResultsTable.tsx     # Options results table
│   │   │   ├── ScreeningProgress.tsx # Progress indicator
│   │   │   ├── Sidebar.tsx          # Settings sidebar
│   │   │   └── UserMenu.tsx         # User avatar/menu
│   │   ├── hooks/
│   │   │   └── useAuthSync.ts  # Clerk token sync
│   │   ├── pages/
│   │   │   └── Dashboard.tsx   # Main application page
│   │   ├── stores/
│   │   │   └── useAppStore.ts  # Zustand global state
│   │   ├── types/
│   │   │   └── index.ts        # TypeScript interfaces
│   │   ├── App.tsx             # Routes and auth wrapper
│   │   ├── main.tsx            # Entry point with providers
│   │   └── index.css           # Tailwind + custom styles
│   ├── Dockerfile              # Production container
│   ├── nginx.conf              # Nginx config for serving
│   ├── package.json
│   ├── tailwind.config.js
│   ├── tsconfig.json
│   └── vite.config.ts
│
├── backend/                     # FastAPI application
│   ├── app/
│   │   ├── api/v1/
│   │   │   ├── health.py       # Health check endpoint
│   │   │   ├── router.py       # Route aggregator
│   │   │   ├── screen.py       # Screening endpoints
│   │   │   └── settings.py     # User settings endpoints
│   │   ├── core/
│   │   │   ├── config.py       # Settings from env vars
│   │   │   ├── database.py     # SQLAlchemy setup
│   │   │   └── deps.py         # FastAPI dependencies
│   │   ├── models/
│   │   │   └── user.py         # User + UserSettings models
│   │   ├── schemas/
│   │   │   ├── screen.py       # Request/response schemas
│   │   │   └── user.py         # User schemas
│   │   ├── services/
│   │   │   ├── screener.py           # Options screening orchestration
│   │   │   ├── options_screener.py   # Core screening logic
│   │   │   ├── massive_api_client.py # Massive.com API client
│   │   │   └── user.py               # User management
│   │   └── main.py             # FastAPI app entry point
│   ├── Dockerfile              # Production container
│   └── requirements.txt        # Python dependencies
│
├── scripts/
│   └── dev.sh                  # Local development script
│
├── docker-compose.yml          # Local dev with PostgreSQL
└── railway.toml                # Railway deployment config
```

---

## Quick Start

### Prerequisites

- **Python 3.11+** - [Download](https://python.org)
- **Node.js 18+** - [Download](https://nodejs.org)
- **Massive.com API Key** - [Sign up](https://massive.com)
- **Clerk Account** (optional for dev) - [Sign up](https://clerk.com)

### Local Development Setup

#### 1. Clone the Repository

```bash
git clone https://github.com/your-org/PutOptionsTrading.git
cd PutOptionsTrading
```

#### 2. Backend Setup

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
cd backend
pip install -r requirements.txt

# Create environment file
cp .env.example .env
# Edit .env and add your MASSIVE_API_KEY
```

#### 3. Frontend Setup

```bash
cd frontend
npm install

# Create environment file
cp .env.example .env
# Edit .env if needed (defaults work for local dev)
```

#### 4. Run the Application

**Option A: Using the dev script**

```bash
./scripts/dev.sh
```

**Option B: Manual start (two terminals)**

Terminal 1 - Backend:
```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

Terminal 2 - Frontend:
```bash
cd frontend
npm run dev
```

#### 5. Access the Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Docs**: http://localhost:8000/docs

### Running with Docker

```bash
# Start all services (PostgreSQL + Backend + Frontend)
docker-compose up -d

# View logs
docker-compose logs -f

# Stop services
docker-compose down
```

Access at http://localhost:3000

---

## Deployment

### Railway Deployment

Railway provides easy deployment with automatic builds and managed PostgreSQL.

#### Step 1: Create Railway Project

1. Go to [railway.app](https://railway.app) and sign up with GitHub
2. Click **"New Project"** → **"Empty Project"**

#### Step 2: Add PostgreSQL Database

1. In your project, click **"+ New"** → **"Database"** → **"PostgreSQL"**
2. Wait for provisioning (~30 seconds)
3. Click on the PostgreSQL service → **Variables** tab
4. Copy the `DATABASE_URL` value (you'll need this for the backend)

#### Step 3: Deploy Backend

1. Click **"+ New"** → **"GitHub Repo"**
2. Select your repository
3. **Configure the service:**
   - Click on the new service → **Settings** tab
   - **Root Directory**: `backend`
   - **Leave Build Command and Start Command EMPTY** (the Dockerfile handles this)

4. Go to **Variables** tab and add:

   | Variable | Value |
   |----------|-------|
   | `DATABASE_URL` | Click "Add Reference" → Select from Postgres service, OR paste `postgresql://postgres:PASSWORD@postgres.railway.internal:5432/railway` |
   | `MASSIVE_API_KEY` | Your Massive.com API key |
   | `CLERK_SECRET_KEY` | `sk_test_xxx` from [Clerk Dashboard](https://dashboard.clerk.com) |
   | `CORS_ORIGINS` | `*` (or your frontend URL after Step 4) |

5. Go to **Networking** tab → Click **"Generate Domain"** to get a public URL
6. Note this URL (e.g., `https://backend-xxx.up.railway.app`)

#### Step 4: Deploy Frontend

1. Click **"+ New"** → **"GitHub Repo"**
2. Select your repository **again** (same repo, different service)
3. **Configure the service:**
   - Click on the new service → **Settings** tab
   - **Root Directory**: `frontend`
   - **Leave Build Command and Start Command EMPTY** (the Dockerfile handles this)

4. Go to **Variables** tab and add:

   | Variable | Value |
   |----------|-------|
   | `VITE_API_URL` | `https://backend-xxx.up.railway.app` (your backend URL from Step 3, **must include https://**) |
   | `VITE_CLERK_PUBLISHABLE_KEY` | `pk_test_xxx` from [Clerk Dashboard](https://dashboard.clerk.com) |

5. Go to **Networking** tab → Click **"Generate Domain"** to get a public URL

6. **Update Backend CORS** (now that you have the frontend URL):
   - Go back to Backend service → **Variables**
   - Update `CORS_ORIGINS` to your frontend URL: `https://frontend-xxx.up.railway.app`
   - This will trigger a backend redeploy

#### Step 5: Verify Deployment

1. **Test Backend Health:**
   ```
   https://your-backend-url.up.railway.app/health
   ```
   Should return JSON with `"status": "healthy"`

2. **Test Frontend:**
   - Visit your frontend URL
   - Sign in with Clerk
   - Click "Screen All" - results should appear

#### Troubleshooting Railway Deployment

| Problem | Solution |
|---------|----------|
| Backend shows `$PORT` error | Clear custom Start Command in Settings - let Dockerfile handle it |
| Frontend shows blank page | Check that `VITE_API_URL` includes `https://` and redeploy |
| 502 Bad Gateway | Check backend Deploy logs for startup errors |
| CORS errors (400/403 on OPTIONS) | Verify `CORS_ORIGINS` on backend matches frontend URL exactly (no trailing slash) |
| Screening takes forever | Normal - Massive API is slow. Each symbol takes 5-15 seconds |

#### Step 6: Configure Custom Domain (Optional)

1. Go to frontend service → **Settings** → **Networking**
2. Click **"+ Custom Domain"**
3. Add your domain and configure DNS as instructed

### Docker Production Deployment

#### Building Images

```bash
# Build backend
docker build -t options-backend ./backend

# Build frontend
docker build -t options-frontend ./frontend
```

#### Running in Production

```bash
# Create network
docker network create options-network

# Run PostgreSQL
docker run -d \
  --name options-db \
  --network options-network \
  -e POSTGRES_USER=postgres \
  -e POSTGRES_PASSWORD=your_secure_password \
  -e POSTGRES_DB=options_screener \
  -v postgres_data:/var/lib/postgresql/data \
  postgres:15-alpine

# Run Backend
docker run -d \
  --name options-backend \
  --network options-network \
  -p 8000:8000 \
  -e DATABASE_URL=postgresql://postgres:your_secure_password@options-db:5432/options_screener \
  -e MASSIVE_API_KEY=your_key \
  -e CLERK_SECRET_KEY=sk_live_xxx \
  -e CORS_ORIGINS=https://your-domain.com \
  options-backend

# Run Frontend
docker run -d \
  --name options-frontend \
  --network options-network \
  -p 80:80 \
  -e PORT=80 \
  options-frontend
```

---

## API Reference

### Base URL

- **Local**: `http://localhost:8000`
- **Production**: `https://your-backend-url`

### Authentication

Most endpoints accept an optional Bearer token. When Clerk is configured, include the JWT:

```http
Authorization: Bearer <clerk_jwt_token>
```

### Endpoints

#### Health Check

```http
GET /health
```

Returns service health status.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected",
  "massive_api": "configured",
  "version": "1.0.0"
}
```

#### Get Current User

```http
GET /api/v1/me
Authorization: Bearer <token>
```

**Response:**
```json
{
  "id": "user_123",
  "email": "user@example.com",
  "subscription_status": "free",
  "screens_today": 3,
  "screens_remaining": 2,
  "settings": {
    "symbols": ["AAPL", "MSFT", "GOOGL"],
    "max_dte": 45,
    "min_dte": 15,
    "min_volume": 10,
    "min_open_interest": 10,
    "min_annualized_return": 20.0,
    "max_assignment_probability": 20
  }
}
```

#### Get User Settings

```http
GET /api/v1/settings
Authorization: Bearer <token>
```

#### Update User Settings

```http
PUT /api/v1/settings
Authorization: Bearer <token>
Content-Type: application/json

{
  "symbols": ["AAPL", "TSLA", "NVDA"],
  "max_dte": 30,
  "min_annualized_return": 25.0
}
```

#### Screen Options

```http
POST /api/v1/screen
Content-Type: application/json

{
  "symbols": ["AAPL", "TSLA"],
  "max_dte": 45,
  "min_dte": 15,
  "min_volume": 10,
  "min_open_interest": 10,
  "min_annualized_return": 20.0,
  "max_assignment_probability": 20
}
```

**Response:**
```json
{
  "success": true,
  "results": {
    "AAPL": [
      {
        "symbol": "AAPL",
        "stock_price": 178.50,
        "strike": 170.00,
        "expiry": "2024-02-16",
        "premium": 2.15,
        "annualized_return": 32.5,
        "delta": -0.18,
        "prob_assignment": 18.0,
        "dte": 21,
        "volume": 1250,
        "open_interest": 5430,
        "iv": 0.285
      }
    ]
  },
  "used_yahoo_fallback": false,
  "message": "Screened 2 symbols successfully"
}
```

#### Get News

```http
GET /api/v1/news/{symbol}?limit=10&max_age_days=7
```

**Response:**
```json
{
  "symbol": "AAPL",
  "news": [
    {
      "title": "Apple Reports Q4 Earnings",
      "url": "https://...",
      "source": "Reuters",
      "published_at": "2024-01-25T14:30:00Z"
    }
  ]
}
```

---

## Configuration

### Environment Variables

#### Backend (`backend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | Yes | `sqlite:///./local_test.db` | Database connection string |
| `MASSIVE_API_KEY` | Yes | - | Massive.com API key |
| `CORS_ORIGINS` | No | `*` | Allowed origins (comma-separated) |
| `CLERK_SECRET_KEY` | No | - | Clerk secret key for JWT verification |
| `DEBUG` | No | `false` | Enable debug mode |

#### Frontend (`frontend/.env`)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `VITE_API_URL` | No | `""` (same origin) | Backend API URL |
| `VITE_CLERK_PUBLISHABLE_KEY` | No | - | Clerk publishable key |

### Screening Parameters

Default values in `config.json`:

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_dte` | 45 | Maximum days to expiration |
| `min_dte` | 15 | Minimum days to expiration |
| `min_volume` | 10 | Minimum option volume |
| `min_open_interest` | 10 | Minimum open interest |
| `min_annualized_return` | 20.0 | Minimum annualized return % |
| `max_assignment_probability` | 20 | Maximum assignment probability % |

---

## Troubleshooting

### Common Issues

#### "No such column" Database Error

The database schema is out of sync with the models.

**Solution:** Delete the SQLite database and restart:
```bash
rm backend/local_test.db
# Restart backend - tables will be recreated
```

#### 429 Too Many Requests

Usage limits are being enforced (Phase 3 with Stripe).

**Solution for development:** Ensure `STRIPE_SECRET_KEY` is not set, or delete and recreate your user in the database.

#### CORS Errors

The frontend origin is not allowed.

**Solution:** Add your frontend URL to `CORS_ORIGINS`:
```bash
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

#### Clerk Authentication Not Working

**Checklist:**
1. Verify `VITE_CLERK_PUBLISHABLE_KEY` is set in frontend `.env`
2. Verify `CLERK_SECRET_KEY` is set in backend `.env`
3. Ensure Clerk dashboard has correct redirect URLs
4. Check browser console for Clerk errors

#### No Options Data Returned

**Checklist:**
1. Verify `MASSIVE_API_KEY` is correct
2. Check if the symbol has options (not all stocks do)
3. Try adjusting DTE range (some stocks have limited expirations)
4. Check backend logs for API errors

### Debug Mode

Enable verbose logging:

```bash
# Backend
DEBUG=true uvicorn app.main:app --reload

# Frontend (check browser console)
# Open DevTools → Console
```

### Log Locations

- **Backend**: Terminal output (stdout)
- **Frontend**: Browser DevTools Console
- **Docker**: `docker-compose logs -f <service>`
- **Railway**: Dashboard → Service → Deployments → Logs

---

## Development Phases

### Phase 1: MVP ✓
- React frontend with full UI
- FastAPI backend with screening endpoints
- Local development without authentication
- Railway deployment configuration

### Phase 2: Authentication ✓
- Clerk integration (Google, Apple, Email/Password)
- User settings persistence in database
- Protected routes with auth redirect
- JWT token verification in backend

### Phase 3: Production (Planned)
- Stripe subscription integration
- Usage limits enforcement
- Production hardening

---

## Contributing

### Development Workflow

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/my-feature`
3. Make your changes
4. Run linting: `npm run lint` (frontend)
5. Test locally
6. Commit with descriptive message
7. Push and create a Pull Request

### Code Style

- **Python**: Follow PEP 8, use type hints
- **TypeScript**: ESLint + Prettier configuration
- **Commits**: Use conventional commits (feat, fix, docs, etc.)

### Pull Request Guidelines

- Include description of changes
- Reference any related issues
- Ensure all checks pass
- Request review from maintainers

---

## Data Sources

- **Massive.com** (Primary): Professional-grade Greeks from API - no local calculation required
- **Yahoo Finance** (Fallback): Free data with Greeks calculated locally via Black-Scholes model

---

## Security Notes

- Keep API keys in environment variables or `.env` files
- Never commit secrets to version control
- In production, restrict CORS to your frontend domain only
- Use HTTPS in production
- Regularly rotate API keys

---

## License

MIT License - see [LICENSE](LICENSE) for details.

---

## Support

- **Issues**: [GitHub Issues](https://github.com/your-org/PutOptionsTrading/issues)
- **Discussions**: [GitHub Discussions](https://github.com/your-org/PutOptionsTrading/discussions)
