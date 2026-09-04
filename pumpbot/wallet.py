"""Local Solana keypair handling.

Signing always happens on this machine. The private key is loaded from an
env var into memory, used to sign transactions locally via solders, and is
never sent to PumpPortal, any RPC, or logged anywhere. Paper trading never
touches this module's signing path at all.
"""
from __future__ import annotations

import logging

from pumpbot.config import WalletConfig

logger = logging.getLogger("pumpbot.wallet")


def load_keypair(cfg: WalletConfig):
    """Return a solders.keypair.Keypair for live trading.

    Only called when live_trading=True (config.load_settings already
    guarantees SOLANA_PRIVATE_KEY is set in that case). Accepts either a
    base58-encoded secret key string (the format wallets like Phantom
    export) or a JSON array of ints (the format the Solana CLI writes).
    """
    from solders.keypair import Keypair

    raw = (cfg.private_key or "").strip()
    if not raw:
        raise ValueError("SOLANA_PRIVATE_KEY is empty; cannot build a signing wallet.")

    try:
        if raw.startswith("["):
            import json

            key_bytes = bytes(json.loads(raw))
            keypair = Keypair.from_bytes(key_bytes)
        else:
            keypair = Keypair.from_base58_string(raw)
    except Exception as e:
        raise ValueError(
            "Could not parse SOLANA_PRIVATE_KEY. Expected a base58 secret key "
            "(Phantom export) or a JSON int array (solana-keygen format)."
        ) from e

    logger.info("Loaded signing wallet: %s", keypair.pubkey())
    return keypair
