"""
Stripe webhook handler for payment events.
"""
import logging
from flask import Blueprint, request, jsonify, current_app

from services.payment_service import PaymentService
from db import execute, query
from services import notify

logger = logging.getLogger(__name__)

webhooks_bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


@webhooks_bp.route("/stripe", methods=["POST"])
def stripe_webhook():
    """Handle Stripe webhook events."""
    payload = request.get_data()
    sig_header = request.headers.get("Stripe-Signature")

    event = PaymentService.verify_webhook_signature(payload, sig_header)
    if not event:
        logger.error("Invalid webhook signature")
        return jsonify({"error": "Invalid signature"}), 400

    event_type = event["type"]
    logger.info(f"Processing Stripe webhook: {event_type}")

    try:
        if event_type == "payment_intent.succeeded":
            handle_payment_succeeded(event["data"]["object"])
        elif event_type == "payment_intent.payment_failed":
            handle_payment_failed(event["data"]["object"])
        elif event_type == "refund.created":
            handle_refund_created(event["data"]["object"])
        elif event_type == "charge.dispute.created":
            handle_dispute_created(event["data"]["object"])
        else:
            logger.info(f"Unhandled event type: {event_type}")

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.exception(f"Webhook processing error: {e}")
        return jsonify({"error": "Processing failed"}), 500


def handle_payment_succeeded(payment_intent):
    """Handle successful payment."""
    cart_id = payment_intent.get("metadata", {}).get("cart_id")
    if not cart_id:
        logger.warning("Payment intent missing cart_id in metadata")
        return

    # Update cart as paid
    execute(
        """UPDATE carts SET paid = 1, paid_at = datetime('now', 'localtime')
           WHERE id = ?""",
        (cart_id,)
    )

    # Notify traveler
    cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    if cart and cart["traveler_id"]:
        notify(
            cart["traveler_id"],
            "Payment Received",
            f"Escrow funded for cart #{cart_id}",
            f"/carts/{cart_id}"
        )

    logger.info(f"Payment confirmed for cart #{cart_id}")


def handle_payment_failed(payment_intent):
    """Handle failed payment."""
    cart_id = payment_intent.get("metadata", {}).get("cart_id")
    if not cart_id:
        return

    # Notify buyer
    cart = query("SELECT * FROM carts WHERE id = ?", (cart_id,), one=True)
    if cart and cart["buyer_id"]:
        notify(
            cart["buyer_id"],
            "Payment Failed",
            f"Payment for cart #{cart_id} was declined. Please try again.",
            f"/carts/{cart_id}"
        )

    logger.warning(f"Payment failed for cart #{cart_id}")


def handle_refund_created(refund):
    """Handle refund creation."""
    payment_intent_id = refund.get("payment_intent")
    amount = refund.get("amount")

    logger.info(f"Refund created: {refund['id']} for {amount} millimes")


def handle_dispute_created(dispute):
    """Handle dispute creation."""
    charge_id = dispute.get("charge")
    reason = dispute.get("reason")

    logger.warning(f"Dispute created on charge {charge_id}: {reason}")

    # Notify admins
    from views import notify_admins
    notify_admins(
        "Payment Dispute",
        f"A dispute was opened: {reason}",
        f"/admin/disputes"
    )
