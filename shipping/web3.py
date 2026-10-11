"""
Web3 module for django-ship providing Sign-In with Ethereum (SIWE / EIP-4361),
ENS (Ethereum Name Service) resolution, and EVM crypto payment verification.
"""

import datetime
import logging
import re
import secrets
import string

from django.conf import settings
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

logger = logging.getLogger(__name__)


def generate_siwe_nonce(length: int = 16) -> str:
    """Generates a cryptographically secure EIP-4361 nonce."""
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))


def parse_siwe_message(message: str) -> dict[str, str]:
    """
    Parses an EIP-4361 formatted Sign-In with Ethereum message.
    """
    fields = {}
    lines = [line.strip() for line in message.strip().split("\n") if line.strip()]

    if lines:
        # First line: "{domain} wants you to sign in with your Ethereum account:"
        first_line = lines[0]
        if " wants you to sign in with your Ethereum account:" in first_line:
            fields["domain"] = first_line.split(
                " wants you to sign in with your Ethereum account:"
            )[0]

    # Look for address on line 2 (or find 0x... regex)
    addr_match = re.search(r"0x[a-fA-F0-9]{40}", message)
    if addr_match:
        fields["address"] = Web3.to_checksum_address(addr_match.group(0))

    # Standard prefix key-value lines
    patterns = {
        "uri": r"URI:\s*(\S+)",
        "version": r"Version:\s*(\S+)",
        "chain_id": r"Chain ID:\s*(\d+)",
        "nonce": r"Nonce:\s*([a-zA-Z0-9]+)",
        "issued_at": r"Issued At:\s*(\S+)",
        "expiration_time": r"Expiration Time:\s*(\S+)",
        "not_before": r"Not Before:\s*(\S+)",
    }

    for key, pat in patterns.items():
        m = re.search(pat, message)
        if m:
            fields[key] = m.group(1)

    return fields


def verify_siwe_signature(
    message: str,
    signature: str,
    expected_nonce: str | None = None,
) -> tuple[bool, str | None, dict | None]:
    """
    Verifies an EIP-4361 message signature and checks nonce / expiration.
    Returns (is_valid, address_or_error, parsed_fields).
    """
    fields = parse_siwe_message(message)
    expected_addr = fields.get("address")
    if not expected_addr:
        return False, "Could not extract Ethereum address from message", None

    if expected_nonce and fields.get("nonce") != expected_nonce:
        return (
            False,
            f"Nonce mismatch: expected {expected_nonce}, got {fields.get('nonce')}",
            None,
        )

    # Check expiration time if provided
    exp_time_str = fields.get("expiration_time")
    if exp_time_str:
        try:
            exp_time = datetime.datetime.fromisoformat(
                exp_time_str.replace("Z", "+00:00")
            )
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if now_utc > exp_time:
                return False, "SIWE message has expired", None
        except Exception:
            pass

    try:
        signable_msg = encode_defunct(text=message)
        recovered_address = Account.recover_message(signable_msg, signature=signature)
        recovered_checksum = Web3.to_checksum_address(recovered_address)

        if recovered_checksum.lower() == expected_addr.lower():
            return True, recovered_checksum, fields
        return (
            False,
            f"Signer address {recovered_checksum} does not match {expected_addr}",
            None,
        )
    except Exception as e:
        return False, f"Signature recovery failed: {str(e)}", None


class ENSService:
    """Handles Ethereum Name Service forward and reverse lookups."""

    def __init__(self, provider_url: str | None = None):
        self.provider_url = provider_url or getattr(
            settings, "WEB3_PROVIDER_URL", "https://eth.llamarpc.com"
        )
        self.w3 = Web3(Web3.HTTPProvider(self.provider_url))

    def resolve_name(self, ens_name: str) -> str | None:
        """Forward resolution: name.eth -> 0x... address."""
        if not ens_name.endswith(".eth"):
            return None
        try:
            address = self.w3.ens.address(ens_name)
            return Web3.to_checksum_address(address) if address else None
        except Exception as e:
            logger.warning(f"ENS forward resolution failed for {ens_name}: {e}")
            return None

    def reverse_resolve(self, address: str) -> str | None:
        """Reverse resolution: 0x... -> name.eth."""
        try:
            checksum = Web3.to_checksum_address(address)
            name = self.w3.ens.name(checksum)
            return name
        except Exception as e:
            logger.warning(f"ENS reverse resolution failed for {address}: {e}")
            return None


class CryptoPaymentService:
    """Verifies on-chain transactions for orders, tips, and bounties."""

    def __init__(self, provider_url: str | None = None):
        self.provider_url = provider_url or getattr(
            settings, "WEB3_PROVIDER_URL", "https://eth.llamarpc.com"
        )
        self.w3 = Web3(Web3.HTTPProvider(self.provider_url))

    def verify_transaction(
        self,
        tx_hash: str,
        expected_to: str,
        expected_amount_wei: int | None = None,
    ) -> tuple[bool, dict | str]:
        """
        Verifies an on-chain transaction receipt and confirms receipt status == 1.
        """
        try:
            tx = self.w3.eth.get_transaction(tx_hash)
            receipt = self.w3.eth.get_transaction_receipt(tx_hash)

            if receipt.get("status") != 1:
                return False, "Transaction reverted on-chain"

            tx_to = Web3.to_checksum_address(tx.get("to", ""))
            target_to = Web3.to_checksum_address(expected_to)

            if tx_to.lower() != target_to.lower():
                return False, f"Recipient mismatch: expected {target_to}, got {tx_to}"

            tx_value = tx.get("value", 0)
            if expected_amount_wei is not None and tx_value < expected_amount_wei:
                return (
                    False,
                    f"Amount too low: expected {expected_amount_wei} wei, got {tx_value} wei",
                )

            return True, {
                "tx_hash": tx_hash,
                "from": Web3.to_checksum_address(tx.get("from")),
                "to": tx_to,
                "value_wei": tx_value,
                "block_number": receipt.get("blockNumber"),
            }
        except Exception as e:
            return False, f"Failed to verify transaction on-chain: {str(e)}"
