# 🚀 MegaETH Telegram Bot - Railway Deployment

A Telegram bot for MegaETH chain token alerts, AI chat, and **Portal verification** (like Safeguard), ready for Railway deployment.

## Features

- 📊 **Token Alerts** - New launches, price pumps/dumps, volume spikes
- 💬 **AI Chat** - Powered by Mogra API
- 🔍 **Token Search** - Search any MegaETH token
- 📈 **Market Data** - Trending, gainers, losers, new pairs
- 🔐 **Portal Verification** - Protect your private groups with verification

## 🔐 Portal Feature (Like Safeguard)

Create verification portals to protect your private groups:

1. **Setup Portal** - Link public channel → private group
2. **Post Verification** - Users click button to verify
3. **Auto-Kick** - Unverified users are kicked automatically

### Portal Commands

| Command | Description |
|---------|-------------|
| `/portal setup` | Start setup wizard |
| `/portal list` | List your portals |
| `/portal post <id>` | Get verification message |
| `/portal stats <id>` | View statistics |
| `/portal settings <id>` | Configure portal |
| `/portal delete <id>` | Delete portal |

### How Portal Works

```
Public Channel                    Private Group
┌─────────────────┐              ┌─────────────────┐
│  📢 Your Channel │              │  🔒 Your Group  │
│                 │              │                 │
│  [Verify & Join]│──Verified──▶│  ✅ Allowed     │
│     Button      │              │                 │
└─────────────────┘              │  ❌ Kicked if   │
                                 │  not verified   │
                                 └─────────────────┘
```

## 🚂 Deploy to Railway

### One-Click Deploy

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/template)

### Manual Deploy

1. **Fork/Clone this repository**

2. **Create new project on Railway**
   - Go to [railway.app](https://railway.app)
   - Click "New Project"
   - Select "Deploy from GitHub repo"
   - Choose this repository

3. **Add Environment Variables**
   
   In Railway dashboard → Variables, add:
   
   | Variable | Required | Description |
   |----------|----------|-------------|
   | `TELEGRAM_BOT_TOKEN` | ✅ | Get from [@BotFather](https://t.me/BotFather) |
   | `MOGRA_API_KEY` | ✅ | Get from [mogra.xyz](https://mogra.xyz) |
   | `MIN_VOLUME_USD` | ❌ | Min volume for alerts (default: 1000) |
   | `MIN_LIQUIDITY_USD` | ❌ | Min liquidity for alerts (default: 500) |
   | `PRICE_CHANGE_THRESHOLD` | ❌ | % change for alerts (default: 10) |
   | `POLL_INTERVAL` | ❌ | Seconds between checks (default: 30) |

4. **Deploy**
   - Railway will automatically build and deploy
   - Check logs for "🚀 Starting MegaETH Telegram Bot..."

### Add Persistent Storage (Recommended)

To persist the SQLite database between deployments:

1. Go to your project in Railway
2. Click "New" → "Volume"
3. Set mount path to `/app/data`
4. Redeploy the service

## 📁 Project Structure

```
megaeth_railway_bot/
├── bot.py                  # Main bot + health server
├── config.py               # Environment config
├── dexscreener_client.py   # DexScreener API
├── mogra_client.py         # Mogra AI API
├── alert_service.py        # Token monitoring
├── database.py             # SQLite database
├── requirements.txt        # Dependencies
├── Dockerfile              # Docker build
├── railway.toml            # Railway config
├── nixpacks.toml           # Nixpacks config
├── Procfile                # Process file
└── README.md               # This file
```

## 🤖 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Start the bot |
| `/help` | Show help |
| `/alerts` | Manage alerts |
| `/subscribe` | Subscribe to alerts |
| `/unsubscribe` | Unsubscribe |
| `/trending` | Top tokens by volume |
| `/new` | New tokens (24h) |
| `/gainers` | Top gainers |
| `/losers` | Top losers |
| `/search <query>` | Search token |
| `/price <symbol>` | Get price |
| `/chat` | Start AI chat |
| `/setchat <id>` | Set Mogra chat ID |
| `/portal` | Portal commands (see above) |

## 🔧 Environment Variables

```bash
# Required
TELEGRAM_BOT_TOKEN=your_bot_token
MOGRA_API_KEY=your_mogra_key

# Optional (with defaults)
PORT=8080
POLL_INTERVAL=30
MIN_VOLUME_USD=1000
MIN_LIQUIDITY_USD=500
PRICE_CHANGE_THRESHOLD=10.0
NEW_PAIR_AGE_MINUTES=60
DATABASE_PATH=/app/data/megaeth_bot.db

# Portal Settings
PORTAL_INVITE_EXPIRY_MINUTES=5
PORTAL_MAX_USES=1
```

## 🏥 Health Check

The bot runs a health check server on port `8080`:

- `GET /` - Health status
- `GET /health` - Health status

Railway uses this to monitor the service.

## 📊 API Sources

- **DexScreener**: https://api.dexscreener.com (MegaETH chain data)
- **Mogra**: https://mogra.xyz/api (AI chat)

## 🛠️ Local Development

```bash
# Clone repo
git clone <your-repo>
cd megaeth_railway_bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Set environment variables
export TELEGRAM_BOT_TOKEN=your_token
export MOGRA_API_KEY=your_key

# Run
python bot.py
```

## 📝 License

MIT License

## ⚠️ Disclaimer

This bot is for informational purposes only. Not financial advice. Always DYOR.
