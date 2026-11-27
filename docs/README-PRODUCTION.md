# Production Abroad Marketplace

A modern, scalable marketplace for cross-border shopping in Tunisia.

## ✨ What's New in Production Version

### 🔒 Security
- ✅ Real email service (SendGrid)
- ✅ SMS notifications (Twilio)
- ✅ Payment processing (Stripe)
- ✅ Rate limiting per endpoint
- ✅ Security headers (HSTS, CSP, X-Frame-Options)
- ✅ Input validation schemas
- ✅ Password strength requirements
- ✅ Account lockout after failed attempts
- ✅ HTTPS enforcement
- ✅ File upload security with virus scanning support

### 💾 Database & Infrastructure
- ✅ PostgreSQL support with connection pooling
- ✅ Redis for caching and sessions
- ✅ Celery for background tasks
- ✅ Docker & Docker Compose configuration
- ✅ Nginx reverse proxy with SSL
- ✅ Health check endpoints
- ✅ Structured JSON logging

### 📧 Communications
- ✅ Transactional email templates
- ✅ SMS delivery codes
- ✅ Real-time notifications
- ✅ Webhook handlers for payments

### ☁️ Cloud Storage
- ✅ AWS S3 integration
- ✅ Cloudinary alternative
- ✅ Image processing and optimization
- ✅ EXIF data stripping

### 📊 Monitoring
- ✅ Sentry error tracking
- ✅ Structured logging with rotation
- ✅ Application metrics
- ✅ Request/response logging

### 🚀 Deployment
- ✅ Docker deployment
- ✅ VPS deployment guide
- ✅ Cloud platform support (Heroku, AWS, DigitalOcean)
- ✅ Automated backup scripts
- ✅ Zero-downtime deployment

## 📋 Quick Start

### Development

```bash
# Copy environment template
cp .env.example .env

# Edit .env with your configuration
nano .env

# Install dependencies
pip install -r requirements-production.txt

# Run development server
python app.py
```

### Production (Docker)

```bash
# Configure environment
cp .env.example .env
nano .env

# Start all services
docker-compose up -d

# View logs
docker-compose logs -f

# Check health
curl http://localhost:5000/health
```

## 🔧 Configuration

All configuration is done via environment variables in `.env`:

- **SECRET_KEY**: Flask secret (generate with `python -c "import secrets; print(secrets.token_hex(32))"`)
- **DATABASE_URL**: PostgreSQL connection string
- **REDIS_URL**: Redis connection string
- **SENDGRID_API_KEY**: Email service API key
- **TWILIO_***: SMS service credentials
- **STRIPE_***: Payment gateway credentials
- **AWS_***: S3 storage credentials

See `.env.example` for all available options.

## 📚 Documentation

- [Production Roadmap](PRODUCTION_ROADMAP.md) - Comprehensive improvement checklist
- [Deployment Guide](DEPLOYMENT.md) - Step-by-step deployment instructions
- [Original Proposal](PROPOSAL.md) - Project requirements

## 🏗️ Architecture

```
┌─────────────┐
│   Nginx     │  ← SSL termination, static files, rate limiting
└──────┬──────┘
       │
┌──────▼──────────┐
│  Flask (Gunicorn)│  ← Main application
└──────┬──────────┘
       │
   ┌───┴────┬────────┬────────┐
   ▼        ▼        ▼        ▼
┌────────┐ ┌─────┐ ┌──────┐ ┌───────┐
│Postgres│ │Redis│ │Celery│ │Storage│
└────────┘ └─────┘ └──────┘ └───────┘
```

## 🧪 Testing

```bash
# Run all tests
pytest -v

# Run with coverage
pytest --cov=. --cov-report=html

# Load testing
locust -f tests/load_test.py
```

## 🔐 Security Features

- **Authentication**: Password hashing with PBKDF2, session management
- **Authorization**: Role-based access control (RBAC)
- **CSRF Protection**: Token-based protection on all POST requests
- **Rate Limiting**: Per-IP and per-user limits
- **Input Validation**: Marshmallow schemas for all forms
- **SQL Injection**: Parameterized queries throughout
- **XSS Protection**: Automatic HTML escaping in templates
- **File Upload**: Type validation, size limits, virus scanning support
- **HTTPS**: Enforced in production with HSTS
- **Security Headers**: CSP, X-Frame-Options, X-Content-Type-Options

## 📊 Monitoring & Logging

- **Sentry**: Automatic error tracking and alerting
- **Structured Logs**: JSON format for easy parsing
- **Health Checks**: `/health`, `/health/ready`, `/health/live`
- **Metrics**: Request counts, response times, error rates

## 🌐 API

RESTful API with token authentication:

```bash
# Get API token (from UI)
curl -H "Authorization: Bearer abr_..." \
     http://localhost:5000/api/v1/products
```

See API documentation at `/api/docs` (when enabled).

## 💰 Payment Flow

1. Buyer funds escrow via Stripe
2. Webhook confirms payment
3. Traveler purchases items
4. Admin verifies receipt
5. Delivery with time-limited code
6. Buyer releases escrow
7. Funds distributed to seller + traveler

## 📝 License

Educational project - see LICENSE for details.

## 🤝 Contributing

This is a classroom project that has been enhanced for production readiness.

## 📞 Support

For production deployment support: admin@abroad.tn

---

**Version**: 2.0 (Production Ready)  
**Last Updated**: 2026-11-17
