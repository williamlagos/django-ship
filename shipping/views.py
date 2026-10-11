#!/usr/bin/python
#
# This file is part of django-ship project.
#
# Copyright (C) 2011-2020 William Oliveira de Lagos <william.lagos@icloud.com>
#
# Shipping is free software: you can redistribute it and/or modify
# it under the terms of the Lesser GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# Shipping is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with Shipping. If not, see <http://www.gnu.org/licenses/>.
#

import json
from decimal import Decimal

from django.contrib.auth import login
from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils.decorators import method_decorator
from django.utils.timezone import now
from django.views import View
from django.views.decorators.csrf import csrf_exempt

from .models import (
    Cart,
    CartItem,
    CryptoPayment,
    Order,
    OrderItem,
    Product,
    Subscription,
    SubscriptionTier,
    Tip,
    WalletNonce,
)
from .payments import PayPalV2Service, StripeService
from .web3 import (
    CryptoPaymentService,
    ENSService,
    generate_siwe_nonce,
    verify_siwe_signature,
)


class DeliveriesView(View):
    def get(self, request):
        return JsonResponse({"deliveries": "success"})


class ProductsView(View):
    def get(self, request):
        products = list(
            Product.objects.filter(available=True).values(
                "id", "name", "slug", "description", "price", "sku", "creator_id"
            )
        )
        return JsonResponse({"products": products})


class CartView(View):
    def get(self, request):
        cart = self._get_cart(request)
        items = [
            {
                "product_id": item.product_id,
                "product_name": item.product.name,
                "quantity": item.quantity,
                "subtotal": str(item.subtotal()),
            }
            for item in cart.items.select_related("product").all()
        ]
        return JsonResponse(
            {"cart_id": cart.pk, "items": items, "total": str(cart.total())}
        )

    def post(self, request):
        try:
            data = json.loads(request.body)
            product_id = data["product_id"]
            quantity = int(data.get("quantity", 1))
        except (KeyError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "Invalid request"}, status=400)

        try:
            product = Product.objects.get(pk=product_id, available=True)
        except Product.DoesNotExist:
            return JsonResponse({"error": "Product not found"}, status=404)

        cart = self._get_cart(request)
        item, created = CartItem.objects.get_or_create(cart=cart, product=product)
        if not created:
            item.quantity += quantity
        else:
            item.quantity = quantity
        item.save()
        return JsonResponse(
            {"cart_id": cart.pk, "product_id": product.pk, "quantity": item.quantity}
        )

    def _get_cart(self, request):
        user = request.user if request.user.is_authenticated else None
        if user:
            cart, _ = Cart.objects.get_or_create(
                user=user, defaults={"session_key": request.session.session_key or ""}
            )
        else:
            if not request.session.session_key:
                request.session.create()
            cart, _ = Cart.objects.get_or_create(
                session_key=request.session.session_key, user=None
            )
        return cart


class OrdersView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)
        orders = list(
            Order.objects.filter(user=request.user).values(
                "id", "status", "total", "created"
            )
        )
        return JsonResponse({"orders": orders})

    def post(self, request):
        """Creates an order from the user's current cart."""
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        cart = Cart.objects.filter(user=request.user).first()
        if not cart or not cart.items.exists():
            return JsonResponse({"error": "Cart is empty"}, status=400)

        order = Order.objects.create(
            user=request.user,
            total=cart.total(),
            status=Order.STATUS_PENDING,
        )
        for item in cart.items.all():
            OrderItem.objects.create(
                order=order,
                product=item.product,
                quantity=item.quantity,
                price=item.product.price,
            )

        cart.items.all().delete()
        return JsonResponse(
            {"order_id": order.pk, "total": str(order.total), "status": order.status},
            status=201,
        )


# ==========================================
# Web2 Payments Views (Stripe & PayPal v2)
# ==========================================


@method_decorator(csrf_exempt, name="dispatch")
class StripeCheckoutView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            order_id = data.get("order_id")
            success_url = data.get(
                "success_url", "http://localhost:8000/shop/checkout/success/"
            )
            cancel_url = data.get(
                "cancel_url", "http://localhost:8000/shop/checkout/cancel/"
            )
        except Exception:
            return JsonResponse({"error": "Invalid request body"}, status=400)

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return JsonResponse({"error": "Order not found"}, status=404)

        service = StripeService()
        try:
            session = service.create_checkout_session(
                order=order,
                success_url=success_url,
                cancel_url=cancel_url,
                customer_email=(
                    request.user.email if request.user.is_authenticated else None
                ),
            )
            return JsonResponse(session)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class StripeWebhookView(View):
    def post(self, request):
        sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")
        if not sig_header:
            return JsonResponse(
                {"error": "Missing Stripe-Signature header"}, status=400
            )

        service = StripeService()
        try:
            result = service.handle_webhook(request.body, sig_header)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class PayPalCreateOrderView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            order_id = data.get("order_id")
        except Exception:
            return JsonResponse({"error": "Invalid request body"}, status=400)

        try:
            order = Order.objects.get(pk=order_id)
        except Order.DoesNotExist:
            return JsonResponse({"error": "Order not found"}, status=404)

        service = PayPalV2Service()
        try:
            result = service.create_order(
                amount=order.total,
                currency="USD",
                custom_id=str(order.pk),
            )
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


@method_decorator(csrf_exempt, name="dispatch")
class PayPalCaptureOrderView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            paypal_order_id = data.get("paypal_order_id")
        except Exception:
            return JsonResponse({"error": "Invalid request body"}, status=400)

        if not paypal_order_id:
            return JsonResponse({"error": "paypal_order_id is required"}, status=400)

        service = PayPalV2Service()
        try:
            result = service.capture_order(paypal_order_id)
            return JsonResponse(result)
        except Exception as e:
            return JsonResponse({"error": str(e)}, status=500)


# ==========================================
# Web3 & SIWE Views
# ==========================================


class SiweNonceView(View):
    def get(self, request):
        address = request.GET.get("address")
        if not address:
            return JsonResponse({"error": "Address is required"}, status=400)

        nonce = generate_siwe_nonce()
        WalletNonce.objects.update_or_create(
            address=address.lower(),
            defaults={"nonce": nonce},
        )
        return JsonResponse({"address": address, "nonce": nonce})


@method_decorator(csrf_exempt, name="dispatch")
class SiweVerifyView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            message = data["message"]
            signature = data["signature"]
        except Exception:
            return JsonResponse({"error": "Invalid request"}, status=400)

        # Look up expected nonce
        from .web3 import parse_siwe_message

        fields = parse_siwe_message(message)
        addr = fields.get("address")
        expected_nonce = None
        if addr:
            nonce_record = WalletNonce.objects.filter(address=addr.lower()).first()
            if nonce_record:
                expected_nonce = nonce_record.nonce

        valid, address_or_err, _ = verify_siwe_signature(
            message=message,
            signature=signature,
            expected_nonce=expected_nonce,
        )

        if not valid:
            return JsonResponse({"error": address_or_err}, status=401)

        # Clear used nonce
        if addr:
            WalletNonce.objects.filter(address=addr.lower()).delete()

        # Get or create user for this address
        username = f"eth_{address_or_err.lower()[:10]}"
        user, _ = User.objects.get_or_create(
            username=username,
            defaults={"first_name": "Web3", "last_name": address_or_err[:8]},
        )
        login(request, user)

        return JsonResponse(
            {
                "status": "authenticated",
                "address": address_or_err,
                "user_id": user.pk,
                "username": user.username,
            }
        )


class ENSResolveView(View):
    def get(self, request):
        name = request.GET.get("name")
        address = request.GET.get("address")
        service = ENSService()

        if name:
            resolved_addr = service.resolve_name(name)
            if not resolved_addr:
                return JsonResponse({"error": "Name could not be resolved"}, status=404)
            return JsonResponse({"name": name, "address": resolved_addr})

        if address:
            resolved_name = service.reverse_resolve(address)
            if not resolved_name:
                return JsonResponse(
                    {"error": "Address could not be reverse-resolved"}, status=404
                )
            return JsonResponse({"address": address, "name": resolved_name})

        return JsonResponse({"error": "name or address parameter required"}, status=400)


@method_decorator(csrf_exempt, name="dispatch")
class CryptoPaymentVerifyView(View):
    def post(self, request):
        try:
            data = json.loads(request.body)
            tx_hash = data["tx_hash"]
            expected_to = data["to_address"]
            expected_amount_wei = int(data.get("amount_wei", 0))
            order_id = data.get("order_id")
        except Exception:
            return JsonResponse({"error": "Invalid request body"}, status=400)

        service = CryptoPaymentService()
        valid, details_or_err = service.verify_transaction(
            tx_hash=tx_hash,
            expected_to=expected_to,
            expected_amount_wei=expected_amount_wei,
        )

        if not valid:
            return JsonResponse({"error": str(details_or_err)}, status=400)

        order_obj = Order.objects.filter(pk=order_id).first() if order_id else None
        payment, _ = CryptoPayment.objects.update_or_create(
            tx_hash=tx_hash,
            defaults={
                "order": order_obj,
                "from_address": details_or_err["from"],
                "to_address": details_or_err["to"],
                "amount_wei": details_or_err["value_wei"],
                "status": CryptoPayment.STATUS_CONFIRMED,
            },
        )
        if order_obj:
            order_obj.status = Order.STATUS_PAID
            order_obj.save(update_fields=["status"])

        return JsonResponse(
            {
                "status": "confirmed",
                "tx_hash": tx_hash,
                "from": payment.from_address,
                "to": payment.to_address,
            }
        )


# ==========================================
# Creator Monetization & Tiers Views
# ==========================================


@method_decorator(csrf_exempt, name="dispatch")
class CreatorTiersView(View):
    def get(self, request, user_id):
        tiers = list(
            SubscriptionTier.objects.filter(creator_id=user_id, is_active=True).values(
                "id",
                "name",
                "slug",
                "description",
                "price",
                "currency",
                "billing_frequency",
                "perks",
            )
        )
        return JsonResponse({"tiers": tiers})

    def post(self, request, user_id):
        if not request.user.is_authenticated or request.user.pk != user_id:
            return JsonResponse({"error": "Permission denied"}, status=403)

        try:
            data = json.loads(request.body)
            name = data["name"]
            slug = data.get("slug", name.lower().replace(" ", "-"))
            price = Decimal(str(data["price"]))
            currency = data.get("currency", "USD")
            billing_frequency = data.get("billing_frequency", "monthly")
            perks = data.get("perks", [])
        except Exception:
            return JsonResponse({"error": "Invalid tier data"}, status=400)

        tier, created = SubscriptionTier.objects.get_or_create(
            creator=request.user,
            slug=slug,
            defaults={
                "name": name,
                "price": price,
                "currency": currency,
                "billing_frequency": billing_frequency,
                "perks": perks,
            },
        )
        return JsonResponse(
            {"id": tier.pk, "name": tier.name, "slug": tier.slug, "created": created},
            status=201 if created else 200,
        )


@method_decorator(csrf_exempt, name="dispatch")
class CreatorTipView(View):
    def post(self, request, user_id):
        try:
            recipient = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return JsonResponse({"error": "Recipient creator not found"}, status=404)

        try:
            data = json.loads(request.body)
            amount = Decimal(str(data["amount"]))
            currency = data.get("currency", "USD")
            payment_rail = data.get("payment_rail", "stripe")
            message = data.get("message", "")
            tx_ref = data.get(
                "transaction_reference",
                f"tip_{payment_rail}_{user_id}_{now().timestamp()}",
            )
        except Exception:
            return JsonResponse({"error": "Invalid tip data"}, status=400)

        sender = request.user if request.user.is_authenticated else None
        tip = Tip.objects.create(
            sender=sender,
            recipient=recipient,
            amount=amount,
            currency=currency,
            payment_rail=payment_rail,
            transaction_reference=tx_ref,
            message=message,
        )

        return JsonResponse(
            {
                "id": tip.pk,
                "amount": str(tip.amount),
                "currency": tip.currency,
                "recipient": recipient.username,
                "payment_rail": tip.payment_rail,
                "transaction_reference": tip.transaction_reference,
            },
            status=201,
        )


class SubscriptionsView(View):
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({"error": "Authentication required"}, status=401)

        subs = []
        for s in Subscription.objects.filter(subscriber=request.user).select_related(
            "tier__creator"
        ):
            subs.append(
                {
                    "subscription_id": s.pk,
                    "tier_name": s.tier.name,
                    "creator_username": s.tier.creator.username,
                    "price": str(s.tier.price),
                    "currency": s.tier.currency,
                    "status": s.status,
                    "is_active": s.is_active_now(),
                    "payment_rail": s.payment_rail,
                }
            )
        return JsonResponse({"subscriptions": subs})
