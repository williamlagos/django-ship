"""
Web2 Payment services for django-ship supporting Stripe Checkout / PaymentIntents
and modern PayPal v2 Orders REST API.
"""

import base64
import json
import logging
from decimal import Decimal

import requests
import stripe
from django.conf import settings

from .models import Order, OrderItem, Tip

logger = logging.getLogger(__name__)


class StripeService:
    """Handles Stripe Checkout sessions, PaymentIntents, and Webhooks."""

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or getattr(
            settings, "STRIPE_SECRET_KEY", "sk_test_mock_stripe_key"
        )
        stripe.api_key = self.api_key

    def create_checkout_session(
        self,
        order: Order,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> dict:
        """
        Creates a Stripe Checkout Session for an Order.
        """
        line_items = []
        for item in order.items.select_related("product").all():
            unit_amount_cents = int(item.price * 100)
            line_items.append(
                {
                    "price_data": {
                        "currency": getattr(settings, "STRIPE_CURRENCY", "usd").lower(),
                        "product_data": {
                            "name": item.product.name,
                            "description": item.product.description or "",
                        },
                        "unit_amount": unit_amount_cents,
                    },
                    "quantity": item.quantity,
                }
            )

        # Fallback if no items
        if not line_items:
            unit_amount_cents = int(order.total * 100)
            line_items.append(
                {
                    "price_data": {
                        "currency": getattr(settings, "STRIPE_CURRENCY", "usd").lower(),
                        "product_data": {
                            "name": f"Order #{order.pk}",
                        },
                        "unit_amount": unit_amount_cents,
                    },
                    "quantity": 1,
                }
            )

        session_params = {
            "payment_method_types": ["card"],
            "line_items": line_items,
            "mode": "payment",
            "success_url": success_url,
            "cancel_url": cancel_url,
            "client_reference_id": str(order.pk),
            "metadata": {"order_id": str(order.pk)},
        }
        if customer_email:
            session_params["customer_email"] = customer_email

        session = stripe.checkout.Session.create(**session_params)
        return {
            "session_id": session.id,
            "url": session.url,
        }

    def create_payment_intent(
        self,
        amount: Decimal | float | int,
        currency: str = "usd",
        metadata: dict | None = None,
    ) -> dict:
        """
        Creates a Stripe PaymentIntent for custom payments, tips, or bounties.
        """
        amount_cents = int(Decimal(str(amount)) * 100)
        intent = stripe.PaymentIntent.create(
            amount=amount_cents,
            currency=currency.lower(),
            metadata=metadata or {},
        )
        return {
            "id": intent.id,
            "client_secret": intent.client_secret,
            "status": intent.status,
            "amount": amount_cents,
        }

    def handle_webhook(
        self, payload: bytes | str, sig_header: str, webhook_secret: str | None = None
    ) -> dict:
        """
        Verifies and processes a Stripe webhook event.
        """
        secret = webhook_secret or getattr(settings, "STRIPE_WEBHOOK_SECRET", "")
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        event = stripe.Webhook.construct_event(payload, sig_header, secret)
        event_type = event["type"]
        data_object = event["data"]["object"]

        if event_type == "checkout.session.completed":
            order_id = data_object.get("client_reference_id") or (
                data_object.get("metadata") or {}
            ).get("order_id")
            if order_id:
                try:
                    order = Order.objects.get(pk=int(order_id))
                    order.status = Order.STATUS_PAID
                    order.save(update_fields=["status"])
                    logger.info(f"Order #{order_id} marked as PAID via Stripe webhook")
                except Order.DoesNotExist:
                    logger.warning(f"Order #{order_id} not found in Stripe webhook")

        elif event_type == "payment_intent.succeeded":
            pi_id = data_object.get("id")
            Tip.objects.filter(transaction_reference=pi_id).update(
                payment_rail="stripe"
            )

        return {"status": "processed", "type": event_type}


class PayPalV2Service:
    """
    Handles modern PayPal Checkout v2 Orders REST API.
    """

    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
        sandbox: bool | None = None,
    ):
        self.client_id = client_id or getattr(
            settings, "PAYPAL_CLIENT_ID", "mock_paypal_client_id"
        )
        self.client_secret = client_secret or getattr(
            settings, "PAYPAL_CLIENT_SECRET", "mock_paypal_client_secret"
        )
        self.sandbox = (
            sandbox
            if sandbox is not None
            else getattr(settings, "PAYPAL_SANDBOX", True)
        )
        self.base_url = (
            "https://api-m.sandbox.paypal.com"
            if self.sandbox
            else "https://api-m.paypal.com"
        )

    def get_access_token(self) -> str:
        """Fetches an OAuth2 bearer token from PayPal v2."""
        auth_bytes = f"{self.client_id}:{self.client_secret}".encode("utf-8")
        auth_b64 = base64.b64encode(auth_bytes).decode("utf-8")

        resp = requests.post(
            f"{self.base_url}/v1/oauth2/token",
            headers={
                "Authorization": f"Basic {auth_b64}",
                "Content-Type": "application/x-www-form-urlencoded",
            },
            data={"grant_type": "client_credentials"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()["access_token"]

    def create_order(
        self,
        amount: Decimal | float | int,
        currency: str = "USD",
        custom_id: str | None = None,
        return_url: str | None = None,
        cancel_url: str | None = None,
    ) -> dict:
        """
        Creates an order on PayPal Checkout v2.
        """
        token = self.get_access_token()
        payload = {
            "intent": "CAPTURE",
            "purchase_units": [
                {
                    "amount": {
                        "currency_code": currency.upper(),
                        "value": str(amount),
                    },
                }
            ],
        }
        if custom_id:
            payload["purchase_units"][0]["custom_id"] = custom_id

        if return_url and cancel_url:
            payload["application_context"] = {
                "return_url": return_url,
                "cancel_url": cancel_url,
            }

        resp = requests.post(
            f"{self.base_url}/v2/checkout/orders",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    def capture_order(self, paypal_order_id: str) -> dict:
        """
        Captures authorized funds for a PayPal v2 order.
        """
        token = self.get_access_token()
        resp = requests.post(
            f"{self.base_url}/v2/checkout/orders/{paypal_order_id}/capture",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()

        # Update order if custom_id provided
        if data.get("status") == "COMPLETED":
            purchase_units = data.get("purchase_units", [])
            if purchase_units:
                order_id = purchase_units[0].get("custom_id")
                if order_id and order_id.isdigit():
                    Order.objects.filter(pk=int(order_id)).update(
                        status=Order.STATUS_PAID
                    )

        return data

