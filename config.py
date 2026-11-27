"""Configuration management for different environments."""
import os
from datetime import timedelta


class Config:
    """Base configuration with sensible defaults."""

    # Flask core
    SECRET_KEY = os.environ.get("SECRET_KEY") or "dev-secret-key-change-in-production"

    # Database
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL") or "sqlite:///instance/abroad.sqlite"
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ECHO = False
    DATABASE = os.environ.get("DATABASE_PATH") or "instance/abroad.sqlite"

    # Redis & Caching
    REDIS_URL = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    ENABLE_REDIS = os.environ.get("ENABLE_REDIS", "0") == "1"
    SESSION_TYPE = "redis"  # Store sessions in Redis, not cookies
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Security
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True
    CSRF_ENABLED = True
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", 6 * 1024 * 1024))

    # File uploads
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER") or "instance/uploads"
    ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "pdf"}
    USE_S3 = os.environ.get("USE_S3", "0") == "1"
    AWS_ACCESS_KEY_ID = os.environ.get("AWS_ACCESS_KEY_ID")
    AWS_SECRET_ACCESS_KEY = os.environ.get("AWS_SECRET_ACCESS_KEY")
    AWS_S3_BUCKET = os.environ.get("AWS_S3_BUCKET")
    AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

    # Cloudinary (alternative to S3)
    USE_CLOUDINARY = os.environ.get("USE_CLOUDINARY", "0") == "1"
    CLOUDINARY_CLOUD_NAME = os.environ.get("CLOUDINARY_CLOUD_NAME")
    CLOUDINARY_API_KEY = os.environ.get("CLOUDINARY_API_KEY")
    CLOUDINARY_API_SECRET = os.environ.get("CLOUDINARY_API_SECRET")

    # Email
    SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
    SENDGRID_FROM_EMAIL = os.environ.get("SENDGRID_FROM_EMAIL", "noreply@abroad.tn")
    SENDGRID_FROM_NAME = os.environ.get("SENDGRID_FROM_NAME", "Abroad")

    # SMS
    TWILIO_ACCOUNT_SID = os.environ.get("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN = os.environ.get("TWILIO_AUTH_TOKEN")
    TWILIO_PHONE_NUMBER = os.environ.get("TWILIO_PHONE_NUMBER")

    # Payments
    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY")
    STRIPE_PUBLISHABLE_KEY = os.environ.get("STRIPE_PUBLISHABLE_KEY")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET")

    # Monitoring
    SENTRY_DSN = os.environ.get("SENTRY_DSN")

    # Business logic
    ALLOW_DEMO_ADMIN = os.environ.get("ALLOW_DEMO_ADMIN", "0") == "1"
    AUTO_INIT = os.environ.get("AUTO_INIT", "1") == "1"
    START_REFUND_SWEEPER = False  # Now handled by Celery
    REFUND_SWEEP_SECONDS = int(os.environ.get("REFUND_SWEEP_SECONDS", 3600))
    RECEIPT_DEADLINE_HOURS = int(os.environ.get("RECEIPT_DEADLINE_HOURS", 48))
    DELIVERY_CODE_EXPIRY_HOURS = int(os.environ.get("DELIVERY_CODE_EXPIRY_HOURS", 24))
    MAX_CODE_ATTEMPTS = int(os.environ.get("MAX_CODE_ATTEMPTS", 5))

    # Rate limiting
    RATELIMIT_ENABLED = os.environ.get("RATE_LIMIT_ENABLED", "1") == "1"
    RATELIMIT_STORAGE_URL = os.environ.get("RATE_LIMIT_STORAGE_URL") or "redis://localhost:6379/1"
    RATELIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "100 per hour")
    RATELIMIT_HEADERS_ENABLED = True

    # Celery
    CELERY_BROKER_URL = os.environ.get("CELERY_BROKER_URL") or "redis://localhost:6379/2"
    CELERY_RESULT_BACKEND = os.environ.get("CELERY_RESULT_BACKEND") or "redis://localhost:6379/3"

    # Feature flags
    ENABLE_SMS_NOTIFICATIONS = os.environ.get("ENABLE_SMS_NOTIFICATIONS", "0") == "1"
    ENABLE_EMAIL_NOTIFICATIONS = os.environ.get("ENABLE_EMAIL_NOTIFICATIONS", "1") == "1"
    ENABLE_RECEIPT_OCR = os.environ.get("ENABLE_RECEIPT_OCR", "0") == "1"
    ENABLE_API = os.environ.get("ENABLE_API", "1") == "1"


class DevelopmentConfig(Config):
    """Development environment configuration."""

    DEBUG = True
    TESTING = False
    SQLALCHEMY_ECHO = True
    SESSION_COOKIE_SECURE = False
    ALLOW_DEMO_ADMIN = True
    RATELIMIT_ENABLED = False


class ProductionConfig(Config):
    """Production environment configuration."""

    DEBUG = False
    TESTING = False
    SESSION_COOKIE_SECURE = True
    ALLOW_DEMO_ADMIN = False

    # Stricter security in production
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)

    # Force certain settings
    if not os.environ.get("SECRET_KEY"):
        raise ValueError("SECRET_KEY must be set in production")

    if not os.environ.get("SENDGRID_API_KEY") and Config.ENABLE_EMAIL_NOTIFICATIONS:
        raise ValueError("SENDGRID_API_KEY must be set when email is enabled")


class TestingConfig(Config):
    """Testing environment configuration."""

    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    DATABASE = ":memory:"
    WTF_CSRF_ENABLED = False
    CSRF_ENABLED = False
    RATELIMIT_ENABLED = False
    ALLOW_DEMO_ADMIN = True
    AUTO_INIT = False
    ENABLE_SMS_NOTIFICATIONS = False
    ENABLE_EMAIL_NOTIFICATIONS = False


# Configuration dictionary
config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
    "default": DevelopmentConfig,
}


def get_config():
    """Get configuration based on FLASK_ENV."""
    env = os.environ.get("FLASK_ENV", "development")
    return config.get(env, config["default"])
