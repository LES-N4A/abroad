# Abroad - Quick Start Guide

## 🚀 Get Started in 5 Minutes

### Prerequisites
- Python 3.11+
- pip

### Step 1: Install Dependencies
```bash
pip install -r requirements-production.txt
```

### Step 2: Set Up Environment
```bash
cp .env.example .env
```

**Minimum `.env` for development:**
```env
SECRET_KEY=dev-secret-change-in-production
DATABASE_URL=sqlite:///instance/abroad.sqlite
REDIS_URL=redis://localhost:6379/0
ENABLE_EMAIL_NOTIFICATIONS=0
ENABLE_SMS_NOTIFICATIONS=0
ALLOW_DEMO_ADMIN=1
RATELIMIT_ENABLED=0
```

### Step 3: Run Application
```bash
# Option A: Production-ready version
python app_production.py

# Option B: Original classroom version
python app.py
```

### Step 4: Access Application
Open browser: http://localhost:5000

**Demo accounts (password: `demo1234`):**
- Buyer: sarra@abroad.tn
- Seller: store@abroad.tn
- Traveler: ahmed@abroad.tn
- Admin: admin@abroad.tn

---

## 🐳 Docker Quickstart

```bash
# Configure
cp .env.example .env
nano .env

# Start everything
docker-compose up -d

# Check status
docker-compose ps

# View logs
docker-compose logs -f web

# Stop
docker-compose down
```

---

## 📋 What You Get

### Development Mode (No API Keys Needed)
- ✅ Full marketplace functionality
- ✅ Mock email/SMS (logged to console)
- ✅ Local file storage
- ✅ SQLite database
- ✅ Demo admin access

### Production Mode (API Keys Required)
- ✅ Real email via SendGrid
- ✅ Real SMS via Twilio
- ✅ Real payments via Stripe
- ✅ Cloud storage (S3/Cloudinary)
- ✅ PostgreSQL database
- ✅ Redis caching
- ✅ Background jobs (Celery)
- ✅ Error monitoring (Sentry)

---

## 🔑 API Keys (Production)

### 1. SendGrid (Email)
Sign up: https://sendgrid.com/free
- Get API key from Settings → API Keys
- Add to `.env`: `SENDGRID_API_KEY=SG.xxx`

### 2. Twilio (SMS)
Sign up: https://www.twilio.com/try-twilio
- Get Account SID and Auth Token from Console
- Add to `.env`: `TWILIO_ACCOUNT_SID=xxx` and `TWILIO_AUTH_TOKEN=xxx`

### 3. Stripe (Payments)
Sign up: https://stripe.com
- Get keys from Dashboard → Developers → API keys
- Use test keys for development
- Add to `.env`: `STRIPE_SECRET_KEY=sk_test_xxx`

### 4. AWS S3 (Storage)
Sign up: https://aws.amazon.com
- Create S3 bucket
- Create IAM user with S3 permissions
- Add to `.env`: `AWS_ACCESS_KEY_ID=xxx`, `AWS_SECRET_ACCESS_KEY=xxx`

### 5. Sentry (Monitoring)
Sign up: https://sentry.io
- Create project
- Copy DSN
- Add to `.env`: `SENTRY_DSN=https://xxx@sentry.io/xxx`

---

## ⚡ Common Commands

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
.venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements-production.txt

# Run development server
python app_production.py

# Run tests
pytest -v

# Create admin user
flask create-admin admin@abroad.tn

# Set user password
flask set-password user@example.com

# Backup database
python scripts/backup.py

# Check setup
python test_setup.py
```

---

## 🔧 Troubleshooting

### "Module not found"
```bash
pip install -r requirements-production.txt
```

### "Port already in use"
```bash
# Kill process on port 5000
# Windows
netstat -ano | findstr :5000
taskkill /PID <pid> /F

# Linux/Mac
lsof -ti:5000 | xargs kill -9
```

### "Database is locked"
```bash
# Use PostgreSQL in production
# Install: https://www.postgresql.org/download/
DATABASE_URL=postgresql://user:pass@localhost/abroad
```

### "Redis connection failed"
```bash
# Install Redis
# Windows: https://redis.io/docs/install/install-redis/install-redis-on-windows/
# Linux: sudo apt install redis-server
# Mac: brew install redis

# Start Redis
redis-server
```

---

## 📖 Full Documentation

- **IMPLEMENTATION_SUMMARY.md** - What was built
- **PRODUCTION_ROADMAP.md** - Complete feature list
- **DEPLOYMENT.md** - Production deployment guide
- **README-PRODUCTION.md** - Project overview

---

## ✅ Next Steps

1. **Development**: Use app as-is with mock services
2. **Testing**: Run `pytest -v` to verify everything works
3. **Production**: Get API keys and configure `.env`
4. **Deploy**: Follow DEPLOYMENT.md for your platform

---

## 💡 Tips

- Start with **development mode** (no API keys needed)
- Test with **demo accounts** (password: demo1234)
- Enable **one service at a time** (email first, then SMS, then payments)
- Use **Docker** for easiest production setup
- Check **logs/** folder for debugging

---

## 🆘 Need Help?

1. Check health endpoint: http://localhost:5000/health
2. View logs: `tail -f logs/abroad.log`
3. Read DEPLOYMENT.md for detailed guides
4. Check PRODUCTION_ROADMAP.md for features

---

**🎉 You're all set! Start building your marketplace!**
