# Deployment Guide - Put Options Screener SaaS

This guide walks you through deploying the Put Options Screener as a paid SaaS on Railway.

## Prerequisites

- GitHub account
- Railway account (https://railway.app)
- Clerk account (https://clerk.com)
- Stripe account (https://stripe.com)
- Your Massive.com API key

## Cost Estimate

| Service | Monthly Cost |
|---------|--------------|
| Railway (backend + frontend + DB) | ~$15 |
| Clerk (up to 10K users) | Free |
| Stripe | 2.9% + $0.30 per transaction |
| **Total fixed cost** | **~$15/mo** |

---

## Step 1: Push Code to GitHub

```bash
# If not already a git repo
git init
git add .
git commit -m "Initial SaaS deployment"

# Create repo on GitHub and push
git remote add origin https://github.com/YOUR_USERNAME/put-options-screener.git
git push -u origin main
```

---

## Step 2: Set Up Clerk Authentication

1. Go to https://dashboard.clerk.com
2. Click "Create Application"
3. Name it "Put Options Screener"
4. Enable sign-in options:
   - ✅ Google
   - ✅ Apple
   - ✅ Email
5. Click "Create Application"

### Get Your Keys
- Go to **API Keys** in the sidebar
- Copy:
  - `CLERK_PUBLISHABLE_KEY` (starts with `pk_`)
  - `CLERK_SECRET_KEY` (starts with `sk_`)

### Configure Redirect URLs
- Go to **Paths** in sidebar
- Add your Railway frontend URL once deployed (e.g., `https://your-app.up.railway.app`)

---

## Step 3: Set Up Stripe Billing

1. Go to https://dashboard.stripe.com
2. Click **Products** → **Add Product**
3. Create your Pro plan:
   - Name: "Pro Plan"
   - Price: $9.99/month (recurring)
4. Copy the **Price ID** (starts with `price_`)

### Get Your Keys
- Go to **Developers** → **API Keys**
- Copy:
  - `STRIPE_SECRET_KEY` (starts with `sk_live_` or `sk_test_`)

### Webhook Setup (After Deployment)
- Go to **Developers** → **Webhooks**
- Add endpoint: `https://YOUR-BACKEND.up.railway.app/webhooks/stripe`
- Select events:
  - `customer.subscription.created`
  - `customer.subscription.updated`
  - `customer.subscription.deleted`
- Copy the **Webhook Signing Secret** (starts with `whsec_`)

---

## Step 4: Deploy to Railway

### 4.1 Create Railway Project

1. Go to https://railway.app
2. Click **New Project** → **Deploy from GitHub repo**
3. Authorize Railway to access your GitHub
4. Select your repository

### 4.2 Add PostgreSQL Database

1. In your Railway project, click **New** → **Database** → **PostgreSQL**
2. Railway will create a database and auto-generate `DATABASE_URL`

### 4.3 Deploy Backend Service

1. Click **New** → **GitHub Repo** → Select your repo again
2. Railway will detect it as a second service
3. Configure the backend:

   **Settings Tab:**
   - Root Directory: `backend`
   - Start Command: `uvicorn main:app --host 0.0.0.0 --port $PORT`

   **Variables Tab (Add these):**
   ```
   MASSIVE_API_KEY=your_massive_api_key
   CLERK_SECRET_KEY=sk_live_xxx
   CLERK_PUBLISHABLE_KEY=pk_live_xxx
   STRIPE_SECRET_KEY=sk_live_xxx
   STRIPE_WEBHOOK_SECRET=whsec_xxx
   STRIPE_PRICE_ID=price_xxx
   ```

   **Link Database:**
   - Click **Add Variable** → **Add Reference** → Select your PostgreSQL → `DATABASE_URL`

4. Go to **Settings** → **Networking** → **Generate Domain**
5. Copy the URL (e.g., `https://backend-xxx.up.railway.app`)

### 4.4 Deploy Frontend Service

1. Click on your first service (the one Railway auto-created)
2. Configure the frontend:

   **Settings Tab:**
   - Root Directory: (leave empty - uses project root)
   - Start Command: `streamlit run app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`

   **Variables Tab (Add these):**
   ```
   API_URL=https://backend-xxx.up.railway.app
   CLERK_PUBLISHABLE_KEY=pk_live_xxx
   ```

3. Go to **Settings** → **Networking** → **Generate Domain**
4. Copy the URL - this is your public app URL!

---

## Step 5: Configure Clerk Redirect

1. Go back to Clerk Dashboard
2. Go to **Paths** → **Redirect URLs**
3. Add your Railway frontend URL: `https://your-frontend.up.railway.app`

---

## Step 6: Configure Stripe Webhook

1. Go to Stripe Dashboard → **Developers** → **Webhooks**
2. Click **Add Endpoint**
3. Enter your backend webhook URL: `https://backend-xxx.up.railway.app/webhooks/stripe`
4. Select events:
   - `customer.subscription.created`
   - `customer.subscription.updated`
   - `customer.subscription.deleted`
5. Copy the Signing Secret
6. Add it to Railway backend variables as `STRIPE_WEBHOOK_SECRET`

---

## Step 7: Verify Deployment

### Test Health Check
```bash
curl https://backend-xxx.up.railway.app/health
```
Should return:
```json
{"status": "ok", "database": "connected", "massive_api": "configured"}
```

### Test Frontend
1. Visit your frontend URL
2. You should see the login page
3. Sign in with Google
4. Run a screen - should work!

---

## Troubleshooting

### Backend not starting
- Check Railway logs: Click service → **Logs**
- Common issues:
  - Missing environment variables
  - Database connection failed

### Frontend shows "Auth not configured"
- Verify `CLERK_PUBLISHABLE_KEY` is set
- Check that Clerk redirect URL includes your Railway domain

### Stripe checkout not working
- Verify `STRIPE_SECRET_KEY` and `STRIPE_PRICE_ID` are correct
- Check if using test mode keys vs live keys

### Database errors
- Ensure `DATABASE_URL` is linked from PostgreSQL service
- Tables are auto-created on first startup

---

## Custom Domain (Optional)

1. Buy a domain (Namecheap, Google Domains, etc.)
2. In Railway, go to your frontend service → **Settings** → **Networking**
3. Click **Custom Domain** → Enter your domain
4. Add the DNS records Railway provides to your domain registrar
5. Railway auto-generates SSL certificate

Example:
- `optionsscreener.com` → Frontend
- `api.optionsscreener.com` → Backend

---

## Updating the App

Just push to GitHub:
```bash
git add .
git commit -m "Your changes"
git push
```

Railway auto-deploys on every push to main branch.

---

## Monitoring

- **Railway Dashboard**: View logs, metrics, and deployments
- **Clerk Dashboard**: View users, logins, and auth events
- **Stripe Dashboard**: View subscriptions, revenue, and payments

---

## Support

If you encounter issues:
1. Check Railway logs for error messages
2. Verify all environment variables are set correctly
3. Test endpoints manually with curl
