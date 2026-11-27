"""Core marketplace helpers (carts, wallet ledger, notifications).

These used to live in a top-level ``services.py`` module. When the integrations
package (``services/``) was added the module was shadowed by the package, so the
helpers moved in here and are re-exported from ``services/__init__.py``.
"""

from datetime import datetime

from db import execute, get_db, query


def cart_items(cart_id):
    return query(
        """SELECT ci.*, p.image_url, p.category
           FROM cart_items ci
           LEFT JOIN products p ON p.id = ci.product_id
           WHERE ci.cart_id = ?
           ORDER BY ci.id""",
        (cart_id,),
    )


def cart_totals(cart_id):
    rows = query(
        "SELECT quantity, unit_price, weight_kg FROM cart_items WHERE cart_id = ?",
        (cart_id,),
    )
    total = sum(int(row["quantity"]) * int(row["unit_price"]) for row in rows)
    weight = sum(row["quantity"] * row["weight_kg"] for row in rows)
    return total, weight


def wallet_balance(user_id):
    row = query(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM wallet_transactions WHERE user_id = ?",
        (user_id,),
        one=True,
    )
    return int(row["total"] or 0)


def unread_counts(user_id):
    notifications = query(
        "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read = 0",
        (user_id,),
        one=True,
    )["n"]
    messages = query(
        "SELECT COUNT(*) AS n FROM messages WHERE recipient_id = ? AND read = 0",
        (user_id,),
        one=True,
    )["n"]
    return notifications, messages


def notify(user_id, title, body="", link=None):
    execute(
        """INSERT INTO notifications (user_id, title, body, link, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, title, body, link, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )


def record_wallet(user_id, amount, kind, description, reference):
    """Post one ledger entry in millimes; a repeated reference is ignored."""
    db = get_db()
    cursor = db.execute(
        """INSERT OR IGNORE INTO wallet_transactions
           (user_id, amount, kind, description, reference, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            user_id,
            int(round(amount)),
            kind,
            description,
            reference,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    db.commit()
    return cursor.rowcount == 1


def seller_ids_for_cart(cart_id):
    return [
        row["seller_id"]
        for row in query(
            """SELECT DISTINCT p.seller_id
               FROM cart_items ci
               JOIN products p ON p.id = ci.product_id
               WHERE ci.cart_id = ?""",
            (cart_id,),
        )
    ]
