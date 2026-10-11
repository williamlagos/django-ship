#!/usr/bin/python
#
# This file is part of django-shipping project.
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

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from shipping.models import Cart, CartItem, Category, Order, OrderItem, Product
from shipping.providers.correios import CorreiosShippingService
from shipping.providers.fretefacil import FreteFacilShippingService


class FreteFacilShippingServiceTest(TestCase):
    def setUp(self):
        self.service = FreteFacilShippingService()

    def test_create_deliverable_valid(self):
        result = self.service.create_deliverable(
            "91350-180", "01310-100", "20", "5", "20", "1.0"
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result["sender"], "91350-180")
        self.assertEqual(result["receiver"], "01310-100")

    def test_create_deliverable_height_too_small(self):
        result = self.service.create_deliverable(
            "91350-180", "01310-100", "20", "1", "20", "1.0"
        )
        self.assertIsInstance(result, str)
        self.assertIn("mínimo", result)

    def test_create_deliverable_width_too_small(self):
        result = self.service.create_deliverable(
            "91350-180", "01310-100", "5", "5", "20", "1.0"
        )
        self.assertIsInstance(result, str)
        self.assertIn("mínimo", result)

    def test_create_deliverable_length_too_small(self):
        result = self.service.create_deliverable(
            "91350-180", "01310-100", "20", "5", "10", "1.0"
        )
        self.assertIsInstance(result, str)
        self.assertIn("mínimo", result)


class CorreiosShippingServiceTest(TestCase):
    def setUp(self):
        self.service = CorreiosShippingService()

    def test_validate_sets_minimum_height(self):
        self.service.altura = 0
        self.service._validate()
        self.assertGreaterEqual(self.service.altura, 2)

    def test_validate_sets_minimum_comprimento(self):
        self.service.comprimento = 0
        self.service._validate()
        self.assertGreaterEqual(self.service.comprimento, 16)

    def test_validate_sets_minimum_peso(self):
        self.service.peso = 0.0
        self.service._validate()
        self.assertGreaterEqual(self.service.peso, 0.3)

    def test_validate_largura_package_constraint(self):
        self.service.formato = "PACOTE"
        self.service.largura = 5
        self.service.comprimento = 20
        self.service._validate()
        self.assertGreaterEqual(self.service.largura, 11)

    def test_validate_rolo_format(self):
        self.service.formato = "ROLO"
        self.service.diametro = 0
        self.service.comprimento = 0
        self.service._validate()
        self.assertGreaterEqual(self.service.diametro, 5)
        self.assertGreaterEqual(self.service.comprimento, 18)


class CategoryModelTest(TestCase):
    def test_str(self):
        category = Category(name="Eletrônicos", slug="eletronicos")
        self.assertEqual(str(category), "Eletrônicos")


class ProductModelTest(TestCase):
    def setUp(self):
        self.category = Category.objects.create(name="Eletrônicos", slug="eletronicos")
        self.product = Product.objects.create(
            name="Notebook",
            slug="notebook",
            price=Decimal("2999.99"),
            sku="NB-001",
            category=self.category,
        )

    def test_str(self):
        self.assertEqual(str(self.product), "Notebook")

    def test_available_default(self):
        self.assertTrue(self.product.available)

    def test_category_relationship(self):
        self.assertEqual(self.product.category, self.category)
        self.assertIn(self.product, self.category.products.all())


class CartModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="pass")
        self.product = Product.objects.create(
            name="Mouse",
            slug="mouse",
            price=Decimal("99.90"),
            sku="MS-001",
        )
        self.cart = Cart.objects.create(user=self.user)

    def test_str(self):
        self.assertIn("Cart", str(self.cart))

    def test_empty_total(self):
        self.assertEqual(self.cart.total(), 0)

    def test_total_with_items(self):
        CartItem.objects.create(cart=self.cart, product=self.product, quantity=2)
        self.assertEqual(self.cart.total(), Decimal("199.80"))

    def test_cartitem_subtotal(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=3)
        self.assertEqual(item.subtotal(), Decimal("299.70"))

    def test_cartitem_str(self):
        item = CartItem.objects.create(cart=self.cart, product=self.product, quantity=1)
        self.assertIn("Mouse", str(item))


class OrderModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="buyer", password="pass")
        self.product = Product.objects.create(
            name="Teclado",
            slug="teclado",
            price=Decimal("199.00"),
            sku="KB-001",
        )
        self.order = Order.objects.create(
            user=self.user,
            total=Decimal("199.00"),
        )

    def test_default_status(self):
        self.assertEqual(self.order.status, Order.STATUS_PENDING)

    def test_str(self):
        self.assertIn("Order", str(self.order))
        self.assertIn("pending", str(self.order))

    def test_status_choices(self):
        statuses = [choice[0] for choice in Order.STATUS_CHOICES]
        self.assertIn(Order.STATUS_PENDING, statuses)
        self.assertIn(Order.STATUS_PAID, statuses)
        self.assertIn(Order.STATUS_SHIPPED, statuses)
        self.assertIn(Order.STATUS_DELIVERED, statuses)
        self.assertIn(Order.STATUS_CANCELLED, statuses)

    def test_orderitem_subtotal(self):
        item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=2,
            price=Decimal("199.00"),
        )
        self.assertEqual(item.subtotal(), Decimal("398.00"))

    def test_orderitem_str(self):
        item = OrderItem.objects.create(
            order=self.order,
            product=self.product,
            quantity=1,
            price=Decimal("199.00"),
        )
        self.assertIn("Teclado", str(item))


class ProductsViewTest(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        Product.objects.create(
            name="Produto A", slug="produto-a", price=Decimal("50.00"), sku="PA-001"
        )
        Product.objects.create(
            name="Produto B",
            slug="produto-b",
            price=Decimal("75.00"),
            sku="PB-001",
            available=False,
        )

    def test_lists_only_available_products(self):
        from shipping.views import ProductsView

        request = self.factory.get("/products/")
        response = ProductsView.as_view()(request)
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data["products"]), 1)
        self.assertEqual(data["products"][0]["name"], "Produto A")


class CartViewTest(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="Fone", slug="fone", price=Decimal("150.00"), sku="FN-001"
        )

    def test_add_item_to_cart(self):
        from django.test import Client

        client = Client()
        response = client.post(
            "/cart/",
            data=json.dumps({"product_id": self.product.pk, "quantity": 2}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data["quantity"], 2)

    def test_add_nonexistent_product_returns_404(self):
        from django.test import Client

        client = Client()
        response = client.post(
            "/cart/",
            data=json.dumps({"product_id": 9999, "quantity": 1}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)


class OrdersViewTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="orderer", password="pass")
        Order.objects.create(user=self.user, total=Decimal("100.00"))

    def test_requires_authentication(self):
        from django.test import Client

        client = Client()
        response = client.get("/orders/")
        self.assertEqual(response.status_code, 401)

    def test_returns_user_orders(self):
        from django.test import Client

        client = Client()
        client.login(username="orderer", password="pass")
        response = client.get("/orders/")
        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(len(data["orders"]), 1)


class StripeServiceTest(TestCase):
    def setUp(self):
        from shipping.payments import StripeService

        self.service = StripeService()
        self.user = User.objects.create_user(username="payer", password="password")
        self.product = Product.objects.create(
            name="Book", slug="book", price=Decimal("20.00"), sku="BK-1"
        )
        self.order = Order.objects.create(user=self.user, total=Decimal("40.00"))
        OrderItem.objects.create(
            order=self.order, product=self.product, quantity=2, price=Decimal("20.00")
        )

    def test_create_checkout_session(self):
        from unittest.mock import MagicMock, patch

        mock_session = MagicMock(
            id="cs_test_123", url="https://checkout.stripe.com/cs_test_123"
        )
        with patch("stripe.checkout.Session.create", return_value=mock_session):
            res = self.service.create_checkout_session(
                order=self.order,
                success_url="https://site.com/success",
                cancel_url="https://site.com/cancel",
            )
            self.assertEqual(res["session_id"], "cs_test_123")
            self.assertEqual(res["url"], "https://checkout.stripe.com/cs_test_123")

    def test_create_payment_intent(self):
        from unittest.mock import MagicMock, patch

        mock_intent = MagicMock(
            id="pi_test_123",
            client_secret="pi_secret_123",
            status="requires_payment_method",
        )
        with patch("stripe.PaymentIntent.create", return_value=mock_intent):
            res = self.service.create_payment_intent(
                amount=Decimal("50.00"), currency="usd"
            )
            self.assertEqual(res["id"], "pi_test_123")
            self.assertEqual(res["amount"], 5000)

    def test_handle_webhook_checkout_completed(self):
        from unittest.mock import patch

        event_payload = {
            "type": "checkout.session.completed",
            "data": {
                "object": {
                    "id": "cs_test_123",
                    "client_reference_id": str(self.order.pk),
                }
            },
        }
        with patch("stripe.Webhook.construct_event", return_value=event_payload):
            res = self.service.handle_webhook(b"{}", "sig_header")
            self.assertEqual(res["status"], "processed")
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, Order.STATUS_PAID)


class PayPalV2ServiceTest(TestCase):
    def setUp(self):
        from shipping.payments import PayPalV2Service

        self.service = PayPalV2Service()
        self.user = User.objects.create_user(
            username="paypal_user", password="password"
        )
        self.order = Order.objects.create(user=self.user, total=Decimal("35.00"))

    def test_create_order(self):
        from unittest.mock import MagicMock, patch

        mock_resp_auth = MagicMock(
            status_code=200, json=lambda: {"access_token": "mock_token"}
        )
        mock_resp_order = MagicMock(
            status_code=201,
            json=lambda: {"id": "ORDER-123", "status": "CREATED", "links": []},
        )
        with patch("requests.post", side_effect=[mock_resp_auth, mock_resp_order]):
            res = self.service.create_order(
                amount=Decimal("35.00"), custom_id=str(self.order.pk)
            )
            self.assertEqual(res["id"], "ORDER-123")

    def test_capture_order(self):
        from unittest.mock import MagicMock, patch

        mock_resp_auth = MagicMock(
            status_code=200, json=lambda: {"access_token": "mock_token"}
        )
        mock_resp_capture = MagicMock(
            status_code=200,
            json=lambda: {
                "id": "ORDER-123",
                "status": "COMPLETED",
                "purchase_units": [{"custom_id": str(self.order.pk)}],
            },
        )
        with patch("requests.post", side_effect=[mock_resp_auth, mock_resp_capture]):
            res = self.service.capture_order("ORDER-123")
            self.assertEqual(res["status"], "COMPLETED")
            self.order.refresh_from_db()
            self.assertEqual(self.order.status, Order.STATUS_PAID)


class SiweAndWeb3Test(TestCase):
    def setUp(self):
        from eth_account import Account

        self.account = Account.create()
        self.address = self.account.address

    def test_nonce_generation(self):
        from shipping.web3 import generate_siwe_nonce

        nonce = generate_siwe_nonce()
        self.assertEqual(len(nonce), 16)

    def test_siwe_signature_verification(self):
        from eth_account.messages import encode_defunct
        from shipping.web3 import verify_siwe_signature

        nonce = "abc123xyz890"
        message = (
            f"localhost wants you to sign in with your Ethereum account:\n"
            f"{self.address}\n\n"
            f"Sign in with Ethereum.\n\n"
            f"URI: http://localhost\n"
            f"Version: 1\n"
            f"Chain ID: 1\n"
            f"Nonce: {nonce}\n"
            f"Issued At: 2026-10-09T18:00:00Z\n"
        )
        signable_msg = encode_defunct(text=message)
        signed = self.account.sign_message(signable_msg)
        signature = signed.signature.hex()

        valid, recovered_addr, fields = verify_siwe_signature(
            message=message,
            signature=signature,
            expected_nonce=nonce,
        )
        self.assertTrue(valid)
        self.assertEqual(recovered_addr.lower(), self.address.lower())

    def test_crypto_payment_verification(self):
        from unittest.mock import MagicMock

        from shipping.web3 import CryptoPaymentService

        service = CryptoPaymentService()
        service.w3 = MagicMock()
        service.w3.eth.get_transaction.return_value = {
            "from": self.address,
            "to": "0x1111111111111111111111111111111111111111",
            "value": 1000000000000000000,
        }
        service.w3.eth.get_transaction_receipt.return_value = {
            "status": 1,
            "blockNumber": 12345,
        }

        valid, details = service.verify_transaction(
            tx_hash="0xabcd1234",
            expected_to="0x1111111111111111111111111111111111111111",
            expected_amount_wei=1000000000000000000,
        )
        self.assertTrue(valid)
        self.assertEqual(details["value_wei"], 1000000000000000000)


class CreatorMonetizationTest(TestCase):
    def setUp(self):
        from shipping.models import Subscription, SubscriptionTier, Tip

        self.creator = User.objects.create_user(username="creator_alice")
        self.fan = User.objects.create_user(username="fan_bob")
        self.tier = SubscriptionTier.objects.create(
            creator=self.creator,
            name="Gold Member",
            slug="gold-member",
            price=Decimal("10.00"),
            currency="USD",
            perks=["Discord VIP", "Early access"],
        )

    def test_subscription_active_check(self):
        from datetime import timedelta

        from django.utils.timezone import now
        from shipping.models import Subscription

        sub = Subscription.objects.create(
            subscriber=self.fan,
            tier=self.tier,
            status=Subscription.STATUS_ACTIVE,
            current_period_end=now() + timedelta(days=30),
        )
        self.assertTrue(sub.is_active_now())

        sub.status = Subscription.STATUS_EXPIRED
        self.assertFalse(sub.is_active_now())

    def test_tipping(self):
        from shipping.models import Tip

        tip = Tip.objects.create(
            sender=self.fan,
            recipient=self.creator,
            amount=Decimal("5.00"),
            currency="USD",
            payment_rail="stripe",
            transaction_reference="pi_tip_123",
            message="Great work!",
        )
        self.assertEqual(tip.recipient, self.creator)
        self.assertEqual(tip.amount, Decimal("5.00"))
