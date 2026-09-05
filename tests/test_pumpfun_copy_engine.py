from pumpfun_bot.config import CopyConfig, MintFilterConfig, RiskConfig
from pumpfun_bot.copy_engine import build_copy_signal
from pumpfun_bot.risk import RiskManager
from pumpfun_bot.trade_detector import DetectedTrade


def make_risk(**overrides) -> RiskManager:
    cfg = RiskConfig(
        max_position_sol=1000.0,
        max_total_exposure_sol=1000.0,
        max_daily_loss_sol=1000.0,
        min_virtual_sol_reserves=5.0,
    )
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return RiskManager(cfg)


def make_buy(sol_amount=1.0, mint="mintA", wallet="Wallet1"):
    return DetectedTrade(
        signature="sig1",
        wallet=wallet,
        mint=mint,
        side="BUY",
        sol_amount=sol_amount,
        token_amount=1000.0,
        block_time=None,
    )


def make_sell(sol_amount=1.0, mint="mintA", wallet="Wallet1"):
    return DetectedTrade(
        signature="sig2",
        wallet=wallet,
        mint=mint,
        side="SELL",
        sol_amount=sol_amount,
        token_amount=1000.0,
        block_time=None,
    )


def test_buy_sized_by_ratio():
    risk = make_risk()
    copy_cfg = CopyConfig(size_ratio=0.1, max_sol_per_trade=10.0, min_target_trade_sol=0.05)
    mint_cfg = MintFilterConfig()
    sig = build_copy_signal(make_buy(sol_amount=2.0), copy_cfg, mint_cfg, risk)
    assert sig is not None
    assert sig.side == "BUY"
    assert abs(sig.sol_size - 0.2) < 1e-9


def test_buy_capped_by_max_sol_per_trade():
    risk = make_risk()
    copy_cfg = CopyConfig(size_ratio=0.5, max_sol_per_trade=0.3, min_target_trade_sol=0.05)
    sig = build_copy_signal(make_buy(sol_amount=10.0), copy_cfg, MintFilterConfig(), risk)
    assert sig is not None
    assert abs(sig.sol_size - 0.3) < 1e-9


def test_buy_skipped_below_min_target_trade():
    risk = make_risk()
    copy_cfg = CopyConfig(size_ratio=0.1, max_sol_per_trade=10.0, min_target_trade_sol=0.5)
    sig = build_copy_signal(make_buy(sol_amount=0.1), copy_cfg, MintFilterConfig(), risk)
    assert sig is None


def test_buy_skipped_when_already_holding():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.1)
    copy_cfg = CopyConfig(size_ratio=0.1, max_sol_per_trade=10.0, skip_if_already_holding=True)
    sig = build_copy_signal(make_buy(mint="mintA"), copy_cfg, MintFilterConfig(), risk)
    assert sig is None


def test_buy_capped_by_risk_budget():
    risk = make_risk(max_position_sol=0.05, max_total_exposure_sol=1000.0)
    copy_cfg = CopyConfig(size_ratio=1.0, max_sol_per_trade=10.0, min_target_trade_sol=0.0)
    sig = build_copy_signal(make_buy(sol_amount=1.0), copy_cfg, MintFilterConfig(), risk)
    assert sig is not None
    assert abs(sig.sol_size - 0.05) < 1e-9


def test_buy_skipped_by_mint_blacklist():
    risk = make_risk()
    copy_cfg = CopyConfig(size_ratio=0.1, max_sol_per_trade=10.0, min_target_trade_sol=0.0)
    mint_cfg = MintFilterConfig(blacklist=["mintA"])
    sig = build_copy_signal(make_buy(mint="mintA"), copy_cfg, mint_cfg, risk)
    assert sig is None


def test_buy_skipped_when_not_in_whitelist():
    risk = make_risk()
    copy_cfg = CopyConfig(size_ratio=0.1, max_sol_per_trade=10.0, min_target_trade_sol=0.0)
    mint_cfg = MintFilterConfig(whitelist=["mintB"])
    sig = build_copy_signal(make_buy(mint="mintA"), copy_cfg, mint_cfg, risk)
    assert sig is None


def test_sell_skipped_when_not_holding():
    risk = make_risk()
    copy_cfg = CopyConfig(mirror_sells=True, size_ratio=0.5)
    sig = build_copy_signal(make_sell(mint="mintA"), copy_cfg, MintFilterConfig(), risk)
    assert sig is None


def test_sell_mirrors_slice_of_own_position():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.4)
    copy_cfg = CopyConfig(mirror_sells=True, size_ratio=0.25)
    sig = build_copy_signal(make_sell(mint="mintA"), copy_cfg, MintFilterConfig(), risk)
    assert sig is not None
    assert sig.side == "SELL"
    assert abs(sig.sol_size - 0.1) < 1e-9  # 25% of 0.4 SOL position


def test_sell_ignored_when_mirror_sells_disabled():
    risk = make_risk()
    risk.record_open("mintA", token_amount=100.0, cost_sol=0.4)
    copy_cfg = CopyConfig(mirror_sells=False, size_ratio=0.25)
    sig = build_copy_signal(make_sell(mint="mintA"), copy_cfg, MintFilterConfig(), risk)
    assert sig is None
