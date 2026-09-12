"""Entry point: python -m funding_bot.main"""
from __future__ import annotations

import signal as signal_module
import time

from funding_bot.client import build_clients
from funding_bot.config import load_settings
from funding_bot.execution import OrderExecutor
from funding_bot.journal import TradeJournal
from funding_bot.logger import setup_logging
from funding_bot.market_data import discover_symbols, fetch_snapshot
from funding_bot.risk import RiskManager
from funding_bot.strategies import FundingArbitrageStrategy

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info(
        "Starting funding-rate arbitrage bot | live_trading=%s testnet=%s",
        settings.exchange.live_trading,
        settings.exchange.testnet,
    )
    if settings.exchange.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real orders will be placed with real funds. "
            "Ctrl+C to stop between cycles."
        )
    else:
        logger.info("Running in PAPER TRADING mode — no real orders will be sent.")

    spot_client, futures_client = build_clients(settings.exchange)
    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    executor = OrderExecutor(spot_client, futures_client, risk, journal, live=settings.exchange.live_trading)
    strategy = FundingArbitrageStrategy(settings.funding_arbitrage, risk)

    if not settings.funding_arbitrage.enabled:
        logger.warning("funding_arbitrage.enabled is false in config — bot will idle.")

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    symbols: list[str] = []
    cycle = 0

    while not _stop:
        cycle_start = time.time()

        should_rediscover = (
            not settings.symbols.whitelist
            and (not symbols or cycle % max(1, settings.symbols.rediscover_every_cycles) == 0)
        )
        if should_rediscover:
            try:
                symbols = discover_symbols(futures_client, settings.symbols)
            except Exception:
                logger.exception("Symbol discovery failed; keeping previous symbol list")
        elif settings.symbols.whitelist and not symbols:
            symbols = list(settings.symbols.whitelist)

        funding_credited_this_cycle = 0.0
        try:
            for base in symbols:
                snapshot = fetch_snapshot(spot_client, futures_client, base, settings.symbols.quote_asset)
                if snapshot is None:
                    continue

                credited = risk.accrue_funding(
                    base, snapshot.funding_rate, snapshot.mark_price, snapshot.next_funding_time_ms
                )
                if credited:
                    funding_credited_this_cycle += credited
                    journal.record_funding(
                        mode="live" if settings.exchange.live_trading else "paper",
                        base=base,
                        amount_usd=credited,
                        funding_rate=snapshot.funding_rate,
                    )
                    logger.info("Funding settled for %s: $%.4f credited", base, credited)

                signals = strategy.generate_signals(snapshot)
                if signals:
                    executor.execute_group(signals, snapshot)

            logger.info(
                "Cycle complete: scanned %d symbols | open_positions=%d | "
                "exposure=$%.2f | realized_pnl_today=$%.2f | funding_credited=$%.4f",
                len(symbols),
                len(risk.positions),
                risk.total_exposure_usd,
                risk.realized_pnl_today,
                funding_credited_this_cycle,
            )
        except Exception:
            logger.exception("Unhandled error during scan cycle; continuing")

        if risk.daily_loss_limit_hit:
            logger.warning(
                "Daily loss limit hit (realized_pnl_today=$%.2f) — no new positions until UTC midnight.",
                risk.realized_pnl_today,
            )

        cycle += 1
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
