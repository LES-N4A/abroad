"""Security middleware and utilities."""
import secrets
from functools import wraps

from flask import request, abort, current_app
from flask_talisman import Talisman

# Content Security Policy
CSP = {
    'default-src': ["'self'"],
    'script-src': [
        "'self'",
        "'unsafe-inline'",  # For inline scripts (ideally move to external files)
        "https://js.stripe.com",
        "https://cdn.jsdelivr.net",
    ],
    'style-src': [
        "'self'",
        "'unsafe-inline'",  # For inline styles
        "https://cdnjs.cloudflare.com",
        "https://fonts.googleapis.com",
    ],
    'img-src': [
        "'self'",
        "data:",
        "https:",  # Allow images from any HTTPS source
    ],
    'font-src': [
        "'self'",
        "https://fonts.gstatic.com",
        "https://cdnjs.cloudflare.com",
    ],
    'connect-src': [
        "'self'",
        "https://api.stripe.com",
    ],
    'frame-src': [
        "https://js.stripe.com",
    ],
}


def init_security(app):
    """Initialize security headers and HTTPS enforcement."""
    if app.config.get("ENV") == "production":
        Talisman(
            app,
            force_https=True,
            strict_transport_security=True,
            strict_transport_security_max_age=31536000,  # 1 year
            content_security_policy=CSP,
            content_security_policy_nonce_in=['script-src'],
            referrer_policy='strict-origin-when-cross-origin',
            feature_policy={
                'geolocation': "'none'",
                'microphone': "'none'",
                'camera': "'none'",
            }
        )


def generate_password_reset_token():
    """Generate a secure token for password reset."""
    return secrets.token_urlsafe(32)


def verify_password_strength(password: str) -> tuple[bool, str]:
    """
    Verify password meets security requirements.

    Returns:
        (is_valid, error_message)
    """
    if len(password) < 12:
        return False, "Password must be at least 12 characters"

    if not any(c.isupper() for c in password):
        return False, "Password must contain at least one uppercase letter"

    if not any(c.islower() for c in password):
        return False, "Password must contain at least one lowercase letter"

    if not any(c.isdigit() for c in password):
        return False, "Password must contain at least one number"

    if not any(c in "!@#$%^&*()_+-=[]{}|;:,.<>?" for c in password):
        return False, "Password must contain at least one special character"

    return True, ""


def require_https():
    """Decorator to require HTTPS for sensitive endpoints."""
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if not request.is_secure and current_app.config.get("ENV") == "production":
                abort(403, description="HTTPS required")
            return f(*args, **kwargs)
        return wrapped
    return decorator


def sanitize_filename(filename: str) -> str:
    """Sanitize filename to prevent path traversal."""
    from werkzeug.utils import secure_filename
    import os

    # Remove any directory components
    filename = os.path.basename(filename)

    # Use werkzeug's secure_filename
    filename = secure_filename(filename)

    # Additional sanitization
    filename = filename.replace("..", "")
    filename = filename.replace("/", "")
    filename = filename.replace("\\", "")

    return filename


def verify_file_type(file_path: str, allowed_types: list) -> bool:
    """Verify file type by magic number, not just extension."""
    try:
        import magic

        mime = magic.from_file(file_path, mime=True)
        return mime in allowed_types
    except Exception:
        # Fall back to extension check if python-magic not available
        import os
        ext = os.path.splitext(file_path)[1].lower()
        return ext in [f".{t.split('/')[-1]}" for t in allowed_types]


def check_account_lockout(email: str) -> bool:
    """
    Check if account is locked due to failed login attempts.

    Returns:
        True if account is locked, False otherwise
    """
    from db import query
    from datetime import datetime, timedelta

    # Check failed login attempts in last 15 minutes
    cutoff = (datetime.now() - timedelta(minutes=15)).strftime("%Y-%m-%d %H:%M:%S")

    attempts = query(
        """SELECT COUNT(*) as count FROM audit_log
           WHERE action = 'login_failed'
           AND details = ?
           AND created_at > ?""",
        (email, cutoff),
        one=True
    )

    return attempts and attempts["count"] >= 5


def record_login_attempt(email: str, success: bool):
    """Record login attempt for security auditing."""
    from db import execute
    from datetime import datetime

    action = "login_success" if success else "login_failed"

    execute(
        """INSERT INTO audit_log (action, entity, details, created_at)
           VALUES (?, ?, ?, ?)""",
        (action, "auth", email, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
