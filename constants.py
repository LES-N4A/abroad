ROLE_HOME = {
    "buyer": "main.buyer_dashboard",
    "seller": "main.seller_dashboard",
    "pro": "main.pro_dashboard",
    "traveler": "main.traveler_dashboard",
    "admin": "main.admin_dashboard",
    "staff": "main.staff_dashboard",
}

ROLE_LABEL = {
    "buyer": "Buyer",
    "seller": "Seller",
    "pro": "Pro seller",
    "traveler": "Traveler",
    "admin": "Administrator",
    "staff": "Verifier",
}

ROLE_ICON = {
    "buyer": "fa-bag-shopping",
    "seller": "fa-store",
    "pro": "fa-certificate",
    "traveler": "fa-plane",
    "admin": "fa-shield-halved",
    "staff": "fa-check-double",
}

ROLE_NAV = {
    "buyer": [
        ("main.buyer_dashboard", "Dashboard", "fa-house"),
        ("main.shop", "Shop", "fa-magnifying-glass"),
        ("main.local_market", "Local", "fa-location-dot"),
        ("main.travelers_page", "Travelers", "fa-plane"),
        ("main.orders", "My orders", "fa-box"),
        ("main.escrow", "Escrow", "fa-shield-halved"),
    ],
    "seller": [
        ("main.seller_dashboard", "Dashboard", "fa-house"),
        ("main.products_page", "Products", "fa-shirt"),
        ("main.orders", "Orders", "fa-bag-shopping"),
        ("main.sourcing", "Sourcing", "fa-cart-shopping"),
        ("main.analytics", "Analytics", "fa-chart-line"),
    ],
    "pro": [
        ("main.pro_dashboard", "Dashboard", "fa-house"),
        ("main.products_page", "Products", "fa-shirt"),
        ("main.orders", "Orders", "fa-bag-shopping"),
        ("main.sourcing", "Sourcing", "fa-cart-shopping"),
        ("main.analytics", "Analytics", "fa-chart-line"),
    ],
    "traveler": [
        ("main.traveler_dashboard", "Dashboard", "fa-house"),
        ("main.requests_page", "Requests", "fa-bell"),
        ("main.wallet", "Earnings", "fa-money-bill-wave"),
        ("main.trips", "Schedule", "fa-calendar-days"),
    ],
    "admin": [
        ("main.admin_dashboard", "Overview", "fa-gauge-high"),
        ("main.admin_accounts", "Accounts", "fa-users"),
        ("main.admin_trips", "Trips", "fa-plane-departure"),
        ("main.admin_receipts", "Receipts", "fa-receipt"),
        ("main.admin_orders", "Orders", "fa-box"),
        ("main.admin_staff", "Staff", "fa-user-gear"),
        ("main.admin_audit", "Audit", "fa-clipboard-list"),
    ],
    "staff": [
        ("main.staff_dashboard", "Verification", "fa-check-double"),
        ("main.staff_receipts", "Receipts", "fa-receipt"),
    ],
}

SELLER_ROLES = ("seller", "pro")

STAFF_ROLE = "staff"
CATEGORIES = ["Fashion", "Accessories", "Electronics", "Home", "Beauty", "Shoes"]

ORDER_FLOW = {
    "new": "processing",
    "processing": "shipped",
    "shipped": "delivered",
}

CART_STEPS = ["Ordered", "Purchased", "In transit", "Arrived", "Delivered"]

CART_STEP_INDEX = {
    "assigned": 2,
    "purchased": 2,
    "in_transit": 3,
    "delivered": 4,
    "completed": 5,
}
