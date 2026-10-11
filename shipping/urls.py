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

from django.urls import path

from .views import (
    CartView,
    CreatorTiersView,
    CreatorTipView,
    CryptoPaymentVerifyView,
    DeliveriesView,
    ENSResolveView,
    OrdersView,
    PayPalCaptureOrderView,
    PayPalCreateOrderView,
    ProductsView,
    SiweNonceView,
    SiweVerifyView,
    StripeCheckoutView,
    StripeWebhookView,
    SubscriptionsView,
)

urlpatterns = [
    # Marketplace Core
    path("", DeliveriesView.as_view(), name="deliveries"),
    path("products/", ProductsView.as_view(), name="products"),
    path("cart/", CartView.as_view(), name="cart"),
    path("orders/", OrdersView.as_view(), name="orders"),
    # Web2 Payments (Stripe & PayPal)
    path(
        "payments/stripe/checkout/",
        StripeCheckoutView.as_view(),
        name="stripe-checkout",
    ),
    path(
        "payments/stripe/webhook/",
        StripeWebhookView.as_view(),
        name="stripe-webhook",
    ),
    path(
        "payments/paypal/create-order/",
        PayPalCreateOrderView.as_view(),
        name="paypal-create-order",
    ),
    path(
        "payments/paypal/capture-order/",
        PayPalCaptureOrderView.as_view(),
        name="paypal-capture-order",
    ),
    # Web3 & SIWE
    path("web3/siwe/nonce/", SiweNonceView.as_view(), name="siwe-nonce"),
    path("web3/siwe/verify/", SiweVerifyView.as_view(), name="siwe-verify"),
    path("web3/ens/resolve/", ENSResolveView.as_view(), name="ens-resolve"),
    path(
        "web3/payments/verify/", CryptoPaymentVerifyView.as_view(), name="crypto-verify"
    ),
    # Creator Monetization
    path(
        "creators/<int:user_id>/tiers/",
        CreatorTiersView.as_view(),
        name="creator-tiers",
    ),
    path("creators/<int:user_id>/tip/", CreatorTipView.as_view(), name="creator-tip"),
    path("subscriptions/", SubscriptionsView.as_view(), name="subscriptions"),
]
