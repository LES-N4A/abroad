# Abroad — From Static Mockup to a Working Marketplace

**Student:** ____________________  
**Course / class:** ____________________  
**Date:** 16 November 2026

## The problem

Tunisians often want products that are easier or cheaper to buy abroad, while travelers coming home often have unused luggage capacity. Abroad connects the two: a buyer requests an item, a traveler carries it, and payment is held safely until delivery is confirmed.

The existing Abroad site was a visual prototype. The pages looked finished, but products came from JavaScript arrays, forms did nothing, and “escrow” was only text. My project keeps the design and logo while turning the prototype into a real application with accounts, a database and working workflows.

## What I propose to build

A Flask + SQLite marketplace with four marketplace account types plus an administrator, sharing one responsive, server-rendered interface:

- **Buyers** browse the shop, create traveler requests, track deliveries, release escrow with a delivery code, review sellers and open disputes.
- **Sellers** manage products and stock, process orders, withdraw earnings and read revenue and inventory analytics.
- **Pro sellers** also get team members, promotions, bulk CSV upload and API keys.
- **Travelers** publish trips with a required flight receipt, receive algorithm-ranked requests after admin approval, accept carts, upload purchase receipts, mark deliveries and track earnings.
- **Administrators** approve or suspend accounts, verify flight receipts and purchase receipts, and monitor every request, order, escrow balance, dispute and support ticket.

## What “dynamic” means here

Every button and form is connected to a route that reads or writes SQLite; nothing is a decorative mock action.

| Area | Real behaviour |
|---|---|
| Accounts | Registration with a demo email OTP, admin approval, password hashing, sessions, role-based redirects and access control |
| Shop and matching | Server-side search and category filters; local buyer listings; custom cart links; destination, date, capacity and fee produce a 0–100 trip score |
| Escrow | Traveler accepts → buyer funds escrow → receipt within 2 days → admin verification → in transit → delivered → buyer release; automatic refund after a missed deadline |
| Delivery code | HMAC-derived 6-digit code with 24-hour expiry, five-attempt limit and constant-time comparison |
| Dashboards | Real order status, wallet ledger, withdrawals, reviews, analytics, messages and notifications |
| Extras | Disputes, support tickets, team management, promotions, bulk upload and hashed API tokens |

The original visual design and uploaded logo are preserved. The old static pages remain in `prototype/` for comparison.

## Technical design

- **Backend:** Python 3 and Flask, with an application factory and blueprints for authentication and the marketplace.
- **Database:** SQLite through Python’s `sqlite3`; `schema.sql` defines keys, constraints and indexes; only core accounts are seeded, with all marketplace activity created by real actions.
- **Frontend:** Jinja2 templates, one shared stylesheet and progressive JavaScript for menus, modals, toasts and copy buttons.
- **Security:** PBKDF2 password hashes, signed session cookies, a CSRF token on every POST, server-side role checks, parameterised SQL and SHA-256 API-token hashes.
- **Business logic:** separate modules for escrow transitions, trip matching, delivery codes and shared queries.
- **Tests:** 16 pytest tests cover authentication, admin approval, verified trips, local listings, matching, custom sourcing, escrow receipt verification, automatic refunds, orders, reviews, bulk upload, the API and CSRF; the main journeys were also exercised end-to-end, including failure cases.

## Scope

This is a classroom demonstration, not a production payment platform. Escrow is represented by an internal wallet ledger rather than a real payment provider; the email OTP is displayed on screen; uploaded flight and purchase receipts are stored locally and reviewed manually by the administrator; and there is no courier integration. These boundaries let the project run and be marked offline.

## Demonstration

Register an account and show that it stays pending until the administrator approves it. Sign in as the traveler, add a trip with a flight receipt, then approve it as the administrator. As the buyer, create a custom Shein/Amazon request, have the traveler accept it, pay into escrow and let the traveler upload a receipt; approve that receipt as the administrator. Mark the parcel delivered, release escrow with the code, and show the buyer notification plus the traveler’s earnings. Finally show a local listing, the automatic late-receipt refund, and the 16 passing tests.
