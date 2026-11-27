"""SMS service for critical notifications."""
import logging
from typing import Optional

from flask import current_app
from twilio.rest import Client

logger = logging.getLogger(__name__)


class SMSService:
    """Handle SMS notifications through Twilio."""

    @staticmethod
    def _send(to_phone: str, message: str) -> bool:
        """Send an SMS via Twilio."""
        if not current_app.config.get("ENABLE_SMS_NOTIFICATIONS"):
            logger.info(f"SMS notifications disabled. Would send to {to_phone}: {message}")
            return True

        account_sid = current_app.config.get("TWILIO_ACCOUNT_SID")
        auth_token = current_app.config.get("TWILIO_AUTH_TOKEN")
        from_phone = current_app.config.get("TWILIO_PHONE_NUMBER")

        if not all([account_sid, auth_token, from_phone]):
            logger.error("Twilio credentials not configured")
            return False

        try:
            client = Client(account_sid, auth_token)

            sms = client.messages.create(
                body=message,
                from_=from_phone,
                to=to_phone
            )

            logger.info(f"SMS sent to {to_phone}: {sms.sid}")
            return True

        except Exception as e:
            logger.exception(f"Failed to send SMS to {to_phone}: {e}")
            return False

    @staticmethod
    def send_delivery_code(phone: str, cart_id: int, code: str) -> bool:
        """Send delivery code via SMS."""
        message = f"Abroad: Your delivery code for cart #{cart_id} is: {code}. Valid for 24 hours."
        return SMSService._send(phone, message)

    @staticmethod
    def send_escrow_alert(phone: str, cart_id: int, message_text: str) -> bool:
        """Send critical escrow-related alerts."""
        message = f"Abroad Alert (Cart #{cart_id}): {message_text}"
        return SMSService._send(phone, message)

    @staticmethod
    def send_verification_code(phone: str, code: str) -> bool:
        """Send verification code for phone verification."""
        message = f"Abroad: Your verification code is {code}. Do not share this code."
        return SMSService._send(phone, message)
