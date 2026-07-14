# VocalizeBot

<div align="center">
  <img src="https://img.shields.io/badge/Python-3.11+-blue.svg" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.109-green.svg" alt="FastAPI">
  <img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="License">
  <img src="https://img.shields.io/badge/WhatsApp-Integration-green.svg" alt="WhatsApp">
  <img src="https://img.shields.io/badge/Instagram-Integration-E4405F.svg" alt="Instagram">
</div>

**VocalizeBot** is an advanced AI-powered customer management, sales coordination, and business operations agent operating over WhatsApp and Instagram. Built with modern AI technologies, it provides intelligent customer interactions, lead qualification, and seamless payment processing.

## 🚀 Features

### Multi-Channel Integration
- **WhatsApp Integration**: Receive and process text messages, media, and voice notes via Twilio
- **Instagram Integration**: Handle DMs, media, and voice messages via Instagram Graph API
- **Voice Note Transcription**: Automatic audio-to-text conversion using OpenAI Whisper

### Omni-Intent AI Engine
- **Intelligent Intent Classification**: Understand customer messages and detect their intent
- **Lead Qualification & Scoring**: Dynamic scoring based on engagement and sales signals
- **Customer Segmentation**: Differentiate behavior between B2B, B2C, and existing customers
- **Blackout Fallback Guard**: Safety mechanism that routes confused AI responses to human agents

### Sales Automation
- **Sales Coordination**: Guide customers through the buying journey
- **Objection Handling**: Professionally address and overcome customer concerns
- **Payment Integration**: Generate Stripe payment links and track payment status
- **Deal Closing**: Direct sales closing in chat with smart recommendations

### Business Operations
- **Customer Management**: Track customer profiles, interactions, and history
- **Complaint Handling**: Automated complaint flows with escalation protocols
- **Follow-up Management**: Automated reminders and re-engagement campaigns
- **Business Analytics**: Pipeline views and sales performance metrics

## 📁 Project Structure

```
vocalizebot/
├── config/                  # Configuration files
│   ├── settings.py         # Application settings (Pydantic)
│   └── __init__.py
├── src/
│   ├── agents/             # AI Agent logic
│   │   ├── core.py         # Main AI agent implementation
│   │   ├── prompts.py      # System prompts & templates
│   │   └── __init__.py
│   ├── channels/           # Channel integrations
│   │   ├── whatsapp.py     # WhatsApp (Twilio) webhook
│   │   ├── instagram.py    # Instagram webhook
│   │   └── __init__.py
│   ├── services/           # Business services
│   │   ├── transcription.py  # Whisper voice transcription
│   │   ├── payment.py      # Stripe payment integration
│   │   ├── sales.py        # Sales coordination
│   │   └── __init__.py
│   ├── database/           # Database models & connection
│   │   ├── models.py       # SQLAlchemy models
│   │   ├── connection.py   # Database connection
│   │   └── __init__.py
│   └── main.py             # FastAPI application
├── tests/                  # Unit tests
│   └── __init__.py
├── main.py                 # Application entry point
├── requirements.txt        # Dependencies
├── .env.example            # Environment variables template
├── .gitignore
└── README.md
```

## 🛠️ Installation

### Prerequisites

- Python 3.11+
- Twilio account (for WhatsApp)
- Instagram Business Account (for Instagram)
- OpenAI API key (for AI and Whisper)
- Stripe account (for payments)

### Setup

1. **Clone the repository**
```bash
git clone https://github.com/yourusername/vocalizebot.git
cd vocalizebot
```

2. **Create virtual environment**
```bash
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
.\venv\Scripts\activate  # Windows
```

3. **Install dependencies**
```bash
pip install -r requirements.txt
```

4. **Configure environment variables**
```bash
cp .env.example .env
# Edit .env with your API keys and configuration
```

5. **Initialize database**
```bash
# The database is automatically created on first run
# Or run manually:
python -c "import asyncio; from src.database.connection import init_db; asyncio.run(init_db())"
```

6. **Run the application**
```bash
python main.py
# Or with uvicorn directly:
uvicorn src.main:app --host 0.0.0.0 --port 8000 --reload
```

## 🔌 API Endpoints

### Webhooks
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhook/whatsapp/webhook` | GET/POST | WhatsApp webhook (Twilio) |
| `/webhook/instagram/webhook` | GET/POST | Instagram webhook |
| `/webhook/stripe` | POST | Stripe payment webhook |

### REST API
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/customers` | GET | List all customers |
| `/api/customers/{id}` | GET | Get customer details |
| `/api/customers/{id}` | PATCH | Update customer |
| `/api/pipeline` | GET | Get sales pipeline |
| `/api/payments/create-link` | POST | Create payment link |
| `/api/sales/{id}/close` | POST | Close a deal |
| `/api/sales/{id}/summary` | GET | Customer sales summary |

### Health & Info
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Application info |
| `/health` | GET | Health check |

## 📱 Setup Guides

### WhatsApp (Twilio)
1. Create a Twilio account
2. Get your Account SID and Auth Token
3. Configure WhatsApp sandbox or business account
4. Set webhook URL: `https://your-domain.com/webhook/whatsapp/webhook`
5. Add credentials to `.env`

### Instagram
1. Create an Instagram Business/Creator account
2. Set up Meta App with Instagram Graph API
3. Configure Webhook URL: `https://your-domain.com/webhook/instagram/webhook`
4. Add credentials to `.env`

### OpenAI
1. Get your API key from [OpenAI](https://platform.openai.com/)
2. Add to `.env` as `OPENAI_API_KEY`

### Stripe
1. Create a Stripe account
2. Get your API keys
3. Configure webhook endpoint: `https://your-domain.com/webhook/stripe`
4. Add credentials to `.env`

## 🔧 Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `OPENAI_API_KEY` | OpenAI API key | Required |
| `ANTHROPIC_API_KEY` | Anthropic API key | Optional |
| `DEFAULT_AI_PROVIDER` | AI provider to use | `openai` |
| `AI_MODEL` | Model to use | `gpt-4-turbo-preview` |
| `TWILIO_ACCOUNT_SID` | Twilio Account SID | Required for WhatsApp |
| `TWILIO_AUTH_TOKEN` | Twilio Auth Token | Required for WhatsApp |
| `STRIPE_API_KEY` | Stripe API key | Required for payments |
| `DATABASE_URL` | Database connection string | `sqlite+aiosqlite:///./vocalizebot.db` |
| `BLACKOUT_MODE_THRESHOLD` | Errors before escalation | `3` |

### Customer Segments

The AI agent automatically detects customer segments:

- **B2B (Business)**: Professional tone, ROI focus, bulk pricing
- **B2C (Consumer)**: Friendly tone, personal benefits
- **Existing Customer**: Loyalty focus, upsell opportunities

### Lead Scoring

Customers are scored 0-100 based on:
- Message engagement
- Purchase intent signals
- Objection handling
- Payment completion

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test file
pytest tests/test_agents.py -v
```

## 🚢 Deployment

### Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

### Docker Compose

```yaml
version: '3.8'
services:
  vocalizebot:
    build: .
    ports:
      - "8000:8000"
    env_file:
      - .env
    depends_on:
      - redis
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
```

## 🔒 Security

- All API keys stored in environment variables
- Webhook signature verification (Twilio, Instagram, Stripe)
- Rate limiting enabled by default
- CORS configuration for REST API
- Database encryption (with proper configuration)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit changes: `git commit -m 'Add amazing feature'`
4. Push to branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🙏 Acknowledgments

- Built with [FastAPI](https://fastapi.tiangolo.com/)
- AI powered by [OpenAI](https://openai.com/)
- WhatsApp integration via [Twilio](https://www.twilio.com/)
- Instagram integration via [Meta Graph API](https://developers.facebook.com/docs/instagram-api/)
- Payments by [Stripe](https://stripe.com/)

---

<div align="center">
  <p>Built with ❤️ by <a href="https://github.com/yourusername">Your Name</a></p>
  <p>VocalizeBot - Advanced Customer Management & Sales</p>
</div>
