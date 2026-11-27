import re
import sqlite3
from contextlib import contextmanager

import click
from flask import current_app, g


def get_db():
    """Open one SQLite connection per request."""
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


MONEY_COLUMNS = {
    "products": ["price"],
    "orders": ["total"],
    "carts": ["traveler_fee", "receipt_amount"],
    "cart_items": ["unit_price"],
    "trips": ["fee"],
    "wallet_transactions": ["amount"],
}

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_orders_flow ON orders(status, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_carts_buyer ON carts(buyer_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_carts_traveler ON carts(traveler_id, status)",
    "CREATE INDEX IF NOT EXISTS idx_cart_items_cart ON cart_items(cart_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_reference ON wallet_transactions(reference)",
    "CREATE INDEX IF NOT EXISTS idx_products_listing ON products(listing_type, created_at)",
    "CREATE INDEX IF NOT EXISTS idx_trips_status ON trips(status, arrival_date)",
)

SCHEMA_COLUMNS = {
    "users": [
        ("status", "TEXT NOT NULL DEFAULT 'active'"),
        ("is_admin", "INTEGER NOT NULL DEFAULT 0"),
        ("is_staff", "INTEGER NOT NULL DEFAULT 0"),
    ],
    "products": [
        ("listing_type", "TEXT NOT NULL DEFAULT 'travel'"),
    ],
    "orders": [
        ("variant", "TEXT"),
        ("confirmed_at", "TEXT"),
        ("cancelled_at", "TEXT"),
    ],
    "cart_items": [
        ("variant", "TEXT"),
    ],
    "product_reviews": [
        ("order_id", "INTEGER"),
    ],
    "trips": [
        ("verified_at", "TEXT"),
        ("verified_by", "INTEGER"),
        ("rejection_reason", "TEXT"),
    ],
    "carts": [
        ("receipt_hash", "TEXT"),
        ("receipt_flag", "TEXT"),
        ("request_type", "TEXT NOT NULL DEFAULT 'shop'"),
        ("external_url", "TEXT"),
        ("preferred_traveler_id", "INTEGER"),
        ("paid", "INTEGER NOT NULL DEFAULT 0"),
        ("paid_at", "TEXT"),
        ("receipt_status", "TEXT NOT NULL DEFAULT 'none'"),
        ("receipt_due_at", "TEXT"),
        ("receipt_verified_at", "TEXT"),
        ("receipt_note", "TEXT"),
        ("refunded_at", "TEXT"),
        ("cancelled_at", "TEXT"),
    ],
    "wallet_transactions": [
        ("reference", "TEXT"),
    ],
}


def ensure_schema():
    """Add columns introduced after the first classroom build."""
    db = get_db()
    for table, columns in SCHEMA_COLUMNS.items():
        existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
        for name, definition in columns:
            if name not in existing:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
    db.execute(
        """CREATE TABLE IF NOT EXISTS app_meta (
               key TEXT PRIMARY KEY,
               value TEXT NOT NULL
           )"""
    )
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_wallet_reference "
        "ON wallet_transactions(reference)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS product_images (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
               url TEXT NOT NULL,
               position INTEGER NOT NULL DEFAULT 0,
               created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
           )"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS product_reviews (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
               buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
               comment TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_images_product "
        "ON product_images(product_id, position)"
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_reviews_product "
        "ON product_reviews(product_id, created_at)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS product_options (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
               kind TEXT NOT NULL CHECK (kind IN ('size', 'color')),
               value TEXT NOT NULL,
               position INTEGER NOT NULL DEFAULT 0
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_product_options_product "
        "ON product_options(product_id, kind, position)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS audit_log (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               actor_id INTEGER,
               action TEXT NOT NULL,
               entity TEXT,
               entity_id INTEGER,
               details TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_log(created_at)"
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS payout_requests (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
               amount INTEGER NOT NULL CHECK (amount > 0),
               method TEXT NOT NULL DEFAULT 'Bank transfer',
               details TEXT,
               status TEXT NOT NULL DEFAULT 'pending'
                   CHECK (status IN ('pending', 'paid', 'rejected')),
               note TEXT,
               decided_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
               decided_at TEXT,
               created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
           )"""
    )
    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_payout_status "
        "ON payout_requests(status, created_at)"
    )
    migrate_to_millimes(db)
    _ensure_wallet_kind(db)
    for statement in INDEXES:
        db.execute(statement)
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_product_reviews_once "
        "ON product_reviews(product_id, buyer_id)"
    )
    db.commit()


def _money_is_real(db, table):
    for row in db.execute(f"PRAGMA table_info({table})"):
        if row["name"] in MONEY_COLUMNS[table] and (row["type"] or "").upper() == "REAL":
            return True
    return False


def migrate_to_millimes(db):
    """Rewrite money columns from dinars (REAL) to integer millimes.

    SQLite cannot change a column type in place, so each affected table is
    rebuilt with the same definition, its values multiplied by 1000, and the
    original row ids preserved.
    """
    tables = [table for table in MONEY_COLUMNS if _money_is_real(db, table)]
    if not tables:
        return
    db.commit()
    db.execute("PRAGMA foreign_keys = OFF")
    db.execute("PRAGMA legacy_alter_table = ON")
    try:
        for table in tables:
            ddl = db.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            ).fetchone()["sql"]
            for column in MONEY_COLUMNS[table]:
                ddl = re.sub(rf"(\b{column}\s+)REAL\b", r"\1INTEGER", ddl)
            columns = [(row["name"], row["type"]) for row in db.execute(f"PRAGMA table_info({table})")]
            names = ", ".join(name for name, _ in columns)
            selected = ", ".join(
                f"CAST(ROUND({name} * 1000) AS INTEGER)" if name in MONEY_COLUMNS[table] else name
                for name, _ in columns
            )
            db.execute(f"ALTER TABLE {table} RENAME TO {table}_dinars")
            db.execute(ddl)
            db.execute(
                f"INSERT INTO {table} ({names}) SELECT {selected} FROM {table}_dinars"
            )
            db.execute(f"DROP TABLE {table}_dinars")
        db.commit()
    finally:
        db.execute("PRAGMA legacy_alter_table = OFF")
        db.execute("PRAGMA foreign_keys = ON")


def _ensure_wallet_kind(db):
    """Allow every ledger kind the app writes, without rebuilding other tables."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'wallet_transactions'"
    ).fetchone()
    if not row or "'deposit'" in (row["sql"] or ""):
        return
    db.execute("PRAGMA foreign_keys = OFF")
    db.executescript(
        """
        BEGIN;
        ALTER TABLE wallet_transactions RENAME TO wallet_transactions_old;
        CREATE TABLE wallet_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            amount INTEGER NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('sale', 'traveler_fee', 'payout', 'refund', 'escrow', 'deposit')),
            description TEXT NOT NULL,
            reference TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
        );
        INSERT INTO wallet_transactions
            (id, user_id, amount, kind, description, reference, created_at)
        SELECT id, user_id, amount, kind, description, reference, created_at
        FROM wallet_transactions_old;
        DROP TABLE wallet_transactions_old;
        COMMIT;
        """
    )
    db.execute("PRAGMA foreign_keys = ON")


def init_db():
    db = get_db()
    with current_app.open_resource("schema.sql") as schema:
        db.executescript(schema.read().decode("utf-8"))
    db.commit()
    ensure_schema()


def meta_get(key, default=None):
    row = query("SELECT value FROM app_meta WHERE key = ?", (key,), one=True)
    return row["value"] if row else default


def meta_set(key, value):
    execute(
        """INSERT INTO app_meta (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, value),
    )


@contextmanager
def transaction():
    """Run several statements as one unit so money and stock cannot half-move."""
    db = get_db()
    db.commit()
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    else:
        db.commit()


def query(sql, args=(), one=False):
    cursor = get_db().execute(sql, args)
    rows = cursor.fetchall()
    cursor.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, args=()):
    db = get_db()
    cursor = db.execute(sql, args)
    db.commit()
    return cursor.lastrowid


def execute_many(sql, rows):
    db = get_db()
    db.executemany(sql, rows)
    db.commit()


@click.command("init-db")
def init_db_command():
    """Create the database tables and add any new columns."""
    from seed import seed

    init_db()
    seed()
    click.echo("Database initialised.")


def init_app(app):
    app.teardown_appcontext(close_db)
    app.cli.add_command(init_db_command)
