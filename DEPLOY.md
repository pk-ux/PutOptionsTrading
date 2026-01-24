# Deployment Guide - Put Options Screener SaaS

This guide walks you through deploying the Put Options Screener as a paid SaaS on Railway.

## Prerequisites

- GitHub account
- Railway account (https://railway.app)
- Stripe account (https://stripe.com) - for payments
- Your Massive.com API key

## Cost Estimate

| Service | Monthly Cost |
|---------|--------------|
| Railway (backend + frontend + DB) | ~$15 |
| Stripe | 2.9% + $0.30 per transaction |
| **Total fixed cost** | **~$15/mo** |

---

## Step 1: Push Code to GitHub

```bash
cd /Users/prashant/Projects/PutOptionsTrading

# If not already a git repo
git init
git add .
git commit -m "Initial SaaS deployment"

# Create repo on GitHub, then:
git remote add origin https://github.com/YOUR_USERNAME/put-options-screener.git
git push -u origin main
```

---

## Step 2: Set Up Stripe Billing

### Create a Product

1. Go to https://dashboard.stripe.com
2. Make sure you're in **Test Mode** (toggle in sidebar) for testing
3. Click **Products** → **+ Add Product**
4. Fill in:
   - **Name**: `Pro Plan`
   - **Description**: `Unlimited options screening with real-time data`
5. Under **Price information**:
   - **Price**: `9.99`
   - **Recurring**: Select **Monthly**
6. Click **Save product**

### Get Your Price ID

1. Click on the product you just created
2. Under **Pricing**, click on the price
3. Copy the **Price ID** (looks like `price_1Qxxxxxxxxxx`)

### Get Your API Keys

1. Go to **Developers** → **API Keys**
2. Copy your **Secret key** (starts with `sk_test_` or `sk_live_`)

---

## Step 3: Deploy to Railway

### 3.1 Create Railway Account & Project

1. Go to https://railway.app
2. Sign up with GitHub
3. Click **New Project** → **Deploy from GitHub repo**
4. Authorize Railway to access your GitHub
5. Select your `put-options-screener` repository

### 3.2 Add PostgreSQL Database

1. In your Railway project dashboard, click **+ New**
2. Select **Database** → **PostgreSQL**
3. Railway will create a database automatically

### 3.3 Configure Backend Service

1. Click **+ New** → **GitHub Repo** → Select your repo again
2. This creates a second service for the backend
3. Click on this new service, then:

**Settings Tab:**
- **Root Directory**: `backend`
- **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`

**Variables Tab** - Click "New Variable" and add each:

| Variable | Value |
|----------|-------|
| `MASSIVE_API_KEY` | `FEqqzDBrV0ZMOmoHR51NNPLHNC1LPrxo` |
| `JWT_SECRET` | (click "Generate" for a random secret) |
| `STRIPE_SECRET_KEY` | `sk_test_51SsI3WLV...` (your Stripe key) |
| `STRIPE_PRICE_ID` | `price_1Qxxxxxxxxxx` (your price ID) |

**Link Database:**
- Click **+ New Variable** → **Add Reference**
- Select your PostgreSQL → Choose `DATABASE_URL`

**Generate Domain:**
- Go to **Settings** → **Networking** → **Generate Domain**
- Copy the URL (e.g., `https://backend-production-xxxx.up.railway.app`)

### 3.4 Configure Frontend Service

1. Click on your first service (the one Railway auto-created from your repo)
2. Configure:

**Settings Tab:**
- **Root Directory**: (leave empty)
- **Start Command**: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`

**Variables Tab:**

| Variable | Value |
|----------|-------|
| `API_URL` | `https://backend-production-xxxx.up.railway.app` (your backend URL) |

**Generate Domain:**
- Go to **Settings** → **Networking** → **Generate Domain**
- Copy the URL - **this is your public app URL!**

---

## Step 4: Set Up Stripe Webhook (For Subscriptions)

After deployment, set up webhooks so Stripe can notify your app about subscription changes:

1. Go to Stripe Dashboard → **Developers** → **Webhooks**
2. Click **+ Add Endpoint**
3. Enter your backend webhook URL:
   ```
   https://backend-production-xxxx.up.railway.app/webhooks/stripe
   ```
4. Click **Select events** and choose:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Click **Add Endpoint**
6. Copy the **Signing Secret** (starts with `whsec_`)
7. Go back to Railway → Backend service → Variables
8. Add: `STRIPE_WEBHOOK_SECRET` = `whsec_xxxxx`

---

## Step 5: Verify Deployment

### Test Backend Health

```bash
curl https://your-backend.up.railway.app/health
```

Should return:
```json
{
  "status": "ok",
  "database": "connected",
  "massive_api": "configured"
}
```

### Test Frontend

1. Visit your frontend URL (e.g., `https://your-frontend.up.railway.app`)
2. You should see the login page
3. Click **Sign Up** with an email and password
4. Run a screen - it should work!

---

## Step 6: Test the Full Flow

### Free User Flow
1. Sign up with a new email
2. You get 5 free screens per day
3. After 5 screens, you'll see "Upgrade to Pro"

### Upgrade Flow (Test Mode)
1. Click "Upgrade to Pro"
2. Use Stripe test card: `4242 4242 4242 4242`
3. Any future date, any CVC
4. Complete checkout
5. Refresh the app - you should see "⭐ Pro Member"

---

## Environment Variables Reference

### Backend Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `DATABASE_URL` | ✅ | PostgreSQL connection string (auto-linked from Railway) |
| `MASSIVE_API_KEY` | ✅ | Your Massive.com API key |
| `JWT_SECRET` | ✅ | Secret for signing JWT tokens (generate a random string) |
| `STRIPE_SECRET_KEY` | ✅ | Stripe API secret key |
| `STRIPE_PRICE_ID` | ✅ | Stripe Price ID for Pro plan |
| `STRIPE_WEBHOOK_SECRET` | ⚠️ | Required for subscription updates |

### Frontend Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `API_URL` | ✅ | URL of your backend service |

---

## Going Live (Production)

When ready to accept real payments:

1. **Stripe**: Switch from Test Mode to Live Mode
   - Get live API keys (`sk_live_...`)
   - Create a live product and price
   - Update Railway variables with live keys

2. **Custom Domain** (Optional):
   - Buy a domain (Namecheap, Google Domains, Cloudflare)
   - In Railway, go to service → **Settings** → **Networking** → **Custom Domain**
   - Add DNS records as instructed
   - Railway auto-generates SSL certificates

---

## Updating Your App

Just push to GitHub - Railway auto-deploys:

```bash
git add .
git commit -m "Your changes"
git push
```

Deployments typically take 1-2 minutes.

---

## Monitoring & Administration

### Railway Dashboard
- View logs, metrics, and deployment history
- Monitor resource usage
- Scale services if needed

### Stripe Dashboard
- View subscriptions and revenue
- Manage customers
- Process refunds

### Database Access
- Railway provides a connection string
- Use a tool like TablePlus or pgAdmin to connect directly

---

## Troubleshooting

### Backend not starting
- Check Railway logs: Click service → **Logs**
- Verify all environment variables are set
- Check `DATABASE_URL` is linked correctly

### Login not working
- Verify backend is running (check `/health` endpoint)
- Check `API_URL` is correct in frontend variables
- Look for errors in browser console

### Stripe checkout fails
- Verify you're using matching test/live keys
- Check `STRIPE_PRICE_ID` is correct
- Test with Stripe test cards first

### Database errors
- Ensure `DATABASE_URL` is linked from PostgreSQL
- Tables are auto-created on first startup
- Check backend logs for SQL errors

---

## Support

If you encounter issues:
1. Check Railway logs for error messages
2. Verify all environment variables are set correctly
3. Test endpoints manually with curl
4. Check browser developer console for frontend errors
