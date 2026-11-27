"""Payment processing through Stripe."""
import logging
from typing import Dict, Optional

import stripe
from flask import current_app

logger = logging.getLogger(__name__)


class PaymentService:
    """Handle payment processing through Stripe."""

    @staticmethod
    def _get_stripe():
        """Initialize Stripe with API key."""
        api_key = current_app.config.get("STRIPE_SECRET_KEY")
        if not api_key:
            raise ValueError("STRIPE_SECRET_KEY not configured")
        stripe.api_key = api_key
        return stripe

    @staticmethod
    def create_payment_intent(
        amount_millimes: int,
        currency: str = "tnd",
        metadata: Optional[Dict] = None,
        description: str = ""
    ) -> Optional[Dict]:
        """
        Create a Stripe Payment Intent.

        Args:
            amount_millimes: Amount in millimes (Tunisian millimes)
            currency: Currency code (default: TND)
            metadata: Additional metadata to attach
            description: Payment description

        Returns:
            Payment intent dict with client_secret, or None on failure
        """
        try:
            stripe_client = PaymentService._get_stripe()

            # Stripe amounts are in smallest currency unit
            # For TND: 1 dinar = 1000 millimes
            intent = stripe_client.PaymentIntent.create(
                amount=amount_millimes,
                currency=currency.lower(),
                metadata=metadata or {},
                description=description,
                automatic_payment_methods={"enabled": True},
            )

            logger.info(f"Created payment intent {intent.id} for {amount_millimes} millimes")

            return {
                "id": intent.id,
                "client_secret": intent.client_secret,
                "amount": intent.amount,
                "status": intent.status,
            }

        except stripe.error.StripeError as e:
            logger.exception(f"Stripe error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Payment intent creation failed: {e}")
            return None

    @staticmethod
    def confirm_payment(payment_intent_id: str) -> bool:
        """
        Verify a payment intent was successful.

        Args:
            payment_intent_id: Stripe payment intent ID

        Returns:
            True if payment succeeded, False otherwise
        """
        try:
            stripe_client = PaymentService._get_stripe()
            intent = stripe_client.PaymentIntent.retrieve(payment_intent_id)

            if intent.status == "succeeded":
                logger.info(f"Payment confirmed: {payment_intent_id}")
                return True
            else:
                logger.warning(f"Payment not succeeded: {payment_intent_id} status={intent.status}")
                return False

        except stripe.error.StripeError as e:
            logger.exception(f"Stripe error confirming payment: {e}")
            return False
        except Exception as e:
            logger.exception(f"Payment confirmation failed: {e}")
            return False

    @staticmethod
    def create_refund(
        payment_intent_id: str,
        amount_millimes: Optional[int] = None,
        reason: str = "requested_by_customer"
    ) -> Optional[str]:
        """
        Create a refund for a payment.

        Args:
            payment_intent_id: Original payment intent ID
            amount_millimes: Amount to refund (None = full refund)
            reason: Refund reason

        Returns:
            Refund ID if successful, None otherwise
        """
        try:
            stripe_client = PaymentService._get_stripe()

            refund_params = {
                "payment_intent": payment_intent_id,
                "reason": reason,
            }

            if amount_millimes is not None:
                refund_params["amount"] = amount_millimes

            refund = stripe_client.Refund.create(**refund_params)

            logger.info(f"Created refund {refund.id} for payment {payment_intent_id}")
            return refund.id

        except stripe.error.StripeError as e:
            logger.exception(f"Stripe refund error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Refund creation failed: {e}")
            return None

    @staticmethod
    def create_payout(
        amount_millimes: int,
        destination_account: str,
        metadata: Optional[Dict] = None
    ) -> Optional[str]:
        """
        Create a payout to seller/traveler (requires Stripe Connect).

        Args:
            amount_millimes: Amount to payout
            destination_account: Stripe connected account ID
            metadata: Additional metadata

        Returns:
            Payout ID if successful, None otherwise
        """
        try:
            stripe_client = PaymentService._get_stripe()

            transfer = stripe_client.Transfer.create(
                amount=amount_millimes,
                currency="tnd",
                destination=destination_account,
                metadata=metadata or {},
            )

            logger.info(f"Created transfer {transfer.id} to {destination_account}")
            return transfer.id

        except stripe.error.StripeError as e:
            logger.exception(f"Stripe transfer error: {e}")
            return None
        except Exception as e:
            logger.exception(f"Transfer creation failed: {e}")
            return None

    @staticmethod
    def verify_webhook_signature(payload: bytes, sig_header: str) -> Optional[Dict]:
        """
        Verify Stripe webhook signature.

        Args:
            payload: Raw request body
            sig_header: Stripe-Signature header value

        Returns:
            Parsed event dict if valid, None if invalid
        """
        webhook_secret = current_app.config.get("STRIPE_WEBHOOK_SECRET")
        if not webhook_secret:
            logger.error("STRIPE_WEBHOOK_SECRET not configured")
            return None

        try:
            stripe_client = PaymentService._get_stripe()
            event = stripe_client.Webhook.construct_event(
                payload, sig_header, webhook_secret
            )
            logger.info(f"Verified webhook: {event['type']}")
            return event

        except stripe.error.SignatureVerificationError as e:
            logger.error(f"Invalid webhook signature: {e}")
            return None
        except Exception as e:
            logger.exception(f"Webhook verification failed: {e}")
            return None

    @staticmethod
    def get_publishable_key() -> str:
        """Get Stripe publishable key for frontend."""
        return current_app.config.get("STRIPE_PUBLISHABLE_KEY", "")
