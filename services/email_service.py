"""Email service for transactional emails."""
import logging
from typing import Optional

from flask import current_app, render_template_string
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

logger = logging.getLogger(__name__)


class EmailService:
    """Handle all email sending through SendGrid."""

    @staticmethod
    def _send(to_email: str, subject: str, html_content: str, text_content: Optional[str] = None) -> bool:
        """Send an email via SendGrid."""
        if not current_app.config.get("ENABLE_EMAIL_NOTIFICATIONS"):
            logger.info(f"Email notifications disabled. Would send to {to_email}: {subject}")
            return True

        api_key = current_app.config.get("SENDGRID_API_KEY")
        if not api_key:
            logger.error("SENDGRID_API_KEY not configured")
            return False

        try:
            message = Mail(
                from_email=(
                    current_app.config.get("SENDGRID_FROM_EMAIL"),
                    current_app.config.get("SENDGRID_FROM_NAME"),
                ),
                to_emails=to_email,
                subject=subject,
                html_content=html_content,
                plain_text_content=text_content or html_content,
            )

            sg = SendGridAPIClient(api_key)
            response = sg.send(message)

            if response.status_code >= 200 and response.status_code < 300:
                logger.info(f"Email sent to {to_email}: {subject}")
                return True
            else:
                logger.error(f"SendGrid error {response.status_code}: {response.body}")
                return False

        except Exception as e:
            logger.exception(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    def send_otp(email: str, otp_code: str, name: str) -> bool:
        """Send OTP code for registration."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Welcome to Abroad, {name}!</h2>
            <p>Your verification code is:</p>
            <h1 style="background: #f0f0f0; padding: 20px; text-align: center; letter-spacing: 5px;">
                {otp_code}
            </h1>
            <p>This code will expire in 10 minutes.</p>
            <p>If you didn't request this code, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace - Cross-border shopping made easy</p>
        </body>
        </html>
        """

        text = f"""
        Welcome to Abroad, {name}!

        Your verification code is: {otp_code}

        This code will expire in 10 minutes.
        If you didn't request this code, please ignore this email.
        """

        return EmailService._send(email, "Your Abroad Verification Code", html, text)

    @staticmethod
    def send_account_approved(email: str, name: str, role: str) -> bool:
        """Notify user their account was approved."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Account Approved!</h2>
            <p>Hi {name},</p>
            <p>Great news! Your Abroad {role} account has been approved.</p>
            <p>You can now <a href="https://abroad.tn/login">sign in</a> and start using our platform.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Your Abroad Account is Ready", html)

    @staticmethod
    def send_order_confirmation(email: str, name: str, order_id: int, total: str) -> bool:
        """Send order confirmation to buyer."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Order Confirmed</h2>
            <p>Hi {name},</p>
            <p>Your order #{order_id} has been confirmed.</p>
            <p><strong>Total:</strong> {total}</p>
            <p><a href="https://abroad.tn/orders/{order_id}">View Order Details</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, f"Order #{order_id} Confirmed", html)

    @staticmethod
    def send_escrow_funded(email: str, name: str, cart_id: int, amount: str) -> bool:
        """Notify traveler that escrow is funded."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Payment Received</h2>
            <p>Hi {name},</p>
            <p>The buyer has funded escrow for cart #{cart_id}.</p>
            <p><strong>Amount:</strong> {amount}</p>
            <p>You can now proceed with purchasing the items.</p>
            <p><a href="https://abroad.tn/carts/{cart_id}">View Cart</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Escrow Funded", html)

    @staticmethod
    def send_receipt_verified(email: str, name: str, cart_id: int) -> bool:
        """Notify traveler their receipt was verified."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Receipt Verified</h2>
            <p>Hi {name},</p>
            <p>Your purchase receipt for cart #{cart_id} has been verified by our team.</p>
            <p>You can now proceed with delivery.</p>
            <p><a href="https://abroad.tn/carts/{cart_id}">View Cart</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Receipt Verified", html)

    @staticmethod
    def send_receipt_rejected(email: str, name: str, cart_id: int, reason: str) -> bool:
        """Notify traveler their receipt was rejected."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Receipt Requires Attention</h2>
            <p>Hi {name},</p>
            <p>Your purchase receipt for cart #{cart_id} could not be verified.</p>
            <p><strong>Reason:</strong> {reason}</p>
            <p>Please upload a clearer receipt or contact support.</p>
            <p><a href="https://abroad.tn/carts/{cart_id}">View Cart</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Receipt Needs Review", html)

    @staticmethod
    def send_delivery_code(email: str, name: str, cart_id: int, code: str) -> bool:
        """Send delivery code to buyer."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Delivery Code</h2>
            <p>Hi {name},</p>
            <p>Your items for cart #{cart_id} have been delivered!</p>
            <p>Share this code with the traveler to release payment:</p>
            <h1 style="background: #4CAF50; color: white; padding: 20px; text-align: center; letter-spacing: 5px;">
                {code}
            </h1>
            <p><strong>This code expires in 24 hours.</strong></p>
            <p><a href="https://abroad.tn/carts/{cart_id}">Release Payment</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, f"Delivery Code for Cart #{cart_id}", html)

    @staticmethod
    def send_escrow_released(email: str, name: str, cart_id: int, amount: str) -> bool:
        """Notify seller/traveler that payment was released."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Payment Released</h2>
            <p>Hi {name},</p>
            <p>Great news! Payment for cart #{cart_id} has been released.</p>
            <p><strong>Amount:</strong> {amount}</p>
            <p>The funds are now available in your wallet.</p>
            <p><a href="https://abroad.tn/wallet">View Wallet</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Payment Released", html)

    @staticmethod
    def send_refund_processed(email: str, name: str, cart_id: int, amount: str, reason: str) -> bool:
        """Notify buyer of automatic refund."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Refund Processed</h2>
            <p>Hi {name},</p>
            <p>A refund has been processed for cart #{cart_id}.</p>
            <p><strong>Amount:</strong> {amount}</p>
            <p><strong>Reason:</strong> {reason}</p>
            <p>The funds have been returned to your wallet.</p>
            <p><a href="https://abroad.tn/wallet">View Wallet</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, f"Refund for Cart #{cart_id}", html)

    @staticmethod
    def send_dispute_opened(email: str, name: str, cart_id: int, dispute_id: int) -> bool:
        """Notify about dispute opening."""
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Dispute Opened</h2>
            <p>Hi {name},</p>
            <p>A dispute has been opened for cart #{cart_id}.</p>
            <p><strong>Dispute ID:</strong> #{dispute_id}</p>
            <p>Our team will review the case and contact you soon.</p>
            <p><a href="https://abroad.tn/disputes/{dispute_id}">View Dispute</a></p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, f"Dispute Opened - Cart #{cart_id}", html)

    @staticmethod
    def send_password_reset(email: str, name: str, reset_token: str) -> bool:
        """Send password reset link."""
        reset_url = f"https://abroad.tn/reset-password?token={reset_token}"

        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Password Reset Request</h2>
            <p>Hi {name},</p>
            <p>You requested to reset your password. Click the link below:</p>
            <p><a href="{reset_url}" style="background: #2196F3; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; display: inline-block;">
                Reset Password
            </a></p>
            <p>This link expires in 1 hour.</p>
            <p>If you didn't request this, please ignore this email.</p>
            <hr>
            <p style="color: #666; font-size: 12px;">Abroad Marketplace</p>
        </body>
        </html>
        """

        return EmailService._send(email, "Reset Your Password", html)
