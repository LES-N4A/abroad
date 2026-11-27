from datetime import datetime

from db import execute, query
from services import record_wallet

STAMP = "%Y-%m-%d %H:%M:%S"

# action: (allowed_from_states, destination_state, roles_allowed)
TRANSITIONS = {
    "accept": (("open",), "assigned", ("traveler",)),
    "purchase": (("assigned",), "purchased", ("traveler",)),
    "ship": (("purchased",), "in_transit", ("traveler",)),
    "deliver": (("purchased", "in_transit"), "delivered", ("traveler",)),
    "release": (("delivered",), "completed", ("buyer", "seller", "pro")),
    "dispute": (("assigned", "purchased", "in_transit", "delivered"), "disputed", ("buyer", "seller", "pro")),
}

ACTION_LABEL = {
    "accept": "Traveler accepted the cart",
    "purchase": "Receipt uploaded",
    "ship": "Parcel in transit",
    "deliver": "Parcel delivered",
    "release": "Buyer released escrow",
    "dispute": "Dispute opened",
}


def can_transition(cart, action, role):
    if action not in TRANSITIONS:
        return False
    allowed_from, _, roles = TRANSITIONS[action]
    return cart["status"] in allowed_from and role in roles


def transition(cart, action, user, note=None):
    """Apply a validated escrow transition and write an audit event."""
    allowed_from, target, roles = TRANSITIONS[action]
    if user["role"] not in roles:
        raise PermissionError(f"The {user['role']} role cannot {action} this cart.")
    if cart["status"] not in allowed_from:
        raise ValueError(f"Cannot {action} a cart in state '{cart['status']}'.")

    source = cart["status"]
    execute(
        """UPDATE carts SET status = ?, updated_at = ? WHERE id = ?""",
        (target, datetime.now().strftime(STAMP), cart["id"]),
    )
    log_event(cart["id"], source, target, user["id"], note or ACTION_LABEL[action])

    if action == "release":
        credit_escrow(cart)

    return query("SELECT * FROM carts WHERE id = ?", (cart["id"],), one=True)


def log_event(cart_id, source, target, actor_id, note):
    execute(
        """INSERT INTO escrow_events (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (cart_id, source, target, actor_id, note, datetime.now().strftime(STAMP)),
    )


def credit_escrow(cart):
    """On release, credit the seller(s) and traveler exactly once.

    The buyer was already debited when escrow was funded, so there is no
    second buyer-side ledger entry here.
    """
    items = query(
        """SELECT p.seller_id, SUM(ci.quantity * ci.unit_price) AS amount
           FROM cart_items ci
           JOIN products p ON p.id = ci.product_id
           WHERE ci.cart_id = ?
           GROUP BY p.seller_id""",
        (cart["id"],),
    )
    for row in items:
        record_wallet(
            row["seller_id"],
            row["amount"],
            "sale",
            f"Escrow released · cart #{cart['id']}",
            f"escrow-sale-{cart['id']}-{row['seller_id']}",
        )

    if cart["traveler_id"]:
        record_wallet(
            cart["traveler_id"],
            cart["traveler_fee"],
            "traveler_fee",
            f"Delivery fee · cart #{cart['id']}",
            f"escrow-fee-{cart['id']}",
        )
