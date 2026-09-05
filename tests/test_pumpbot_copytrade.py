from pumpbot.config import CopyTradeConfig, RiskConfig
from pumpbot.risk import RiskManager
from pumpbot.strategies.copytrade import CopyTradeStrategy

LEADER = "LeaderWa11etAddress1111111111111111111111"
OTHER = "SomeoneElse2222222222222222222222222222222"


def make_strategy(**overrides):
    cfg = CopyTradeConfig(
        enabled=True,
        wallets=[LEADER],
        copy_buys=True,
        copy_sells=True,
        sizing_mode="fixed",
        copy_ratio=0.01,
        min_leader_buy_sol=0.0,
        blacklist_mints=[],
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    rcfg = RiskConfig(
        max_position_sol=0.05,
        max_total_exposure_sol=0.25,
        max_concurrent_positions=5,
        max_daily_loss_sol=0.5,
        min_order_size_sol=0.01,
    )
    risk = RiskManager(rcfg)
    return CopyTradeStrategy(cfg, risk), risk


def buy_payload(**overrides) -> dict:
    p = dict(
        txType="buy",
        traderPublicKey=LEADER,
        mint="MintAAAA1111111111111111111111111111111",
        symbol="FOO",
        solAmount=2.0,
        vTokensInBondingCurve=1_000_000.0,
        vSolInBondingCurve=100.0,  # price = 100/1_000_000 = 0.0001 SOL/token
    )
    p.update(overrides)
    return p


def sell_payload(**overrides) -> dict:
    p = dict(
        txType="sell",
        traderPublicKey=LEADER,
        mint="MintAAAA1111111111111111111111111111111",
        symbol="FOO",
        solAmount=1.0,
        vTokensInBondingCurve=1_000_000.0,
        vSolInBondingCurve=100.0,
    )
    p.update(overrides)
    return p


def test_ignores_non_followed_wallet():
    strategy, _ = make_strategy()
    sig = strategy.on_trade_event(buy_payload(traderPublicKey=OTHER))
    assert sig is None


def test_ignores_blacklisted_mint():
    strategy, _ = make_strategy(blacklist_mints=["MintAAAA1111111111111111111111111111111"])
    sig = strategy.on_trade_event(buy_payload())
    assert sig is None


def test_copies_leader_buy_fixed_sizing():
    strategy, risk = make_strategy(sizing_mode="fixed")
    sig = strategy.on_trade_event(buy_payload())
    assert sig is not None
    assert sig.side == "BUY"
    assert sig.strategy == "copytrade"
    assert abs(sig.size_sol - 0.05) < 1e-9  # capped at max_position_sol
    assert abs(sig.reference_price_sol - 0.0001) < 1e-12


def test_copies_leader_buy_proportional_sizing():
    strategy, risk = make_strategy(sizing_mode="proportional", copy_ratio=0.01)
    sig = strategy.on_trade_event(buy_payload(solAmount=2.0))  # 2.0 * 0.01 = 0.02
    assert sig is not None
    assert abs(sig.size_sol - 0.02) < 1e-9


def test_proportional_sizing_still_capped_by_risk_budget():
    strategy, risk = make_strategy(sizing_mode="proportional", copy_ratio=1.0)
    sig = strategy.on_trade_event(buy_payload(solAmount=10.0))  # 10.0 * 1.0 = 10, way over cap
    assert sig is not None
    assert abs(sig.size_sol - 0.05) < 1e-9  # clamped to max_position_sol


def test_copy_buys_disabled_skips_buy():
    strategy, _ = make_strategy(copy_buys=False)
    sig = strategy.on_trade_event(buy_payload())
    assert sig is None


def test_ignores_buy_below_min_leader_buy_sol():
    strategy, _ = make_strategy(min_leader_buy_sol=5.0)
    sig = strategy.on_trade_event(buy_payload(solAmount=2.0))
    assert sig is None


def test_no_signal_without_price_data():
    strategy, _ = make_strategy()
    sig = strategy.on_trade_event(buy_payload(vTokensInBondingCurve=None, vSolInBondingCurve=None))
    assert sig is None


def test_respects_existing_risk_caps_on_buy():
    strategy, risk = make_strategy()
    risk.record_open("otherMint", "BAR", token_amount=1.0, cost_sol=0.25)  # exhausts exposure
    sig = strategy.on_trade_event(buy_payload())
    assert sig is None


def test_does_not_duplicate_into_already_held_mint():
    strategy, risk = make_strategy()
    mint = "MintAAAA1111111111111111111111111111111"
    risk.record_open(mint, "FOO", token_amount=100.0, cost_sol=0.01)
    sig = strategy.on_trade_event(buy_payload())
    assert sig is None  # RiskManager.can_open blocks a second position in the same mint


def test_copies_leader_sell_when_we_hold_a_position():
    strategy, risk = make_strategy()
    mint = "MintAAAA1111111111111111111111111111111"
    risk.record_open(mint, "FOO", token_amount=500.0, cost_sol=0.05)  # avg 0.0001/token
    sig = strategy.on_trade_event(sell_payload())
    assert sig is not None
    assert sig.side == "SELL"
    assert sig.mint == mint


def test_leader_sell_ignored_when_we_hold_nothing():
    strategy, _ = make_strategy()
    sig = strategy.on_trade_event(sell_payload())
    assert sig is None


def test_copy_sells_disabled_skips_sell():
    strategy, risk = make_strategy(copy_sells=False)
    mint = "MintAAAA1111111111111111111111111111111"
    risk.record_open(mint, "FOO", token_amount=500.0, cost_sol=0.05)
    sig = strategy.on_trade_event(sell_payload())
    assert sig is None


def test_unrecognized_tx_type_is_ignored():
    strategy, _ = make_strategy()
    sig = strategy.on_trade_event(buy_payload(txType="create"))
    assert sig is None
