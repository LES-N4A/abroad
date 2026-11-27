# Abroad — Flask + SQLite marketplace

Abroad is a working classroom marketplace for cross-border shopping in Tunisia. Buyers request products, travelers carry them, and money is held in escrow until the buyer confirms delivery with a code. Sellers also run a local catalogue where buyers order directly, without escrow or a traveler.

The original design and logo are preserved. Everything is rendered by Flask from the templates in `templates/`.

## Quick start (development)

Requires Python 3.10+.

```bash
# from the project root
python -m venv .venv

# Windows (Git Bash / PowerShell)
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe app.py

# macOS / Linux
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

Open <http://127.0.0.1:5000>. On Windows, `start-abroad.cmd` does the same thing, writes to `instance\flask.log`, and can open a Cloudflare quick tunnel so the site can be shown from another device.

### Sharing the site with friends

`tunnel-abroad.cmd` (Windows) opens a public `https://...trycloudflare.com` link to the running app, copies it to the clipboard and checks that it answers. If nothing is listening yet it starts `app.py` on port 5000 first; `tunnel-abroad.cmd 5001` tunnels the production app instead. The address is different on every start and is public — anyone with the link can open the site — so close it with `stop-abroad.cmd` when you are done.

The first start creates `instance/abroad.sqlite` and seeds the five core accounts only. No products, orders, carts, trips, messages or wallet activity are created automatically.

To reset the database, stop the server, delete `instance/abroad.sqlite`, and start it again. The database and uploads are ignored by Git.

## Phone app

`abroad-mobile-1.0.0.apk` in the project root is the Android client: a small native app that opens the running site full-screen, with the Abroad logo as its icon. The Flask server keeps running on the computer; on first launch the app asks for the public tunnel link and remembers it. Copy the APK to the phone and open it, allowing installs from that source. The sources are in `android/`, and `android/README.md` explains how to rebuild it.

## Running the production entrypoint

`app_production.py` is the production factory: it reads its settings from `.env`, refuses to boot without `SECRET_KEY`, and serves the same app with production security settings and structured logging.

```bash
.venv/Scripts/python.exe -m pip install -r requirements-production.txt
# create .env with at least SECRET_KEY=...
start-production.cmd
```

`start-production.cmd` starts `app_production.py` on **port 5001**, using `FLASK_RUN_HOST` / `FLASK_RUN_PORT` from `.env`, waits for the port to accept connections, and logs to `instance\production.log`.

- App: <http://127.0.0.1:5001>
- Health: <http://127.0.0.1:5001/health>

The optional SendGrid, Stripe and Twilio integrations stay disabled (`ENABLE_EMAIL_NOTIFICATIONS=0`, etc.); no provider credentials are required to boot locally. Redis and Celery checks are gated behind `ENABLE_REDIS=0`, so `/health/ready` works without either service.


## Demo accounts

All core accounts use the password **`demo1234`**. The coloured buttons on the login page sign in instantly.

| Role | Email | What to try |
|---|---|---|
| Buyer | `sarra@abroad.tn` | Browse the shop, create a custom store request, pay escrow, order from the local market, review a delivered order |
| Seller | `store@abroad.tn` | Add products, source a custom item, advance orders, request a payout |
| Traveler | `ahmed@abroad.tn` | Add a trip with a flight receipt, accept a request, upload a receipt, withdraw earnings |
| Pro seller | `pro@abroad.tn` | Revenue chart, bulk upload, team, promotions, API |
| Administrator | `admin@abroad.tn` | Approve accounts, verify flights and receipts, decide payouts, monitor every request |

New registrations stay **pending** until the administrator approves them.

## Money

Every amount is stored as an **integer number of millimes** (1 DT = 1000 millimes). `money.py` converts dinars input to millimes (`to_millimes`), formats millimes for display (`format_dt`), and the `money` / `dinars` Jinja filters render them in templates. `db.migrate_to_millimes()` upgraded the original floating-point columns in place without changing row ids.

Wallets are a ledger of `wallet_transactions` rows, and the balance is their sum:

- **Top-ups** — `/wallet/top-up` credits the wallet immediately as a demo payment (no gateway). A single top-up is capped at 5 000 DT.
- **Escrow** — paying a request debits the buyer, and releasing the delivery credits the traveler's fee.
- **Payouts** — sellers and travelers request a withdrawal from `/wallet/payout`. The amount is debited from the wallet immediately and held as a `payout_requests` row until an administrator pays or rejects it from `/admin/payouts`; a rejection returns the money to the wallet. Every step is recorded in the audit log and the notification inbox.

## Orders

Local catalogue orders have their own lifecycle, separate from escrow:

1. A buyer orders from a product page (stock is reserved immediately).
2. The seller advances the order through **Placed → Processing → Shipped → Delivered**.
3. The buyer can cancel while the order is still `new` or `processing`, which puts the stock back.
4. After delivery the buyer confirms receipt, and only then can they leave a product review. Reviews on delivered orders carry a **Verified purchase** badge.

`/orders` lists the signed-in user's orders and `/orders/<id>` shows the full timeline.

## What is implemented

- Session authentication, admin approval for new accounts, password hashing and role-based access.
- Buyer marketplace with shop search, category filters and seller-uploaded local listings.
- Verified traveler directory; only trips with an admin-checked flight receipt are visible.
- Custom requests to Shein, Amazon or any online store using a pasted cart link.
- Traveler matching by destination, date, available weight and fee, with a 0–100 score.
- Escrow payment after traveler acceptance, receipt upload with fraud checks, admin verification, and automatic buyer refunds for late receipts.
- Local order flow with stock handling, cancellation, delivery confirmation and gated reviews.
- Wallet ledger, demo top-ups, payout requests and the admin payout queue.
- Admin interface for accounts, trips, purchase receipts, requests, orders, payouts, disputes and support.
- Escrow state machine with audit events, HMAC delivery codes, expiry, attempt limits and wallet payouts.
- Seller catalogue CRUD, stock, featured products, CSV bulk upload, analytics, promotions and reviews.
- Persistent messaging, notification inbox, disputes, support tickets, team management.
- Hashed API tokens and a real `/api/v1/products` endpoint.
- CSRF protection on every POST.
- Health endpoints (`/health`, `/health/ready`, `/health/live`).

## Project structure

```
app.py               development factory, filters, CSRF, error pages, legacy redirects
app_production.py    production factory (app_production.py entrypoint, port 5001)
wsgi.py              gunicorn entrypoint: gunicorn wsgi:app
config.py            Config / Development / Production / Testing settings
auth.py              login, registration + OTP, demo sign-in, logout
views.py             all marketplace routes (orders, escrow, wallet, payouts, admin)
db.py                sqlite3 connection, schema init, millime migration, helpers
schema.sql           tables, constraints and indexes
seed.py              clean core accounts
money.py             millime conversion and formatting helpers
services/            core helpers (cart totals, wallet balance, notifications)
escrow.py            escrow state machine and payouts
matching.py          traveler/trip scoring
otp.py               HMAC delivery codes
refunds.py           overdue receipt refund sweeper
health.py            health and readiness endpoints
security.py          password hashing and CSRF
rate_limiting.py     request throttling
webhooks.py          payment webhook handling
constants.py         roles, navigation, order/cart workflow
templates/           Jinja pages and partials
assets/              shared CSS, JS, logo and favicon (Flask static folder)
tests/               pytest suite
docs/                production notes, deployment guide and roadmap
start-abroad.cmd     dev launcher (port 5000) + optional Cloudflare tunnel
start-production.cmd production launcher (port 5001) with its own log
tunnel-abroad.cmd    public Cloudflare link only (starts the app if needed)
stop-abroad.cmd      stops Flask and the tunnel
```

## Tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

The suite creates temporary databases, so it never touches `instance/abroad.sqlite`. Its 23 tests cover the clean seed, role isolation, registration/OTP, admin account approval, flight-receipt verification, local listings, shop requests, traveler matching, custom sourcing, escrow payment, receipt verification and fraud flags, delivery release, automatic late-receipt refunds, order progression, the local order lifecycle and review gate, review ownership, bulk upload, API tokens, CSRF, admin auditing, millime storage, and top-up/payout approval.

## API example

1. Sign in as a seller or pro seller.
2. Open **Account menu → API access**, generate a key and copy it.
3. Call the endpoint:

```bash
curl -H "Authorization: Bearer abr_..." http://127.0.0.1:5000/api/v1/products
```

The response contains only that seller’s products. Keys are stored as SHA-256 hashes and shown only once.

## Configuration

Development reads `app.py`, which uses environment variables with sensible defaults. The production entrypoint loads `.env`.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask session/CSRF signing key. Required by `app_production.py`. |
| `FLASK_ENV` | `development` (default) or `production`. |
| `FLASK_RUN_HOST` / `FLASK_RUN_PORT` | Address used by `app_production.py` and `start-production.cmd` (default `127.0.0.1:5001`). |
| `DATABASE_PATH` | SQLite file (default `instance/abroad.sqlite`). |
| `UPLOAD_FOLDER` | Upload directory (default `instance/uploads`). |
| `ENABLE_REDIS` | Set to `1` only when Redis is running; otherwise `/health/ready` skips Redis and Celery. |
| `ENABLE_EMAIL_NOTIFICATIONS` / `ENABLE_SMS_NOTIFICATIONS` | Optional provider integrations, off by default. |
| `START_REFUND_SWEEPER` | Enables the background overdue-receipt sweeper in the dev entrypoint. |

Administrator access is stored on the user record (`users.is_admin`) rather than a new database role value, so existing accounts and data remain compatible. The owner account cannot be suspended from the admin screen.

Uploads go to `instance/uploads/` and are served from `/uploads/<filename>`.

## Documentation

The `docs/` folder holds the longer production notes: `QUICKSTART.md`, `DEPLOYMENT.md`, `PRODUCTION_ROADMAP.md`, `IMPLEMENTATION_SUMMARY.md`, `COMPLETE.md` and `README-PRODUCTION.md`. `PROPOSAL.md` in the project root is the one-page coursework proposal.

## Known limitations

This is a teaching project, not a production marketplace: escrow and wallet top-ups are an internal ledger rather than a payment-provider integration, the email OTP is displayed on the page, flight and purchase receipts are checked manually by the administrator, and uploaded files are stored on the local disk. No real email, SMS, courier or card payment is sent. Payouts are recorded for the administrator to settle outside the app. Both entrypoints currently run on the Werkzeug development server; `wsgi.py` is ready for gunicorn when a real deployment is set up.
