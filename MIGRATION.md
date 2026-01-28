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

After running the migration, admins can reorder system filters and trade ideas via drag-and-drop in the Admin Dashboard.

### Step 9: (Optional) Cleanup Old Columns

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

### Modified Endpoints

| Endpoint | Changes |
|----------|---------|
| `GET /api/v1/settings` | Now includes `selected_filter_id` and `selected_trade_idea_id` |
| `PUT /api/v1/settings` | Can now update `selected_filter_id` and `selected_trade_idea_id` |

## Questions?

If you encounter issues not covered here, please check:
1. Backend logs for error messages
2. Browser console for frontend errors
3. Database for data integrity
