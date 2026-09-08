"""Verifies the on-chain-confirmation fix in OrderExecutor._execute_live.

Before this fix, a fill was recorded (risk.record_open/record_close, and
journal filled=True) as soon as sendTransaction returned a signature — which
only means the RPC node accepted it for forwarding, not that it landed or
succeeded on-chain. That let a failed/dropped SELL "free up" risk budget
for new BUYs without the SOL actually coming back, and a failed/dropped BUY
get recorded as an open position that was never really opened.
"""
from unittest.mock import patch

from pumpbot.config import DataConfig, RiskConfig, TradingConfig, WalletConfig
from pumpbot.execution import OrderExecutor
from pumpbot.journal import TradeJournal
from pumpbot.risk import RiskManager
from pumpbot.strategies.base import Signal


def make_executor(tmp_path):
    risk = RiskManager(RiskConfig())
    journal = TradeJournal(path=str(tmp_path / "trades.csv"))
    executor = OrderExecutor(
        risk=risk,
        journal=journal,
        live=True,
        data_cfg=DataConfig(ws_url="wss://x", trade_api_url="https://x", api_key=None),
        trading_cfg=TradingConfig(),
        wallet_cfg=WalletConfig(private_key="k", rpc_url="https://rpc.invalid", live_trading=True),
        keypair=object(),  # unused: _attempt_live_trade is mocked out below
    )
    return executor, risk


def make_signal(side="BUY") -> Signal:
    return Signal(
        strategy="momentum", mint="MINT1", symbol="TEST", side=side,
        reference_price_sol=0.0001, size_sol=0.05, reason="test",
    )


def test_buy_not_recorded_when_send_succeeds_but_never_confirms(tmp_path):
    executor, risk = make_executor(tmp_path)

    with patch.object(executor, "_attempt_live_trade", return_value=("SIG123", "")), \
         patch("pumpbot.execution._wait_for_confirmation", return_value=(False, "dropped")), \
         patch("pumpbot.execution.time.sleep"):
        filled = executor.execute(make_signal("BUY"))

    assert filled is False
    assert "MINT1" not in risk.positions  # no phantom open position


def test_buy_recorded_only_after_confirmation(tmp_path):
    executor, risk = make_executor(tmp_path)

    with patch.object(executor, "_attempt_live_trade", return_value=("SIG123", "")), \
         patch("pumpbot.execution._wait_for_confirmation", return_value=(True, "")):
        filled = executor.execute(make_signal("BUY"))

    assert filled is True
    assert "MINT1" in risk.positions


def test_sell_not_recorded_when_transaction_lands_but_reverts(tmp_path):
    """The exact failure mode that drained the wallet: a SELL transaction
    lands on-chain (charging the fee) but its instruction fails — before
    this fix, that was still recorded as a closed position, wrongly
    freeing risk budget for a new BUY while the tokens were never sold.
    """
    executor, risk = make_executor(tmp_path)
    risk.record_open("MINT1", "TEST", token_amount=500_000.0, cost_sol=0.05)
    assert "MINT1" in risk.positions

    sell_signal = make_signal("SELL")
    with patch.object(executor, "_attempt_live_trade", return_value=("SIG456", "")), \
         patch("pumpbot.execution._wait_for_confirmation",
               return_value=(False, "transaction landed but failed on-chain: {'InstructionError': ...}")), \
         patch("pumpbot.execution.time.sleep"):
        filled = executor.execute(sell_signal)

    assert filled is False
    assert "MINT1" in risk.positions  # position must still be considered open


def test_retries_with_a_fresh_transaction_after_a_dropped_attempt(tmp_path):
    executor, risk = make_executor(tmp_path)

    attempts = [("SIG_DROPPED", ""), ("SIG_LANDED", "")]
    confirmations = [(False, "not confirmed within timeout"), (True, "")]

    with patch.object(executor, "_attempt_live_trade", side_effect=attempts), \
         patch("pumpbot.execution._wait_for_confirmation", side_effect=confirmations), \
         patch("pumpbot.execution.time.sleep"):  # skip the real retry delay
        filled = executor.execute(make_signal("BUY"))

    assert filled is True
    assert "MINT1" in risk.positions
