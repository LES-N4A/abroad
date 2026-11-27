import os
import sqlite3
import sys
from datetime import datetime

import click

from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   send_from_directory, session, url_for)
from werkzeug.exceptions import HTTPException

import db
import seed as seed_module
from auth import auth_bp
from constants import ROLE_HOME, ROLE_ICON, ROLE_LABEL, ROLE_NAV
from db import get_db
from security import csrf_token, hash_password, valid_csrf
from services import unread_counts
from views import main_bp


def create_app(test_config=None):
    app = Flask(
        __name__,
        instance_relative_config=True,
        static_folder="assets",
        static_url_path="/assets",
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY", "abroad-classroom-demo-secret-key"),
        DATABASE=os.environ.get(
            "DATABASE_PATH", os.path.join(app.instance_path, "abroad.sqlite")
        ),
        UPLOAD_FOLDER=os.environ.get(
            "UPLOAD_FOLDER", os.path.join(app.instance_path, "uploads")
        ),
        ALLOW_DEMO_ADMIN=os.environ.get("ALLOW_DEMO_ADMIN", "1").lower()
        not in ("0", "false", "no"),
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        CSRF_ENABLED=True,
        AUTO_INIT=True,
        START_REFUND_SWEEPER=os.environ.get("START_REFUND_SWEEPER", "1").lower()
        not in ("0", "false", "no"),
        REFUND_SWEEP_SECONDS=int(os.environ.get("REFUND_SWEEP_SECONDS", "60")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    db.init_app(app)
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)

    app.jinja_env.filters["money"] = money
    app.jinja_env.filters["dinars"] = dinars
    app.jinja_env.filters["when"] = when
    app.jinja_env.filters["day"] = day
    app.jinja_env.filters["initials"] = initials
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["ROLE_LABEL"] = ROLE_LABEL
    app.jinja_env.globals["ROLE_ICON"] = ROLE_ICON
    app.jinja_env.globals["today"] = lambda: datetime.now().strftime("%d %b %Y")

    @app.before_request
    def protect_from_csrf():
        if request.method == "POST" and app.config.get("CSRF_ENABLED", True):
            if not valid_csrf():
                abort(400, description="Your form session expired. Reload the page and try again.")

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

    @app.route("/uploads/<path:filename>")
    def uploaded_file(filename):
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.errorhandler(403)
    def forbidden(error):
        return render_template("error.html", code=403, message="That page belongs to another account."), 403

    @app.errorhandler(404)
    def not_found(error):
        return render_template("error.html", code=404, message="We could not find that page."), 404

    @app.errorhandler(HTTPException)
    def http_error(error):
        return render_template("error.html", code=error.code, message=error.description), error.code

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

    if app.config.get("AUTO_INIT", True):
        with app.app_context():
            initialise_if_needed()

    # The sweeper does not depend on a page view.  It is disabled in tests and
    # when running under pytest so test databases are never touched in the
    # background.
    if (
        app.config.get("START_REFUND_SWEEPER", True)
        and not app.config.get("TESTING")
        and "pytest" not in sys.modules
    ):
        from refunds import start_refund_sweeper

        start_refund_sweeper(app)

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

    return app


def initialise_if_needed():
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
    if not value:
        return ""
    try:
        return datetime.strptime(value, "%Y-%m-%d").strftime("%d %b %Y")
    except ValueError:
        return value


def initials(name):
    if not name:
        return "?"
    parts = [part for part in name.replace("-", " ").split() if part]
    return "".join(part[0] for part in parts[:2]).upper()


app = create_app()


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
