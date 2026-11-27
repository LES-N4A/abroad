"""Automatic receipt-deadline refunds and the background sweeper.

The sweeper is intentionally dependency-free.  It runs inside the Flask
process while the app is up, so a refund does not depend on a user opening a
page.  Every write is guarded by a conditional update and a unique ledger
reference, which makes repeated sweeps harmless.
"""

import threading
import time
from datetime import datetime

from flask import has_request_context, url_for

from db import get_db, query
from services import cart_totals, notify

STAMP = "%Y-%m-%d %H:%M:%S"


def _link(endpoint, fallback):
    """Build a request-aware link, but keep working in the background worker."""
    return url_for(endpoint) if has_request_context() else fallback


def notify_admins(title, body, link=None):
    for admin in query("SELECT id FROM users WHERE is_admin = 1"):
        notify(admin["id"], title, body, link)


def expire_overdue_carts():
    """Refund paid carts that missed the receipt deadline, exactly once."""
    current = datetime.now().strftime(STAMP)
    rows = query(
        """SELECT * FROM carts
           WHERE status = 'assigned' AND paid = 1
             AND receipt_due_at IS NOT NULL AND receipt_due_at < ?
             AND receipt_status IN ('none', 'rejected')""",
        (current,),
    )
    for cart in rows:
        total, weight = cart_totals(cart["id"])
        refund = int(total) + int(cart["traveler_fee"] or 0)
        db = get_db()
        cursor = db.execute(
            """UPDATE carts
               SET status = 'completed', refunded_at = ?, cancelled_at = ?,
                   updated_at = ?
               WHERE id = ? AND status = 'assigned' AND paid = 1
                 AND refunded_at IS NULL""",
            (current, current, current, cart["id"]),
        )
        if cursor.rowcount != 1:
            db.rollback()
            continue

        db.execute(
            """INSERT OR IGNORE INTO wallet_transactions
               (user_id, amount, kind, description, reference, created_at)
               VALUES (?, ?, 'refund', ?, ?, ?)""",
            (
                cart["buyer_id"],
                refund,
                f"Automatic refund for cart #{cart['id']} — receipt not uploaded in 2 days",
                f"escrow-refund-{cart['id']}",
                current,
            ),
        )
        db.execute(
            """INSERT INTO escrow_events
               (cart_id, from_state, to_state, actor_id, note, created_at)
               VALUES (?, 'assigned', 'cancelled', NULL, ?, ?)""",
            (cart["id"], "Receipt deadline passed; buyer refunded automatically", current),
        )
        if cart["trip_id"]:
            db.execute(
                "UPDATE trips SET used_kg = MAX(0, used_kg - ?) WHERE id = ?",
                (weight, cart["trip_id"]),
            )
        db.commit()

        notify(
            cart["buyer_id"],
            "Escrow refunded",
            f"Cart #{cart['id']} was refunded because the receipt was not uploaded within 2 days.",
            _link("main.escrow", "/escrow"),
        )
        if cart["traveler_id"]:
            notify(
                cart["traveler_id"],
                "Receipt deadline passed",
                f"Cart #{cart['id']} was refunded to the buyer after the 2-day receipt window.",
                _link("main.traveler_dashboard", "/traveler"),
            )
        notify_admins(
            "Automatic refund issued",
            f"Cart #{cart['id']} missed the receipt deadline.",
            _link("main.admin_receipts", "/admin/receipts"),
        )


def start_refund_sweeper(app):
    """Start one daemon thread for this Flask process."""
    existing = app.extensions.get("refund_sweeper")
    if existing and existing.is_alive():
        return existing

    interval = max(5, int(app.config.get("REFUND_SWEEP_SECONDS", 60)))

    def loop():
        while True:
            try:
                with app.app_context():
                    expire_overdue_carts()
            except Exception:  # keep the worker alive after a transient DB error
                app.logger.exception("Escrow refund sweep failed")
            time.sleep(interval)

    thread = threading.Thread(target=loop, name="abroad-refund-sweeper", daemon=True)
    thread.start()
    app.extensions["refund_sweeper"] = thread
    app.logger.info("Escrow refund sweeper started (every %s seconds)", interval)
    return thread
