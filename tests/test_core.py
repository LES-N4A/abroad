import io
from datetime import date, datetime, timedelta

import pytest

from app import create_app
from db import execute, query
from escrow import can_transition, transition
from matching import eligible_trips, score_trip
from otp import code_display
from refunds import expire_overdue_carts
from services import wallet_balance

STAMP = "%Y-%m-%d %H:%M:%S"


@pytest.fixture()
def app(tmp_path):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "pytest-secret",
        "DATABASE": str(tmp_path / "test.sqlite"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "CSRF_ENABLED": False,
    })
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


def sign_in(client, role="buyer"):
    client.post("/logout")
    return client.post(f"/demo/{role}")


def login(client, email, password="demo1234"):
    client.post("/logout")
    return client.post("/login", data={"email": email, "password": password})


def account_ids(app):
    with app.app_context():
        return {
            row["role"]: row["id"]
            for row in query("SELECT id, role FROM users ORDER BY id")
        }


def add_product(app, seller_id=None, name="Test product", listing_type="travel"):
    if seller_id is None:
        seller_id = account_ids(app)["seller"]
    with app.app_context():
        return execute(
            """INSERT INTO products
               (seller_id, name, description, price, stock, category, listing_type,
                image_url, weight_kg, created_at)
               VALUES (?, ?, 'Test listing', 100, 5, 'Fashion', ?, NULL, 1.0, ?)""",
            (seller_id, name, listing_type, datetime.now().strftime(STAMP)),
        )


def add_trip(app, traveler_id=None, destination="Tunis", status="verified"):
    if traveler_id is None:
        traveler_id = account_ids(app)["traveler"]
    departure = (date.today() + timedelta(days=5)).isoformat()
    arrival = (date.today() + timedelta(days=6)).isoformat()
    with app.app_context():
        return execute(
            """INSERT INTO trips
               (traveler_id, from_city, to_city, departure_date, arrival_date,
                capacity_kg, fee, status, documents_submitted, document_file, created_at)
               VALUES (?, 'Paris', ?, ?, ?, 20, 10, ?, 1, '/uploads/test-ticket.png', ?)""",
            (traveler_id, destination, departure, arrival, status,
             datetime.now().strftime(STAMP)),
        )


def add_cart(app, *, buyer_id=None, traveler_id=None, trip_id=None,
             status="open", paid=0, request_type="shop", store_name="Test store",
             external_url=None, delivery_city="Tunis", item_name="Test item",
             price=100.0, fee=10.0, receipt_status="none", receipt_due_at=None):
    ids = account_ids(app)
    buyer_id = buyer_id or ids["buyer"]
    delivery_date = (date.today() + timedelta(days=7)).isoformat()
    with app.app_context():
        cart_id = execute(
            """INSERT INTO carts
               (buyer_id, traveler_id, trip_id, store_name, status, delivery_city,
                delivery_date, traveler_fee, instructions, request_type, external_url,
                paid, receipt_status, receipt_due_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)""",
            (
                buyer_id, traveler_id, trip_id, store_name, status, delivery_city,
                delivery_date, fee, request_type, external_url, paid, receipt_status,
                receipt_due_at, datetime.now().strftime(STAMP),
                datetime.now().strftime(STAMP),
            ),
        )
        execute(
            """INSERT INTO cart_items (cart_id, product_id, name, quantity, unit_price, weight_kg)
               VALUES (?, NULL, ?, 1, ?, 1.0)""",
            (cart_id, item_name, price),
        )
        return cart_id


def test_clean_seed_has_core_accounts_without_demo_activity(app):
    with app.app_context():
        assert query("SELECT COUNT(*) n FROM users", one=True)["n"] == 5
        assert query("SELECT COUNT(*) n FROM products", one=True)["n"] == 0
        for table in ("orders", "carts", "cart_items", "trips", "wallet_transactions",
                      "messages", "notifications", "reviews", "support_tickets", "team_members"):
            assert query(f"SELECT COUNT(*) n FROM {table}", one=True)["n"] == 0, table
        admin = query("SELECT * FROM users WHERE email = 'admin@abroad.tn'", one=True)
        assert admin["is_admin"] == 1


def test_demo_dashboards_render_without_fake_activity(app, client):
    assert sign_in(client, "buyer").status_code == 302
    page = client.get("/buyer")
    assert page.status_code == 200
    assert b"Buyer workspace" in page.data
    assert b"No active delivery yet" in page.data
    assert b"Track cart" not in page.data

    assert sign_in(client, "seller").status_code == 302
    assert b"No orders yet" in client.get("/seller").data

    assert sign_in(client, "traveler").status_code == 302
    assert b"No carts yet" in client.get("/traveler").data

    assert sign_in(client, "admin").status_code == 302
    admin_page = client.get("/admin")
    assert admin_page.status_code == 200
    assert b"Marketplace control centre" in admin_page.data


def test_admin_demo_login_can_be_disabled(app, client):
    app.config["ALLOW_DEMO_ADMIN"] = False
    response = client.post("/demo/admin")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]
    with client.session_transaction() as session:
        assert "user_id" not in session
    assert b"/demo/admin" not in client.get("/login").data


def test_role_isolation(client):
    sign_in(client, "buyer")
    assert client.get("/seller").status_code == 302

    seller_client = client.application.test_client()
    sign_in(seller_client, "seller")
    assert seller_client.get("/buyer").status_code == 302
    assert seller_client.get("/admin").status_code == 302


def test_buyer_request_groups_items_by_store(app):
    first = add_product(app, name="First product")
    second = add_product(app, name="Second product")
    buyer = app.test_client()
    sign_in(buyer, "buyer")

    with app.app_context():
        before = query("SELECT COUNT(*) n FROM carts", one=True)["n"]

    assert buyer.post(f"/shop/{first}/request").status_code == 302
    assert buyer.post(f"/shop/{second}/request").status_code == 302

    with app.app_context():
        assert query("SELECT COUNT(*) n FROM carts", one=True)["n"] == before + 1
        cart = query(
            "SELECT * FROM carts WHERE buyer_id = ? AND status = 'open' ORDER BY id DESC LIMIT 1",
            (account_ids(app)["buyer"],), one=True,
        )
        assert query("SELECT COUNT(*) n FROM cart_items WHERE cart_id = ?", (cart["id"],), one=True)["n"] == 2
        assert cart["request_type"] == "shop"


def test_admin_approves_new_account(app, client):
    response = client.post("/register", data={
        "role": "buyer", "name": "Pending Buyer",
        "email": "pending@example.com", "password": "secret123", "country": "Tunisia",
    })
    assert response.status_code == 200
    with client.session_transaction() as session:
        code = session["pending_signup"]["code"]
    client.post("/register/verify", data={"code": code})

    with app.app_context():
        pending = query("SELECT * FROM users WHERE email = 'pending@example.com'", one=True)
        assert pending["status"] == "pending"

    assert login(client, "pending@example.com", "secret123").status_code == 403

    assert login(client, "admin@abroad.tn").status_code == 302
    assert client.post(
        f"/admin/accounts/{pending['id']}/status",
        data={"status": "active"},
    ).status_code == 302

    result = login(client, "pending@example.com", "secret123")
    assert result.status_code == 302
    assert result.headers["Location"].endswith("/buyer")


def test_trip_requires_flight_proof_and_admin_verification(app, client):
    trip_id = add_trip(app, status="pending")
    sign_in(client, "traveler")

    missing = client.post("/trips/add", data={
        "from_city": "Rome", "to_city": "Tunis",
        "departure_date": (date.today() + timedelta(days=5)).isoformat(),
        "arrival_date": (date.today() + timedelta(days=6)).isoformat(),
        "capacity": "20", "fee": "10",
    })
    assert missing.status_code == 302
    with app.app_context():
        assert query("SELECT COUNT(*) n FROM trips", one=True)["n"] == 1
        assert query("SELECT COUNT(*) n FROM trips WHERE from_city = 'Rome'", one=True)["n"] == 0

    sign_in(client, "buyer")
    assert b"Paris" not in client.get("/travelers").data

    sign_in(client, "admin")
    assert client.post(f"/admin/trips/{trip_id}/verify").status_code == 302
    sign_in(client, "buyer")
    assert b"Paris" in client.get("/travelers").data


def test_matching_requires_destination_and_capacity(app):
    trip_id = add_trip(app)
    cart_id = add_cart(app, delivery_city="Tunis")
    with app.app_context():
        traveler_id = account_ids(app)["traveler"]
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        matches = eligible_trips(cart, traveler_id)
        assert matches
        assert matches[0]["trip"]["id"] == trip_id

        wrong_city = dict(cart)
        wrong_city["delivery_city"] = "Sfax"
        trip = query("SELECT * FROM trips WHERE id = ?", (trip_id,), one=True)
        assert score_trip(trip, wrong_city, 1.0) is None


def test_custom_request_escrow_receipt_verification_and_release(app, client):
    trip_id = add_trip(app)
    traveler_id = account_ids(app)["traveler"]
    delivery_date = (date.today() + timedelta(days=7)).isoformat()

    sign_in(client, "buyer")
    response = client.post("/requests/new", data={
        "store_name": "Shein",
        "external_url": "https://www.shein.com/cart/abc123",
        "item_name": "Black summer dress",
        "item_price": "100",
        "weight": "1.0",
        "delivery_city": "Tunis",
        "delivery_date": delivery_date,
        "traveler_fee": "10",
        "instructions": "Size M",
        "preferred_traveler_id": str(traveler_id),
    })
    assert response.status_code == 302

    with app.app_context():
        cart = query(
            "SELECT * FROM carts WHERE request_type = 'custom' ORDER BY id DESC LIMIT 1",
            one=True,
        )
        cart_id = cart["id"]
        assert cart["external_url"].startswith("https://www.shein.com")

    sign_in(client, "traveler")
    assert client.post(
        f"/carts/{cart_id}/accept", data={"trip_id": str(trip_id)}
    ).status_code == 302
    with app.app_context():
        assert query("SELECT status FROM carts WHERE id = ?", (cart_id,), one=True)["status"] == "assigned"

    sign_in(client, "buyer")
    assert client.post(f"/escrow/{cart_id}/pay").status_code == 302
    assert client.post(f"/escrow/{cart_id}/pay").status_code == 302
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        assert cart["paid"] == 1
        assert cart["receipt_due_at"]
        buyer_id = account_ids(app)["buyer"]
        assert wallet_balance(buyer_id) == pytest.approx(-110000)
        assert query(
            "SELECT COUNT(*) n FROM wallet_transactions WHERE reference = ?",
            (f"escrow-pay-{cart_id}",), one=True,
        )["n"] == 1

    sign_in(client, "traveler")
    assert client.post(
        f"/carts/{cart_id}/receipt",
        data={
            "store": "Shein",
            "amount": "100",
            "purchase_date": date.today().isoformat(),
            "receipt": (io.BytesIO(b"receipt"), "receipt.jpg"),
        },
        content_type="multipart/form-data",
    ).status_code == 302
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        assert cart["receipt_status"] == "pending"
        assert cart["status"] == "assigned"

    sign_in(client, "admin")
    assert client.post(f"/admin/receipts/{cart_id}/verify").status_code == 302
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        assert cart["status"] == "purchased"
        assert cart["receipt_status"] == "verified"
        assert query(
            "SELECT COUNT(*) n FROM messages WHERE recipient_id = ?",
            (account_ids(app)["buyer"],), one=True,
        )["n"] >= 1

    sign_in(client, "traveler")
    client.post(f"/carts/{cart_id}/ship")
    client.post(f"/carts/{cart_id}/deliver")
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        code = code_display(cart)
        before = wallet_balance(account_ids(app)["traveler"])

    sign_in(client, "buyer")
    assert client.post(f"/escrow/{cart_id}/release", data={"code": code}).status_code == 302
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        assert cart["status"] == "completed"
        assert wallet_balance(account_ids(app)["traveler"]) == pytest.approx(before + 10000)
        assert wallet_balance(account_ids(app)["buyer"]) == pytest.approx(-110000)
        assert query(
            "SELECT COUNT(*) n FROM wallet_transactions WHERE reference LIKE ?",
            (f"escrow-%-{cart_id}%",), one=True,
        )["n"] == 2


def test_late_receipt_refunds_buyer_automatically_without_a_page_visit(app, client):
    trip_id = add_trip(app)
    traveler_id = account_ids(app)["traveler"]
    cart_id = add_cart(
        app, traveler_id=traveler_id, trip_id=trip_id, status="assigned",
        paid=1, fee=10, receipt_due_at="2020-01-01 00:00:00",
    )
    with app.app_context():
        execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, kind, description, reference, created_at)
               VALUES (?, -110, 'escrow', 'Test escrow payment', ?, ?)""",
            (account_ids(app)["buyer"], f"escrow-pay-{cart_id}",
             datetime.now().strftime(STAMP)),
        )
        expire_overdue_carts()
        expire_overdue_carts()
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        assert cart["cancelled_at"] is not None
        assert cart["refunded_at"] is not None
        assert wallet_balance(account_ids(app)["buyer"]) == pytest.approx(0)
        assert query(
            "SELECT COUNT(*) n FROM wallet_transactions WHERE reference = ?",
            (f"escrow-refund-{cart_id}",), one=True,
        )["n"] == 1


def test_seller_adds_and_bulk_uploads_products(app, client):
    sign_in(client, "seller")
    assert client.post("/products/add", data={
        "name": "Pytest Jacket",
        "description": "Added by the test suite",
        "price": "123",
        "stock": "9",
        "category": "Fashion",
        "weight": "1.2",
    }).status_code == 302

    client.post("/products/bulk", data={
        "csv": "Pytest Bulk One,10,3,Fashion\nPytest Bulk Two,20,4,Home\ninvalid row"
    })

    with app.app_context():
        assert query("SELECT COUNT(*) n FROM products WHERE name = 'Pytest Jacket'", one=True)["n"] == 1
        assert query("SELECT COUNT(*) n FROM products WHERE name LIKE 'Pytest Bulk%'", one=True)["n"] == 2
        assert query(
            "SELECT listing_type FROM products WHERE name = 'Pytest Jacket'", one=True,
        )["listing_type"] == "local"

    sign_in(client, "buyer")
    assert b"Pytest Jacket" in client.get("/local").data


def test_order_advance_and_review(app, client):
    product_id = add_product(app, name="Ordered product")
    ids = account_ids(app)
    with app.app_context():
        new_order = execute(
            """INSERT INTO orders (buyer_id, seller_id, product_id, quantity, total, status, created_at, updated_at)
               VALUES (?, ?, ?, 1, 100, 'new', ?, ?)""",
            (ids["buyer"], ids["seller"], product_id,
             datetime.now().strftime(STAMP), datetime.now().strftime(STAMP)),
        )
        delivered_order = execute(
            """INSERT INTO orders (buyer_id, seller_id, product_id, quantity, total, status, created_at, updated_at)
               VALUES (?, ?, ?, 1, 100, 'delivered', ?, ?)""",
            (ids["buyer"], ids["seller"], product_id,
             datetime.now().strftime(STAMP), datetime.now().strftime(STAMP)),
        )

    sign_in(client, "seller")
    assert client.post(f"/orders/{new_order}/advance").status_code == 302
    with app.app_context():
        assert query("SELECT status FROM orders WHERE id = ?", (new_order,), one=True)["status"] == "processing"

    sign_in(client, "buyer")
    assert client.post("/reviews/add", data={
        "order_id": str(delivered_order), "rating": "5", "comment": "Exactly as described.",
    }).status_code == 302
    with app.app_context():
        assert query("SELECT COUNT(*) n FROM reviews WHERE order_id = ?", (delivered_order,), one=True)["n"] == 1


def test_local_listing_upload(app, client):
    # Buyers cannot list local marketplace products any more; only sellers/pro can.
    sign_in(client, "buyer")
    response = client.post("/local/add", data={
        "name": "Local bag", "description": "Handmade", "price": "80",
        "stock": "2", "category": "Accessories", "weight": "0.8",
    })
    assert response.status_code == 302
    with app.app_context():
        product = query("SELECT * FROM products WHERE name = 'Local bag'", one=True)
        assert product is None

    # A registered seller can still add a local listing.
    sign_in(client, "seller")
    assert client.post("/local/add", data={
        "name": "Local bag", "description": "Handmade", "price": "80",
        "stock": "2", "category": "Accessories", "weight": "0.8",
    }).status_code == 302
    with app.app_context():
        product = query("SELECT * FROM products WHERE name = 'Local bag'", one=True)
        assert product["listing_type"] == "local"
    assert b"Local bag" in client.get("/local").data


def test_escrow_state_machine_guards(app, client):
    cart_id = add_cart(app, status="delivered", paid=1)
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
        buyer = query("SELECT * FROM users WHERE role = 'buyer'", one=True)
        traveler = query("SELECT * FROM users WHERE role = 'traveler'", one=True)
        assert can_transition(cart, "release", "buyer") is True
        assert can_transition(cart, "release", "seller") is True
        assert can_transition(cart, "release", "traveler") is False
        with pytest.raises(PermissionError):
            transition(cart, "release", traveler)
        with pytest.raises(ValueError):
            transition(cart, "accept", traveler)


def test_api_token_round_trip(app, client):
    add_product(app, name="API product")
    sign_in(client, "seller")
    assert client.post("/api/token", data={"label": "Pytest key"}).status_code == 302

    with client.session_transaction() as session:
        token = session.get("new_api_token")
    assert token and token.startswith("abr_")

    response = client.get("/api/v1/products", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json["count"] >= 1
    assert client.get("/api/v1/products", headers={"Authorization": "Bearer nope"}).status_code == 401

    with app.app_context():
        record = query("SELECT * FROM api_tokens WHERE label = 'Pytest key'", one=True)
        assert record["token_hash"] != token
        assert record["prefix"] == token[:10]


def test_registration_uses_demo_otp_and_stays_pending(app, client):
    response = client.post("/register", data={
        "role": "buyer", "name": "Test Buyer",
        "email": "test.buyer@example.com", "password": "secret123", "country": "Tunisia",
    })
    assert response.status_code == 200
    assert b"Verify your account" in response.data

    with client.session_transaction() as session:
        pending = session["pending_signup"]
        code = pending["code"]
        assert pending["city"] == "Tunis"

    assert client.post("/register/verify", data={"code": code}).status_code == 302
    with app.app_context():
        user = query("SELECT * FROM users WHERE email = 'test.buyer@example.com'", one=True)
        assert user["role"] == "buyer"
        assert user["status"] == "pending"


def test_csrf_is_required_for_posts(tmp_path):
    application = create_app({
        "TESTING": True,
        "SECRET_KEY": "csrf-test-secret",
        "DATABASE": str(tmp_path / "csrf.sqlite"),
        "UPLOAD_FOLDER": str(tmp_path / "uploads"),
        "CSRF_ENABLED": True,
    })
    client = application.test_client()
    client.get("/login")

    blocked = client.post("/login", data={"email": "sarra@abroad.tn", "password": "demo1234"})
    assert blocked.status_code == 400

    with client.session_transaction() as session:
        token = session["csrf_token"]

    allowed = client.post("/login", data={
        "email": "sarra@abroad.tn",
        "password": "demo1234",
        "csrf_token": token,
    })
    assert allowed.status_code == 302


def test_local_order_lifecycle_cancel_confirm_and_review_gate(app, client):
    product_id = add_product(app, name="Lifecycle lamp", listing_type="local")

    sign_in(client, "buyer")
    assert client.post(f"/products/{product_id}/order", data={"quantity": "2"}).status_code == 302
    with app.app_context():
        order = query("SELECT * FROM orders WHERE product_id = ?", (product_id,), one=True)
        stock = query("SELECT stock FROM products WHERE id = ?", (product_id,), one=True)["stock"]
    assert order["quantity"] == 2
    assert order["total"] == pytest.approx(200)
    assert stock == 3

    # Reviews stay closed until the product has been delivered.
    client.post(f"/product/{product_id}/review", data={"rating": "5", "comment": "Too early"})
    with app.app_context():
        assert query("SELECT COUNT(*) n FROM product_reviews WHERE product_id = ?",
                     (product_id,), one=True)["n"] == 0

    # Cancelling before shipping puts the stock back.
    assert client.post(f"/orders/{order['id']}/cancel").status_code == 302
    with app.app_context():
        assert query("SELECT status FROM orders WHERE id = ?", (order["id"],), one=True)["status"] == "cancelled"
        assert query("SELECT stock FROM products WHERE id = ?", (product_id,), one=True)["stock"] == 5

    client.post(f"/products/{product_id}/order", data={"quantity": "1"})
    with app.app_context():
        order = query("SELECT * FROM orders WHERE product_id = ? AND status = 'new'",
                      (product_id,), one=True)

    sign_in(client, "seller")
    for _ in range(3):
        client.post(f"/orders/{order['id']}/advance")
    with app.app_context():
        assert query("SELECT status FROM orders WHERE id = ?", (order["id"],), one=True)["status"] == "delivered"

    sign_in(client, "buyer")
    assert client.post(f"/orders/{order['id']}/confirm").status_code == 302
    with app.app_context():
        assert query("SELECT confirmed_at FROM orders WHERE id = ?", (order["id"],), one=True)["confirmed_at"]

    assert client.post(f"/product/{product_id}/review",
                       data={"rating": "5", "comment": "Arrived fast"}).status_code == 302
    with app.app_context():
        review = query("SELECT * FROM product_reviews WHERE product_id = ?", (product_id,), one=True)
    assert review["order_id"] == order["id"]


def test_buyer_never_sees_listing_controls(app, client):
    ids = account_ids(app)
    buyer_owned = add_product(app, seller_id=ids["buyer"], name="Buyer listing", listing_type="local")
    seller_product = add_product(app, name="Seller listing", listing_type="local")

    sign_in(client, "buyer")
    page = client.get(f"/product/{buyer_owned}").data
    assert b"Edit listing" not in page
    assert b"Manage photos" not in page
    assert b"cannot review your own listing" in page

    sign_in(client, "seller")
    assert b"Edit listing" in client.get(f"/product/{seller_product}").data


def test_admin_actions_are_audited(app, client):
    ids = account_ids(app)
    sign_in(client, "admin")
    assert client.post(f"/admin/staff/{ids['seller']}/toggle").status_code == 302
    with app.app_context():
        entry = query("SELECT * FROM audit_log WHERE action = 'staff.toggle'", one=True)
    assert entry is not None
    assert entry["entity"] == "users"
    page = client.get("/admin/audit")
    assert page.status_code == 200
    assert b"staff.toggle" in page.data


def test_receipt_amount_mismatch_is_flagged(app, client):
    ids = account_ids(app)
    cart_id = add_cart(app, status="assigned", paid=1, traveler_id=ids["traveler"],
                       fee=10.0, price=100.0)
    sign_in(client, "traveler")
    response = client.post(
        f"/carts/{cart_id}/receipt",
        data={
            "store": "Another store",
            "amount": "10",
            "purchase_date": date.today().isoformat(),
            "receipt": (io.BytesIO(b"receipt-bytes"), "receipt.jpg"),
        },
        content_type="multipart/form-data",
    )
    assert response.status_code == 302
    with app.app_context():
        cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    assert cart["receipt_status"] == "pending"
    assert cart["receipt_hash"]
    assert "amount" in cart["receipt_flag"]


def test_money_is_stored_in_integer_millimes(app, client):
    sign_in(client, "seller")
    assert client.post("/products/add", data={
        "name": "Millime check", "description": "Stored as millimes", "price": "12.5",
        "stock": "3", "category": "Fashion", "weight": "1",
    }).status_code == 302
    with app.app_context():
        row = query("SELECT price FROM products WHERE name = 'Millime check'", one=True)
        types = {column["name"]: column["type"] for column in query("PRAGMA table_info(products)")}
    assert row["price"] == 12500
    assert types["price"] == "INTEGER"


def test_top_up_and_payout_approval(app, client):
    ids = account_ids(app)
    sign_in(client, "buyer")
    client.post("/wallet/top-up", data={"amount": "100"})
    with app.app_context():
        assert wallet_balance(ids["buyer"]) == 100000

    # A single top-up cannot exceed the demo limit.
    client.post("/wallet/top-up", data={"amount": "9000"})
    with app.app_context():
        assert wallet_balance(ids["buyer"]) == 100000

    sign_in(client, "seller")
    client.post("/wallet/top-up", data={"amount": "50"})
    client.post("/wallet/payout", data={"amount": "20", "method": "D17", "details": "12345678"})
    with app.app_context():
        payout = query("SELECT * FROM payout_requests ORDER BY id DESC LIMIT 1", one=True)
        assert payout["status"] == "pending"
        assert payout["amount"] == 20000
        assert wallet_balance(ids["seller"]) == 30000

    # Requesting more than the balance is refused.
    client.post("/wallet/payout", data={"amount": "500"})
    with app.app_context():
        assert query("SELECT COUNT(*) n FROM payout_requests", one=True)["n"] == 1

    sign_in(client, "admin")
    assert client.post(f"/admin/payouts/{payout['id']}/pay").status_code == 302
    with app.app_context():
        assert query("SELECT status FROM payout_requests WHERE id = ?",
                     (payout["id"],), one=True)["status"] == "paid"
