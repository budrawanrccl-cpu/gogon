"""Loads a Solana signing keypair from the configured private key string.

Accepts the two formats wallets commonly export:
  - base58 (Phantom/Solflare "export private key")
  - a JSON array of 64 ints (Solana CLI keypair file contents, as a string)
"""
from __future__ import annotations

import json

import base58
from solders.keypair import Keypair


def load_keypair(private_key: str) -> Keypair:
    key = private_key.strip()
    if key.startswith("["):
        raw = bytes(json.loads(key))
        return Keypair.from_bytes(raw)
    raw = base58.b58decode(key)
    return Keypair.from_bytes(raw)
