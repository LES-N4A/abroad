PRAGMA foreign_keys = ON;

CREATE TABLE users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('buyer', 'seller', 'traveler', 'pro')),
    status TEXT NOT NULL DEFAULT 'active',
    is_admin INTEGER NOT NULL DEFAULT 0,
    city TEXT NOT NULL DEFAULT 'Tunis',
    phone TEXT,
    store_name TEXT,
    rating REAL NOT NULL DEFAULT 0,
    deliveries INTEGER NOT NULL DEFAULT 0,
    shipping_notes TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    price INTEGER NOT NULL CHECK (price >= 0),
    stock INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    category TEXT NOT NULL DEFAULT 'Fashion',
    listing_type TEXT NOT NULL DEFAULT 'travel',
    image_url TEXT,
    video_url TEXT,
    weight_kg REAL NOT NULL DEFAULT 0.5,
    featured INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    total INTEGER NOT NULL CHECK (total >= 0),
    status TEXT NOT NULL DEFAULT 'new'
        CHECK (status IN ('new', 'processing', 'shipped', 'delivered', 'cancelled')),
    variant TEXT,
    confirmed_at TEXT,
    cancelled_at TEXT,
    wallet_posted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE trips (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    traveler_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    from_city TEXT NOT NULL,
    to_city TEXT NOT NULL,
    departure_date TEXT NOT NULL,
    arrival_date TEXT NOT NULL,
    capacity_kg REAL NOT NULL CHECK (capacity_kg > 0),
    used_kg REAL NOT NULL DEFAULT 0,
    fee INTEGER NOT NULL DEFAULT 5000,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'verified', 'rejected')),
    notes TEXT,
    documents_submitted INTEGER NOT NULL DEFAULT 0,
    document_file TEXT,
    verified_at TEXT,
    verified_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE carts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    traveler_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    trip_id INTEGER REFERENCES trips(id) ON DELETE SET NULL,
    store_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'assigned', 'purchased', 'in_transit', 'delivered', 'completed', 'disputed')),
    delivery_city TEXT NOT NULL,
    delivery_date TEXT NOT NULL,
    traveler_fee INTEGER NOT NULL DEFAULT 5000,
    instructions TEXT,
    request_type TEXT NOT NULL DEFAULT 'shop',
    external_url TEXT,
    preferred_traveler_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    paid INTEGER NOT NULL DEFAULT 0,
    paid_at TEXT,
    receipt_status TEXT NOT NULL DEFAULT 'none',
    receipt_due_at TEXT,
    receipt_verified_at TEXT,
    receipt_note TEXT,
    refunded_at TEXT,
    cancelled_at TEXT,
    code_issued_at TEXT,
    code_expires_at TEXT,
    code_attempts INTEGER NOT NULL DEFAULT 0,
    receipt_amount INTEGER,
    receipt_store TEXT,
    receipt_date TEXT,
    receipt_file TEXT,
    receipt_hash TEXT,
    receipt_flag TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE cart_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
    name TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1 CHECK (quantity > 0),
    unit_price INTEGER NOT NULL CHECK (unit_price >= 0),
    weight_kg REAL NOT NULL DEFAULT 0.5,
    variant TEXT
);

CREATE TABLE cart_declines (
    cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    traveler_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    PRIMARY KEY (cart_id, traveler_id)
);

CREATE TABLE escrow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    from_state TEXT NOT NULL,
    to_state TEXT NOT NULL,
    actor_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE wallet_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('sale', 'traveler_fee', 'payout', 'refund', 'escrow', 'deposit')),
    description TEXT NOT NULL,
    reference TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    sender_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    recipient_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    seller_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id INTEGER UNIQUE REFERENCES orders(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE product_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    url TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE product_options (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('size', 'color')),
    value TEXT NOT NULL,
    position INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE product_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    buyer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    order_id INTEGER REFERENCES orders(id) ON DELETE SET NULL,
    rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    comment TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE payout_requests (
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
);

CREATE TABLE audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER,
    action TEXT NOT NULL,
    entity TEXT,
    entity_id INTEGER,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE disputes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cart_id INTEGER NOT NULL REFERENCES carts(id) ON DELETE CASCADE,
    opener_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE support_tickets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved')),
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE team_members (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'Staff',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE api_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL,
    prefix TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT 'Default key',
    revoked INTEGER NOT NULL DEFAULT 0,
    last_used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX idx_orders_seller ON orders(seller_id, status);
CREATE INDEX idx_orders_buyer ON orders(buyer_id, created_at);
CREATE INDEX idx_carts_buyer ON carts(buyer_id, status);
CREATE INDEX idx_carts_traveler ON carts(traveler_id, status);
CREATE INDEX idx_cart_items_cart ON cart_items(cart_id);
CREATE INDEX idx_messages_pair ON messages(sender_id, recipient_id);
CREATE INDEX idx_notifications_user ON notifications(user_id, read);
CREATE UNIQUE INDEX idx_wallet_reference ON wallet_transactions(reference);
CREATE INDEX idx_products_listing ON products(listing_type, created_at);
CREATE INDEX idx_trips_status ON trips(status, arrival_date);
CREATE INDEX idx_product_images_product ON product_images(product_id, position);
CREATE INDEX idx_product_reviews_product ON product_reviews(product_id, created_at);
CREATE INDEX idx_product_options_product ON product_options(product_id, kind, position);
CREATE INDEX idx_audit_created ON audit_log(created_at);
CREATE INDEX idx_payout_status ON payout_requests(status, created_at);
CREATE INDEX idx_orders_flow ON orders(status, created_at);
CREATE UNIQUE INDEX idx_product_reviews_once ON product_reviews(product_id, buyer_id);

CREATE TABLE app_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
