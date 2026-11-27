# Abroad Deployment Guide

## Prerequisites

- Python 3.11+
- PostgreSQL 15+
- Redis 7+
- Nginx (for production)
- Domain with SSL certificate

## Environment Setup

1. **Copy environment template:**
```bash
cp .env.example .env
```

2. **Edit `.env` and set all required values:**
- Generate a secure `SECRET_KEY`: `python -c "import secrets; print(secrets.token_hex(32))"`
- Set database credentials
- Add API keys for SendGrid, Twilio, Stripe
- Configure AWS S3 or Cloudinary

## Local Development

```bash
# Create virtual environment
python -m venv .venv

# Activate (Windows)
.venv\Scripts\activate

# Activate (Linux/Mac)
source .venv/bin/activate

# Install dependencies
pip install -r requirements-production.txt

# Initialize database
flask db upgrade  # or: python -m flask init-db

# Run development server
python app.py
```

## Production Deployment

### Option 1: Docker (Recommended)

```bash
# Build and start all services
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop services
docker-compose down
```

### Option 2: VPS Deployment

#### 1. Install System Dependencies

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install -y python3.11 python3-pip postgresql redis-server nginx

# Start services
sudo systemctl enable postgresql redis-server nginx
sudo systemctl start postgresql redis-server nginx
```

#### 2. Set Up PostgreSQL

```bash
sudo -u postgres psql

CREATE DATABASE abroad_production;
CREATE USER abroad_user WITH PASSWORD 'secure_password_here';
GRANT ALL PRIVILEGES ON DATABASE abroad_production TO abroad_user;
\q
```

#### 3. Deploy Application

```bash
# Clone repository
git clone https://github.com/yourusername/abroad.git
cd abroad

# Create virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements-production.txt

# Set up environment
cp .env.example .env
nano .env  # Edit configuration

# Initialize database
flask db upgrade

# Test application
gunicorn -w 4 -b 127.0.0.1:5000 "app:create_app()"
```

#### 4. Set Up Systemd Services

Create `/etc/systemd/system/abroad-web.service`:

```ini
[Unit]
Description=Abroad Web Application
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=abroad
Group=abroad
WorkingDirectory=/home/abroad/abroad
Environment="PATH=/home/abroad/abroad/.venv/bin"
ExecStart=/home/abroad/abroad/.venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 "app:create_app()"
Restart=always

[Install]
WantedBy=multi-user.target
```

Create `/etc/systemd/system/abroad-celery.service`:

```ini
[Unit]
Description=Abroad Celery Worker
After=network.target redis.service

[Service]
Type=forking
User=abroad
Group=abroad
WorkingDirectory=/home/abroad/abroad
Environment="PATH=/home/abroad/abroad/.venv/bin"
ExecStart=/home/abroad/abroad/.venv/bin/celery -A tasks.celery worker --detach
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:

```bash
sudo systemctl enable abroad-web abroad-celery
sudo systemctl start abroad-web abroad-celery
```

#### 5. Configure Nginx

Create `/etc/nginx/sites-available/abroad`:

```nginx
server {
    listen 80;
    server_name abroad.tn www.abroad.tn;
    
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Enable site:

```bash
sudo ln -s /etc/nginx/sites-available/abroad /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 6. Set Up SSL with Let's Encrypt

```bash
sudo apt install certbot python3-certbot-nginx
sudo certbot --nginx -d abroad.tn -d www.abroad.tn
```

### Option 3: Cloud Platform

#### Heroku

```bash
# Login to Heroku
heroku login

# Create app
heroku create abroad-marketplace

# Add PostgreSQL
heroku addons:create heroku-postgresql:mini

# Add Redis
heroku addons:create heroku-redis:mini

# Set environment variables
heroku config:set SECRET_KEY=your_secret_key
heroku config:set SENDGRID_API_KEY=your_key
# ... set all other vars

# Deploy
git push heroku main

# Run migrations
heroku run flask db upgrade

# Scale workers
heroku ps:scale web=2 worker=1
```

#### AWS Elastic Beanstalk

See AWS documentation for detailed setup.

#### DigitalOcean App Platform

1. Connect GitHub repository
2. Configure environment variables
3. Set build/run commands
4. Deploy

## Database Migrations

```bash
# Create migration
flask db migrate -m "Description of changes"

# Apply migration
flask db upgrade

# Rollback migration
flask db downgrade
```

## Monitoring

### View Logs

```bash
# Docker
docker-compose logs -f web

# Systemd
sudo journalctl -u abroad-web -f

# Log files
tail -f logs/abroad.log
tail -f logs/abroad-errors.log
```

### Health Checks

```bash
curl http://localhost:5000/health
```

### Sentry Integration

Errors are automatically reported to Sentry when `SENTRY_DSN` is configured.

## Backups

### Automated Daily Backups

Add to crontab:

```bash
0 2 * * * /home/abroad/abroad/.venv/bin/python /home/abroad/abroad/scripts/backup.py
```

### Manual Backup

```bash
python scripts/backup.py
```

### Restore from Backup

```bash
# PostgreSQL
gunzip -c backups/abroad_backup_TIMESTAMP.sql.gz | psql DATABASE_URL

# SQLite
gunzip -c backups/abroad_backup_TIMESTAMP.sqlite.gz > instance/abroad.sqlite
```

## Security Checklist

- [ ] Change default `SECRET_KEY`
- [ ] Use strong database passwords
- [ ] Enable HTTPS with valid SSL certificate
- [ ] Set `SESSION_COOKIE_SECURE=1`
- [ ] Disable `ALLOW_DEMO_ADMIN`
- [ ] Configure firewall (allow only 80, 443, 22)
- [ ] Set up fail2ban for SSH
- [ ] Enable database backups
- [ ] Configure Sentry for error monitoring
- [ ] Set up log rotation
- [ ] Review and restrict file upload permissions
- [ ] Enable rate limiting
- [ ] Configure CORS properly if needed

## Troubleshooting

### Application won't start

```bash
# Check logs
journalctl -u abroad-web -n 50

# Test configuration
flask --app app:create_app() shell
```

### Database connection issues

```bash
# Test connection
psql $DATABASE_URL

# Check PostgreSQL is running
sudo systemctl status postgresql
```

### Redis connection issues

```bash
# Test Redis
redis-cli ping

# Check Redis is running
sudo systemctl status redis
```

### Celery not processing tasks

```bash
# Check Celery status
celery -A tasks.celery inspect active

# Restart Celery
sudo systemctl restart abroad-celery
```

## Performance Tuning

### Gunicorn Workers

Rule of thumb: `(CPU cores × 2) + 1`

```bash
gunicorn -w 9 -b 0.0.0.0:5000 "app:create_app()"  # For 4 cores
```

### Database Optimization

```sql
-- Create indexes for common queries
CREATE INDEX idx_users_email ON users(email);
CREATE INDEX idx_carts_status ON carts(status, created_at);
```

### Redis Memory

Edit `/etc/redis/redis.conf`:

```
maxmemory 256mb
maxmemory-policy allkeys-lru
```

## Scaling

### Horizontal Scaling

1. Deploy multiple web instances behind load balancer
2. Use shared PostgreSQL and Redis
3. Store uploads on S3/Cloudinary (not local filesystem)
4. Use CDN for static assets

### Vertical Scaling

Increase server resources as needed.

## Support

For issues, contact: admin@abroad.tn
