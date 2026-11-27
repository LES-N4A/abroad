import secrets
from hmac import compare_digest

from flask import request, session
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password):
    return generate_password_hash(password)


def verify_password(password_hash, password):
    return check_password_hash(password_hash, password)


def csrf_token():
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_urlsafe(32)
    return session["csrf_token"]


def valid_csrf():
    sent = request.form.get("csrf_token", "")
    stored = session.get("csrf_token", "")
    return bool(sent and stored and compare_digest(sent, stored))
