from solders.pubkey import Pubkey

from pumpfun_bot.pumpfun_program import (
    compute_buy_tokens_out,
    compute_sell_sol_out,
    find_bonding_curve_pda,
    find_global_pda,
    instruction_discriminator,
)

# pump.fun's known, publicly documented mainnet addresses — used here purely
# to sanity-check that our seed derivation matches the real deployed program,
# not fetched from the network.
KNOWN_GLOBAL_PDA = "4wTV1YmiEkRvAtNtsSGPtUrqRYQMe5SKy2uB4Jjaxnjf"
KNOWN_BUY_DISCRIMINATOR = bytes([102, 6, 61, 18, 1, 218, 235, 234])
KNOWN_SELL_DISCRIMINATOR = bytes([51, 230, 133, 164, 1, 127, 131, 173])


def test_global_pda_matches_known_mainnet_address():
    assert str(find_global_pda()) == KNOWN_GLOBAL_PDA


def test_instruction_discriminators_match_known_values():
    assert instruction_discriminator("buy") == KNOWN_BUY_DISCRIMINATOR
    assert instruction_discriminator("sell") == KNOWN_SELL_DISCRIMINATOR


def test_bonding_curve_pda_is_deterministic_and_mint_specific():
    mint_a = Pubkey.new_unique()
    mint_b = Pubkey.new_unique()
    assert find_bonding_curve_pda(mint_a) == find_bonding_curve_pda(mint_a)
    assert find_bonding_curve_pda(mint_a) != find_bonding_curve_pda(mint_b)


def test_buy_then_sell_round_trip_loses_to_curve_slippage():
    virtual_sol = 30_000_000_000  # 30 SOL, typical pump.fun initial reserve
    virtual_tokens = 1_073_000_000_000_000
    sol_in = 1_000_000_000  # 1 SOL

    tokens_out = compute_buy_tokens_out(virtual_sol, virtual_tokens, sol_in)
    assert tokens_out > 0

    sol_out = compute_sell_sol_out(virtual_sol + sol_in, virtual_tokens - tokens_out, tokens_out)
    # Selling the exact tokens back immediately returns very close to (never
    # meaningfully more than) what was paid — a round trip on a
    # constant-product curve loses at most a little to integer rounding, it
    # never manufactures free SOL.
    assert 0 < sol_out <= sol_in + 1


def test_buy_more_sol_yields_more_tokens_but_worse_price():
    virtual_sol = 30_000_000_000
    virtual_tokens = 1_073_000_000_000_000

    small = compute_buy_tokens_out(virtual_sol, virtual_tokens, 100_000_000)  # 0.1 SOL
    large = compute_buy_tokens_out(virtual_sol, virtual_tokens, 1_000_000_000)  # 1 SOL

    assert large > small
    # price per token should worsen (curve moves against the buyer) as size grows
    assert (100_000_000 / small) < (1_000_000_000 / large)


def test_zero_input_yields_zero_output():
    assert compute_buy_tokens_out(30_000_000_000, 1_073_000_000_000_000, 0) == 0
    assert compute_sell_sol_out(30_000_000_000, 1_073_000_000_000_000, 0) == 0
