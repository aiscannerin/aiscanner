import hashlib
import hmac
import uuid

import razorpay
from flask import current_app


def _client() -> razorpay.Client:
    return razorpay.Client(
        auth=(
            current_app.config["RAZORPAY_KEY_ID"],
            current_app.config["RAZORPAY_KEY_SECRET"],
        )
    )


def create_order(amount_paise: int, currency: str = "INR") -> dict:
    """
    Create a Razorpay order and return the raw Razorpay response dict.
    amount_paise must be in the smallest currency unit (paise for INR).
    receipt is auto-generated as a UUID to satisfy Razorpay's uniqueness requirement.
    """
    return _client().order.create(
        {
            "amount": amount_paise,
            "currency": currency,
            "receipt": f"rcpt_{uuid.uuid4().hex[:20]}",
            "payment_capture": 1,  # auto-capture on payment success
        }
    )


def verify_payment_signature(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> bool:
    """
    Verify the HMAC-SHA256 signature sent by Razorpay after frontend payment.
    Message format: "<order_id>|<payment_id>"
    Key: RAZORPAY_KEY_SECRET
    """
    key_secret = current_app.config["RAZORPAY_KEY_SECRET"].encode()
    message = f"{razorpay_order_id}|{razorpay_payment_id}".encode()
    expected = hmac.new(key_secret, message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, razorpay_signature)


def verify_webhook_signature(raw_body: bytes, signature: str) -> bool:
    """
    Verify the HMAC-SHA256 signature on an incoming Razorpay webhook.
    raw_body must be the unmodified request bytes — never the parsed JSON.
    Key: RAZORPAY_WEBHOOK_SECRET
    """
    webhook_secret = current_app.config["RAZORPAY_WEBHOOK_SECRET"].encode()
    expected = hmac.new(webhook_secret, raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
