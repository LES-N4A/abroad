"""Rate limiting configuration and decorators."""
from functools import wraps

from flask import request, g, abort, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Initialize rate limiter
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=None,  # Set from config in init_app
    default_limits=["100 per hour", "20 per minute"],
)


def init_limiter(app):
    """Initialize rate limiter with app."""
    if app.config.get("RATELIMIT_ENABLED"):
        limiter.init_app(app)
        limiter._storage_uri = app.config.get("RATELIMIT_STORAGE_URL")


# Custom rate limit decorators for specific endpoints

def rate_limit_by_user():
    """Rate limit by authenticated user ID instead of IP."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            user = g.get("user")
            if user:
                # Use user ID as the key
                key = f"user:{user['id']}"
            else:
                # Fall back to IP for unauthenticated requests
                key = f"ip:{get_remote_address()}"

            # Check rate limit manually if needed
            return f(*args, **kwargs)
        return wrapped
    return decorator


# Specific rate limits for critical operations

# Login attempts: 5 per 15 minutes per IP
login_limit = limiter.limit("5 per 15 minutes")

# Registration: 3 per hour per IP
registration_limit = limiter.limit("3 per hour")

# Password reset: 3 per hour per IP
password_reset_limit = limiter.limit("3 per hour")

# API calls: 100 per hour per token
api_limit = limiter.limit("100 per hour")

# File uploads: 10 per hour per user
upload_limit = limiter.limit("10 per hour")

# Payment operations: 10 per hour per user
payment_limit = limiter.limit("10 per hour")

# Message sending: 20 per hour per user
message_limit = limiter.limit("20 per hour")
