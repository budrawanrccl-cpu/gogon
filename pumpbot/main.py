"""Entry point: python -m pumpbot.main"""
from __future__ import annotations

import signal as signal_module
import time

from pumpbot.config import load_settings
from pumpbot.exits import evaluate_exit
from pumpbot.execution import OrderExecutor
from pumpbot.journal import TradeJournal
from pumpbot.logger import setup_logging
from pumpbot.market_data import PumpPortalFeed, TokenTracker
from pumpbot.risk import RiskManager
from pumpbot.strategies import CopyTradeStrategy, MomentumEntryStrategy

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info("Starting pump.fun bot | live_trading=%s", settings.wallet.live_trading)
    if settings.wallet.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real SOL will be spent on real, mostly-worthless "
            "meme tokens. This is high-risk, speculative software. Ctrl+C to stop between cycles."
        )
    else:
        logger.info("Running in PAPER TRADING mode — no real transactions will be sent.")

    keypair = None
    if settings.wallet.live_trading:
        from pumpbot.wallet import load_keypair

        keypair = load_keypair(settings.wallet)

    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    executor = OrderExecutor(
        risk=risk,
        journal=journal,
        live=settings.wallet.live_trading,
        data_cfg=settings.data,
        trading_cfg=settings.trading,
        wallet_cfg=settings.wallet,
        keypair=keypair,
    )
    strategy = MomentumEntryStrategy(settings.filters, risk)
    copytrade = CopyTradeStrategy(settings.copytrade, risk) if settings.copytrade.enabled else None
    tracker = TokenTracker()

    feed = PumpPortalFeed(settings.data)
    feed.start()
    if copytrade is not None:
        logger.info("Copy-trading enabled, following %d wallet(s): %s",
                     len(copytrade.wallets), ", ".join(w[:8] + "…" for w in copytrade.wallets))
        feed.subscribe_account_trades(copytrade.wallets)

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    while not _stop:
        cycle_start = time.time()

        try:
            for event in feed.drain():
                tracker.apply(event)
                if copytrade is not None:
                    sig = copytrade.on_trade_event(event.payload)
                    if sig is not None:
                        executor.execute(sig)

            # Track trades (buyer count, volume) for every candidate we've
            # seen but not yet decided on, and for every open position (to
            # know its current price for exit rules). subscribe_trades is
            # safe to call every cycle with the full list — the feed dedups
            # internally and re-subscribes everything after a reconnect.
            watch_mints = [m for m, s in tracker.tokens.items() if not s.decided] + list(risk.positions.keys())
            feed.subscribe_trades(watch_mints)

            tracker.prune(settings.filters.watch_window_seconds)

            # -- entries (momentum strategy) --------------------------------
            for mint, stats in list(tracker.tokens.items()):
                sig = strategy.evaluate(stats)
                if sig is not None:
                    executor.execute(sig)

            # -- exits (take-profit / stop-loss / trailing / max-hold) -------
            # Runs for every open position regardless of which strategy opened
            # it — a copy-traded position is still subject to our own risk caps.
            for mint, pos in list(risk.positions.items()):
                stats = tracker.tokens.get(mint)
                current_price = stats.last_price_sol_per_token if stats else None
                exit_sig = evaluate_exit(risk, pos, current_price)
                if exit_sig is not None:
                    executor.execute(exit_sig)

            logger.info(
                "Cycle complete: tracking %d tokens | open_positions=%d | "
                "exposure=%.4f SOL | realized_pnl_today=%.4f SOL",
                len(tracker.tokens), len(risk.positions), risk.total_exposure_sol,
                risk.realized_pnl_today_sol,
            )
        except Exception:
            logger.exception("Unhandled error during cycle; continuing")

        if risk.daily_loss_limit_hit:
            logger.warning(
                "Daily loss limit hit (realized_pnl_today=%.4f SOL) — no new positions until UTC midnight.",
                risk.realized_pnl_today_sol,
            )

        elapsed = time.time() - cycle_start
        remaining = max(0.0, settings.polling_interval_seconds - elapsed)
        while remaining > 0 and not _stop:
            step = min(0.5, remaining)
            time.sleep(step)
            remaining -= step

    feed.stop()
    logger.info("Bot stopped.")


if __name__ == "__main__":
    run()
