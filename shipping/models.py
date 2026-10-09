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

from django.contrib.auth.models import User
from django.db import models
from django.utils.timezone import now

from .strings import (
    ORDER_STATUS_CANCELLED,
    ORDER_STATUS_DELIVERED,
    ORDER_STATUS_PAID,
    ORDER_STATUS_PENDING,
    ORDER_STATUS_SHIPPED,
)


class DeliverableProperty(models.Model):
    class Meta:
        verbose_name_plural = "Deliverable Properties"

    sku = models.CharField(default="", max_length=20)
    height = models.IntegerField(default=16)
    length = models.IntegerField(default=16)
    width = models.IntegerField(default=16)
    weight = models.FloatField(default=0.1)


class Deliverable(models.Model):
    name = models.CharField(default="((", max_length=50)
    user = models.ForeignKey(User, related_name="+", on_delete=models.CASCADE)
    product = models.IntegerField(default=1)
    mail_code = models.CharField(default="", max_length=100)
    height = models.IntegerField(default=1)
    length = models.IntegerField(default=1)
    width = models.IntegerField(default=1)
    weight = models.IntegerField(default=10)
    value = models.FloatField(default=0.0)
    date = models.DateTimeField(default=now)

    def token(self):
        return self.name[:2]

    def name_trimmed(self):
        return self.name.split(";")[0][1:]

    def month(self):
        return self.date.strftime("%b")


class Amount(models.Model):
    coins = models.IntegerField(default=0)


class Category(models.Model):
    class Meta:
        verbose_name_plural = "Categories"

    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class Product(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    sku = models.CharField(max_length=20, unique=True)
    creator = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="created_products",
        on_delete=models.SET_NULL,
    )
    category = models.ForeignKey(
        Category,
        null=True,
        blank=True,
        related_name="products",
        on_delete=models.SET_NULL,
    )
    available = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class Cart(models.Model):
    user = models.ForeignKey(
        User,
        null=True,
        blank=True,
        related_name="carts",
        on_delete=models.SET_NULL,
    )
    session_key = models.CharField(max_length=40, blank=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def total(self):
        return sum(item.subtotal() for item in self.items.all())

    def __str__(self):
        return f"Cart {self.pk}"


class CartItem(models.Model):
    cart = models.ForeignKey(Cart, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)

    def subtotal(self):
        return self.product.price * self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"


class Order(models.Model):
    STATUS_PENDING = "pending"
    STATUS_PAID = "paid"
    STATUS_SHIPPED = "shipped"
    STATUS_DELIVERED = "delivered"
    STATUS_CANCELLED = "cancelled"

    STATUS_CHOICES = [
        (STATUS_PENDING, ORDER_STATUS_PENDING),
        (STATUS_PAID, ORDER_STATUS_PAID),
        (STATUS_SHIPPED, ORDER_STATUS_SHIPPED),
        (STATUS_DELIVERED, ORDER_STATUS_DELIVERED),
        (STATUS_CANCELLED, ORDER_STATUS_CANCELLED),
    ]

    user = models.ForeignKey(User, related_name="orders", on_delete=models.CASCADE)
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Order {self.pk} ({self.status})"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    price = models.DecimalField(max_digits=10, decimal_places=2)

    def subtotal(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.quantity}x {self.product.name}"


class SubscriptionTier(models.Model):
    """Creator membership / subscription tier."""

    FREQUENCY_MONTHLY = "monthly"
    FREQUENCY_YEARLY = "yearly"
    FREQUENCY_CHOICES = [
        (FREQUENCY_MONTHLY, "Monthly"),
        (FREQUENCY_YEARLY, "Yearly"),
    ]

    creator = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="subscription_tiers"
    )
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120)
    description = models.TextField(blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=10, default="USD")
    billing_frequency = models.CharField(
        max_length=20, choices=FREQUENCY_CHOICES, default=FREQUENCY_MONTHLY
    )
    perks = models.JSONField(default=list, blank=True)
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("creator", "slug")

    def __str__(self):
        return f"{self.creator.username} - {self.name} ({self.price} {self.currency}/{self.billing_frequency})"


class Subscription(models.Model):
    """Subscriber membership to a creator tier."""

    STATUS_ACTIVE = "active"
    STATUS_CANCELLED = "cancelled"
    STATUS_EXPIRED = "expired"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_EXPIRED, "Expired"),
    ]

    RAIL_STRIPE = "stripe"
    RAIL_PAYPAL = "paypal"
    RAIL_CRYPTO = "crypto"
    RAIL_CHOICES = [
        (RAIL_STRIPE, "Stripe"),
        (RAIL_PAYPAL, "PayPal"),
        (RAIL_CRYPTO, "Crypto"),
    ]

    subscriber = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="subscriptions"
    )
    tier = models.ForeignKey(
        SubscriptionTier, on_delete=models.CASCADE, related_name="subscribers"
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE
    )
    payment_rail = models.CharField(
        max_length=20, choices=RAIL_CHOICES, default=RAIL_STRIPE
    )
    external_id = models.CharField(max_length=255, blank=True, default="")
    current_period_end = models.DateTimeField(null=True, blank=True)
    created = models.DateTimeField(auto_now_add=True)

    def is_active_now(self) -> bool:
        """Returns True if the subscription is active and not expired."""
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.current_period_end and self.current_period_end < now():
            return False
        return True

    def __str__(self):
        return (
            f"{self.subscriber.username} subscribed to {self.tier.name} ({self.status})"
        )


class Tip(models.Model):
    """Direct tips / creator donations via Web2 (Stripe/PayPal) or Web3 (crypto)."""

    sender = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_tips",
    )
    recipient = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="received_tips"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=4)
    currency = models.CharField(max_length=10, default="USD")
    payment_rail = models.CharField(max_length=20, default="stripe")
    transaction_reference = models.CharField(max_length=255, unique=True)
    message = models.TextField(blank=True, default="")
    created = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        sender_name = self.sender.username if self.sender else "Anonymous"
        return f"Tip: {sender_name} -> {self.recipient.username} ({self.amount} {self.currency})"


class CryptoPayment(models.Model):
    """Tracks on-chain EVM crypto payments for orders, tips, or bounties."""

    STATUS_PENDING = "pending"
    STATUS_CONFIRMED = "confirmed"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_FAILED, "Failed"),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="crypto_payments",
    )
    tx_hash = models.CharField(max_length=100, unique=True)
    chain_id = models.IntegerField(default=1)  # 1 = Ethereum, 137 = Polygon, etc.
    from_address = models.CharField(max_length=42)
    to_address = models.CharField(max_length=42)
    amount_wei = models.DecimalField(max_digits=40, decimal_places=0, default=0)
    token_address = models.CharField(max_length=42, blank=True, default="")
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING
    )
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"CryptoPayment {self.tx_hash[:10]}... ({self.status})"


class WalletNonce(models.Model):
    """Nonce store for Sign-In with Ethereum (SIWE)."""

    address = models.CharField(max_length=42, unique=True)
    nonce = models.CharField(max_length=64)
    created = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Nonce for {self.address}: {self.nonce}"
