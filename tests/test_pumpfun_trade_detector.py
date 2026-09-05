from pumpfun_bot.pumpfun_program import PUMPFUN_PROGRAM_ID
from pumpfun_bot.trade_detector import parse_pumpfun_trade

WALLET = "Wallet1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
MINT = "MintABCxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
PROGRAM_ID_STR = str(PUMPFUN_PROGRAM_ID)


def make_tx(*, side: str, pre_sol: int, post_sol: int, pre_tokens: float, post_tokens: float, failed=False):
    return {
        "blockTime": 1_700_000_000,
        "transaction": {
            "signatures": ["sig123"],
            "message": {
                "accountKeys": [
                    {"pubkey": WALLET, "signer": True, "writable": True},
                    {"pubkey": PROGRAM_ID_STR, "signer": False, "writable": False},
                ],
                "instructions": [
                    {"programId": PROGRAM_ID_STR, "accounts": [], "data": "abc"},
                ],
            },
        },
        "meta": {
            "err": ({"InstructionError": [0, "Custom"]} if failed else None),
            "logMessages": [
                f"Program {PROGRAM_ID_STR} invoke [1]",
                f"Program log: Instruction: {side.capitalize()}",
                f"Program {PROGRAM_ID_STR} success",
            ],
            "preBalances": [pre_sol, 0],
            "postBalances": [post_sol, 0],
            "preTokenBalances": (
                [{"accountIndex": 0, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"uiAmount": pre_tokens}}]
                if pre_tokens
                else []
            ),
            "postTokenBalances": (
                [{"accountIndex": 0, "mint": MINT, "owner": WALLET, "uiTokenAmount": {"uiAmount": post_tokens}}]
                if post_tokens
                else []
            ),
            "innerInstructions": [],
        },
    }


def test_detects_buy():
    tx = make_tx(side="buy", pre_sol=5_000_000_000, post_sol=3_995_000_000, pre_tokens=0.0, post_tokens=1000.0)
    trade = parse_pumpfun_trade(tx, WALLET, "sig123")
    assert trade is not None
    assert trade.side == "BUY"
    assert trade.mint == MINT
    assert abs(trade.token_amount - 1000.0) < 1e-9
    assert abs(trade.sol_amount - 1.005) < 1e-6


def test_detects_sell():
    tx = make_tx(side="sell", pre_sol=3_995_000_000, post_sol=4_990_000_000, pre_tokens=1000.0, post_tokens=400.0)
    trade = parse_pumpfun_trade(tx, WALLET, "sig123")
    assert trade is not None
    assert trade.side == "SELL"
    assert abs(trade.token_amount - 600.0) < 1e-9


def test_ignores_failed_transaction():
    tx = make_tx(side="buy", pre_sol=5_000_000_000, post_sol=3_995_000_000, pre_tokens=0.0, post_tokens=1000.0, failed=True)
    assert parse_pumpfun_trade(tx, WALLET, "sig123") is None


def test_ignores_transaction_without_pumpfun_program():
    tx = make_tx(side="buy", pre_sol=5_000_000_000, post_sol=3_995_000_000, pre_tokens=0.0, post_tokens=1000.0)
    tx["transaction"]["message"]["instructions"] = [{"programId": "SomeOtherProgram11111111111111111111111111", "data": "x"}]
    assert parse_pumpfun_trade(tx, WALLET, "sig123") is None


def test_ignores_wrong_wallet_token_balance():
    tx = make_tx(side="buy", pre_sol=5_000_000_000, post_sol=3_995_000_000, pre_tokens=0.0, post_tokens=1000.0)
    tx["meta"]["postTokenBalances"][0]["owner"] = "SomeoneElse"
    assert parse_pumpfun_trade(tx, WALLET, "sig123") is None


def test_none_transaction_returns_none():
    assert parse_pumpfun_trade(None, WALLET, "sig123") is None
