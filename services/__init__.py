"""Services package: core marketplace helpers plus external integrations.

The integration modules (email_service, payment_service, ...) import optional
third-party SDKs, so they are deliberately not imported here; only the core
helpers are re-exported for ``from services import ...`` compatibility.
"""

from services.core import (cart_items, cart_totals, notify, record_wallet,
                           seller_ids_for_cart, unread_counts, wallet_balance)

__all__ = [
    "cart_items",
    "cart_totals",
    "notify",
    "record_wallet",
    "seller_ids_for_cart",
    "unread_counts",
    "wallet_balance",
]
