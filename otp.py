import hashlib
import hmac
import re
from datetime import datetime, timedelta

from flask import current_app

from db import execute, query

CODE_LIFETIME_HOURS = 24
MAX_ATTEMPTS = 5
STAMP = "%Y-%m-%d %H:%M:%S"


def _digits(cart_id, issued_at):
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    message = f"{cart_id}:{issued_at}".encode("utf-8")
    digest = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"{int(digest[:12], 16) % 1_000_000:06d}"


def issue(cart_id):
    """Create (or refresh) the delivery code for a cart."""
    now = datetime.now()
    expires = now + timedelta(hours=CODE_LIFETIME_HOURS)
    execute(
        """UPDATE carts
           SET code_issued_at = ?, code_expires_at = ?, code_attempts = 0
           WHERE id = ?""",
        (now.strftime(STAMP), expires.strftime(STAMP), cart_id),
    )
    return now.strftime(STAMP)


def code_display(cart):
    if not cart or not cart["code_issued_at"]:
        return None
    digits = _digits(cart["id"], cart["code_issued_at"])
    return f"{digits[:3]}-{digits[3:]}"


def is_expired(cart):
    if not cart or not cart["code_expires_at"]:
        return True
    return datetime.strptime(cart["code_expires_at"], STAMP) < datetime.now()


def verify(cart, entered):
    """Return (ok, reason) without leaking which detail failed to the user."""
    if not cart or not cart["code_issued_at"]:
        return False, "missing"
    if cart["code_attempts"] >= MAX_ATTEMPTS:
        return False, "locked"
    if is_expired(cart):
        return False, "expired"

    cleaned = re.sub(r"\D", "", entered or "")
    expected = _digits(cart["id"], cart["code_issued_at"])
    if not hmac.compare_digest(cleaned, expected):
        execute(
            "UPDATE carts SET code_attempts = code_attempts + 1 WHERE id = ?",
            (cart["id"],),
        )
        return False, "invalid"

    return True, "ok"


def refresh_if_expired(cart):
    if cart and cart["code_issued_at"] and is_expired(cart):
        issue(cart["id"])
        return query("SELECT * FROM carts WHERE id = ?", (cart["id"],), one=True)
    return cart
