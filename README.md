# VocalizeBot 🇮🇱

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.109-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/Telegram-Bot-blue.svg" alt="Telegram">
  <img src="https://img.shields.io/badge/Google-AI/Gemini-red.svg" alt="Google AI">
</div>

**VocalizeBot** is an AI-powered Telegram bot that transcribes voice messages into text in seconds. Perfect for Hebrew-speaking users who receive endless voice notes! Built with Google AI (Gemini), it provides fast, accurate transcriptions with a freemium subscription model.

🎯 **Try it now**: [@replyq1_bot](https://t.me/replyq1_bot)

---

## 🚀 Features

### 🎙️ Voice Transcription
- **Instant Transcription**: Convert voice messages to text in under 2 seconds
- **Hebrew Support**: Optimized for Hebrew with excellent accuracy
- **Group Support**: Auto-transcribe voice messages in Telegram groups
- **Multi-format Support**: Works with OGG, MP3, WAV, and other audio formats

### 💳 Subscription Tiers
| Feature | Free | Premium |
|---------|------|---------|
| Daily Transcriptions | 3 | Unlimited |
| Max Voice Length | 30s | 5min |
| Group Transcription | ✅ | ✅ |
| Priority Support | ❌ | ✅ |

### 📊 Admin Dashboard
- **User Management**: View and manage all users
- **Broadcast System**: Send messages to all users or premium only
- **Statistics**: Track usage, conversions, and revenue
- **Subscription Management**: Manual upgrades and refunds

---

## 📱 Termux Setup Guide

### Step 1: Install Termux Dependencies

```bash
# Update package list
pkg update && pkg upgrade -y

# Install Python and required tools
pkg install python python-dev libjpeg-turbo-dev zlib-dev freetype-dev

# Install git and openssl
pkg install git openssl

# Upgrade pip
pip install --upgrade pip
```

### Step 2: Clone and Setup

```bash
# Navigate to your storage
cd /sdcard/VocalizeBot

# Or clone from GitHub
git clone https://github.com/infinityempire/vocalizebot.git
cd vocalizebot

# Make scripts executable
chmod +x check_setup.py
```

### Step 3: Configure Environment

```bash
# Copy the example environment file
cp .env.example .env

# Edit with your favorite editor (nano/vim)
nano .env
```

**Required variables to configure:**
```bash
# Telegram Bot Token (from @BotFather)
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrsTUVwxyz

# Google AI API Key (from https://aistudio.google.com/app/apikey)
GOOGLE_AI_API_KEY=AIzaSy...

# Admin Dashboard Token (generate with: python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ADMIN_DASHBOARD_TOKEN=your_secure_token_here

# PayPal (for premium subscriptions)
PAYPAL_CLIENT_ID=your_paypal_client_id
PAYPAL_CLIENT_SECRET=your_paypal_secret
PAYPAL_UPGRADE_LINK=https://paypal.me/talhatil/premium
```

### Step 4: Install Python Dependencies

```bash
pip install -r requirements.txt
```

### Step 5: Run Self-Diagnostics

```bash
python3 check_setup.py
```

This will verify:
- ✅ Environment variables are configured
- ✅ Python version is correct
- ✅ All dependencies are installed
- ✅ Network connectivity to Telegram & Google AI
- ✅ Dashboard port availability

### Step 6: Start the Bot

**Option A: Run in Foreground (for testing)**
```bash
python3 src/main.py
```

**Option B: Run in Background (recommended for production)**

```bash
# Start the bot in background with nohup
nohup python3 src/main.py > bot.log 2>&1 &

# Check if running
ps aux | grep python

# View logs
tail -f bot.log
```

**Option C: Run Bot and Dashboard Separately**

```bash
# Terminal 1: Run the Telegram Bot (polling mode)
python3 -c "
import asyncio
from src.channels.telegram import start_telegram_bot
from subscription_manager import SubscriptionManager

async def main():
    sub_manager = SubscriptionManager()
    bot = await start_telegram_bot(sub_manager)
    while True:
        await asyncio.sleep(3600)

asyncio.run(main())
"

# Terminal 2: Run the Dashboard (FastAPI on port 8000)
python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000

# Or in background:
nohup python3 -m uvicorn src.main:app --host 0.0.0.0 --port 8000 > dashboard.log 2>&1 &
```

### Step 7: Verify Bot is Running

```bash
# Check bot status
curl http://localhost:8000/health

# Check bot info
curl http://localhost:8000/

# View bot logs
tail -f bot.log
```

---

## 🖥️ Admin Dashboard API

### Authentication
All admin endpoints require the `ADMIN_DASHBOARD_TOKEN` in the Authorization header:
```
Authorization: Bearer YOUR_ADMIN_DASHBOARD_TOKEN
```

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/admin/stats` | GET | Get dashboard statistics |
| `/api/admin/users` | GET | List all users (with pagination) |
| `/api/broadcast/send` | POST | Send broadcast to users |
| `/api/broadcast/stats` | GET | Get user counts |

### Broadcast Example

```bash
# Send message to all users
curl -X POST http://localhost:8000/api/broadcast/send \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "🎉 Special offer! Premium 50% off today!", "target": "all"}'

# Send to premium users only
curl -X POST http://localhost:8000/api/broadcast/send \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"message": "Thank you for being premium! 🎁", "target": "premium"}'
```

---

## 💰 Payment & Subscription

### Free Tier
- 3 transcriptions per day
- Voice messages up to 30 seconds
- Basic support

### Premium Tier
- Unlimited transcriptions
- Voice messages up to 5 minutes
- Priority support
- Monthly subscription via PayPal

### Upgrade Flow
1. User hits daily limit
2. Bot sends upgrade message with PayPal link
3. User pays via PayPal
4. Admin manually upgrades user via API or database

```python
# Manual upgrade via Python
from subscription_manager import SubscriptionManager

sub_manager = SubscriptionManager()
sub_manager.upgrade_tier("USER_ID", "premium", duration_days=30)
```

---

## 🔧 Configuration Reference

| Variable | Description | Required |
|----------|-------------|----------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather | ✅ |
| `GOOGLE_AI_API_KEY` | Google AI Studio API key | ✅ |
| `ADMIN_DASHBOARD_TOKEN` | Secure token for admin API | ✅ |
| `PAYPAL_CLIENT_ID` | PayPal sandbox/live client ID | For payments |
| `PAYPAL_CLIENT_SECRET` | PayPal sandbox/live secret | For payments |
| `PAYPAL_UPGRADE_LINK` | PayPal.me link for upgrades | ✅ |
| `FREE_MAX_TRANSCRIPTIONS` | Daily free transcription limit | Default: 3 |
| `FREE_MAX_VOICE_SECONDS` | Max voice length for free users | Default: 30 |
| `PORT` | Dashboard server port | Default: 8000 |

---

## 📁 Project Structure

```
vocalizebot/
├── config/
│   └── settings.py         # Application settings (Pydantic)
├── src/
│   ├── channels/
│   │   └── telegram.py     # Telegram bot handler
│   ├── services/
│   │   ├── payment.py      # PayPal integration
│   │   └── transcription.py # Google AI transcription
│   ├── database/
│   │   ├── models.py       # SQLAlchemy models
│   │   └── connection.py   # Database connection
│   └── main.py             # FastAPI application
├── subscription_manager.py  # User tiers & paywall
├── check_setup.py          # Self-diagnostic script
├── .env.example            # Environment template
└── requirements.txt        # Dependencies
```

---

## 🧪 Testing

```bash
# Run diagnostics
python3 check_setup.py

# Run unit tests
pytest tests/

# Test Telegram bot locally
python3 -c "
from src.channels.telegram import TelegramBot
from subscription_manager import SubscriptionManager
sub = SubscriptionManager()
bot = TelegramBot(subscription_manager=sub)
print('Bot initialized successfully!')
"
```

---

## 🚢 Deployment

### Termux (Android)
See [📱 Termux Setup Guide](#📱-termux-setup-guide) above.

### VPS/Server
```bash
# Install dependencies
pip install -r requirements.txt

# Run with systemd (example)
sudo tee /etc/systemd/system/vocalizebot.service > /dev/null <<EOF
[Unit]
Description=VocalizeBot Service
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/opt/vocalizebot
ExecStart=/usr/bin/python3 /opt/vocalizebot/src/main.py
Restart=always

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable vocalizebot
sudo systemctl start vocalizebot
```

### Docker
```bash
docker build -t vocalizebot .
docker run -d \
  --name vocalizebot \
  -p 8000:8000 \
  --env-file .env \
  vocalizebot
```

---

## 🔒 Security

- Never commit `.env` to version control
- Use strong tokens for `ADMIN_DASHBOARD_TOKEN`
- Enable HTTPS in production
- Rate limiting is enabled by default
- CORS is configured (use `ALLOWED_ORIGINS` in production)

---

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

---

## 📄 License

MIT License - Built with ❤️ by [Tal HaTil Empire](https://github.com/infinityempire)

---

<div align="center">
  <p>🎙️ VocalizeBot - Stop drowning in voice messages!</p>
  <p>Try it now: <a href="https://t.me/replyq1_bot">@replyq1_bot</a></p>
</div>

