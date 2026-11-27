import csv
import hashlib
import io
import os
import re
import secrets
from datetime import date, datetime, timedelta
from urllib.parse import urlparse

from flask import (Blueprint, abort, current_app, flash, g, jsonify, redirect,
                   render_template, request, session, url_for)
from werkzeug.utils import secure_filename

from auth import admin_required, login_required, roles_required, staff_required
from constants import (CART_STEP_INDEX, CART_STEPS, CATEGORIES, ORDER_FLOW,
                       SELLER_ROLES, STAFF_ROLE)
from db import execute, get_db, query, transaction
from escrow import can_transition, transition
from matching import eligible_trips
from money import format_dt, from_millimes, to_millimes
from otp import code_display, issue as issue_code, refresh_if_expired, verify as verify_code
from refunds import expire_overdue_carts
from services import (cart_items, cart_totals, notify, record_wallet,
                      seller_ids_for_cart, wallet_balance)

main_bp = Blueprint("main", __name__)
STAMP = "%Y-%m-%d %H:%M:%S"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def cart_with_people(cart_id=None, where=None, args=()):
    sql = """SELECT c.*, b.name AS buyer_name, b.email AS buyer_email,
                    tr.name AS traveler_name, tr.email AS traveler_email,
                    pt.name AS preferred_traveler_name,
                    t.from_city, t.to_city, t.departure_date, t.arrival_date
             FROM carts c
             JOIN users b ON b.id = c.buyer_id
             LEFT JOIN users tr ON tr.id = c.traveler_id
             LEFT JOIN users pt ON pt.id = c.preferred_traveler_id
             LEFT JOIN trips t ON t.id = c.trip_id"""
    if cart_id is not None:
        return query(sql + " WHERE c.id = ?", (cart_id,), one=True)
    return query(sql + " WHERE " + where, args)


def as_dict(row):
    if isinstance(row, dict):
        return dict(row)
    return {key: row[key] for key in row.keys()}


def hydrate(row, traveler_matches=False):
    cart = as_dict(row)
    cart["line_items"] = cart_items(cart["id"])
    cart["total"], cart["weight"] = cart_totals(cart["id"])
    cart["code"] = code_display(cart) if cart["code_issued_at"] else None
    cart["payment_due"] = cart["status"] == "assigned" and not cart["paid"]
    cart["is_custom"] = cart["request_type"] == "custom"
    cart["receipt_waiting"] = cart["receipt_status"] == "pending"
    if traveler_matches:
        cart["matches"] = eligible_trips(cart, g.user["id"])
    return cart


def require_cart_access(cart):
    user = g.user
    if user["is_admin"]:
        return
    if cart["buyer_id"] == user["id"]:
        return
    if user["role"] == "traveler" and (cart["traveler_id"] == user["id"] or cart["status"] == "open"):
        return
    abort(403)


def notify_admins(title, body, link=None):
    for admin in query("SELECT id FROM users WHERE is_admin = 1"):
        notify(admin["id"], title, body, link)


def audit(action, entity, entity_id=None, details=None):
    """Record who changed what — staff and admin decisions must be traceable."""
    actor = g.get("user")
    execute(
        """INSERT INTO audit_log (actor_id, action, entity, entity_id, details, created_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (
            actor["id"] if actor else None,
            action[:80], entity[:40] if entity else None, entity_id,
            (details or "")[:400], datetime.now().strftime(STAMP),
        ),
    )


def available_trip_rows(limit=None):
    sql = """SELECT t.*, u.name AS traveler_name, u.city AS traveler_city,
                    u.rating AS traveler_rating, u.deliveries,
                    (t.capacity_kg - t.used_kg) AS remaining_kg
             FROM trips t JOIN users u ON u.id = t.traveler_id
             WHERE t.status = 'verified' AND t.arrival_date >= ?
               AND (t.capacity_kg - t.used_kg) > 0
             ORDER BY t.arrival_date"""
    rows = query(sql, (date.today().isoformat(),))
    return rows[:limit] if limit else rows


def store_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    safe = secure_filename(file_storage.filename)
    unique = f"{secrets.token_hex(6)}-{safe}"
    file_storage.save(os.path.join(current_app.config["UPLOAD_FOLDER"], unique))
    return f"/uploads/{unique}"


PROOF_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}


def store_uploads(file_storages, limit=6):
    """Store every uploaded photo and return the saved URLs."""
    urls = []
    for file_storage in file_storages or []:
        if not file_storage or not file_storage.filename:
            continue
        url = store_upload(file_storage)
        if url:
            urls.append(url)
        if len(urls) >= limit:
            break
    return urls


def gallery_images(product):
    """Primary photo first, then every extra photo the seller uploaded."""
    rows = query(
        "SELECT id, url FROM product_images WHERE product_id = ? ORDER BY position, id",
        (product["id"],),
    )
    images = []
    primary = product["image_url"]
    if primary and not primary.startswith("https://placehold.co"):
        images.append({"id": None, "url": primary})
    for row in rows:
        if all(row["url"] != image["url"] for image in images):
            images.append({"id": row["id"], "url": row["url"]})
    if not images:
        images.append({"id": None, "url": "https://placehold.co/600x400/eef3fb/1e3a8a?text=Product"})
    return images


def suggested_products(user_id, exclude=None, category=None, limit=8):
    """Simple "you may also like" ranking based on the shopper's history."""
    rows = query(
        """SELECT p.*, u.store_name, u.name AS seller_name, u.city AS seller_city,
                  (SELECT COUNT(*) FROM product_options po WHERE po.product_id = p.id) AS option_count
           FROM products p JOIN users u ON u.id = p.seller_id
           WHERE p.stock > 0"""
    )
    liked = {row["category"] for row in query(
        """SELECT DISTINCT p.category
           FROM products p JOIN orders o ON o.product_id = p.id
           WHERE o.buyer_id = ?""",
        (user_id,),
    )}
    liked |= {row["category"] for row in query(
        """SELECT DISTINCT p.category
           FROM products p
           JOIN cart_items ci ON ci.product_id = p.id
           JOIN carts c ON c.id = ci.cart_id
           WHERE c.buyer_id = ?""",
        (user_id,),
    )}

    scored = []
    for product in rows:
        if exclude is not None and product["id"] == exclude:
            continue
        score = 0
        if category and product["category"] == category:
            score += 5
        if product["category"] in liked:
            score += 3
        if product["featured"]:
            score += 2
        if product["listing_type"] == "local":
            score += 1
        scored.append((score, product))
    scored.sort(key=lambda item: (-item[0], (item[1]["name"] or "").lower()))
    return [product for _, product in scored[:limit]]


def store_proof(file_storage):
    if not file_storage or not file_storage.filename:
        return None
    extension = os.path.splitext(file_storage.filename)[1].lower()
    if extension not in PROOF_EXTENSIONS:
        return None
    return store_upload(file_storage)


def weekly_revenue(user_id):
    start = (date.today() - timedelta(days=6)).isoformat()
    rows = query(
        """SELECT date(created_at) AS day, SUM(amount) AS total
           FROM wallet_transactions
           WHERE user_id = ? AND kind = 'sale' AND date(created_at) >= ?
           GROUP BY date(created_at)""",
        (user_id, start),
    )
    totals = {row["day"]: row["total"] for row in rows}
    series = []
    for offset in range(6, -1, -1):
        moment = date.today() - timedelta(days=offset)
        series.append({"label": moment.strftime("%a"), "value": float(totals.get(moment.isoformat(), 0))})
    peak = max([point["value"] for point in series] + [1])
    for point in series:
        point["height"] = max(4, round(point["value"] / peak * 100))
    return series


def seller_context(user):
    products = query(
        """SELECT p.*, COALESCE(SUM(o.quantity), 0) AS sold
           FROM products p
           LEFT JOIN orders o ON o.product_id = p.id AND o.status != 'cancelled'
           WHERE p.seller_id = ?
           GROUP BY p.id
           ORDER BY p.featured DESC, p.created_at DESC""",
        (user["id"],),
    )
    orders = query(
        """SELECT o.*, p.name AS product_name, p.image_url,
                  b.name AS buyer_name, b.city AS buyer_city
           FROM orders o
           JOIN products p ON p.id = o.product_id
           JOIN users b ON b.id = o.buyer_id
           WHERE o.seller_id = ?
           ORDER BY o.created_at DESC
           LIMIT 8""",
        (user["id"],),
    )
    stats = {
        "revenue": query(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM wallet_transactions WHERE user_id = ? AND kind = 'sale'",
            (user["id"],), one=True)["total"],
        "balance": wallet_balance(user["id"]),
        "orders": query("SELECT COUNT(*) AS n FROM orders WHERE seller_id = ?",
                        (user["id"],), one=True)["n"],
        "products": len(products),
        "pending": query("SELECT COUNT(*) AS n FROM orders WHERE seller_id = ? AND status = 'new'",
                         (user["id"],), one=True)["n"],
        "low_stock": len([p for p in products if p["stock"] <= 5]),
        "reviews": query("SELECT COUNT(*) AS n FROM reviews WHERE seller_id = ?",
                         (user["id"],), one=True)["n"],
        "rating": query("SELECT AVG(rating) AS avg FROM reviews WHERE seller_id = ?",
                        (user["id"],), one=True)["avg"] or user["rating"],
    }
    messages = query(
        "SELECT COUNT(*) AS n FROM messages WHERE recipient_id = ? AND read = 0",
        (user["id"],), one=True)["n"]

    activities = query(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 5",
        (user["id"],),
    )
    top_products = query(
        """SELECT p.name, SUM(o.quantity) AS qty, SUM(o.total) AS revenue
           FROM orders o JOIN products p ON p.id = o.product_id
           WHERE o.seller_id = ?
           GROUP BY p.id
           ORDER BY revenue DESC
           LIMIT 5""",
        (user["id"],),
    )
    status_counts = {
        row["status"]: row["n"]
        for row in query(
            "SELECT status, COUNT(*) AS n FROM orders WHERE seller_id = ? GROUP BY status",
            (user["id"],),
        )
    }
    return {
        "products": products,
        "orders": orders,
        "stats": stats,
        "messages": messages,
        "activities": activities,
        "top_products": top_products,
        "status_counts": status_counts,
        "chart": weekly_revenue(user["id"]),
    }


# ---------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------

@main_bp.get("/")
def index():
    if g.user:
        from constants import ROLE_HOME
        if g.user["is_admin"]:
            return redirect(url_for("main.admin_dashboard"))
        return redirect(url_for(ROLE_HOME[g.user["role"]]))
    return redirect(url_for("auth.login"))


@main_bp.get("/buyer")
@roles_required("buyer")
def buyer_dashboard():
    expire_overdue_carts()
    cart_rows = cart_with_people(
        where="c.buyer_id = ? AND c.status IN ('assigned', 'purchased', 'in_transit', 'delivered') ORDER BY c.updated_at DESC LIMIT 1",
        args=(g.user["id"],),
    )
    cart = hydrate(cart_rows[0]) if cart_rows else None
    if cart and cart["status"] == "delivered":
        line_items = cart["line_items"]
        cart = as_dict(refresh_if_expired(cart))
        cart["line_items"] = line_items
        cart["code"] = code_display(cart)

    orders = query(
        """SELECT o.*, p.name AS product_name, p.image_url, s.store_name AS seller_name, s.name AS seller_legal
           FROM orders o
           JOIN products p ON p.id = o.product_id
           JOIN users s ON s.id = o.seller_id
           WHERE o.buyer_id = ?
           ORDER BY o.created_at DESC
           LIMIT 3""",
        (g.user["id"],),
    )
    escrow_total = query(
        """SELECT COALESCE(SUM(ci.quantity * ci.unit_price), 0) AS total
           FROM carts c JOIN cart_items ci ON ci.cart_id = c.id
           WHERE c.buyer_id = ? AND c.paid = 1
             AND c.status IN ('assigned', 'purchased', 'in_transit', 'delivered')""",
        (g.user["id"],), one=True)["total"]
    payment_due = query(
        """SELECT COALESCE(SUM(ci.quantity * ci.unit_price), 0) AS total
           FROM carts c JOIN cart_items ci ON ci.cart_id = c.id
           WHERE c.buyer_id = ? AND c.paid = 0 AND c.status = 'assigned'""",
        (g.user["id"],), one=True)["total"]
    local_products = query(
        """SELECT p.*, u.name AS seller_name, u.store_name, u.city AS seller_city,
                  (SELECT COUNT(*) FROM product_options po WHERE po.product_id = p.id) AS option_count
           FROM products p JOIN users u ON u.id = p.seller_id
           WHERE p.listing_type = 'local' AND p.stock > 0
           ORDER BY p.created_at DESC LIMIT 4"""
    )
    travelers = available_trip_rows(limit=3)

    return render_template(
        "dashboard_buyer.html",
        cart=cart,
        steps=CART_STEPS,
        step=CART_STEP_INDEX.get(cart["status"], 1) if cart else 0,
        orders=orders,
        escrow_total=escrow_total,
        payment_due=payment_due,
        local_products=local_products,
        travelers=travelers,
    )


@main_bp.get("/seller")
@roles_required(*SELLER_ROLES)
def seller_dashboard():
    if g.user["is_admin"]:
        return redirect(url_for("main.admin_dashboard"))
    if g.user["role"] == "pro":
        return redirect(url_for("main.pro_dashboard"))
    return render_template("dashboard_seller.html", **seller_context(g.user), is_pro=False)


@main_bp.get("/pro")
@roles_required(*SELLER_ROLES)
def pro_dashboard():
    if g.user["is_admin"]:
        return redirect(url_for("main.admin_dashboard"))
    if g.user["role"] == "seller":
        return redirect(url_for("main.seller_dashboard"))
    return render_template("dashboard_pro.html", **seller_context(g.user), is_pro=True)


@main_bp.get("/traveler")
@roles_required("traveler")
def traveler_dashboard():
    expire_overdue_carts()
    tab = request.args.get("tab", "carts")
    if tab not in ("carts", "requests", "verification"):
        tab = "carts"

    active_rows = cart_with_people(
        where="c.traveler_id = ? AND c.status IN ('assigned', 'purchased', 'in_transit', 'delivered') ORDER BY c.updated_at DESC",
        args=(g.user["id"],),
    )
    active = [hydrate(row) for row in active_rows]

    request_rows = cart_with_people(
        where="""c.status = 'open'
                 AND (c.preferred_traveler_id IS NULL OR c.preferred_traveler_id = ?)
                 AND NOT EXISTS (SELECT 1 FROM cart_declines d WHERE d.cart_id = c.id AND d.traveler_id = ?)
                 ORDER BY c.created_at DESC""",
        args=(g.user["id"], g.user["id"]),
    )
    requests = [hydrate(row, traveler_matches=True) for row in request_rows]

    trips = query(
        "SELECT * FROM trips WHERE traveler_id = ? ORDER BY departure_date",
        (g.user["id"],),
    )
    verified_trips = [trip for trip in trips if trip["status"] == "verified" and trip["arrival_date"] >= date.today().isoformat()]
    active_trip = verified_trips[0] if verified_trips else None
    pending_trips = [trip for trip in trips if trip["status"] == "pending"]

    escrow_total = sum(cart["total"] + (cart["traveler_fee"] or 0) for cart in active if cart["paid"])
    earnings = query(
        "SELECT COALESCE(SUM(amount), 0) AS total FROM wallet_transactions WHERE user_id = ? AND kind = 'traveler_fee'",
        (g.user["id"],), one=True)["total"]
    completed = query(
        "SELECT COUNT(*) AS n FROM carts WHERE traveler_id = ? AND status = 'completed'",
        (g.user["id"],), one=True)["n"]
    receipt_count = query(
        """SELECT COUNT(*) AS n FROM carts
           WHERE traveler_id = ? AND paid = 1 AND status = 'assigned'
             AND receipt_status IN ('none', 'rejected')""",
        (g.user["id"],), one=True)["n"]

    return render_template(
        "dashboard_traveler.html",
        active=active,
        requests=requests,
        trips=trips,
        upcoming=verified_trips[:4],
        pending_trips=pending_trips,
        active_trip=active_trip,
        escrow_total=escrow_total,
        earnings=earnings,
        deliveries=g.user["deliveries"] + completed,
        receipt_count=receipt_count,
        tab=tab,
    )


# ---------------------------------------------------------------------------
# Shop and buyer requests
# ---------------------------------------------------------------------------

@main_bp.get("/shop")
@login_required
def shop():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "").strip()
    tab = (request.args.get("tab") or "all").strip()
    if tab not in ("all", "suggestions"):
        tab = "all"

    if tab == "suggestions":
        products = suggested_products(g.user["id"], limit=60)
    else:
        products = query(
            """SELECT p.*, u.store_name, u.name AS seller_name, u.rating, u.city AS seller_city,
                      (SELECT COUNT(*) FROM product_options po WHERE po.product_id = p.id) AS option_count
               FROM products p JOIN users u ON u.id = p.seller_id
               WHERE p.stock >= 0
               ORDER BY p.featured DESC, p.created_at DESC"""
        )
    if q:
        needle = q.lower()
        products = [
            product for product in products
            if needle in (product["name"] or "").lower()
            or needle in (product["description"] or "").lower()
            or needle in (product["store_name"] or "").lower()
            or needle in (product["seller_name"] or "").lower()
            or needle in (product["category"] or "").lower()
        ]
    if category:
        products = [product for product in products if product["category"] == category]
    open_carts = query(
        "SELECT * FROM carts WHERE buyer_id = ? AND status = 'open' ORDER BY created_at DESC",
        (g.user["id"],),
    ) if g.user["role"] == "buyer" else []
    return render_template(
        "shop.html",
        products=products,
        open_carts=open_carts,
        categories=CATEGORIES,
        q=q,
        active_category=category,
        tab=tab,
    )


@main_bp.post("/shop/<int:product_id>/request")
@roles_required("buyer")
def request_product(product_id):
    product = query(
        """SELECT p.*, u.store_name, u.name AS seller_name
           FROM products p JOIN users u ON u.id = p.seller_id
           WHERE p.id = ? AND p.listing_type = 'travel'""",
        (product_id,), one=True,
    )
    if not product or product["stock"] < 1:
        flash("That product is out of stock.", "error")
        return redirect(url_for("main.shop"))

    store = product["store_name"] or product["seller_name"]
    cart = query(
        """SELECT * FROM carts
           WHERE buyer_id = ? AND status = 'open' AND store_name = ?
           ORDER BY id DESC LIMIT 1""",
        (g.user["id"], store), one=True,
    )
    if not cart:
        cart_id = execute(
            """INSERT INTO carts
               (buyer_id, store_name, status, delivery_city, delivery_date,
                traveler_fee, instructions, request_type, created_at, updated_at)
               VALUES (?, ?, 'open', ?, ?, 5, '', 'shop', ?, ?)""",
            (
                g.user["id"], store, g.user["city"],
                (date.today() + timedelta(days=20)).isoformat(),
                datetime.now().strftime(STAMP), datetime.now().strftime(STAMP),
            ),
        )
    else:
        cart_id = cart["id"]
        execute("UPDATE carts SET updated_at = ? WHERE id = ?",
                (datetime.now().strftime(STAMP), cart_id))

    quantity = read_quantity(product)
    variant, error = read_variant(product_id)
    if error:
        flash(error, "error")
        return redirect(url_for("main.product_detail", product_id=product_id))
    line_name = product["name"] + (f" · {variant}" if variant else "")
    execute(
        """INSERT INTO cart_items
           (cart_id, product_id, name, quantity, unit_price, weight_kg, variant)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (cart_id, product["id"], line_name, quantity, product["price"],
         product["weight_kg"], variant),
    )
    notify(
        g.user["id"],
        "Traveler request created",
        f"{quantity} × {line_name} was added to your {store} request.",
        url_for("main.escrow"),
    )
    flash(f"{product['name']} added to your traveler request.", "success")
    return redirect(url_for("main.shop"))


@main_bp.get("/local")
@login_required
def local_market():
    products = query(
        """SELECT p.*, u.name AS seller_name, u.store_name, u.city AS seller_city,
                  u.rating AS seller_rating,
                  (SELECT COUNT(*) FROM product_options po WHERE po.product_id = p.id) AS option_count
           FROM products p JOIN users u ON u.id = p.seller_id
           WHERE p.listing_type = 'local' AND p.stock > 0
           ORDER BY p.created_at DESC"""
    )
    mine = [p for p in products if p["seller_id"] == g.user["id"]]
    return render_template(
        "local_market.html",
        products=products,
        mine=mine,
        categories=CATEGORIES,
    )


@main_bp.post("/local/add")
@roles_required("seller", "pro")
def local_product_add():
    data = read_product_form()
    if not data:
        return redirect(url_for("main.local_market"))
    execute(
        """INSERT INTO products
           (seller_id, name, description, price, stock, category, listing_type,
            image_url, video_url, weight_kg, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'local', ?, ?, ?, ?)""",
        (
            g.user["id"], data["name"], data["description"], data["price"],
            data["stock"], data["category"], data["image_url"], data["video_url"],
            data["weight"], datetime.now().strftime(STAMP),
        ),
    )
    flash(f"“{data['name']}” is now listed in the local Tunisian marketplace.", "success")
    return redirect(url_for("main.local_market"))


@main_bp.post("/local/<int:product_id>/delete")
@roles_required("seller", "pro")
def local_product_delete(product_id):
    product = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ? AND listing_type = 'local'",
        (product_id, g.user["id"]), one=True,
    )
    if not product:
        abort(404)
    execute("DELETE FROM products WHERE id = ?", (product_id,))
    flash("Local listing removed.", "success")
    return redirect(url_for("main.local_market"))


# ---------------------------------------------------------------------------
# Product page: photo gallery, reviews and suggestions
# ---------------------------------------------------------------------------

@main_bp.get("/product/<int:product_id>")
@login_required
def product_detail(product_id):
    product = query(
        """SELECT p.*, u.name AS seller_name, u.store_name, u.city AS seller_city,
                  u.rating AS seller_rating
           FROM products p JOIN users u ON u.id = p.seller_id
           WHERE p.id = ?""",
        (product_id,), one=True,
    )
    if not product:
        abort(404)

    tab = (request.args.get("tab") or "reviews").strip()
    if tab not in ("reviews", "suggestions"):
        tab = "reviews"

    review_rows = query(
        """SELECT r.*, b.name AS buyer_name, b.city AS buyer_city
           FROM product_reviews r JOIN users b ON b.id = r.buyer_id
           WHERE r.product_id = ?
           ORDER BY r.created_at DESC, r.id DESC""",
        (product_id,),
    )
    stats = query(
        """SELECT COUNT(*) AS n, COALESCE(AVG(rating), 0) AS average
           FROM product_reviews WHERE product_id = ?""",
        (product_id,), one=True,
    )
    my_review = query(
        "SELECT * FROM product_reviews WHERE product_id = ? AND buyer_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    purchased = query(
        """SELECT id FROM orders
           WHERE buyer_id = ? AND product_id = ? AND status = 'delivered'
           ORDER BY id DESC LIMIT 1""",
        (product_id, g.user["id"]), one=True,
    )
    return render_template(
        "product_detail.html",
        product=product,
        can_review=bool(purchased),
        options=product_options(product_id),
        images=gallery_images(product),
        reviews=review_rows,
        review_count=stats["n"],
        review_average=round(stats["average"], 1),
        my_review=my_review,
        suggestions=suggested_products(g.user["id"], exclude=product_id,
                                       category=product["category"]),
        tab=tab,
    )


@main_bp.post("/product/<int:product_id>/review")
@login_required
def product_review_add(product_id):
    product = query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        abort(404)
    if product["seller_id"] == g.user["id"]:
        flash("You cannot review your own listing.", "error")
        return redirect(url_for("main.product_detail", product_id=product_id))

    purchased = query(
        """SELECT id FROM orders
           WHERE buyer_id = ? AND product_id = ? AND status = 'delivered'
           ORDER BY id DESC LIMIT 1""",
        (g.user["id"], product_id), one=True,
    )
    if not purchased:
        flash("Reviews open once this product has been delivered to you.", "error")
        return redirect(url_for("main.product_detail", product_id=product_id, tab="reviews"))

    try:
        rating = int(request.form.get("rating") or 0)
    except ValueError:
        rating = 0
    comment = (request.form.get("comment") or "").strip()
    if rating not in range(1, 6):
        flash("Choose a rating between 1 and 5.", "error")
        return redirect(url_for("main.product_detail", product_id=product_id, tab="reviews"))

    existing = query(
        "SELECT id FROM product_reviews WHERE product_id = ? AND buyer_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if existing:
        execute(
            """UPDATE product_reviews SET rating = ?, comment = ?, created_at = ?
               WHERE id = ?""",
            (rating, comment, datetime.now().strftime(STAMP), existing["id"]),
        )
        flash("Your review was updated.", "success")
    else:
        execute(
            """INSERT INTO product_reviews
               (product_id, buyer_id, order_id, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (product_id, g.user["id"], purchased["id"], rating, comment,
             datetime.now().strftime(STAMP)),
        )
        notify(
            product["seller_id"],
            "New review on your listing",
            f"{rating}/5 · {product['name']}",
            url_for("main.product_detail", product_id=product_id, tab="reviews"),
        )
        flash("Thanks — your review is published.", "success")
    return redirect(url_for("main.product_detail", product_id=product_id, tab="reviews"))


@main_bp.get("/travelers")
@login_required
def travelers_page():
    return render_template("travelers.html", travelers=available_trip_rows())


@main_bp.route("/requests/new", methods=["GET", "POST"])
@roles_required("buyer", "seller", "pro")
def custom_request():
    requested_traveler_id = request.values.get("traveler_id", type=int)
    traveler = None
    trip = None
    if requested_traveler_id:
        traveler = query(
            "SELECT * FROM users WHERE id = ? AND role = 'traveler' AND status = 'active'",
            (requested_traveler_id,), one=True,
        )
        if traveler:
            trip = query(
                """SELECT * FROM trips
                   WHERE traveler_id = ? AND status = 'verified' AND arrival_date >= ?
                   ORDER BY arrival_date LIMIT 1""",
                (traveler["id"], date.today().isoformat()), one=True,
            )

    form_values = {
        "store_name": (request.form.get("store_name") or "").strip(),
        "external_url": (request.form.get("external_url") or "").strip(),
        "item_name": (request.form.get("item_name") or "").strip(),
        "item_price": (request.form.get("item_price") or "").strip(),
        "weight": (request.form.get("weight") or "").strip(),
        "delivery_city": (request.form.get("delivery_city") or (trip["to_city"] if trip else g.user["city"])).strip(),
        "delivery_date": (request.form.get("delivery_date") or (trip["arrival_date"] if trip else (date.today() + timedelta(days=20)).isoformat())).strip(),
        "traveler_fee": (
            request.form.get("traveler_fee")
            or (f"{from_millimes(trip['fee']):g}" if trip else "8")
        ).strip(),
        "instructions": (request.form.get("instructions") or "").strip(),
    }

    if request.method == "POST":
        try:
            item_price = to_millimes(form_values["item_price"])
            weight = float(form_values["weight"])
            fee = to_millimes(form_values["traveler_fee"])
        except ValueError:
            flash("Item price, weight and traveler fee must be numbers.", "error")
            return render_template(
                "custom_request.html", traveler=traveler, trip=trip,
                values=form_values, categories=CATEGORIES,
            ), 400

        parsed = urlparse(form_values["external_url"])
        errors = []
        if len(form_values["store_name"]) < 2:
            errors.append("Add the online store name (for example Shein).")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            errors.append("Paste the full cart link, starting with https://.")
        if len(form_values["item_name"]) < 2:
            errors.append("Describe the item you want.")
        if item_price <= 0 or weight <= 0 or fee < 0:
            errors.append("The item price and weight must be positive.")
        try:
            delivery_day = date.fromisoformat(form_values["delivery_date"])
            if delivery_day < date.today():
                errors.append("Choose a delivery date in the future.")
        except ValueError:
            errors.append("Choose a valid delivery date.")

        preferred_id = request.form.get("preferred_traveler_id", type=int)
        if preferred_id:
            preferred = query(
                "SELECT id FROM users WHERE id = ? AND role = 'traveler' AND status = 'active'",
                (preferred_id,), one=True,
            )
            if not preferred:
                errors.append("That traveler is not available.")
        if errors:
            for message in errors:
                flash(message, "error")
            return render_template(
                "custom_request.html", traveler=traveler, trip=trip,
                values=form_values, categories=CATEGORIES,
            ), 400

        cart_id = execute(
            """INSERT INTO carts
               (buyer_id, store_name, status, delivery_city, delivery_date,
                traveler_fee, instructions, request_type, external_url,
                preferred_traveler_id, created_at, updated_at)
               VALUES (?, ?, 'open', ?, ?, ?, ?, 'custom', ?, ?, ?, ?)""",
            (
                g.user["id"], form_values["store_name"], form_values["delivery_city"],
                form_values["delivery_date"], fee, form_values["instructions"],
                form_values["external_url"], preferred_id or None,
                datetime.now().strftime(STAMP), datetime.now().strftime(STAMP),
            ),
        )
        execute(
            """INSERT INTO cart_items (cart_id, product_id, name, quantity, unit_price, weight_kg)
               VALUES (?, NULL, ?, 1, ?, ?)""",
            (cart_id, form_values["item_name"], item_price, weight),
        )

        recipients = []
        if preferred_id:
            recipients = [preferred_id]
        else:
            recipients = [
                row["traveler_id"]
                for row in query(
                    """SELECT DISTINCT traveler_id FROM trips
                       WHERE status = 'verified' AND arrival_date >= ?""",
                    (date.today().isoformat(),),
                )
            ]
        for traveler_id in recipients:
            notify(
                traveler_id,
                "New custom shopping request",
                f"{g.user['name']} wants a {form_values['item_name']} from {form_values['store_name']}.",
                url_for("main.requests_page"),
            )
        notify(
            g.user["id"],
            "Custom request published",
            f"A traveler can now accept your {form_values['store_name']} request.",
            url_for("main.escrow"),
        )
        flash("Request published. A verified traveler can accept it; payment stays in escrow.", "success")
        return redirect(url_for("main.sourcing") if g.user["role"] in SELLER_ROLES else url_for("main.buyer_dashboard"))

    return render_template(
        "custom_request.html", traveler=traveler, trip=trip,
        values=form_values, categories=CATEGORIES,
    )


@main_bp.get("/sourcing")
@roles_required(*SELLER_ROLES)
def sourcing():
    expire_overdue_carts()
    rows = cart_with_people(
        where="c.buyer_id = ? AND c.request_type = 'custom' ORDER BY c.created_at DESC",
        args=(g.user["id"],),
    )
    requests = [hydrate(row) for row in rows]
    return render_template("sourcing.html", requests=requests)


# ---------------------------------------------------------------------------
# Seller products
# ---------------------------------------------------------------------------

@main_bp.get("/products")
@roles_required(*SELLER_ROLES)
def products_page():
    products = query(
        """SELECT p.*, COALESCE(SUM(o.quantity), 0) AS sold
           FROM products p
           LEFT JOIN orders o ON o.product_id = p.id AND o.status != 'cancelled'
           WHERE p.seller_id = ?
           GROUP BY p.id
           ORDER BY p.featured DESC, p.created_at DESC""",
        (g.user["id"],),
    )
    edit_product = None
    edit_id = request.args.get("edit", type=int)
    if edit_id:
        edit_product = query(
            "SELECT * FROM products WHERE id = ? AND seller_id = ?",
            (edit_id, g.user["id"]), one=True,
        )
    return render_template(
        "products.html",
        products=products,
        edit_product=edit_product,
        edit_sizes=product_options(edit_product["id"], "size") if edit_product else [],
        edit_colors=product_options(edit_product["id"], "color") if edit_product else [],
        categories=CATEGORIES,
        inventory=request.args.get("view") == "inventory",
    )


def read_product_form(existing=None):
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    category = request.form.get("category") or "Fashion"
    try:
        price = to_millimes(request.form.get("price") or 0)
        stock = int(request.form.get("stock") or 0)
        weight = float(request.form.get("weight") or 0.5)
    except ValueError:
        flash("Price, stock and weight must be numbers.", "error")
        return None

    if len(name) < 2 or price < 0 or stock < 0 or weight <= 0:
        flash("Check the product name, price, stock and weight.", "error")
        return None
    if category not in CATEGORIES:
        category = "Fashion"

    uploads = store_uploads(request.files.getlist("images") or [request.files.get("image")])
    image_url = uploads[0] if uploads else ""
    if not image_url:
        image_url = (request.form.get("image_url") or "").strip()
    if not image_url and existing:
        image_url = existing["image_url"]
    if not image_url:
        image_url = "https://placehold.co/600x400/eef3fb/1e3a8a?text=Product"

    video_url = (request.form.get("video_url") or "").strip() or None
    listing_type = request.form.get("listing_type")
    if listing_type not in ("local", "travel"):
        listing_type = existing["listing_type"] if existing else "local"
    return {
        "name": name,
        "description": description,
        "price": price,
        "stock": stock,
        "category": category,
        "weight": weight,
        "image_url": image_url,
        "extra_images": uploads[1:],
        "video_url": video_url,
        "listing_type": listing_type,
        "sizes": parse_options(request.form.get("sizes")),
        "colors": parse_options(request.form.get("colors")),
    }


def product_options(product_id, kind=None):
    """Sizes and colours/models a seller attached to a listing."""
    rows = query(
        "SELECT kind, value FROM product_options WHERE product_id = ? ORDER BY kind, position, id",
        (product_id,),
    )
    options = {"sizes": [], "colors": []}
    for row in rows:
        key = "sizes" if row["kind"] == "size" else "colors"
        options[key].append(row["value"])
    if kind:
        return options["sizes"] if kind == "size" else options["colors"]
    return options


def parse_options(raw, limit=12):
    """Turn "S, M, L" or one-per-line input into a clean option list."""
    values = []
    for part in re.split(r"[,;\n]+", raw or ""):
        value = part.strip()
        if value and value.lower() not in (item.lower() for item in values):
            values.append(value[:40])
        if len(values) >= limit:
            break
    return values


def save_product_options(product_id, sizes, colors):
    execute("DELETE FROM product_options WHERE product_id = ?", (product_id,))
    for kind, values in (("size", sizes), ("color", colors)):
        for position, value in enumerate(values):
            execute(
                """INSERT INTO product_options (product_id, kind, value, position)
                   VALUES (?, ?, ?, ?)""",
                (product_id, kind, value, position),
            )


def save_extra_images(product_id, urls):
    """Append uploaded gallery photos to a product."""
    if not urls:
        return
    start = query(
        "SELECT COALESCE(MAX(position), 0) AS pos FROM product_images WHERE product_id = ?",
        (product_id,), one=True,
    )["pos"]
    stamp = datetime.now().strftime(STAMP)
    for offset, url in enumerate(urls, start=1):
        execute(
            """INSERT INTO product_images (product_id, url, position, created_at)
               VALUES (?, ?, ?, ?)""",
            (product_id, url, start + offset, stamp),
        )


@main_bp.post("/products/add")
@roles_required(*SELLER_ROLES)
def product_add():
    data = read_product_form()
    if not data:
        return redirect(url_for("main.products_page"))
    product_id = execute(
        """INSERT INTO products
           (seller_id, name, description, price, stock, category, listing_type,
            image_url, video_url, weight_kg, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            g.user["id"], data["name"], data["description"], data["price"],
            data["stock"], data["category"], data["listing_type"], data["image_url"],
            data["video_url"], data["weight"], datetime.now().strftime(STAMP),
        ),
    )
    save_extra_images(product_id, data["extra_images"])
    save_product_options(product_id, data["sizes"], data["colors"])
    flash(f"Product “{data['name']}” added.", "success")
    return redirect(url_for("main.products_page"))


@main_bp.post("/products/<int:product_id>/edit")
@roles_required(*SELLER_ROLES)
def product_edit(product_id):
    existing = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if not existing:
        abort(404)
    data = read_product_form(existing)
    if not data:
        return redirect(url_for("main.products_page", edit=product_id))
    execute(
        """UPDATE products
           SET name = ?, description = ?, price = ?, stock = ?, category = ?,
               listing_type = ?, image_url = ?, video_url = ?, weight_kg = ?
           WHERE id = ?""",
        (
            data["name"], data["description"], data["price"], data["stock"],
            data["category"], data["listing_type"], data["image_url"],
            data["video_url"], data["weight"], product_id,
        ),
    )
    save_extra_images(product_id, data["extra_images"])
    save_product_options(product_id, data["sizes"], data["colors"])
    flash(f"Product “{data['name']}” updated.", "success")
    return redirect(url_for("main.products_page"))


def read_variant(product_id):
    """Validate the chosen size/colour and return a printable label."""
    options = product_options(product_id)
    size = (request.form.get("size") or "").strip()
    color = (request.form.get("color") or "").strip()
    if options["sizes"] and size not in options["sizes"]:
        return None, ("Choose one of the available sizes." if not size else "That size is not offered.")
    if options["colors"] and color not in options["colors"]:
        return None, ("Choose a colour or model." if not color else "That colour is not offered.")
    parts = [part for part in (color, size) if part and part in (options["colors"] + options["sizes"])]
    return (" / ".join(parts) or None), None


def read_quantity(product):
    try:
        quantity = int(request.form.get("quantity") or 1)
    except ValueError:
        quantity = 1
    quantity = max(1, quantity)
    if product["stock"] and quantity > product["stock"]:
        quantity = product["stock"]
    return quantity


@main_bp.post("/products/<int:product_id>/order")
@roles_required("buyer")
def product_order(product_id):
    product = query("SELECT * FROM products WHERE id = ?", (product_id,), one=True)
    if not product:
        abort(404)
    back = request.referrer or url_for("main.shop")
    if product["stock"] < 1:
        flash("That product is out of stock.", "error")
        return redirect(back)

    variant, error = read_variant(product_id)
    if error:
        flash(error, "error")
        return redirect(url_for("main.product_detail", product_id=product_id))

    quantity = read_quantity(product)
    total = product["price"] * quantity
    stamp = datetime.now().strftime(STAMP)

    # One transaction: the stock guard and the order row move together or not at all.
    try:
        with transaction() as db:
            reserved = db.execute(
                "UPDATE products SET stock = stock - ? WHERE id = ? AND stock >= ?",
                (quantity, product_id, quantity),
            )
            if reserved.rowcount != 1:
                raise ValueError("out of stock")
            order_id = db.execute(
                """INSERT INTO orders
                   (buyer_id, seller_id, product_id, quantity, total, status, variant,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'new', ?, ?, ?)""",
                (g.user["id"], product["seller_id"], product_id, quantity, total,
                 variant, stamp, stamp),
            ).lastrowid
    except ValueError:
        flash("Those units were just taken by another buyer. Lower the quantity and try again.",
              "error")
        return redirect(url_for("main.product_detail", product_id=product_id))
    notify(
        product["seller_id"],
        "New order received",
        f"{g.user['name']} ordered {quantity} × {product['name']}"
        + (f" ({variant})" if variant else "") + f" · {format_dt(total)}.",
        url_for("main.orders"),
    )
    notify(
        g.user["id"],
        f"Order #{order_id} placed",
        f"{quantity} × {product['name']}" + (f" ({variant})" if variant else "")
        + f" · {format_dt(total)}. The seller will confirm it shortly.",
        url_for("main.orders"),
    )
    flash(f"Order #{order_id} placed. The seller has been notified.", "success")
    return redirect(url_for("main.order_detail", order_id=order_id))


# ---------------------------------------------------------------------------
# Local marketplace orders: their own lifecycle, no traveler escrow involved
# ---------------------------------------------------------------------------

ORDER_STEPS = ["Placed", "Processing", "Shipped", "Delivered", "Confirmed"]
ORDER_STEP_INDEX = {"new": 1, "processing": 2, "shipped": 3, "delivered": 4, "cancelled": 0}


def order_with_people(order_id=None, where=None, args=()):
    sql = """SELECT o.*, p.name AS product_name, p.image_url, p.listing_type,
                    p.category AS product_category,
                    s.name AS seller_name, s.store_name AS seller_store,
                    s.city AS seller_city, b.name AS buyer_name, b.city AS buyer_city
             FROM orders o
             JOIN products p ON p.id = o.product_id
             JOIN users s ON s.id = o.seller_id
             JOIN users b ON b.id = o.buyer_id"""
    if order_id is not None:
        return query(sql + " WHERE o.id = ?", (order_id,), one=True)
    return query(sql + " WHERE " + where, args)


@main_bp.get("/orders/<int:order_id>")
@login_required
def order_detail(order_id):
    order = order_with_people(order_id)
    if not order:
        abort(404)
    if g.user["id"] not in (order["buyer_id"], order["seller_id"]) and not g.user["is_admin"]:
        abort(403)
    review = query(
        "SELECT * FROM product_reviews WHERE product_id = ? AND buyer_id = ?",
        (order["product_id"], order["buyer_id"]), one=True,
    )
    return render_template(
        "order_detail.html",
        order=order,
        steps=ORDER_STEPS,
        step=ORDER_STEP_INDEX.get(order["status"], 1),
        review=review,
        is_buyer=g.user["id"] == order["buyer_id"],
    )


@main_bp.post("/orders/<int:order_id>/cancel")
@roles_required("buyer")
def order_cancel(order_id):
    order = query("SELECT * FROM orders WHERE id = ? AND buyer_id = ?",
                  (order_id, g.user["id"]), one=True)
    if not order:
        abort(404)
    if order["status"] not in ("new", "processing"):
        flash("This order has already shipped. Open the order and message the seller instead.",
              "error")
        return redirect(url_for("main.order_detail", order_id=order_id))

    stamp = datetime.now().strftime(STAMP)
    try:
        with transaction() as db:
            cancelled = db.execute(
                """UPDATE orders SET status = 'cancelled', cancelled_at = ?, updated_at = ?
                   WHERE id = ? AND status IN ('new', 'processing')""",
                (stamp, stamp, order_id),
            )
            if cancelled.rowcount != 1:
                raise ValueError("already moved")
            db.execute("UPDATE products SET stock = stock + ? WHERE id = ?",
                       (order["quantity"], order["product_id"]))
    except ValueError:
        flash("That order just moved forward, so it cannot be cancelled any more.", "error")
        return redirect(url_for("main.order_detail", order_id=order_id))
    notify(
        order["seller_id"],
        f"Order #{order_id} cancelled",
        f"{g.user['name']} cancelled the order. The stock was returned to your catalogue.",
        url_for("main.order_detail", order_id=order_id),
    )
    audit("order.cancel", "orders", order_id,
          f"buyer cancelled {order['quantity']} unit(s)")
    flash("Order cancelled and the stock is back with the seller.", "info")
    return redirect(url_for("main.order_detail", order_id=order_id))


@main_bp.post("/orders/<int:order_id>/confirm")
@roles_required("buyer")
def order_confirm(order_id):
    order = query("SELECT * FROM orders WHERE id = ? AND buyer_id = ?",
                  (order_id, g.user["id"]), one=True)
    if not order:
        abort(404)
    if order["status"] != "delivered" or order["confirmed_at"]:
        flash("Only a delivered order can be confirmed.", "error")
        return redirect(url_for("main.order_detail", order_id=order_id))
    execute("UPDATE orders SET confirmed_at = ?, updated_at = ? WHERE id = ?",
            (datetime.now().strftime(STAMP), datetime.now().strftime(STAMP), order_id))
    notify(
        order["seller_id"],
        f"Order #{order_id} confirmed",
        f"{g.user['name']} confirmed they received the order.",
        url_for("main.order_detail", order_id=order_id),
    )
    flash("Thanks — the order is confirmed. You can review the product now.", "success")
    return redirect(url_for("main.order_detail", order_id=order_id))


@main_bp.post("/products/<int:product_id>/delete")
@roles_required(*SELLER_ROLES)
def product_delete(product_id):
    product = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if not product:
        abort(404)
    used = query("SELECT COUNT(*) AS n FROM orders WHERE product_id = ?",
                 (product_id,), one=True)["n"]
    if used:
        flash("Products with orders cannot be deleted. Set the stock to 0 instead.", "error")
    else:
        execute("DELETE FROM products WHERE id = ?", (product_id,))
        flash("Product deleted.", "success")
    return redirect(url_for("main.products_page"))


@main_bp.post("/products/<int:product_id>/stock")
@roles_required(*SELLER_ROLES)
def product_stock(product_id):
    product = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if not product:
        abort(404)
    try:
        stock = max(0, int(request.form.get("stock") or 0))
    except ValueError:
        flash("Stock must be a whole number.", "error")
        return redirect(url_for("main.products_page", view="inventory"))
    execute("UPDATE products SET stock = ? WHERE id = ?", (stock, product_id))
    flash(f"Stock for {product['name']} updated to {stock}.", "success")
    return redirect(url_for("main.products_page", view="inventory"))


@main_bp.post("/products/<int:product_id>/feature")
@roles_required(*SELLER_ROLES)
def product_feature(product_id):
    product = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if not product:
        abort(404)
    execute("UPDATE products SET featured = ? WHERE id = ?",
            (0 if product["featured"] else 1, product_id))
    flash(
        f"{product['name']} {'removed from' if product['featured'] else 'added to'} featured products.",
        "success",
    )
    return redirect(request.referrer or url_for("main.products_page"))


@main_bp.post("/products/<int:product_id>/images/<int:image_id>/delete")
@roles_required(*SELLER_ROLES)
def product_image_delete(product_id, image_id):
    product = query(
        "SELECT * FROM products WHERE id = ? AND seller_id = ?",
        (product_id, g.user["id"]), one=True,
    )
    if not product:
        abort(404)
    execute("DELETE FROM product_images WHERE id = ? AND product_id = ?",
            (image_id, product_id))
    flash("Photo removed.", "success")
    return redirect(url_for("main.product_detail", product_id=product_id))


@main_bp.get("/products/bulk")
@roles_required(*SELLER_ROLES)
def products_bulk():
    return render_template("bulk_products.html", categories=CATEGORIES)


@main_bp.post("/products/bulk")
@roles_required(*SELLER_ROLES)
def products_bulk_upload():
    text = (request.form.get("csv") or "").strip()
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        text = uploaded.read().decode("utf-8-sig", errors="replace").strip()

    if not text:
        flash("Paste CSV rows or upload a CSV file.", "error")
        return redirect(url_for("main.products_bulk"))

    added, skipped = 0, 0
    for row in csv.reader(io.StringIO(text)):
        if not row or not row[0].strip() or row[0].strip().lower() == "name":
            continue
        try:
            name = row[0].strip()
            price = to_millimes(row[1])
            stock = int(row[2])
            category = row[3].strip() if len(row) > 3 and row[3].strip() in CATEGORIES else "Fashion"
        except (IndexError, ValueError):
            skipped += 1
            continue
        execute(
            """INSERT INTO products
               (seller_id, name, description, price, stock, category, listing_type,
                weight_kg, image_url, created_at)
               VALUES (?, ?, '', ?, ?, ?, 'local', 0.5, ?, ?)""",
            (
                g.user["id"], name, price, stock, category,
                "https://placehold.co/600x400/eef3fb/1e3a8a?text=Product",
                datetime.now().strftime(STAMP),
            ),
        )
        added += 1
    flash(f"Bulk upload finished: {added} added, {skipped} skipped.", "success" if added else "warning")
    return redirect(url_for("main.products_page"))


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

@main_bp.get("/orders")
@login_required
def orders():
    if g.user["role"] in SELLER_ROLES:
        rows = query(
            """SELECT o.*, p.name AS product_name, p.image_url,
                      b.name AS buyer_name, b.city AS buyer_city
               FROM orders o
               JOIN products p ON p.id = o.product_id
               JOIN users b ON b.id = o.buyer_id
               WHERE o.seller_id = ?
               ORDER BY o.created_at DESC""",
            (g.user["id"],),
        )
        status = request.args.get("status")
        if status:
            rows = [row for row in rows if row["status"] == status]
        return render_template(
            "orders.html",
            orders=rows,
            seller_view=True,
            active_status=status,
            next_status=ORDER_FLOW,
        )

    rows = query(
        """SELECT o.*, p.name AS product_name, p.image_url,
                  s.store_name AS seller_name, s.name AS seller_legal,
                  (SELECT COUNT(*) FROM product_reviews pr
                   WHERE pr.product_id = o.product_id AND pr.buyer_id = o.buyer_id) AS reviewed
           FROM orders o
           JOIN products p ON p.id = o.product_id
           JOIN users s ON s.id = o.seller_id
           WHERE o.buyer_id = ?
           ORDER BY o.created_at DESC""",
        (g.user["id"],),
    )
    return render_template("orders.html", orders=rows, seller_view=False, active_status=None)


@main_bp.post("/orders/<int:order_id>/advance")
@roles_required(*SELLER_ROLES)
def order_advance(order_id):
    order = query(
        "SELECT * FROM orders WHERE id = ? AND seller_id = ?",
        (order_id, g.user["id"]), one=True,
    )
    if not order:
        abort(404)
    target = ORDER_FLOW.get(order["status"])
    if not target:
        flash("That order is already complete.", "info")
        return redirect(url_for("main.orders"))

    execute("UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
            (target, datetime.now().strftime(STAMP), order_id))

    if target == "delivered" and not order["wallet_posted"]:
        record_wallet(
            g.user["id"],
            order["total"],
            "sale",
            f"Order #{order_id} delivered",
            f"order-sale-{order_id}",
        )
        execute("UPDATE orders SET wallet_posted = 1 WHERE id = ?", (order_id,))

    notify(
        order["buyer_id"],
        f"Order #{order_id} is {target}",
        "Track the latest status from your orders page.",
        url_for("main.orders"),
    )
    flash(f"Order #{order_id} moved to {target}.", "success")
    return redirect(request.referrer or url_for("main.orders"))


# ---------------------------------------------------------------------------
# Escrow / carts
# ---------------------------------------------------------------------------

@main_bp.get("/escrow")
@login_required
def escrow():
    expire_overdue_carts()
    rows = cart_with_people(
        where="c.buyer_id = ? ORDER BY CASE c.status WHEN 'delivered' THEN 0 WHEN 'in_transit' THEN 1 WHEN 'assigned' THEN 2 WHEN 'purchased' THEN 3 ELSE 4 END, c.updated_at DESC",
        args=(g.user["id"],),
    )
    carts = []
    for row in rows:
        cart = hydrate(row)
        if cart["status"] == "delivered":
            line_items = cart["line_items"]
            cart = as_dict(refresh_if_expired(cart))
            cart["line_items"] = line_items
            cart["code"] = code_display(cart)
        carts.append(cart)
    active_total = sum(
        c["total"] + (c["traveler_fee"] or 0)
        for c in carts
        if c["paid"] and c["status"] in ("assigned", "purchased", "in_transit", "delivered")
    )
    payment_due = sum(
        c["total"] + (c["traveler_fee"] or 0)
        for c in carts if c["payment_due"]
    )
    return render_template(
        "escrow.html", carts=carts, active_total=active_total,
        payment_due=payment_due,
    )


@main_bp.post("/escrow/<int:cart_id>/pay")
@login_required
def pay_escrow(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ? AND buyer_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    if cart["status"] != "assigned" or cart["paid"]:
        flash("That escrow payment is not available.", "info")
        return redirect(request.referrer or url_for("main.escrow"))

    current = datetime.now()
    due = (current + timedelta(days=2)).strftime(STAMP)
    total, _ = cart_totals(cart_id)
    amount = total + (cart["traveler_fee"] or 0)
    db = get_db()
    cursor = db.execute(
        """UPDATE carts SET paid = 1, paid_at = ?, receipt_due_at = ?,
                            updated_at = ?
           WHERE id = ? AND buyer_id = ? AND status = 'assigned' AND paid = 0""",
        (
            current.strftime(STAMP), due, current.strftime(STAMP),
            cart_id, g.user["id"],
        ),
    )
    if cursor.rowcount != 1:
        db.rollback()
        flash("That escrow payment was already recorded.", "info")
        return redirect(request.referrer or url_for("main.escrow"))
    db.execute(
        """INSERT OR IGNORE INTO wallet_transactions
           (user_id, amount, kind, description, reference, created_at)
           VALUES (?, ?, 'escrow', ?, ?, ?)""",
        (
            g.user["id"],
            -amount,
            f"Escrow payment · cart #{cart_id}",
            f"escrow-pay-{cart_id}",
            current.strftime(STAMP),
        ),
    )
    db.execute(
        """INSERT INTO escrow_events
           (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, 'assigned', 'assigned', ?, 'Buyer paid into escrow', ?)""",
        (cart_id, g.user["id"], current.strftime(STAMP)),
    )
    db.commit()
    notify(
        cart["traveler_id"],
        "Buyer paid into escrow",
        f"Cart #{cart_id} has {format_dt(cart['traveler_fee'])} delivery fee secured. Upload the receipt within 2 days.",
        url_for("main.traveler_dashboard"),
    )
    notify(
        g.user["id"],
        "Payment secured in escrow",
        f"Cart #{cart_id} has 2 days for the receipt to be uploaded.",
        url_for("main.escrow"),
    )
    flash("Payment secured in escrow. The traveler has 2 days to upload the purchase receipt.", "success")
    return redirect(request.referrer or url_for("main.escrow"))


@main_bp.post("/escrow/<int:cart_id>/release")
@login_required
def release_escrow(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ? AND buyer_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    if cart["status"] != "delivered" or not cart["paid"]:
        flash("Escrow can only be released after delivery and payment.", "error")
        return redirect(request.referrer or url_for("main.escrow"))
    ok, reason = verify_code(cart, request.form.get("code") or "")
    if not ok:
        messages = {
            "invalid": "That release code is not correct. Check the code and try again.",
            "expired": "That code expired. Reload the page to generate a fresh one.",
            "locked": "Too many attempts. Contact support to unlock this delivery.",
        }
        flash(messages.get(reason, "Enter the delivery code."), "error")
        return redirect(request.referrer or url_for("main.escrow"))

    cart = transition(cart, "release", g.user)
    notify(cart["traveler_id"], "Escrow released",
           f"Cart #{cart['id']} is complete and your delivery fee was credited.",
           url_for("main.wallet"))
    for seller_id in seller_ids_for_cart(cart["id"]):
        notify(seller_id, "Escrow released",
               f"Your items in cart #{cart['id']} were paid out.", url_for("main.wallet"))
    flash("Escrow released. The seller and traveler have been paid.", "success")
    return redirect(request.referrer or url_for("main.escrow"))


@main_bp.get("/carts/<int:cart_id>")
@login_required
def cart_detail(cart_id):
    expire_overdue_carts()
    row = cart_with_people(cart_id)
    if not row:
        abort(404)
    cart = hydrate(row)
    require_cart_access(cart)
    if cart["status"] == "delivered" and g.user["role"] == "buyer":
        line_items = cart["line_items"]
        cart = as_dict(refresh_if_expired(cart))
        cart["line_items"] = line_items
        cart["code"] = code_display(cart)
    events = query(
        """SELECT e.*, u.name AS actor_name
           FROM escrow_events e LEFT JOIN users u ON u.id = e.actor_id
           WHERE e.cart_id = ? ORDER BY e.created_at, e.id""",
        (cart_id,),
    )
    return render_template("cart_detail.html", cart=cart, events=events)


@main_bp.post("/carts/<int:cart_id>/cancel")
@login_required
def cart_cancel(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ? AND buyer_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    if cart["status"] not in ("open", "assigned") or cart["paid"]:
        flash("A paid or in-progress request cannot be cancelled here.", "error")
        return redirect(request.referrer or url_for("main.escrow"))
    if cart["status"] == "assigned" and cart["trip_id"]:
        _, weight = cart_totals(cart_id)
        execute("UPDATE trips SET used_kg = MAX(0, used_kg - ?) WHERE id = ?",
                (weight, cart["trip_id"]))
    execute(
        """UPDATE carts SET status = 'completed', cancelled_at = ?, updated_at = ?
           WHERE id = ?""",
        (datetime.now().strftime(STAMP), datetime.now().strftime(STAMP), cart_id),
    )
    if cart["traveler_id"]:
        notify(cart["traveler_id"], "Request cancelled",
               f"Cart #{cart_id} was cancelled by the buyer.",
               url_for("main.traveler_dashboard"))
    flash("Request cancelled.", "info")
    return redirect(url_for("main.escrow"))


@main_bp.get("/requests")
@roles_required("traveler")
def requests_page():
    expire_overdue_carts()
    rows = cart_with_people(
        where="""c.status = 'open'
                 AND (c.preferred_traveler_id IS NULL OR c.preferred_traveler_id = ?)
                 AND NOT EXISTS (SELECT 1 FROM cart_declines d WHERE d.cart_id = c.id AND d.traveler_id = ?)
                 ORDER BY c.created_at DESC""",
        args=(g.user["id"], g.user["id"]),
    )
    carts = [hydrate(row, traveler_matches=True) for row in rows]
    return render_template("requests.html", carts=carts)


@main_bp.post("/carts/<int:cart_id>/accept")
@roles_required("traveler")
def cart_accept(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    if not cart or cart["status"] != "open":
        flash("That request is no longer open.", "error")
        return redirect(url_for("main.requests_page"))
    if cart["preferred_traveler_id"] and cart["preferred_traveler_id"] != g.user["id"]:
        abort(403)

    matches = eligible_trips(cart, g.user["id"])
    trip_id = request.form.get("trip_id", type=int)
    match = next((item for item in matches if item["trip"]["id"] == trip_id), None)
    if not match:
        flash("Choose one of your eligible trips first.", "error")
        return redirect(url_for("main.requests_page"))

    _, weight = cart_totals(cart_id)
    execute(
        """UPDATE carts SET traveler_id = ?, trip_id = ?, updated_at = ? WHERE id = ?""",
        (g.user["id"], trip_id, datetime.now().strftime(STAMP), cart_id),
    )
    try:
        transition(cart, "accept", g.user)
    except (ValueError, PermissionError):
        execute("UPDATE carts SET traveler_id = NULL, trip_id = NULL WHERE id = ?", (cart_id,))
        flash("That cart could not be accepted. Try again.", "error")
        return redirect(url_for("main.requests_page"))

    execute("UPDATE trips SET used_kg = used_kg + ? WHERE id = ?", (weight, trip_id))
    issue_code(cart_id)
    notify(
        cart["buyer_id"],
        "Traveler accepted — payment required",
        f"{g.user['name']} accepted your {cart['store_name']} request. Pay into escrow so they can buy it.",
        url_for("main.escrow"),
    )
    notify(
        g.user["id"],
        "Request accepted",
        f"Cart #{cart_id} is yours. Wait for the buyer to fund escrow.",
        url_for("main.traveler_dashboard"),
    )
    flash("Request accepted. The buyer now needs to pay into escrow.", "success")
    return redirect(url_for("main.traveler_dashboard"))


@main_bp.post("/carts/<int:cart_id>/decline")
@roles_required("traveler")
def cart_decline(cart_id):
    execute(
        "INSERT OR IGNORE INTO cart_declines (cart_id, traveler_id, created_at) VALUES (?, ?, ?)",
        (cart_id, g.user["id"], datetime.now().strftime(STAMP)),
    )
    flash("Request hidden from your list.", "info")
    return redirect(request.referrer or url_for("main.requests_page"))


@main_bp.post("/carts/<int:cart_id>/receipt")
@roles_required("traveler")
def cart_receipt(cart_id):
    expire_overdue_carts()
    cart = query("SELECT * FROM carts WHERE id = ? AND traveler_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    if cart["status"] != "assigned" or not cart["paid"]:
        flash("Upload is available after the buyer has paid into escrow.", "error")
        return redirect(url_for("main.traveler_dashboard"))
    amount = to_millimes(request.form.get("amount") or 0)
    store = (request.form.get("store") or cart["store_name"]).strip()
    receipt_date = request.form.get("purchase_date") or date.today().isoformat()
    receipt_file = store_proof(request.files.get("receipt"))
    if amount <= 0 or not receipt_file:
        flash("Attach a clear receipt photo and enter the amount you paid.", "error")
        return redirect(url_for("main.traveler_dashboard"))

    # Fraud checks before a human ever looks at the photo.
    saved = os.path.join(current_app.config["UPLOAD_FOLDER"], os.path.basename(receipt_file))
    try:
        with open(saved, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()
    except OSError:
        digest = None
    if digest and query("SELECT id FROM carts WHERE receipt_hash = ? AND id != ?",
                        (digest, cart_id), one=True):
        flash("This exact receipt photo was already submitted for another order.", "error")
        return redirect(url_for("main.traveler_dashboard"))

    flags = []
    items_total, _ = cart_totals(cart_id)
    if items_total and not (items_total * 0.9 <= amount <= items_total * 1.1):
        flags.append(f"amount {format_dt(amount)} vs cart {format_dt(items_total)}")
    if store and cart["store_name"] and store.strip().lower() != cart["store_name"].strip().lower():
        flags.append(f"store “{store}” vs request “{cart['store_name']}”")
    if cart["trip_id"]:
        trip = query("SELECT arrival_date FROM trips WHERE id = ?", (cart["trip_id"],), one=True)
        if trip and receipt_date > trip["arrival_date"]:
            flags.append(f"receipt dated {receipt_date}, after arrival {trip['arrival_date']}")

    execute(
        """UPDATE carts SET receipt_amount = ?, receipt_store = ?, receipt_date = ?,
                            receipt_file = ?, receipt_hash = ?, receipt_flag = ?,
                            receipt_status = 'pending',
                            receipt_note = NULL, updated_at = ?
           WHERE id = ?""",
        (amount, store, receipt_date, receipt_file, digest, "; ".join(flags) or None,
         datetime.now().strftime(STAMP), cart_id),
    )
    execute(
        """INSERT INTO escrow_events
           (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, 'assigned', 'assigned', ?, 'Receipt submitted for admin verification', ?)""",
        (cart_id, g.user["id"], datetime.now().strftime(STAMP)),
    )
    notify(
        cart["buyer_id"],
        "Receipt uploaded — waiting for verification",
        f"{g.user['name']} uploaded a {store} receipt for cart #{cart_id}. An admin will verify it.",
        url_for("main.cart_detail", cart_id=cart_id),
    )
    flag_note = f" Checks: {'; '.join(flags)}." if flags else ""
    for reviewer in query("SELECT id FROM users WHERE is_staff = 1 AND is_admin = 0"):
        notify(
            reviewer["id"],
            "Receipt awaiting verification",
            f"Cart #{cart_id} · {format_dt(amount)} from {store}.{flag_note}",
            url_for("main.staff_receipts"),
        )
    notify_admins(
        "Receipt awaiting verification",
        f"Cart #{cart_id} has a {format_dt(amount)} receipt from {store}.{flag_note}",
        url_for("main.admin_receipts"),
    )
    flash("Receipt submitted. It is not confirmed until an administrator verifies it.", "success")
    return redirect(url_for("main.traveler_dashboard"))


@main_bp.post("/carts/<int:cart_id>/ship")
@roles_required("traveler")
def cart_ship(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ? AND traveler_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    try:
        transition(cart, "ship", g.user)
    except (ValueError, PermissionError):
        flash("That parcel cannot be marked in transit.", "error")
    else:
        notify(cart["buyer_id"], "Parcel in transit", "Your traveler is on the way.",
               url_for("main.escrow"))
        flash("Marked as in transit.", "success")
    return redirect(request.referrer or url_for("main.traveler_dashboard"))


@main_bp.post("/carts/<int:cart_id>/deliver")
@roles_required("traveler")
def cart_deliver(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ? AND traveler_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart:
        abort(404)
    try:
        transition(cart, "deliver", g.user)
    except (ValueError, PermissionError):
        flash("That parcel cannot be marked delivered.", "error")
    else:
        if not cart["code_issued_at"]:
            issue_code(cart_id)
        notify(cart["buyer_id"], "Parcel delivered",
               "Inspect your item, then release the escrow with your delivery code.",
               url_for("main.escrow"))
        flash("Marked as delivered. The buyer can now release escrow.", "success")
    return redirect(request.referrer or url_for("main.traveler_dashboard"))


# ---------------------------------------------------------------------------
# Staff pages (verifiers - some admin privileges, not the important ones)
# ---------------------------------------------------------------------------

@main_bp.get("/staff")
@staff_required
def staff_dashboard():
    pending_receipts = query(
        """SELECT c.*, b.name AS buyer_name, b.email AS buyer_email,
                  tr.name AS traveler_name, tr.email AS traveler_email,
                  t.from_city, t.to_city, t.departure_date
           FROM carts c
           JOIN users b ON b.id = c.buyer_id
           LEFT JOIN users tr ON tr.id = c.traveler_id
           LEFT JOIN trips t ON t.id = c.trip_id
           WHERE c.receipt_status = 'pending'
           ORDER BY c.updated_at DESC""",
    )
    return render_template(
        "staff_dashboard.html",
        pending_receipts=pending_receipts,
    )


@main_bp.get("/staff/receipts")
@staff_required
def staff_receipts():
    receipts = query(
        """SELECT c.*, b.name AS buyer_name, b.email AS buyer_email,
                  tr.name AS traveler_name, tr.email AS traveler_email,
                  t.from_city, t.to_city, t.departure_date
           FROM carts c
           JOIN users b ON b.id = c.buyer_id
           LEFT JOIN users tr ON tr.id = c.traveler_id
           LEFT JOIN trips t ON t.id = c.trip_id
           WHERE c.receipt_status IN ('pending', 'rejected')
           ORDER BY c.updated_at DESC""",
    )
    return render_template(
        "staff_receipts.html",
        receipts=receipts,
    )


@main_bp.post("/staff/receipts/<int:cart_id>/verify")
@staff_required
def staff_verify_receipt(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    if not cart:
        abort(404)
    if cart["receipt_status"] != "pending" or cart["status"] != "assigned":
        flash("That receipt is not pending verification.", "error")
        return redirect(url_for("main.staff_receipts"))
    current = datetime.now().strftime(STAMP)
    execute(
        """UPDATE carts SET status = 'purchased', receipt_status = 'verified',
                            receipt_verified_at = ?, updated_at = ? WHERE id = ?""",
        (current, current, cart_id),
    )
    execute(
        """INSERT INTO escrow_events
           (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, 'assigned', 'purchased', ?, 'Receipt verified by staff', ?)""",
        (cart_id, g.user["id"], current),
    )
    if cart["traveler_id"]:
        notify(
            cart["traveler_id"],
            "Receipt approved",
            f"Your receipt for cart #{cart_id} was verified. You can now mark it in transit.",
            url_for("main.traveler_dashboard"),
        )
    notify(
        cart["buyer_id"],
        "Receipt verified",
        f"Your {cart['receipt_store']} receipt for cart #{cart_id} has been verified by staff.",
        url_for("main.cart_detail", cart_id=cart_id),
    )
    notify_admins(
        "Receipt verified by staff",
        f"Staff verified the {cart['receipt_store']} receipt for cart #{cart_id}.",
        url_for("main.admin_receipts"),
    )
    audit("receipt.verify", "carts", cart_id,
          f"staff verified {format_dt(cart['receipt_amount'] or 0)} receipt")
    flash("Receipt verified.", "success")
    return redirect(url_for("main.staff_receipts"))


@main_bp.post("/staff/receipts/<int:cart_id>/reject")
@staff_required
def staff_reject_receipt(cart_id):
    cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    if not cart:
        abort(404)
    if cart["receipt_status"] != "pending":
        flash("That receipt is not pending verification.", "error")
        return redirect(url_for("main.staff_receipts"))
    reason = (request.form.get("reason") or "").strip()
    if not reason:
        flash("Please enter a reason for rejection.", "error")
        return redirect(url_for("main.staff_receipts"))
    execute(
        """UPDATE carts SET receipt_status = 'rejected', receipt_note = ?,
                            receipt_verified_by = ?, updated_at = ? WHERE id = ?""",
        (reason, g.user["id"], datetime.now().strftime(STAMP), cart_id),
    )
    execute(
        """INSERT INTO escrow_events
           (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, 'assigned', 'assigned', ?, ?, ?)""",
        (cart_id, g.user["id"], f"Receipt rejected by staff: {reason}", datetime.now().strftime(STAMP)),
    )
    notify(
        cart["buyer_id"],
        "Receipt rejected",
        f"Your receipt for cart #{cart_id} was rejected: {reason}",
        url_for("main.cart_detail", cart_id=cart_id),
    )
    if cart["traveler_id"]:
        notify(
            cart["traveler_id"],
            "Receipt rejected by staff",
            reason,
            url_for("main.traveler_dashboard"),
        )
    audit("receipt.reject", "carts", cart_id, f"staff rejected: {reason}")
    flash("Receipt rejected.", "warning")
    return redirect(url_for("main.staff_receipts"))


# ---------------------------------------------------------------------------
# Admin staff management
# ---------------------------------------------------------------------------

@main_bp.get("/admin/staff")
@admin_required
def admin_staff():
    users = query(
        """SELECT id, name, email, role, city, status, is_staff
           FROM users
           WHERE is_admin = 0
           ORDER BY is_staff DESC, name""",
    )
    return render_template("admin_staff.html", users=users)


@main_bp.post("/admin/staff/<int:user_id>/toggle")
@admin_required
def admin_staff_toggle(user_id):
    user = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not user:
        abort(404)
    new_value = 0 if user["is_staff"] else 1
    execute("UPDATE users SET is_staff = ? WHERE id = ?", (new_value, user_id))
    action = "granted staff access to" if new_value else "removed staff access from"
    notify(
        user_id,
        "Staff access updated",
        f"An administrator has {action} you. You can now access the verification dashboard." if new_value
        else f"An administrator has {action} you.",
        url_for("main.staff_dashboard") if new_value else url_for("auth.login"),
    )
    audit("staff.toggle", "users", user_id,
          f"{'granted' if new_value else 'revoked'} staff access for {user['email']}")
    flash(
        f"Staff access {'granted' if new_value else 'revoked'} for {user['name']}.",
        "success",
    )
    return redirect(url_for("main.admin_staff"))


# ---------------------------------------------------------------------------
# Trips
# ---------------------------------------------------------------------------

@main_bp.get("/trips")
@roles_required("traveler")
def trips():
    rows = query(
        "SELECT * FROM trips WHERE traveler_id = ? ORDER BY departure_date",
        (g.user["id"],),
    )
    return render_template("trips.html", trips=rows)


@main_bp.post("/trips/add")
@roles_required("traveler")
def trip_add():
    origin = (request.form.get("from_city") or "").strip()
    destination = (request.form.get("to_city") or "").strip()
    departure = request.form.get("departure_date")
    arrival = request.form.get("arrival_date")
    try:
        capacity = float(request.form.get("capacity") or 25)
        fee = to_millimes(request.form.get("fee") or 5000)
    except ValueError:
        capacity, fee = 25, to_millimes(5)

    if not origin or not destination or not departure or not arrival:
        flash("Add both cities and both dates.", "error")
        return redirect(url_for("main.trips"))
    if arrival < departure or capacity <= 0 or capacity > 50 or fee < 0:
        flash("Check the trip dates, capacity (1-50 kg) and fee.", "error")
        return redirect(url_for("main.trips"))

    document = store_proof(request.files.get("document"))
    if not document:
        flash("A flight ticket or receipt photo is required before a trip can be added.", "error")
        return redirect(url_for("main.trips"))

    trip_id = execute(
        """INSERT INTO trips
           (traveler_id, from_city, to_city, departure_date, arrival_date,
            capacity_kg, fee, status, notes, documents_submitted, document_file,
            created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, 1, ?, ?)""",
        (
            g.user["id"], origin, destination, departure, arrival, capacity, fee,
            (request.form.get("notes") or "").strip(), document,
            datetime.now().strftime(STAMP),
        ),
    )
    notify_admins(
        "Trip proof waiting for verification",
        f"{g.user['name']} added {origin} → {destination} with a flight receipt.",
        url_for("main.admin_trips"),
    )
    notify(
        g.user["id"], "Trip submitted for review",
        "The administrator will check your flight receipt before buyers can see the trip.",
        url_for("main.trips"),
    )
    flash("Trip submitted. It stays hidden until the administrator verifies your flight receipt.", "success")
    return redirect(url_for("main.trips"))


@main_bp.post("/trips/<int:trip_id>/documents")
@roles_required("traveler")
def trip_documents(trip_id):
    trip = query("SELECT * FROM trips WHERE id = ? AND traveler_id = ?",
                 (trip_id, g.user["id"]), one=True)
    if not trip:
        abort(404)
    document = store_proof(request.files.get("document"))
    if not document:
        flash("Attach a flight ticket or receipt image (JPG, PNG, WEBP or PDF).", "error")
        return redirect(url_for("main.trips"))

    execute(
        """UPDATE trips SET documents_submitted = 1, document_file = ?,
                            status = 'pending', verified_at = NULL,
                            verified_by = NULL, rejection_reason = NULL
           WHERE id = ?""",
        (document, trip_id),
    )
    notify_admins(
        "Flight proof resubmitted",
        f"{g.user['name']} resubmitted proof for {trip['from_city']} → {trip['to_city']}.",
        url_for("main.admin_trips"),
    )
    notify(
        g.user["id"], "Flight receipt resubmitted",
        "The administrator will verify it before your trip is shown to buyers.",
        url_for("main.trips"),
    )
    flash("Flight receipt resubmitted. Waiting for administrator verification.", "success")
    return redirect(url_for("main.trips"))


# ---------------------------------------------------------------------------
# Wallet, analytics
# ---------------------------------------------------------------------------

MAX_TOP_UP = 5000 * 1000  # 5 000 DT in millimes


@main_bp.get("/wallet")
@login_required
def wallet():
    transactions = query(
        "SELECT * FROM wallet_transactions WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (g.user["id"],),
    )
    payouts = query(
        """SELECT * FROM payout_requests WHERE user_id = ?
           ORDER BY created_at DESC, id DESC LIMIT 20""",
        (g.user["id"],),
    )
    return render_template(
        "wallet.html",
        transactions=transactions,
        balance=wallet_balance(g.user["id"]),
        credited=sum(t["amount"] for t in transactions if t["amount"] > 0),
        debited=sum(-t["amount"] for t in transactions if t["amount"] < 0),
        payouts=payouts,
        can_earn=g.user["role"] in SELLER_ROLES + ("traveler",),
        max_top_up=MAX_TOP_UP,
    )


@main_bp.post("/wallet/top-up")
@login_required
def wallet_top_up():
    """Demo funding: credits the wallet immediately, no payment gateway yet."""
    amount = to_millimes(request.form.get("amount") or 0)
    if amount <= 0:
        flash("Enter an amount to add to your wallet.", "error")
    elif amount > MAX_TOP_UP:
        flash(f"A single top-up is limited to {format_dt(MAX_TOP_UP)}.", "error")
    else:
        record_wallet(
            g.user["id"], amount, "deposit", "Wallet top-up (demo payment)",
            f"topup-{secrets.token_hex(8)}",
        )
        audit("wallet.top_up", "users", g.user["id"], format_dt(amount))
        notify(g.user["id"], "Wallet topped up",
               f"{format_dt(amount)} was added to your balance.", url_for("main.wallet"))
        flash(f"{format_dt(amount)} added to your wallet.", "success")
    return redirect(url_for("main.wallet"))


@main_bp.post("/wallet/payout")
@login_required
def wallet_payout_request():
    """Sellers and travelers ask for their earnings; an admin pays or declines."""
    if g.user["role"] not in SELLER_ROLES + ("traveler",):
        flash("Payouts are available to sellers and travelers.", "error")
        return redirect(url_for("main.wallet"))
    amount = to_millimes(request.form.get("amount") or 0)
    method = (request.form.get("method") or "Bank transfer").strip()[:60]
    details = (request.form.get("details") or "").strip()[:300]
    balance = wallet_balance(g.user["id"])
    if amount <= 0:
        flash("Enter an amount to withdraw.", "error")
        return redirect(url_for("main.wallet"))
    if amount > balance:
        flash("That is more than your available balance.", "error")
        return redirect(url_for("main.wallet"))

    stamp = datetime.now().strftime(STAMP)
    with transaction() as db:
        payout_id = db.execute(
            """INSERT INTO payout_requests (user_id, amount, method, details, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (g.user["id"], amount, method, details or None, stamp),
        ).lastrowid
        db.execute(
            """INSERT INTO wallet_transactions
               (user_id, amount, kind, description, reference, created_at)
               VALUES (?, ?, 'payout', ?, ?, ?)""",
            (g.user["id"], -amount, f"Payout request #{payout_id} · {method}",
             f"payout-{payout_id}", stamp),
        )
    audit("wallet.payout_request", "payout_requests", payout_id,
          f"{format_dt(amount)} via {method}")
    notify(g.user["id"], "Payout requested",
           f"{format_dt(amount)} is held until an administrator approves it.",
           url_for("main.wallet"))
    notify_admins(
        "Payout awaiting approval",
        f"{g.user['name']} requested {format_dt(amount)} via {method}.",
        url_for("main.admin_payouts"),
    )
    flash(f"Payout request for {format_dt(amount)} sent for approval.", "success")
    return redirect(url_for("main.wallet"))


@main_bp.get("/admin/payouts")
@admin_required
def admin_payouts():
    pending = query(
        """SELECT p.*, u.name AS user_name, u.email, u.role
           FROM payout_requests p JOIN users u ON u.id = p.user_id
           WHERE p.status = 'pending' ORDER BY p.created_at"""
    )
    decided = query(
        """SELECT p.*, u.name AS user_name, u.email, u.role
           FROM payout_requests p JOIN users u ON u.id = p.user_id
           WHERE p.status != 'pending' ORDER BY p.decided_at DESC, p.id DESC LIMIT 25"""
    )
    return render_template("admin_payouts.html", pending=pending, decided=decided)


@main_bp.post("/admin/payouts/<int:payout_id>/<action>")
@admin_required
def admin_payout_decide(payout_id, action):
    if action not in ("pay", "reject"):
        abort(404)
    payout = query("SELECT * FROM payout_requests WHERE id = ?", (payout_id,), one=True)
    if not payout:
        abort(404)
    if payout["status"] != "pending":
        flash("That payout was already decided.", "info")
        return redirect(url_for("main.admin_payouts"))
    stamp = datetime.now().strftime(STAMP)
    note = (request.form.get("note") or "").strip()[:300] or None
    status = "paid" if action == "pay" else "rejected"
    try:
        with transaction() as db:
            changed = db.execute(
                """UPDATE payout_requests
                   SET status = ?, note = ?, decided_by = ?, decided_at = ?
                   WHERE id = ? AND status = 'pending'""",
                (status, note, g.user["id"], stamp, payout_id),
            )
            if changed.rowcount != 1:
                raise ValueError("already decided")
            if status == "rejected":
                db.execute(
                    """INSERT OR IGNORE INTO wallet_transactions
                       (user_id, amount, kind, description, reference, created_at)
                       VALUES (?, ?, 'refund', ?, ?, ?)""",
                    (payout["user_id"], payout["amount"],
                     f"Payout request #{payout_id} declined — returned to wallet",
                     f"payout-reject-{payout_id}", stamp),
                )
    except ValueError:
        flash("That payout was already decided.", "info")
        return redirect(url_for("main.admin_payouts"))

    audit(f"payout.{action}", "payout_requests", payout_id,
          f"{format_dt(payout['amount'])} · {payout['user_id']}")
    if status == "paid":
        notify(payout["user_id"], "Payout approved",
               f"{format_dt(payout['amount'])} was sent to your {payout['method']}."
               + (f" Note: {note}" if note else ""), url_for("main.wallet"))
        flash(f"Payout #{payout_id} marked as paid.", "success")
    else:
        notify(payout["user_id"], "Payout declined",
               f"{format_dt(payout['amount'])} was returned to your wallet."
               + (f" Reason: {note}" if note else ""), url_for("main.wallet"))
        flash(f"Payout #{payout_id} declined and refunded to the wallet.", "success")
    return redirect(url_for("main.admin_payouts"))


@main_bp.get("/analytics")
@roles_required(*SELLER_ROLES)
def analytics():
    context = seller_context(g.user)
    return render_template("analytics.html", **context)


# ---------------------------------------------------------------------------
# Administrator
# ---------------------------------------------------------------------------

@main_bp.get("/admin")
@admin_required
def admin_dashboard():
    expire_overdue_carts()
    stats = {
        "accounts": query("SELECT COUNT(*) AS n FROM users WHERE is_admin = 0", one=True)["n"],
        "pending_accounts": query("SELECT COUNT(*) AS n FROM users WHERE status = 'pending'", one=True)["n"],
        "travelers": query("SELECT COUNT(*) AS n FROM users WHERE role = 'traveler'", one=True)["n"],
        "pending_trips": query("SELECT COUNT(*) AS n FROM trips WHERE status = 'pending'", one=True)["n"],
        "pending_receipts": query("SELECT COUNT(*) AS n FROM carts WHERE receipt_status = 'pending'", one=True)["n"],
        "escrow": query(
            """SELECT COALESCE(SUM(ci.quantity * ci.unit_price), 0) AS total
               FROM carts c JOIN cart_items ci ON ci.cart_id = c.id
               WHERE c.paid = 1 AND c.status IN ('assigned', 'purchased', 'in_transit', 'delivered')""",
            one=True,
        )["total"],
        "open_disputes": query("SELECT COUNT(*) AS n FROM disputes WHERE status = 'open'", one=True)["n"],
        "support": query("SELECT COUNT(*) AS n FROM support_tickets WHERE status = 'open'", one=True)["n"],
        "orders": query("SELECT COUNT(*) AS n FROM orders", one=True)["n"],
    }
    pending_accounts = query(
        "SELECT * FROM users WHERE status = 'pending' ORDER BY created_at DESC LIMIT 5"
    )
    pending_trips = query(
        """SELECT t.*, u.name AS traveler_name FROM trips t
           JOIN users u ON u.id = t.traveler_id
           WHERE t.status = 'pending' ORDER BY t.created_at DESC LIMIT 5"""
    )
    pending_receipts = cart_with_people(
        where="c.receipt_status = 'pending' ORDER BY c.updated_at DESC LIMIT 5"
    )
    recent_requests = query(
        """SELECT c.*, b.name AS buyer_name, tr.name AS traveler_name
           FROM carts c JOIN users b ON b.id = c.buyer_id
           LEFT JOIN users tr ON tr.id = c.traveler_id
           ORDER BY c.updated_at DESC LIMIT 8"""
    )
    return render_template(
        "admin_dashboard.html",
        stats=stats,
        pending_accounts=pending_accounts,
        pending_trips=pending_trips,
        pending_receipts=pending_receipts,
        recent_requests=recent_requests,
    )


@main_bp.get("/admin/accounts")
@admin_required
def admin_accounts():
    status = request.args.get("status", "all")
    if status not in ("all", "active", "pending", "suspended"):
        status = "all"
    if status == "all":
        rows = query("SELECT * FROM users ORDER BY is_admin DESC, created_at DESC")
    else:
        rows = query(
            "SELECT * FROM users WHERE status = ? ORDER BY created_at DESC", (status,)
        )
    return render_template("admin_accounts.html", users=rows, status=status)


@main_bp.post("/admin/accounts/<int:user_id>/status")
@admin_required
def admin_account_status(user_id):
    target = query("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
    if not target:
        abort(404)
    if target["is_admin"]:
        flash("The owner account cannot be suspended here.", "error")
        return redirect(url_for("main.admin_accounts"))
    status = request.form.get("status")
    if status not in ("active", "pending", "suspended"):
        flash("Choose a valid account status.", "error")
        return redirect(url_for("main.admin_accounts"))
    execute("UPDATE users SET status = ? WHERE id = ?", (status, user_id))
    if status == "active":
        notify(
            user_id, "Account approved",
            "Your Abroad account was approved by the administrator. You can sign in now.",
            url_for("auth.login"),
        )
        flash(f"{target['name']} can now sign in.", "success")
    elif status == "suspended":
        notify(user_id, "Account suspended", "Contact the administrator for details.")
        flash(f"{target['name']} has been suspended.", "warning")
    else:
        flash(f"{target['name']} is back in the approval queue.", "info")
    audit("account.status", "users", user_id, f"{target['email']} set to {status}")
    return redirect(request.referrer or url_for("main.admin_accounts"))


@main_bp.get("/admin/trips")
@admin_required
def admin_trips():
    status = request.args.get("status", "pending")
    if status not in ("all", "pending", "verified", "rejected"):
        status = "pending"
    sql = """SELECT t.*, u.name AS traveler_name, u.email AS traveler_email
             FROM trips t JOIN users u ON u.id = t.traveler_id"""
    if status == "all":
        rows = query(sql + " ORDER BY t.created_at DESC")
    else:
        rows = query(sql + " WHERE t.status = ? ORDER BY t.created_at DESC", (status,))
    return render_template("admin_trips.html", trips=rows, status=status)


@main_bp.post("/admin/trips/<int:trip_id>/verify")
@admin_required
def admin_trip_verify(trip_id):
    trip = query("SELECT * FROM trips WHERE id = ?", (trip_id,), one=True)
    if not trip:
        abort(404)
    if not trip["document_file"]:
        flash("This trip has no flight receipt to verify.", "error")
        return redirect(url_for("main.admin_trips"))
    execute(
        """UPDATE trips SET status = 'verified', verified_at = ?, verified_by = ?,
                            rejection_reason = NULL WHERE id = ?""",
        (datetime.now().strftime(STAMP), g.user["id"], trip_id),
    )
    notify(
        trip["traveler_id"],
        "Trip verified",
        f"{trip['from_city']} → {trip['to_city']} is now visible to buyers.",
        url_for("main.trips"),
    )
    audit("trip.verify", "trips", trip_id,
          f"{trip['from_city']} → {trip['to_city']} verified")
    flash("Flight receipt verified. The trip is now visible to buyers.", "success")
    return redirect(request.referrer or url_for("main.admin_trips"))


@main_bp.post("/admin/trips/<int:trip_id>/reject")
@admin_required
def admin_trip_reject(trip_id):
    trip = query("SELECT * FROM trips WHERE id = ?", (trip_id,), one=True)
    if not trip:
        abort(404)
    reason = (request.form.get("reason") or "The flight receipt was not clear enough.").strip()
    execute(
        """UPDATE trips SET status = 'rejected', rejection_reason = ?,
                            verified_at = NULL, verified_by = NULL WHERE id = ?""",
        (reason[:300], trip_id),
    )
    notify(
        trip["traveler_id"],
        "Flight receipt rejected",
        reason,
        url_for("main.trips"),
    )
    audit("trip.reject", "trips", trip_id, f"rejected: {reason}")
    flash("Trip rejected and the traveler was notified.", "warning")
    return redirect(request.referrer or url_for("main.admin_trips"))


@main_bp.get("/admin/receipts")
@admin_required
def admin_receipts():
    expire_overdue_carts()
    rows = cart_with_people(
        where="c.receipt_status = 'pending' ORDER BY c.updated_at DESC"
    )
    receipts = [hydrate(row) for row in rows]
    return render_template("admin_receipts.html", receipts=receipts)


@main_bp.post("/admin/receipts/<int:cart_id>/verify")
@admin_required
def admin_receipt_verify(cart_id):
    cart = cart_with_people(cart_id)
    if not cart:
        abort(404)
    if cart["receipt_status"] != "pending" or cart["status"] != "assigned":
        flash("That receipt is no longer waiting for verification.", "info")
        return redirect(url_for("main.admin_receipts"))
    current = datetime.now().strftime(STAMP)
    execute(
        """UPDATE carts SET status = 'purchased', receipt_status = 'verified',
                            receipt_verified_at = ?, updated_at = ? WHERE id = ?""",
        (current, current, cart_id),
    )
    execute(
        """INSERT INTO escrow_events
           (cart_id, from_state, to_state, actor_id, note, created_at)
           VALUES (?, 'assigned', 'purchased', ?, 'Administrator verified the receipt', ?)""",
        (cart_id, g.user["id"], current),
    )
    notify(
        cart["buyer_id"],
        f"Receipt verified for cart #{cart_id}",
        "Your purchase is confirmed. The traveler can now bring your order.",
        url_for("main.cart_detail", cart_id=cart_id),
    )
    if cart["traveler_id"]:
        notify(
            cart["traveler_id"],
            "Receipt approved",
            f"Your receipt for cart #{cart_id} was verified. You can now mark it in transit.",
            url_for("main.traveler_dashboard"),
        )
        execute(
            """INSERT INTO messages (sender_id, recipient_id, body, created_at)
               VALUES (?, ?, ?, ?)""",
            (
                cart["traveler_id"], cart["buyer_id"],
                f"Receipt for cart #{cart_id} was verified by Abroad. Your order is confirmed.",
                current,
            ),
        )
    audit("receipt.verify", "carts", cart_id, "administrator verified the receipt")
    flash("Receipt verified and the buyer has been messaged.", "success")
    return redirect(url_for("main.admin_receipts"))


@main_bp.post("/admin/receipts/<int:cart_id>/reject")
@admin_required
def admin_receipt_reject(cart_id):
    cart = cart_with_people(cart_id)
    if not cart:
        abort(404)
    if cart["receipt_status"] != "pending" or cart["status"] != "assigned":
        flash("That receipt is no longer waiting for verification.", "info")
        return redirect(url_for("main.admin_receipts"))
    reason = (request.form.get("reason") or "Receipt could not be verified.").strip()
    execute(
        """UPDATE carts SET receipt_status = 'rejected', receipt_note = ?,
                            updated_at = ? WHERE id = ?""",
        (reason[:300], datetime.now().strftime(STAMP), cart_id),
    )
    notify(
        cart["buyer_id"],
        "Receipt needs attention",
        f"The receipt for cart #{cart_id} was rejected: {reason}",
        url_for("main.cart_detail", cart_id=cart_id),
    )
    if cart["traveler_id"]:
        notify(
            cart["traveler_id"],
            "Receipt rejected — re-upload required",
            reason,
            url_for("main.traveler_dashboard"),
        )
    audit("receipt.reject", "carts", cart_id, f"administrator rejected: {reason}")
    flash("Receipt rejected. The traveler must upload a new receipt before the deadline.", "warning")
    return redirect(url_for("main.admin_receipts"))


@main_bp.get("/admin/orders")
@admin_required
def admin_orders():
    rows = query(
        """SELECT o.*, p.name AS product_name, b.name AS buyer_name,
                  s.name AS seller_name, s.store_name
           FROM orders o JOIN products p ON p.id = o.product_id
           JOIN users b ON b.id = o.buyer_id
           JOIN users s ON s.id = o.seller_id
           ORDER BY o.created_at DESC"""
    )
    return render_template("admin_orders.html", orders=rows)


@main_bp.get("/admin/requests")
@admin_required
def admin_requests():
    rows = cart_with_people(where="1 = 1 ORDER BY c.updated_at DESC")
    return render_template("admin_requests.html", requests=[hydrate(row) for row in rows])


@main_bp.get("/admin/disputes")
@admin_required
def admin_disputes():
    rows = query(
        """SELECT d.*, c.store_name, b.name AS buyer_name, t.name AS traveler_name
           FROM disputes d JOIN carts c ON c.id = d.cart_id
           JOIN users b ON b.id = d.opener_id
           LEFT JOIN users t ON t.id = c.traveler_id
           ORDER BY d.created_at DESC"""
    )
    return render_template("admin_disputes.html", disputes=rows)


@main_bp.post("/admin/disputes/<int:dispute_id>/resolve")
@admin_required
def admin_dispute_resolve(dispute_id):
    dispute = query("SELECT * FROM disputes WHERE id = ?", (dispute_id,), one=True)
    if not dispute:
        abort(404)
    execute("UPDATE disputes SET status = 'resolved' WHERE id = ?", (dispute_id,))
    notify(dispute["opener_id"], "Dispute resolved",
           "An administrator has reviewed your dispute.", url_for("main.disputes"))
    audit("dispute.resolve", "disputes", dispute_id,
          f"cart #{dispute['cart_id']} resolved")
    flash("Dispute marked as resolved.", "success")
    return redirect(url_for("main.admin_disputes"))


@main_bp.get("/admin/support")
@admin_required
def admin_support():
    rows = query(
        """SELECT s.*, u.name AS user_name, u.email FROM support_tickets s
           JOIN users u ON u.id = s.user_id ORDER BY s.created_at DESC"""
    )
    return render_template("admin_support.html", tickets=rows)


@main_bp.post("/admin/support/<int:ticket_id>/resolve")
@admin_required
def admin_support_resolve(ticket_id):
    ticket = query("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,), one=True)
    if not ticket:
        abort(404)
    execute("UPDATE support_tickets SET status = 'resolved' WHERE id = ?", (ticket_id,))
    notify(ticket["user_id"], "Support ticket resolved",
           "An administrator has answered your support request.", url_for("main.support"))
    audit("support.resolve", "support_tickets", ticket_id, ticket["subject"])
    flash("Support ticket marked as resolved.", "success")
    return redirect(url_for("main.admin_support"))


@main_bp.get("/admin/audit")
@admin_required
def admin_audit():
    prefix = (request.args.get("action") or "").strip()
    sql = """SELECT a.*, u.name AS actor_name, u.role AS actor_role, u.email AS actor_email
             FROM audit_log a LEFT JOIN users u ON u.id = a.actor_id"""
    if prefix:
        entries = query(sql + " WHERE a.action LIKE ? ORDER BY a.id DESC LIMIT 300",
                        (prefix + "%",))
    else:
        entries = query(sql + " ORDER BY a.id DESC LIMIT 300")
    actions = [row["action"] for row in query(
        "SELECT DISTINCT action FROM audit_log ORDER BY action")]
    return render_template("admin_audit.html", entries=entries, actions=actions,
                           action_filter=prefix)


# ---------------------------------------------------------------------------
# Messages and notifications
# ---------------------------------------------------------------------------

@main_bp.get("/messages")
@login_required
def messages():
    contacts = query(
        """SELECT u.*, 
                  (SELECT COUNT(*) FROM messages m
                   WHERE (m.sender_id = ? AND m.recipient_id = u.id)
                      OR (m.sender_id = u.id AND m.recipient_id = ?)) AS exchanges
           FROM users u
           WHERE u.id != ?
           ORDER BY exchanges DESC, u.name
           LIMIT 12""",
        (g.user["id"], g.user["id"], g.user["id"]),
    )
    partner = None
    thread = []
    partner_id = request.args.get("with", type=int)
    if partner_id:
        partner = query("SELECT * FROM users WHERE id = ?", (partner_id,), one=True)
        if not partner:
            abort(404)
        thread = query(
            """SELECT m.*, s.name AS sender_name
               FROM messages m JOIN users s ON s.id = m.sender_id
               WHERE (m.sender_id = ? AND m.recipient_id = ?)
                  OR (m.sender_id = ? AND m.recipient_id = ?)
               ORDER BY m.created_at, m.id""",
            (g.user["id"], partner_id, partner_id, g.user["id"]),
        )
        execute("UPDATE messages SET read = 1 WHERE sender_id = ? AND recipient_id = ?",
                (partner_id, g.user["id"]))
    return render_template(
        "messages.html",
        contacts=contacts,
        partner=partner,
        thread=thread,
    )


@main_bp.post("/messages/send")
@login_required
def message_send():
    recipient_id = request.form.get("recipient_id", type=int)
    body = (request.form.get("body") or "").strip()
    recipient = query("SELECT * FROM users WHERE id = ?", (recipient_id,), one=True) if recipient_id else None
    if not recipient or recipient["id"] == g.user["id"]:
        flash("Choose someone to message.", "error")
        return redirect(url_for("main.messages"))
    if not body:
        flash("Write a message first.", "error")
        return redirect(url_for("main.messages", **{"with": recipient_id}))
    if len(body) > 1000:
        body = body[:1000]

    execute(
        "INSERT INTO messages (sender_id, recipient_id, body, created_at) VALUES (?, ?, ?, ?)",
        (g.user["id"], recipient_id, body, datetime.now().strftime(STAMP)),
    )
    notify(recipient_id, f"New message from {g.user['name']}", body[:90],
           url_for("main.messages", **{"with": g.user["id"]}))
    return redirect(url_for("main.messages", **{"with": recipient_id}))


@main_bp.get("/notifications")
@login_required
def notifications():
    rows = query(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC, id DESC",
        (g.user["id"],),
    )
    return render_template("notifications.html", notifications=rows)


@main_bp.post("/notifications/read")
@login_required
def notifications_read():
    execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (g.user["id"],))
    flash("All notifications marked as read.", "info")
    return redirect(url_for("main.notifications"))


@main_bp.post("/notifications/<int:notification_id>/read")
@login_required
def notification_read(notification_id):
    row = query("SELECT * FROM notifications WHERE id = ? AND user_id = ?",
                (notification_id, g.user["id"]), one=True)
    if not row:
        abort(404)
    execute("UPDATE notifications SET read = 1 WHERE id = ?", (notification_id,))
    return redirect(row["link"] or url_for("main.notifications"))


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

@main_bp.get("/settings")
@login_required
def settings():
    return render_template("settings.html", categories=CATEGORIES)


@main_bp.post("/settings/profile")
@login_required
def settings_profile():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    city = (request.form.get("city") or "").strip()
    store_name = (request.form.get("store_name") or "").strip() or None
    shipping_notes = (request.form.get("shipping_notes") or "").strip() or None

    if len(name) < 2 or not email:
        flash("Name and email are required.", "error")
        return redirect(url_for("main.settings"))
    existing = query("SELECT id FROM users WHERE email = ? AND id != ?",
                     (email, g.user["id"]), one=True)
    if existing:
        flash("Another account already uses that email.", "error")
        return redirect(url_for("main.settings"))

    execute(
        """UPDATE users SET name = ?, email = ?, city = ?, store_name = ?, shipping_notes = ?
           WHERE id = ?""",
        (name, email, city, store_name, shipping_notes, g.user["id"]),
    )
    flash("Profile updated.", "success")
    return redirect(url_for("main.settings"))


@main_bp.post("/settings/password")
@login_required
def settings_password():
    from security import hash_password, verify_password
    current = request.form.get("current_password") or ""
    new = request.form.get("new_password") or ""
    if not verify_password(g.user["password_hash"], current):
        flash("Your current password is incorrect.", "error")
    elif len(new) < 6:
        flash("The new password needs at least 6 characters.", "error")
    else:
        execute("UPDATE users SET password_hash = ? WHERE id = ?",
                (hash_password(new), g.user["id"]))
        flash("Password updated.", "success")
    return redirect(url_for("main.settings"))


# ---------------------------------------------------------------------------
# Promotions, reviews, disputes, support, team, API
# ---------------------------------------------------------------------------

@main_bp.get("/promotions")
@roles_required(*SELLER_ROLES)
def promotions():
    products = query("SELECT * FROM products WHERE seller_id = ? ORDER BY featured DESC, name",
                     (g.user["id"],))
    return render_template("promotions.html", products=products)


@main_bp.post("/promotions/<int:product_id>/toggle")
@roles_required(*SELLER_ROLES)
def promotion_toggle(product_id):
    product = query("SELECT * FROM products WHERE id = ? AND seller_id = ?",
                    (product_id, g.user["id"]), one=True)
    if not product:
        abort(404)
    execute("UPDATE products SET featured = ? WHERE id = ?",
            (0 if product["featured"] else 1, product_id))
    flash(f"{product['name']} is {'no longer' if product['featured'] else 'now'} featured.",
          "success")
    return redirect(url_for("main.promotions"))


@main_bp.get("/reviews")
@login_required
def reviews():
    if g.user["role"] in SELLER_ROLES:
        rows = query(
            """SELECT r.*, b.name AS buyer_name
               FROM reviews r JOIN users b ON b.id = r.buyer_id
               WHERE r.seller_id = ?
               ORDER BY r.created_at DESC""",
            (g.user["id"],),
        )
        orders = []
    else:
        rows = query(
            """SELECT r.*, s.store_name AS seller_name
               FROM reviews r JOIN users s ON s.id = r.seller_id
               WHERE r.buyer_id = ?
               ORDER BY r.created_at DESC""",
            (g.user["id"],),
        )
        orders = query(
            """SELECT o.*, p.name AS product_name,
                      s.store_name AS seller_name
               FROM orders o
               JOIN products p ON p.id = o.product_id
               JOIN users s ON s.id = o.seller_id
               WHERE o.buyer_id = ? AND o.status = 'delivered'
                 AND NOT EXISTS (SELECT 1 FROM reviews r WHERE r.order_id = o.id)
               ORDER BY o.created_at DESC""",
            (g.user["id"],),
        )
    return render_template("reviews.html", reviews=rows, order_options=orders)


@main_bp.post("/reviews/add")
@roles_required("buyer")
def review_add():
    order_id = request.form.get("order_id", type=int)
    try:
        rating = int(request.form.get("rating") or 0)
    except ValueError:
        rating = 0
    comment = (request.form.get("comment") or "").strip()

    order = query(
        "SELECT * FROM orders WHERE id = ? AND buyer_id = ? AND status = 'delivered'",
        (order_id, g.user["id"]), one=True,
    )
    if not order:
        flash("You can only review one of your delivered orders.", "error")
    elif rating not in range(1, 6):
        flash("Choose a rating between 1 and 5.", "error")
    elif query("SELECT id FROM reviews WHERE order_id = ?", (order_id,), one=True):
        flash("That order already has a review.", "error")
    else:
        execute(
            """INSERT INTO reviews (buyer_id, seller_id, order_id, rating, comment, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (g.user["id"], order["seller_id"], order_id, rating, comment,
             datetime.now().strftime(STAMP)),
        )
        notify(order["seller_id"], "New review received", f"{rating}/5 · {comment[:70]}",
               url_for("main.reviews"))
        flash("Thanks — your review is published.", "success")
    return redirect(url_for("main.reviews"))


@main_bp.get("/disputes")
@login_required
def disputes():
    if g.user["role"] == "traveler":
        rows = query(
            """SELECT d.*, c.store_name, b.name AS buyer_name
               FROM disputes d
               JOIN carts c ON c.id = d.cart_id
               JOIN users b ON b.id = c.buyer_id
               WHERE c.traveler_id = ?
               ORDER BY d.created_at DESC""",
            (g.user["id"],),
        )
    else:
        rows = query(
            """SELECT d.*, c.store_name, t.name AS traveler_name
               FROM disputes d
               JOIN carts c ON c.id = d.cart_id
               LEFT JOIN users t ON t.id = c.traveler_id
               WHERE d.opener_id = ?
               ORDER BY d.created_at DESC""",
            (g.user["id"],),
        )
    cart_options = query(
        """SELECT * FROM carts
           WHERE buyer_id = ? AND status IN ('assigned', 'purchased', 'in_transit', 'delivered')
           ORDER BY updated_at DESC""",
        (g.user["id"],),
    ) if g.user["role"] == "buyer" else []
    return render_template("disputes.html", disputes=rows, cart_options=cart_options)


@main_bp.post("/disputes/add")
@roles_required("buyer")
def dispute_add():
    cart_id = request.form.get("cart_id", type=int)
    reason = (request.form.get("reason") or "").strip()
    cart = query("SELECT * FROM carts WHERE id = ? AND buyer_id = ?",
                 (cart_id, g.user["id"]), one=True)
    if not cart or not reason:
        flash("Choose a delivery and describe the problem.", "error")
        return redirect(url_for("main.disputes"))
    try:
        transition(cart, "dispute", g.user, note=reason[:180])
    except (ValueError, PermissionError):
        flash("That delivery can no longer be disputed.", "error")
        return redirect(url_for("main.disputes"))

    execute(
        "INSERT INTO disputes (cart_id, opener_id, reason, created_at) VALUES (?, ?, ?, ?)",
        (cart_id, g.user["id"], reason, datetime.now().strftime(STAMP)),
    )
    notify(cart["traveler_id"], "Dispute opened", reason[:90], url_for("main.disputes"))
    for seller_id in seller_ids_for_cart(cart_id):
        notify(seller_id, "Dispute opened", reason[:90], url_for("main.disputes"))
    flash("Dispute opened. Our team will review it.", "warning")
    return redirect(url_for("main.disputes"))


@main_bp.get("/support")
@login_required
def support():
    rows = query(
        "SELECT * FROM support_tickets WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    )
    return render_template("support.html", tickets=rows)


@main_bp.post("/support/add")
@login_required
def support_add():
    subject = (request.form.get("subject") or "").strip()
    body = (request.form.get("body") or "").strip()
    if not subject or not body:
        flash("Add a subject and a message.", "error")
    else:
        execute(
            "INSERT INTO support_tickets (user_id, subject, body, created_at) VALUES (?, ?, ?, ?)",
            (g.user["id"], subject, body, datetime.now().strftime(STAMP)),
        )
        flash("Support ticket created. We usually answer within a day.", "success")
    return redirect(url_for("main.support"))


@main_bp.get("/team")
@roles_required(*SELLER_ROLES)
def team():
    members = query(
        "SELECT * FROM team_members WHERE owner_id = ? ORDER BY created_at",
        (g.user["id"],),
    )
    return render_template("team.html", members=members)


@main_bp.post("/team/add")
@roles_required(*SELLER_ROLES)
def team_add():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    role = (request.form.get("role") or "Staff").strip()
    if len(name) < 2 or "@" not in email:
        flash("Add a name and a valid email.", "error")
    else:
        execute(
            """INSERT INTO team_members (owner_id, name, email, role, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (g.user["id"], name, email, role, datetime.now().strftime(STAMP)),
        )
        flash(f"{name} added to your team.", "success")
    return redirect(url_for("main.team"))


@main_bp.post("/team/<int:member_id>/remove")
@roles_required(*SELLER_ROLES)
def team_remove(member_id):
    execute("DELETE FROM team_members WHERE id = ? AND owner_id = ?",
            (member_id, g.user["id"]))
    flash("Team member removed.", "info")
    return redirect(url_for("main.team"))


@main_bp.get("/api")
@roles_required(*SELLER_ROLES)
def api_page():
    tokens = query(
        "SELECT * FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    )
    new_token = session.pop("new_api_token", None)
    return render_template("api.html", tokens=tokens, new_token=new_token)


@main_bp.post("/api/token")
@roles_required(*SELLER_ROLES)
def api_token_create():
    label = (request.form.get("label") or "Default key").strip()[:60]
    token = "abr_" + secrets.token_urlsafe(24)
    execute(
        """INSERT INTO api_tokens (user_id, token_hash, prefix, label, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (
            g.user["id"],
            hashlib.sha256(token.encode()).hexdigest(),
            token[:10],
            label,
            datetime.now().strftime(STAMP),
        ),
    )
    session["new_api_token"] = token
    flash("API key generated. Copy it now — it is only shown once.", "success")
    return redirect(url_for("main.api_page"))


@main_bp.post("/api/token/revoke")
@roles_required(*SELLER_ROLES)
def api_token_revoke():
    execute("UPDATE api_tokens SET revoked = 1 WHERE user_id = ?", (g.user["id"],))
    flash("All API keys revoked.", "info")
    return redirect(url_for("main.api_page"))


@main_bp.get("/api/v1/products")
def api_products():
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return jsonify(error="Missing bearer token"), 401
    token = header.replace("Bearer ", "", 1).strip()
    digest = hashlib.sha256(token.encode()).hexdigest()
    record = query(
        """SELECT at.*, u.role FROM api_tokens at
           JOIN users u ON u.id = at.user_id
           WHERE at.token_hash = ? AND at.revoked = 0""",
        (digest,), one=True,
    )
    if not record:
        return jsonify(error="Invalid or revoked token"), 401
    if record["role"] not in SELLER_ROLES:
        return jsonify(error="This API is available to seller accounts only"), 403
    execute("UPDATE api_tokens SET last_used_at = ? WHERE id = ?",
            (datetime.now().strftime(STAMP), record["id"]))
    products = query(
        """SELECT id, name, price, stock, category, featured
           FROM products WHERE seller_id = ? ORDER BY id""",
        (record["user_id"],),
    )
    return jsonify(
        account=record["user_id"],
        count=len(products),
        products=[dict(product) for product in products],
    )
