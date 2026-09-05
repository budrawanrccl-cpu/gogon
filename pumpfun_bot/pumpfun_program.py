"""pump.fun on-chain program interface: constants, PDA derivation, the
constant-product bonding-curve math, and instruction builders for Buy/Sell.

Account layout, seeds, and the instruction discriminator scheme below are
pump.fun's public on-chain interface (this is the same program every pump.fun
trade on mainnet already calls — nothing here is private or reverse-engineered
from anything besides publicly readable account data). Anchor programs derive
each instruction's 8-byte discriminator as
``sha256(f"global:{instruction_name}")[:8]``; this module computes it that way
rather than hardcoding magic bytes, so it stays correct as long as pump.fun's
instruction names don't change.

Nothing in this file has been exercised against mainnet from this sandboxed,
network-restricted dev environment. `find_program_address` (PDA derivation)
and the discriminator scheme were verified against pump.fun's known, publicly
documented account addresses. Before trusting this with real funds: run in
paper mode, then test live with a trivial amount first.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass

from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey

PUMPFUN_PROGRAM_ID = Pubkey.from_string("6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P")
TOKEN_PROGRAM_ID = Pubkey.from_string("TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA")
ASSOCIATED_TOKEN_PROGRAM_ID = Pubkey.from_string("ATokenGPvbdGVxr1b2hvZbsiqW5xWH25efTNsLJA8knL")
SYSTEM_PROGRAM_ID = Pubkey.from_string("11111111111111111111111111111111")
SYSVAR_RENT_ID = Pubkey.from_string("SysvarRent111111111111111111111111111111111")

LAMPORTS_PER_SOL = 1_000_000_000
TOKEN_DECIMALS = 6  # all pump.fun-launched tokens use 6 decimals


def instruction_discriminator(name: str) -> bytes:
    """Anchor's global-namespace 8-byte instruction discriminator."""
    return hashlib.sha256(f"global:{name}".encode("utf-8")).digest()[:8]


# -- PDA derivation ----------------------------------------------------------
def find_global_pda() -> Pubkey:
    pda, _bump = Pubkey.find_program_address([b"global"], PUMPFUN_PROGRAM_ID)
    return pda


def find_event_authority_pda() -> Pubkey:
    pda, _bump = Pubkey.find_program_address([b"__event_authority"], PUMPFUN_PROGRAM_ID)
    return pda


def find_bonding_curve_pda(mint: Pubkey) -> Pubkey:
    pda, _bump = Pubkey.find_program_address([b"bonding-curve", bytes(mint)], PUMPFUN_PROGRAM_ID)
    return pda


def find_associated_token_address(owner: Pubkey, mint: Pubkey) -> Pubkey:
    pda, _bump = Pubkey.find_program_address(
        [bytes(owner), bytes(TOKEN_PROGRAM_ID), bytes(mint)], ASSOCIATED_TOKEN_PROGRAM_ID
    )
    return pda


def find_associated_bonding_curve(bonding_curve: Pubkey, mint: Pubkey) -> Pubkey:
    return find_associated_token_address(bonding_curve, mint)


# -- account parsing -----------------------------------------------------
@dataclass
class GlobalAccount:
    initialized: bool
    authority: Pubkey
    fee_recipient: Pubkey
    initial_virtual_token_reserves: int
    initial_virtual_sol_reserves: int
    initial_real_token_reserves: int
    token_total_supply: int
    fee_basis_points: int


@dataclass
class BondingCurveAccount:
    virtual_token_reserves: int
    virtual_sol_reserves: int
    real_token_reserves: int
    real_sol_reserves: int
    token_total_supply: int
    complete: bool


def parse_global_account(data: bytes) -> GlobalAccount:
    # 8-byte anchor discriminator, then: bool, 3x pubkey (32B each: authority,
    # fee_recipient... note field order below matches pump.fun's published IDL),
    # then 4x u64, then u64 fee_basis_points.
    off = 8
    initialized = data[off] != 0
    off += 1
    authority = Pubkey.from_bytes(data[off : off + 32])
    off += 32
    fee_recipient = Pubkey.from_bytes(data[off : off + 32])
    off += 32
    initial_virtual_token_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    initial_virtual_sol_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    initial_real_token_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    token_total_supply = struct.unpack_from("<Q", data, off)[0]
    off += 8
    fee_basis_points = struct.unpack_from("<Q", data, off)[0]
    return GlobalAccount(
        initialized=initialized,
        authority=authority,
        fee_recipient=fee_recipient,
        initial_virtual_token_reserves=initial_virtual_token_reserves,
        initial_virtual_sol_reserves=initial_virtual_sol_reserves,
        initial_real_token_reserves=initial_real_token_reserves,
        token_total_supply=token_total_supply,
        fee_basis_points=fee_basis_points,
    )


def parse_bonding_curve_account(data: bytes) -> BondingCurveAccount:
    off = 8  # anchor discriminator
    virtual_token_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    virtual_sol_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    real_token_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    real_sol_reserves = struct.unpack_from("<Q", data, off)[0]
    off += 8
    token_total_supply = struct.unpack_from("<Q", data, off)[0]
    off += 8
    complete = data[off] != 0
    return BondingCurveAccount(
        virtual_token_reserves=virtual_token_reserves,
        virtual_sol_reserves=virtual_sol_reserves,
        real_token_reserves=real_token_reserves,
        real_sol_reserves=real_sol_reserves,
        token_total_supply=token_total_supply,
        complete=complete,
    )


# -- bonding-curve math (constant product, x*y=k) ----------------------------
def compute_buy_tokens_out(virtual_sol_reserves: int, virtual_token_reserves: int, sol_in_lamports: int) -> int:
    """Tokens (raw, 6-decimal units) received for `sol_in_lamports` lamports."""
    if sol_in_lamports <= 0:
        return 0
    k = virtual_sol_reserves * virtual_token_reserves
    new_virtual_sol = virtual_sol_reserves + sol_in_lamports
    new_virtual_tokens = k // new_virtual_sol
    tokens_out = virtual_token_reserves - new_virtual_tokens
    return max(0, tokens_out)


def compute_sell_sol_out(virtual_sol_reserves: int, virtual_token_reserves: int, token_in_raw: int) -> int:
    """Lamports received for selling `token_in_raw` raw token units."""
    if token_in_raw <= 0:
        return 0
    k = virtual_sol_reserves * virtual_token_reserves
    new_virtual_tokens = virtual_token_reserves + token_in_raw
    new_virtual_sol = k // new_virtual_tokens
    sol_out = virtual_sol_reserves - new_virtual_sol
    return max(0, sol_out)


def apply_slippage(amount: int, slippage_bps: int, worse_direction: bool) -> int:
    """Widen (buy's max cost) or narrow (sell's min output) `amount` by slippage_bps."""
    factor = slippage_bps / 10_000
    if worse_direction:
        return int(amount * (1 + factor))
    return int(amount * (1 - factor))


# -- instruction builders -----------------------------------------------
def build_create_ata_idempotent_instruction(payer: Pubkey, owner: Pubkey, mint: Pubkey) -> Instruction:
    """SPL 'CreateIdempotent' associated-token-account instruction (no-op if it exists)."""
    ata = find_associated_token_address(owner, mint)
    accounts = [
        AccountMeta(payer, is_signer=True, is_writable=True),
        AccountMeta(ata, is_signer=False, is_writable=True),
        AccountMeta(owner, is_signer=False, is_writable=False),
        AccountMeta(mint, is_signer=False, is_writable=False),
        AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    return Instruction(ASSOCIATED_TOKEN_PROGRAM_ID, bytes([1]), accounts)  # 1 = CreateIdempotent


def build_buy_instruction(
    *, buyer: Pubkey, mint: Pubkey, fee_recipient: Pubkey, token_amount_raw: int, max_sol_cost_lamports: int
) -> Instruction:
    bonding_curve = find_bonding_curve_pda(mint)
    associated_bonding_curve = find_associated_bonding_curve(bonding_curve, mint)
    associated_user = find_associated_token_address(buyer, mint)

    accounts = [
        AccountMeta(find_global_pda(), is_signer=False, is_writable=False),
        AccountMeta(fee_recipient, is_signer=False, is_writable=True),
        AccountMeta(mint, is_signer=False, is_writable=False),
        AccountMeta(bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(associated_bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(associated_user, is_signer=False, is_writable=True),
        AccountMeta(buyer, is_signer=True, is_writable=True),
        AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(SYSVAR_RENT_ID, is_signer=False, is_writable=False),
        AccountMeta(find_event_authority_pda(), is_signer=False, is_writable=False),
        AccountMeta(PUMPFUN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    data = instruction_discriminator("buy") + struct.pack("<QQ", token_amount_raw, max_sol_cost_lamports)
    return Instruction(PUMPFUN_PROGRAM_ID, data, accounts)


def build_sell_instruction(
    *, seller: Pubkey, mint: Pubkey, fee_recipient: Pubkey, token_amount_raw: int, min_sol_output_lamports: int
) -> Instruction:
    bonding_curve = find_bonding_curve_pda(mint)
    associated_bonding_curve = find_associated_bonding_curve(bonding_curve, mint)
    associated_user = find_associated_token_address(seller, mint)

    accounts = [
        AccountMeta(find_global_pda(), is_signer=False, is_writable=False),
        AccountMeta(fee_recipient, is_signer=False, is_writable=True),
        AccountMeta(mint, is_signer=False, is_writable=False),
        AccountMeta(bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(associated_bonding_curve, is_signer=False, is_writable=True),
        AccountMeta(associated_user, is_signer=False, is_writable=True),
        AccountMeta(seller, is_signer=True, is_writable=True),
        AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(ASSOCIATED_TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(TOKEN_PROGRAM_ID, is_signer=False, is_writable=False),
        AccountMeta(find_event_authority_pda(), is_signer=False, is_writable=False),
        AccountMeta(PUMPFUN_PROGRAM_ID, is_signer=False, is_writable=False),
    ]
    data = instruction_discriminator("sell") + struct.pack("<QQ", token_amount_raw, min_sol_output_lamports)
    return Instruction(PUMPFUN_PROGRAM_ID, data, accounts)
