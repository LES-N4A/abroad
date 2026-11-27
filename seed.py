"""Clean bootstrap data.

The first prototype shipped with seeded products, orders and carts.  This
module keeps only the real accounts and removes that old demo activity once.
No marketplace activity is created automatically: every order, request, trip
and escrow entry must come from a real user action.
"""

from db import execute, meta_get, meta_set, query
from security import hash_password

DEMO_PASSWORD = "demo1234"
CLEAN_MARKER = "marketplace_clean_v2"

LEGACY_DEMO_EMAILS = (
    "rania@abroad.tn",
    "lina@abroad.tn",
    "karim@abroad.tn",
    "nour@abroad.tn",
    "leila@abroad.tn",
    "mohamed@abroad.tn",
    "sarah@abroad.tn",
    "amine@abroad.tn",
)

# Only the accounts needed to use and administer the site.
CORE_ACCOUNTS = (
    {
        "email": "sarra@abroad.tn",
        "password": DEMO_PASSWORD,
        "name": "Sarra",
        "role": "buyer",
        "phone": "+216 55 100 200",
        "city": "Tunis",
        "store_name": None,
        "is_admin": 0,
    },
    {
        "email": "store@abroad.tn",
        "password": DEMO_PASSWORD,
        "name": "Sarra Store",
        "role": "seller",
        "phone": "+216 55 300 400",
        "city": "Tunis",
        "store_name": "Sarra Store",
        "is_admin": 0,
    },
    {
        "email": "ahmed@abroad.tn",
        "password": DEMO_PASSWORD,
        "name": "Ahmed Trabelsi",
        "role": "traveler",
        "phone": "+216 55 500 600",
        "city": "Tunis",
        "store_name": None,
        "is_admin": 0,
    },
    {
        "email": "pro@abroad.tn",
        "password": DEMO_PASSWORD,
        "name": "Nadia Ben Salah",
        "role": "pro",
        "phone": "+216 55 700 800",
        "city": "Tunis",
        "store_name": "Nadia Pro Sourcing",
        "is_admin": 0,
    },
    {
        "email": "admin@abroad.tn",
        "password": DEMO_PASSWORD,
        "name": "Abroad Administrator",
        "role": "pro",
        "phone": "+216 55 900 100",
        "city": "Tunis",
        "store_name": "Abroad Control",
        "is_admin": 1,
    },
)


def _ensure_account(account):
    existing = query("SELECT * FROM users WHERE email = ?", (account["email"],), one=True)
    if existing:
        if account["is_admin"] and not existing["is_admin"]:
            execute("UPDATE users SET is_admin = 1 WHERE id = ?", (existing["id"],))
        return
    execute(
        """INSERT INTO users
           (email, password_hash, name, role, status, is_admin, phone, city, store_name)
           VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?)""",
        (
            account["email"],
            hash_password(account["password"]),
            account["name"],
            account["role"],
            account["is_admin"],
            account["phone"],
            account["city"],
            account["store_name"],
        ),
    )


def seed_accounts():
    for account in CORE_ACCOUNTS:
        _ensure_account(account)


def cleanup_legacy_marketplace():
    """Delete the old prototype's demo activity exactly once."""
    if meta_get(CLEAN_MARKER):
        return

    # Transactional demo data, in dependency order.
    for table in (
        "cart_declines",
        "escrow_events",
        "cart_items",
        "carts",
        "reviews",
        "orders",
        "wallet_transactions",
        "messages",
        "notifications",
        "disputes",
        "support_tickets",
        "team_members",
        "api_tokens",
        "trips",
    ):
        execute(f"DELETE FROM {table}")

    # The original catalogue used IDs 1-11.  Product 12 ("leather") was added
    # by the owner after setup, so it stays.  Anything later is real content.
    execute("DELETE FROM products WHERE id <= 11")

    placeholders = ",".join("?" for _ in LEGACY_DEMO_EMAILS)
    execute(
        f"DELETE FROM users WHERE email IN ({placeholders}) AND is_admin = 0",
        LEGACY_DEMO_EMAILS,
    )

    seed_accounts()
    execute("UPDATE users SET status = 'active' WHERE status IS NULL OR status = ''")
    meta_set(CLEAN_MARKER, "done")


def migrate_seller_listings():
    """Old seller uploads had no destination and defaulted to travel."""
    marker = "seller_listings_local_v1"
    if meta_get(marker):
        return
    execute(
        """UPDATE products SET listing_type = 'local'
           WHERE seller_id IN (SELECT id FROM users WHERE role IN ('seller', 'pro'))"""
    )
    meta_set(marker, "done")


def seed():
    cleanup_legacy_marketplace()
    seed_accounts()
    migrate_seller_listings()


if __name__ == "__main__":
    from app import app

    with app.app_context():
        seed()
        print("Clean accounts ready; demo marketplace activity removed.")
