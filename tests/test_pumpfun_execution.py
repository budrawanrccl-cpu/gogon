import csv

from pumpfun_bot.config import ExecutionConfig, RiskConfig
from pumpfun_bot.copy_engine import CopySignal
from pumpfun_bot.execution import TradeExecutor
from pumpfun_bot.journal import TradeJournal
from pumpfun_bot.risk import RiskManager


class FakeRpc:
    """No-network stand-in for SolanaRpcClient. get_account_info returns
    None so paper-mode BUY falls back to its 0-token path — the sell-side
    fraction math under test doesn't touch the RPC at all."""

    def get_account_info(self, address: str):
        return None


def make_executor(tmp_path):
    risk = RiskManager(
        RiskConfig(max_position_sol=10.0, max_total_exposure_sol=10.0, max_daily_loss_sol=10.0)
    )
    journal = TradeJournal(path=str(tmp_path / "trades.csv"))
    executor = TradeExecutor(FakeRpc(), risk, journal, ExecutionConfig(), live=False)
    return executor, risk, journal


def test_sell_token_amount_is_proportional_to_sol_size(tmp_path):
    executor, risk, _ = make_executor(tmp_path)
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.4)

    # Mirroring a sell sized at 25% of our position's SOL cost should sell
    # 25% of our tokens too — not 0%, and not 100%.
    signal = CopySignal(
        source_wallet="w1", source_signature="sig1", mint="mintA", side="SELL", sol_size=0.1, reason="test"
    )
    amount = executor._sell_token_amount(signal)
    assert abs(amount - 250.0) < 1e-9


def test_sell_token_amount_capped_at_full_position(tmp_path):
    executor, risk, _ = make_executor(tmp_path)
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.4)

    signal = CopySignal(
        source_wallet="w1", source_signature="sig1", mint="mintA", side="SELL", sol_size=999.0, reason="test"
    )
    amount = executor._sell_token_amount(signal)
    assert abs(amount - 1000.0) < 1e-9  # never more than what we actually hold


def test_sell_token_amount_zero_without_position(tmp_path):
    executor, _, _ = make_executor(tmp_path)
    signal = CopySignal(
        source_wallet="w1", source_signature="sig1", mint="mintB", side="SELL", sol_size=0.1, reason="test"
    )
    assert executor._sell_token_amount(signal) == 0.0


def test_paper_sell_reduces_position_by_the_sized_fraction(tmp_path):
    executor, risk, journal = make_executor(tmp_path)
    risk.record_open("mintA", token_amount=1000.0, cost_sol=0.4)

    signal = CopySignal(
        source_wallet="w1", source_signature="sig1", mint="mintA", side="SELL", sol_size=0.1, reason="test"
    )
    filled = executor.execute(signal)
    assert filled
    # Sold 25% of tokens and 25% of cost basis — position isn't wiped out
    # (the pre-fix bug sold 0 tokens in paper mode) and isn't fully closed.
    assert "mintA" in risk.positions
    assert abs(risk.positions["mintA"].token_amount - 750.0) < 1e-6
    assert abs(risk.positions["mintA"].cost_sol - 0.3) < 1e-6

    with open(journal.path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert rows[-1]["side"] == "SELL"
    assert abs(float(rows[-1]["token_amount"]) - 250.0) < 1e-6
