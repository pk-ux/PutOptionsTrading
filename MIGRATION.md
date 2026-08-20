# Migration Guide: Filters and Trade Ideas

This document provides step-by-step instructions for migrating the Put Options Screener application to the new Filters and Trade Ideas feature system.

## Overview

The migration transforms the application from using flat user settings to a more flexible system with:
- **Filters**: Reusable screening parameter presets (system + user-defined)
- **Trade Ideas**: Curated watchlists with descriptive names (system + user-defined)

## Prerequisites

- Access to the production database
- Admin access to Railway (or your hosting platform)
- Ability to run Python scripts in the backend environment

## Migration Steps

### Step 1: Backup Your Database

Before starting, create a backup of your production database.

**Railway PostgreSQL:**
```bash
# Connect to Railway and create a dump
railway run pg_dump $DATABASE_URL > backup_$(date +%Y%m%d).sql
```

### Step 2: Deploy the New Backend

Deploy the updated backend code. The new code is backward compatible and will:
- Create new tables (`filters`, `trade_ideas`)
- Add new columns to `user_settings` (`selected_filter_id`, `selected_trade_idea_id`)
- Keep all existing columns for backward compatibility

```bash
# Push to your deployment branch
git push origin main
```

The database schema will be automatically updated when the app starts.

> **Scope of the automatic update:** startup calls `Base.metadata.create_all()`, which
> creates **new tables** but does **not** add columns to tables that already exist, and
> the project has no Alembic setup. Adding a column to an existing model therefore needs
> either an explicit `ALTER TABLE` (see `ensure_schema()` in
> `backend/app/modules/breakout_scanner/integration.py`) or defensive
> `getattr(row, "field", default)` reads. Adding a whole new table needs neither.

### Step 3: Set Admin User(s)

Add your Clerk user ID to the `ADMIN_CLERK_IDS` environment variable:

1. Find your Clerk User ID:
   - Go to [Clerk Dashboard](https://dashboard.clerk.com)
   - Navigate to Users
   - Click on your user
   - Copy the User ID (e.g., `user_2abc123def456`)

2. Set the environment variable in Railway:
   ```
   ADMIN_CLERK_IDS=user_2abc123def456
   ```

   For multiple admins, use comma-separated values:
   ```
   ADMIN_CLERK_IDS=user_2abc123def456,user_2xyz789ghi012
   ```

### Step 4: Seed System Data

Run the seed script to create initial system filters and trade ideas:

**Option A: Railway Shell**
```bash
railway run python -m scripts.seed_system_data
```

**Option B: Local with Production Database**
```bash
cd backend
DATABASE_URL="your_production_url" python -m scripts.seed_system_data
```

This will create:

**System Filters:**
| Name | DTE Range | Volume | OI | Min Return | Max Prob |
|------|-----------|--------|----|-----------:|----------|
| Conservative (default) | 15-45 | 10 | 10 | 20% | 20% |
| Moderate | 7-21 | 50 | 50 | 30% | 15% |
| Aggressive | 3-14 | 100 | 100 | 50% | 10% |

**System Trade Ideas:**
| Name | Symbols |
|------|---------|
| Mag 7 (default) | AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA |
| Crypto Plays | COIN, MSTR, IBIT, ETHA |
| AI and Chips | NVDA, AMD, AVGO, PLTR, CRWV |

### Step 5: Migrate Existing User Data

Run the migration script to convert existing user settings to personal filters and trade ideas:

**Option A: Railway Shell**
```bash
railway run python -m scripts.migrate_user_settings
```

**Option B: Local with Production Database**
```bash
cd backend
DATABASE_URL="your_production_url" python -m scripts.migrate_user_settings
```

This will:
- Create a personal "My Settings (Migrated)" filter for each user
- Create a personal "My Watchlist (Migrated)" trade idea for each user
- Set these as the user's selected filter and trade idea

The script is idempotent - running it multiple times is safe.

### Step 6: Deploy the New Frontend

Deploy the updated frontend code:

```bash
# Rebuild and deploy
railway up
```

### Step 7: Verify the Migration

1. **Test as a regular user:**
   - Log in to the application
   - Verify you see the Trade Ideas and Filters chip selectors
   - Verify your migrated settings appear as "My Settings (Migrated)" and "My Watchlist (Migrated)"
   - Test creating, editing, and deleting personal filters and trade ideas

2. **Test as an admin:**
   - Navigate to `/admin`
   - Verify you can see the Admin Dashboard
   - Test creating, editing, and deleting system filters and trade ideas
   - Test setting different items as default

### Step 8: Add display_order Column (Reordering Feature)

If you're adding the drag-and-drop reordering feature, run these SQL commands:

**Railway PostgreSQL (using public URL):**
```bash
cd backend
DATABASE_URL="postgresql://postgres:password@host.railway.app:port/railway" python -c "
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    conn.execute(text('ALTER TABLE filters ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0'))
    conn.execute(text('ALTER TABLE trade_ideas ADD COLUMN IF NOT EXISTS display_order INTEGER DEFAULT 0'))
    conn.commit()
    print('Successfully added display_order columns')
"
```

Or directly in psql:
```sql
ALTER TABLE filters ADD COLUMN display_order INTEGER DEFAULT 0;
ALTER TABLE trade_ideas ADD COLUMN display_order INTEGER DEFAULT 0;
```

### Step 9: Add Cache Settings Table (Admin Cache Control)

If you're adding the admin cache settings feature, run these SQL commands:

**Railway PostgreSQL (using public URL):**
```bash
cd backend
DATABASE_URL="postgresql://postgres:password@host.railway.app:port/railway" python -c "
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    # Create cache_settings table
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS cache_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            cache_enabled BOOLEAN NOT NULL DEFAULT true,
            ttl_stock_price INTEGER NOT NULL DEFAULT 180,
            ttl_options_chain INTEGER NOT NULL DEFAULT 300,
            ttl_news INTEGER NOT NULL DEFAULT 900,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))
    
    # Insert default row if not exists
    conn.execute(text('''
        INSERT INTO cache_settings (id, cache_enabled, ttl_stock_price, ttl_options_chain, ttl_news)
        VALUES (1, true, 180, 300, 900)
        ON CONFLICT (id) DO NOTHING
    '''))
    
    conn.commit()
    print('Successfully created cache_settings table')
"
```

Or directly in psql:
```sql
CREATE TABLE IF NOT EXISTS cache_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    cache_enabled BOOLEAN NOT NULL DEFAULT true,
    ttl_stock_price INTEGER NOT NULL DEFAULT 180,
    ttl_options_chain INTEGER NOT NULL DEFAULT 300,
    ttl_news INTEGER NOT NULL DEFAULT 900,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO cache_settings (id, cache_enabled, ttl_stock_price, ttl_options_chain, ttl_news)
VALUES (1, true, 180, 300, 900)
ON CONFLICT (id) DO NOTHING;
```

After running the migration, admins can control caching via the Admin Dashboard under "Cache Settings".

After running the migration, admins can reorder system filters and trade ideas via drag-and-drop in the Admin Dashboard.

### Step 10: Add API Provider Settings Table (Alpaca Integration)

If you're adding the Alpaca API integration feature, run these SQL commands:

**Railway PostgreSQL (using public URL):**
```bash
cd backend
DATABASE_URL="postgresql://postgres:password@host.railway.app:port/railway" python -c "
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    # Create api_provider_settings table
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS api_provider_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            active_provider VARCHAR(20) NOT NULL DEFAULT 'massive',
            use_midpoint_pricing BOOLEAN NOT NULL DEFAULT true,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))
    
    # Insert default row if not exists
    conn.execute(text('''
        INSERT INTO api_provider_settings (id, active_provider, use_midpoint_pricing)
        VALUES (1, 'massive', true)
        ON CONFLICT (id) DO NOTHING
    '''))
    
    conn.commit()
    print('Successfully created api_provider_settings table')
"
```

Or directly in psql:
```sql
CREATE TABLE IF NOT EXISTS api_provider_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    active_provider VARCHAR(20) NOT NULL DEFAULT 'massive',
    use_midpoint_pricing BOOLEAN NOT NULL DEFAULT true,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO api_provider_settings (id, active_provider, use_midpoint_pricing)
VALUES (1, 'massive', true)
ON CONFLICT (id) DO NOTHING;
```

After running the migration, configure your Alpaca API keys in the environment:

```bash
ALPACA_API_KEY=your_alpaca_api_key
ALPACA_SECRET_KEY=your_alpaca_secret_key
```

Then admins can switch between Massive and Alpaca providers via the Admin Dashboard under "API Provider".

### Step 11: Add Market Settings Table (Risk-Free Rate)

If you're adding the configurable risk-free rate feature for Greeks calculations, run these SQL commands:

**Railway PostgreSQL (using public URL):**
```bash
cd backend
DATABASE_URL="postgresql://postgres:password@host.railway.app:port/railway" python -c "
from sqlalchemy import create_engine, text
import os

engine = create_engine(os.getenv('DATABASE_URL'))
with engine.connect() as conn:
    # Create market_settings table
    conn.execute(text('''
        CREATE TABLE IF NOT EXISTS market_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            risk_free_rate FLOAT NOT NULL DEFAULT 0.0367,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    '''))
    
    # Insert default row if not exists
    conn.execute(text('''
        INSERT INTO market_settings (id, risk_free_rate)
        VALUES (1, 0.0367)
        ON CONFLICT (id) DO NOTHING
    '''))
    
    conn.commit()
    print('Successfully created market_settings table')
"
```

Or directly in psql:
```sql
CREATE TABLE IF NOT EXISTS market_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    risk_free_rate FLOAT NOT NULL DEFAULT 0.0367,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO market_settings (id, risk_free_rate)
VALUES (1, 0.0367)
ON CONFLICT (id) DO NOTHING;
```

After running the migration, admins can update the risk-free rate via the Admin Dashboard under "Market Settings". A link to the FRED 3-Month Treasury Rate is provided for reference.

### Step 13: (Optional) Cleanup Old Columns

After confirming everything works, you can optionally remove the old columns from `user_settings`. This is NOT required and can be done later.

**Warning:** This is irreversible. Only do this after thorough testing.

```sql
ALTER TABLE user_settings DROP COLUMN symbols;
ALTER TABLE user_settings DROP COLUMN min_dte;
ALTER TABLE user_settings DROP COLUMN max_dte;
ALTER TABLE user_settings DROP COLUMN min_volume;
ALTER TABLE user_settings DROP COLUMN min_open_interest;
ALTER TABLE user_settings DROP COLUMN min_annualized_return;
ALTER TABLE user_settings DROP COLUMN max_assignment_probability;
```

## Rollback Plan

If issues occur:

1. **Before running migration scripts:**
   - Simply redeploy the old code
   - New tables exist but are unused

2. **After running migration scripts:**
   - Old columns still contain original data
   - Redeploy old code and users will use original settings
   - Delete the new tables if needed:
     ```sql
     DROP TABLE trade_ideas;
     DROP TABLE filters;
     ALTER TABLE user_settings DROP COLUMN selected_filter_id;
     ALTER TABLE user_settings DROP COLUMN selected_trade_idea_id;
     ```

3. **After cleanup (Step 8):**
   - Restore from backup

## Troubleshooting

### "Access denied" on Admin page

- Verify `ADMIN_CLERK_IDS` contains your Clerk User ID
- Restart the backend after changing the environment variable
- Check the User ID format (should be `user_xxxxxxxxx`)

### Migration script shows "0 users migrated"

- Users may have already been migrated (check `selected_filter_id` column)
- Verify users exist in the `user_settings` table

### Filters/Trade Ideas not loading

- Check browser console for API errors
- Verify backend is running and accessible
- Check CORS configuration if using different domains

### System data not appearing

- Run the seed script again
- Check backend logs for errors during startup
- Verify database connection

## API Changes

### New Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/filters` | GET | List all filters |
| `/api/v1/filters` | POST | Create user filter |
| `/api/v1/filters/{id}` | PUT | Update user filter |
| `/api/v1/filters/{id}` | DELETE | Delete user filter |
| `/api/v1/trade-ideas` | GET | List all trade ideas |
| `/api/v1/trade-ideas` | POST | Create user trade idea |
| `/api/v1/trade-ideas/{id}` | PUT | Update user trade idea |
| `/api/v1/trade-ideas/{id}` | DELETE | Delete user trade idea |
| `/api/v1/admin/filters` | POST | Create system filter |
| `/api/v1/admin/filters/{id}` | PUT | Update system filter |
| `/api/v1/admin/filters/{id}/set-default` | PUT | Set default filter |
| `/api/v1/admin/filters/{id}` | DELETE | Delete system filter |
| `/api/v1/admin/trade-ideas` | POST | Create system trade idea |
| `/api/v1/admin/trade-ideas/{id}` | PUT | Update system trade idea |
| `/api/v1/admin/trade-ideas/{id}/set-default` | PUT | Set default trade idea |
| `/api/v1/admin/trade-ideas/{id}` | DELETE | Delete system trade idea |
| `/api/v1/admin/filters/reorder` | PUT | Reorder system filters (admin) |
| `/api/v1/admin/trade-ideas/reorder` | PUT | Reorder system trade ideas (admin) |
| `/api/v1/admin/cache-settings` | GET | Get cache settings (admin) |
| `/api/v1/admin/cache-settings` | PUT | Update cache settings (admin) |
| `/api/v1/admin/api-provider` | GET | Get API provider settings (admin) |
| `/api/v1/admin/api-provider` | PUT | Update API provider settings (admin) |
| `/api/v1/admin/market-settings` | GET | Get market settings (admin) |
| `/api/v1/admin/market-settings` | PUT | Update market settings (admin) |

### Modified Endpoints

| Endpoint | Changes |
|----------|---------|
| `GET /api/v1/settings` | Now includes `selected_filter_id` and `selected_trade_idea_id` |
| `PUT /api/v1/settings` | Can now update `selected_filter_id` and `selected_trade_idea_id` |

---

# Breakout Scanner (Momentum Stocks)

The Breakout Scanner is a self-contained module
(`backend/app/modules/breakout_scanner/`) that ranks a user-defined ticker
universe by a 0-100 **Breakout Readiness Score** built from leading indicators
(volatility compression / VCP, relative strength, pivot proximity) plus a
first-class Unusual Whales smart-money layer (options flow, OI accumulation,
dealer GEX, dark-pool blocks, insider/congress buying, native IV rank). It
publishes the top picks into the **"Momentum Stocks"** system Trade Idea.

## Deploy / migrate

1. **Database** – two new tables are created automatically on startup via
   `init_db()` (`Base.metadata.create_all`): `breakout_scanner_settings` and
   `breakout_scan_results`. No manual migration needed.
2. **Environment variable** – add the Unusual Whales API key (optional; the
   scanner still runs on price structure alone without it):

   ```bash
   # Railway / .env
   UNUSUAL_WHALES_API_KEY=your_key_here
   ```

   > Security: store the key only in environment variables. If a key has been
   > shared in plain text, rotate it in the Unusual Whales dashboard.
3. **Dependencies** – no new packages (uses the existing `httpx`, `numpy`,
   `yfinance`).
4. **Configure the universe** – in the Admin dashboard, open the **Breakout
   Scanner** card, paste your tickers, save, then **Run Scan**.

## Running the scan

- **Manually from the UI**: Admin → Breakout Scanner → *Run Scan* (executes as a
  background task; the card polls for status and shows ranked results).
- **From the CLI**:

  ```bash
  cd backend
  python -m scripts.run_breakout_scan
  ```

## Scheduling

### Built in (recommended)

The backend runs its own scheduler, so **no cron service is required**. In the
Admin dashboard open **Breakout Scanner → Automatic scan**, turn it on, and pick
a time, timezone, and days. It defaults to **16:30 America/New_York, Mon–Fri**
(30 minutes after the close, once the daily bar has settled).

The schedule is stored in the database and applies immediately — no redeploy.
Notes:

- Off by default, so upgrading never starts a recurring job on its own.
- Fires at most once per day, and defers rather than colliding with a manual run.
- If the process was down at the scheduled minute it still runs on restart, up to
  4 hours late; after that the day is skipped.
- Market holidays are **not** skipped (there is no market calendar in the app). A
  holiday run is harmless — the last daily bar is unchanged.
- **Run Scan** in the admin UI always works, schedule on or off.

### External cron (alternative)

Still supported for hosts that prefer an external scheduler. Use one or the
other; running both is safe but redundant. The script reads the universe/config
from the database, so the cron just invokes it.

**Railway** – add a separate *Cron* service (or a scheduled job) pointing at the
backend image with:

```
Schedule (UTC):  30 21 * * 1-5
Command:         python -m scripts.run_breakout_scan
```

**Generic crontab** (any host):

```cron
# 4:30pm ET on weekdays (adjust for your server timezone)
30 16 * * 1-5 cd /app/backend && /usr/bin/python -m scripts.run_breakout_scan >> /var/log/breakout_scan.log 2>&1
```

## New API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/v1/admin/breakout-scanner` | GET | Get scanner settings + last-run status + next scheduled run (admin) |
| `/api/v1/admin/breakout-scanner` | PUT | Update universe, config, and auto-scan schedule (admin) |
| `/api/v1/admin/breakout-scanner/run` | POST | Trigger a scan as a background job (admin) |
| `/api/v1/admin/breakout-scanner/results` | GET | Get the latest ranked results (admin) |

## Removing the feature

Delete `backend/app/modules/breakout_scanner/`, the `breakout_scanner` router
include in `app/api/v1/router.py`, the two models in
`app/models/breakout_scanner.py` (and their registration in
`app/models/__init__.py` and `app/core/database.py`), the `BreakoutScannerCard`
in the frontend (and its mount in `Admin.tsx`), and
`backend/scripts/run_breakout_scan.py`. No other feature depends on it.

## Questions?

If you encounter issues not covered here, please check:
1. Backend logs for error messages
2. Browser console for frontend errors
3. Database for data integrity
