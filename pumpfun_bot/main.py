"""Entry point: python -m pumpfun_bot.main"""
from __future__ import annotations

import signal as signal_module
import time

from pumpfun_bot.config import load_settings
from pumpfun_bot.copy_engine import build_copy_signal
from pumpfun_bot.execution import TradeExecutor
from pumpfun_bot.journal import TradeJournal
from pumpfun_bot.logger import setup_logging
from pumpfun_bot.risk import RiskManager
from pumpfun_bot.rpc import SolanaRpcClient
from pumpfun_bot.trade_detector import WalletWatcher
from pumpfun_bot.wallet import load_keypair

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info(
        "Starting pump.fun copy-trading bot | live_trading=%s | watching %d wallet(s)",
        settings.wallet.live_trading,
        len(settings.wallets_to_watch.watch),
    )
    if settings.wallet.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real SOL will be spent copying trades. "
            "Ctrl+C to stop between cycles."
        )
    else:
        logger.info("Running in PAPER TRADING mode — no real transactions will be sent.")

    rpc = SolanaRpcClient(settings.wallet.rpc_url)
    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    keypair = load_keypair(settings.wallet.private_key) if settings.wallet.live_trading else None
    executor = TradeExecutor(rpc, risk, journal, settings.execution, live=settings.wallet.live_trading, keypair=keypair)

    watchers = [
        WalletWatcher(addr, signatures_per_poll=settings.wallets_to_watch.signatures_per_poll)
        for addr in settings.wallets_to_watch.watch
    ]

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    while not _stop:
        cycle_start = time.time()
        trades_seen = 0
        signals_executed = 0

        try:
            for watcher in watchers:
                for trade in watcher.poll(rpc):
                    trades_seen += 1
                    signal = build_copy_signal(trade, settings.copy, settings.mints, risk)
                    if signal is None:
                        logger.info(
                            "Skipping %s by %s on mint %s (%.4f SOL) — filtered out",
                            trade.side,
                            trade.wallet,
                            trade.mint,
                            trade.sol_amount,
                        )
                        continue
                    if executor.execute(signal):
                        signals_executed += 1

            logger.info(
                "Cycle complete: %d target trade(s) seen | %d copied | open_positions=%d | "
                "exposure=%.4f SOL | realized_pnl_today=%.4f SOL",
                trades_seen,
                signals_executed,
                len(risk.positions),
                risk.total_exposure_sol,
                risk.realized_pnl_today,
            )
        except Exception:
            logger.exception("Unhandled error during scan cycle; continuing")

        if risk.daily_loss_limit_hit:
            logger.warning(
                "Daily loss limit hit (realized_pnl_today=%.4f SOL) — no new positions until UTC midnight.",
                risk.realized_pnl_today,
            )

        elapsed = time.time() - cycle_start
        remaining = max(0.0, settings.polling_interval_seconds - elapsed)
        # Sleep in small increments so Ctrl+C is responsive.
        while remaining > 0 and not _stop:
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    logger.info("Bot stopped.")


if __name__ == "__main__":
    run()
