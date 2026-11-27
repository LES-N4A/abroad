import re
import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import (Blueprint, current_app, flash, g, redirect, render_template,
                   request, session, url_for)

from constants import ROLE_HOME
from db import execute, query
from security import hash_password, verify_password
from services import notify

auth_bp = Blueprint("auth", __name__)

DEMO_ACCOUNTS = {
    "buyer": "sarra@abroad.tn",
    "seller": "store@abroad.tn",
    "traveler": "ahmed@abroad.tn",
    "pro": "pro@abroad.tn",
    "admin": "admin@abroad.tn",
}

PENDING_MINUTES = 15
STAMP = "%Y-%m-%d %H:%M:%S"


def login_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login"))
        return view(**kwargs)

    return wrapped


def roles_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(**kwargs):
            if g.user is None:
                flash("Please sign in to continue.", "info")
                return redirect(url_for("auth.login"))
            if g.user["role"] not in roles:
                flash("That area is not available for your account.", "error")
                return redirect(home_for(g.user))
            return view(**kwargs)

        return wrapped

    return decorator


def admin_required(view):
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login"))
        if not g.user["is_admin"]:
            flash("Administrator access is required for that page.", "error")
            return redirect(home_for(g.user))
        return view(**kwargs)

    return wrapped


def staff_required(view):
    """Login + active account + is_staff (hired verifier).

    Staff are administrator-flagged workers who can verify receipts but should
    not reach the sensitive pages (accounts, trips, full receipts list, money).
    """
    @wraps(view)
    def wrapped(**kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login"))
        if g.user["status"] != "active":
            session.pop("user_id", None)
            g.user = None
            flash("That account is not active.", "error")
            return redirect(url_for("auth.login"))
        if not g.user["is_staff"]:
            flash("You do not have staff access.", "error")
            return redirect(home_for(g.user))
        return view(**kwargs)

    return wrapped


@auth_bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    g.user = (
        query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
        if user_id
        else None
    )
    # Suspended/pending accounts cannot keep an old session alive.
    if g.user and g.user["status"] != "active":
        session.pop("user_id", None)
        g.user = None


def home_for(user):
    if user["is_admin"]:
        return url_for("main.admin_dashboard")
    return url_for(ROLE_HOME[user["role"]])


def sign_in(user):
    session.clear()
    session["user_id"] = user["id"]
    session.permanent = True


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_for(g.user))

    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = query("SELECT * FROM users WHERE email = ?", (email,), one=True)

        if not user or not verify_password(user["password_hash"], password):
            flash("Email or password is incorrect.", "error")
            return render_template("login.html", active_tab="login", email=email), 401

        if user["status"] == "pending":
            flash("Your account is waiting for administrator approval.", "info")
            return render_template("login.html", active_tab="login", email=email), 403
        if user["status"] == "suspended":
            flash("That account is suspended. Contact the administrator.", "error")
            return render_template("login.html", active_tab="login", email=email), 403

        sign_in(user)
        flash(f"Welcome back, {user['name']}.", "success")
        return redirect(home_for(user))

    tab = "register" if request.args.get("tab") == "register" else "login"
    return render_template("login.html", active_tab=tab)


@auth_bp.post("/register")
def register():
    role = request.form.get("role") or "buyer"
    if role not in ROLE_HOME:
        flash("Choose a valid account type.", "error")
        return render_template("login.html", active_tab="register"), 400

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""
    country = (request.form.get("country") or "Tunisia").strip()

    if len(name) < 2:
        flash("Please enter your name or store name.", "error")
        return render_template("login.html", active_tab="register", selected_role=role), 400
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        flash("Enter a valid email address.", "error")
        return render_template("login.html", active_tab="register", selected_role=role), 400
    if len(password) < 6:
        flash("Use a password with at least 6 characters.", "error")
        return render_template("login.html", active_tab="register", selected_role=role), 400
    if query("SELECT id FROM users WHERE email = ?", (email,), one=True):
        flash("That email is already registered. Try signing in.", "error")
        return render_template("login.html", active_tab="register", selected_role=role), 409

    code = f"{secrets.randbelow(1_000_000):06d}"
    session["pending_signup"] = {
        "name": name,
        "email": email,
        "password_hash": hash_password(password),
        "role": role,
        "city": country if role == "traveler" else "Tunis",
        "store_name": name if role in ("seller", "pro") else None,
        "code": code,
        "expires": (datetime.now() + timedelta(minutes=PENDING_MINUTES)).strftime(STAMP),
    }
    return render_template(
        "login.html",
        active_tab="register",
        verification=True,
        demo_code=code,
        selected_role=role,
        pending_email=email,
    )


@auth_bp.post("/register/verify")
def verify_registration():
    pending = session.get("pending_signup")
    if not pending:
        flash("Your signup expired. Please register again.", "error")
        return redirect(url_for("auth.login", tab="register"))

    if datetime.strptime(pending["expires"], STAMP) < datetime.now():
        session.pop("pending_signup", None)
        flash("That verification code expired. Please register again.", "error")
        return redirect(url_for("auth.login", tab="register"))

    entered = re.sub(r"\D", "", request.form.get("code") or "")
    if entered != pending["code"]:
        flash("That code is not correct. Check the demo code and try again.", "error")
        return render_template(
            "login.html",
            active_tab="register",
            verification=True,
            demo_code=pending["code"],
            selected_role=pending["role"],
            pending_email=pending["email"],
        ), 400

    user_id = execute(
        """INSERT INTO users
           (name, email, password_hash, role, status, city, store_name, rating, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?, ?, 4.8, ?)""",
        (
            pending["name"],
            pending["email"],
            pending["password_hash"],
            pending["role"],
            pending["city"],
            pending["store_name"],
            datetime.now().strftime(STAMP),
        ),
    )
    session.pop("pending_signup", None)
    for admin in query("SELECT id FROM users WHERE is_admin = 1"):
        notify(
            admin["id"],
            "New account waiting for approval",
            f"{pending['name']} registered as a {pending['role']}.",
            url_for("main.admin_accounts", status="pending"),
        )
    flash(
        "Email verified. Your account is now waiting for administrator approval before you can sign in.",
        "success",
    )
    return redirect(url_for("auth.login"))


@auth_bp.post("/demo/<role>")
def demo(role):
    if role not in DEMO_ACCOUNTS:
        flash("Unknown demo account.", "error")
        return redirect(url_for("auth.login"))
    if role == "admin" and not current_app.config.get("ALLOW_DEMO_ADMIN", True):
        flash("Administrator demo sign-in is disabled on this deployment.", "error")
        return redirect(url_for("auth.login"))

    user = query("SELECT * FROM users WHERE email = ?", (DEMO_ACCOUNTS[role],), one=True)
    if not user:
        flash("Demo data is missing. Run the seed command.", "error")
        return redirect(url_for("auth.login"))

    sign_in(user)
    provider = request.form.get("provider")
    if provider:
        flash(
            f"{provider} sign-in is not configured in this classroom build, "
            f"so you are signed in as the demo {role}.",
            "info",
        )
    else:
        flash(f"Signed in to the demo {role} account.", "success")
    return redirect(home_for(user))


@auth_bp.post("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("auth.login"))
