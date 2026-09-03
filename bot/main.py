"""Entry point: python -m bot.main"""
from __future__ import annotations

import signal as signal_module
import time

from bot.client import build_client
from bot.config import load_settings
from bot.execution import OrderExecutor
from bot.journal import TradeJournal
from bot.logger import setup_logging
from bot.market_data import BookLevel, best_levels, iter_active_markets
from bot.risk import RiskManager
from bot.strategies import ArbitrageStrategy, ThresholdStrategy

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info("Starting Polymarket bot | live_trading=%s", settings.wallet.live_trading)
    if settings.wallet.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real orders will be placed with real funds. "
            "Ctrl+C to stop between cycles."
        )
    else:
        logger.info("Running in PAPER TRADING mode — no real orders will be sent.")

    client = build_client(settings.wallet)
    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    executor = OrderExecutor(client, risk, journal, live=settings.wallet.live_trading)

    strategies = []
    if settings.arbitrage.enabled:
        strategies.append(ArbitrageStrategy(settings.arbitrage, risk))
    if settings.threshold.enabled:
        strategies.append(ThresholdStrategy(settings.threshold, risk))
    if not strategies:
        logger.warning("No strategies enabled in config/settings.yaml — bot will idle.")

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    while not _stop:
        cycle_start = time.time()
        book_cache: dict[str, BookLevel] = {}

        def get_book(token_id: str) -> BookLevel:
            if token_id not in book_cache:
                try:
                    raw_book = client.get_order_book(token_id)
                    book_cache[token_id] = best_levels(raw_book)
                except Exception:
                    logger.exception("Failed to fetch order book for token %s", token_id)
                    book_cache[token_id] = BookLevel(None, None, 0.0, 0.0)
            return book_cache[token_id]

        try:
            market_count = 0
            for market in iter_active_markets(client, settings.markets):
                market_count += 1
                for strategy in strategies:
                    for sig in strategy.generate_signals(market, get_book):
                        executor.execute(sig)
            logger.info(
                "Cycle complete: scanned %d markets | open_positions=%d | "
                "exposure=$%.2f | realized_pnl_today=$%.2f",
                market_count,
                len(risk.positions),
                risk.total_exposure_usd,
                risk.realized_pnl_today,
            )
        except Exception:
            logger.exception("Unhandled error during scan cycle; continuing")

        if risk.daily_loss_limit_hit:
            logger.warning(
                "Daily loss limit hit (realized_pnl_today=$%.2f) — no new positions until UTC midnight.",
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
