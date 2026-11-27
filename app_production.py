"""
Production-ready Flask application factory.
Integrates all security, monitoring, and infrastructure improvements.
"""
import os
import sys
from datetime import datetime

import click
import sentry_sdk
from dotenv import load_dotenv
from flask import Flask, abort, g, redirect, render_template, request, send_from_directory, session, url_for
from sentry_sdk.integrations.flask import FlaskIntegration
from werkzeug.exceptions import HTTPException

# Load environment variables
load_dotenv()

# Import configuration
from config import get_config

# Import existing modules
import db
import seed as seed_module
from auth import auth_bp
from constants import ROLE_HOME, ROLE_ICON, ROLE_LABEL, ROLE_NAV
from db import get_db
from security import csrf_token, hash_password, valid_csrf
from services import unread_counts
from views import main_bp

# Import new production modules
from health import health_bp
from webhooks import webhooks_bp
from rate_limiting import init_limiter, limiter
from middleware.security import init_security
from middleware.logging_config import init_logging, log_request_context


def create_app(test_config=None):
    """Create and configure the Flask application."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="assets",
        static_url_path="/assets",
    )

    # Load configuration
    if test_config is None:
        config_obj = get_config()
        app.config.from_object(config_obj)
    else:
        app.config.update(test_config)

    # Initialize Sentry for error monitoring
    if app.config.get("SENTRY_DSN") and not app.config.get("TESTING"):
        sentry_sdk.init(
            dsn=app.config["SENTRY_DSN"],
            integrations=[FlaskIntegration()],
            environment=app.config.get("ENV", "production"),
            traces_sample_rate=0.1,
        )

    # Store app start time for health checks
    app.config["START_TIME"] = datetime.now().isoformat()

    # Create necessary directories
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config.get("UPLOAD_FOLDER", "instance/uploads"), exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    # Initialize logging
    init_logging(app)
    log_request_context(app)

    # Initialize security headers
    init_security(app)

    # Initialize rate limiting
    init_limiter(app)

    # Initialize database
    db.init_app(app)

    # Register blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(health_bp)

    # Register webhooks only if payment is enabled
    if app.config.get("STRIPE_SECRET_KEY"):
        app.register_blueprint(webhooks_bp)

    # Jinja2 filters (existing)
    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["dinars"] = dinars
    app.jinja_env.filters["when"] = when
    app.jinja_env.filters["day"] = day
    app.jinja_env.filters["initials"] = initials
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["ROLE_LABEL"] = ROLE_LABEL
    app.jinja_env.globals["ROLE_ICON"] = ROLE_ICON
    app.jinja_env.globals["today"] = lambda: datetime.now().strftime("%d %b %Y")

    # CSRF protection
    @app.before_request
    def protect_from_csrf():
        if request.method == "POST" and app.config.get("CSRF_ENABLED", True):
            if not valid_csrf():
                abort(400, description="Your form session expired. Reload the page and try again.")

    # Context processor for navigation
    @app.context_processor
    def inject_navigation():
        user = g.get("user")
        notifications = messages = 0
        if user:
            notifications, messages = unread_counts(user["id"])
        is_admin = bool(user and user["is_admin"])
        if is_admin:
            role_key = "admin"
        elif user:
            role_key = user["role"]
        else:
            role_key = None
        return {
            "current_user": user,
            "nav_items": ROLE_NAV.get(role_key, []),
            "active_endpoint": request.endpoint,
            "unread_notifications": notifications,
            "unread_messages": messages,
            "role_home": (
                url_for(ROLE_HOME[role_key]) if role_key else url_for("auth.login")
            ),
            "role_label": ROLE_LABEL.get(role_key, "Member") if role_key else "Member",
            "role_icon": ROLE_ICON.get(role_key, "fa-user") if role_key else "fa-user",
            "is_admin": is_admin,
        }

    # File uploads
    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    # Error handlers
    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, message="That page belongs to another account."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="We could not find that page."), 404

    @app.errorhandler(429)
    def rate_limit_exceeded(error):
        return render_template("error.html", code=429, message="Too many requests. Please slow down."), 429

    @app.errorhandler(HTTPException)
    def http_error(error):
        return render_template("error.html", code=error.code, message=error.description), error.code

    # Legacy URL redirects
    @app.route("/login.html")
    def legacy_login():
        return redirect(url_for("auth.login"))

    @app.route("/buyer-dashboard.html")
    def legacy_buyer():
        return redirect(url_for("main.buyer_dashboard"))

    @app.route("/seller-dashboard.html")
    def legacy_seller():
        return redirect(url_for("main.seller_dashboard"))

    @app.route("/traveler-dashboard.html")
    def legacy_traveler():
        return redirect(url_for("main.traveler_dashboard"))

    @app.route("/pro-dashboard.html")
    def legacy_pro():
        return redirect(url_for("main.pro_dashboard"))

    # Initialize database if needed
    if app.config.get("AUTO_INIT", True):
        with app.app_context():
            initialise_if_needed()

    # Background refund sweeper (disabled in production - use Celery)
    if (
        app.config.get("START_REFUND_SWEEPER", False)
        and not app.config.get("TESTING")
        and "pytest" not in sys.modules
    ):
        app.logger.warning(
            "Refund sweeper enabled in request handler. "
            "Use Celery tasks in production for better performance."
        )
        from refunds import start_refund_sweeper
        start_refund_sweeper(app)

    # CLI Commands
    @app.cli.command("set-password")
    @click.argument("email")
    @click.password_option()
    def set_password(email, password):
        """Set a user's password without putting it in shell history."""
        user = db.query(
            "SELECT id FROM users WHERE email = ?", (email.strip().lower(),), one=True
        )
        if not user:
            raise click.ClickException(f"No account found for {email}")
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(password), user["id"]),
        )
        click.echo(f"Password updated for {email}")

    @app.cli.command("create-admin")
    @click.argument("email")
    @click.password_option()
    def create_admin(email, password):
        """Create an admin user."""
        from security import hash_password

        user = db.query(
            "SELECT id FROM users WHERE email = ?", (email.strip().lower(),), one=True
        )
        if user:
            db.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (user["id"],))
            click.echo(f"User {email} promoted to admin")
        else:
            click.echo("User not found. Create account first, then run this command.")

    return app


def initialise_if_needed():
    """Initialize database if it doesn't exist."""
    database = get_db()
    exists = database.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if not exists:
        db.init_db()
    else:
        db.ensure_schema()
    # Removes the old prototype activity once, then keeps real user data.
    seed_module.seed()


# Template filters (existing implementations)
def money(value, decimals=0):
    """Render integer millimes as dinars."""
    try:
        dinars = int(value or 0) / 1000
    except (TypeError, ValueError):
        return "0 DT"
    return f"{dinars:,.{decimals}f} DT"


def dinars(value):
    """Millimes -> plain dinars number, for form values."""
    try:
        return f"{int(value or 0) / 1000:g}"
    except (TypeError, ValueError):
        return "0"


def when(value):
    """Format timestamp as relative time."""
    if not value:
        return ""
    for pattern in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            moment = datetime.strptime(value, pattern)
            break
        except ValueError:
            moment = None
    if moment is None:
        return value
    delta = datetime.now() - moment
    if delta.total_seconds() < 60:
        return "Just now"
    if delta.total_seconds() < 3600:
        return f"{max(1, int(delta.total_seconds() // 60))} min ago"
    if delta.days == 0:
        return f"{int(delta.total_seconds() // 3600)} h ago"
    if delta.days == 1:
        return "Yesterday"
    if delta.days < 7:
        return f"{delta.days} days ago"
    return moment.strftime("%d %b %Y")


def day(value):
    """Format date as day."""
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return value


def initials(name):
    """Get initials from name."""
    if not name:
        return "?"
    parts = [part for part in name.replace("-", " ").split() if part]
    return "".join(part[0] for part in parts[:2]).upper()


# Create app instance for WSGI servers
app = create_app()


if __name__ == "__main__":
    host = os.environ.get("FLASK_RUN_HOST", "127.0.0.1")
    try:
        port = int(os.environ.get("FLASK_RUN_PORT", "5001"))
    except ValueError:
        port = 5001
    app.run(host=host, port=port, debug=app.config.get("DEBUG", False))
