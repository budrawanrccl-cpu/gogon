"""Entry point: python -m bot.main"""
from __future__ import annotations

import json
import os
import signal as signal_module
import time
from datetime import datetime, timezone

from bot.client import build_client
from bot.config import load_settings
from bot.execution import OrderExecutor
from bot.journal import TradeJournal
from bot.logger import setup_logging
from bot.market_data import START_CURSOR, BookLevel, best_levels, iter_active_markets
from bot.risk import RiskManager
from bot.strategies import ArbitrageStrategy, ThresholdStrategy

_stop = False

# Snapshot of the markets scanned in the most recently completed cycle, so
# the dashboard (scripts/dashboard.py) can show what the bot is actually
# looking at — not just the trades it ends up placing. Overwritten every
# cycle; not a history log.
SCAN_SNAPSHOT_PATH = os.path.join("data", "scan_snapshot.json")


def _request_stop(signum, frame):
    global _stop
    _stop = True


def _write_scan_snapshot(entries: list[dict]) -> None:
    os.makedirs(os.path.dirname(SCAN_SNAPSHOT_PATH), exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "markets": entries,
    }
    # Write to a temp file and rename, so the dashboard never reads a
    # half-written file mid-cycle.
    tmp_path = SCAN_SNAPSHOT_PATH + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp_path, SCAN_SNAPSHOT_PATH)


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info("Starting Polymarket bot | live_trading=%s", settings.wallet.live_trading)
    if settings.wallet.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real orders will be placed with real funds. "
            "Ctrl+C to stop between cycles."
        )
        logger.warning(
            "*** KNOWN ISSUE *** py-clob-client has been archived by Polymarket and "
            "its post_order() call currently fails with 'invalid order version, "
            "please use the latest clob-client' — even the latest published version. "
            "Signals will be found but live orders will likely fail to submit until "
            "this bot is migrated to Polymarket's new SDK. See README's Safety notes."
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

    # Where the next cycle's market scan should resume — carried across
    # cycles so the bot rotates through the whole market list over time
    # instead of always rescanning the same first max_markets_per_cycle
    # markets. iter_active_markets wraps this back to START_CURSOR on its
    # own once it reaches the end of the list.
    next_cursor = START_CURSOR

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

        scan_snapshot: list[dict] = []
        cursor_out: dict = {}
        try:
            market_count = 0
            for market in iter_active_markets(
                client, settings.markets, start_cursor=next_cursor, cursor_out=cursor_out
            ):
                market_count += 1
                for strategy in strategies:
                    for sig in strategy.generate_signals(market, get_book):
                        executor.execute(sig)

                # Record what the bot saw for this market, for the dashboard.
                # For 2-outcome markets this reuses get_book's cache — if the
                # arbitrage strategy already fetched these books above (the
                # default), this adds no extra API calls.
                entry: dict = {
                    "market_id": market.condition_id,
                    "question": market.question,
                    "volume_usd": market.volume_usd,
                    "liquidity_usd": market.liquidity_usd,
                    "combined_ask": None,
                    "edge": None,
                    "meets_threshold": False,
                }
                if len(market.tokens) == 2:
                    book_a = get_book(market.tokens[0].token_id)
                    book_b = get_book(market.tokens[1].token_id)
                    if book_a.best_ask is not None and book_b.best_ask is not None:
                        combined_ask = book_a.best_ask + book_b.best_ask
                        edge = 1.0 - combined_ask - settings.arbitrage.fee_buffer
                        entry["combined_ask"] = round(combined_ask, 4)
                        entry["edge"] = round(edge, 4)
                        entry["meets_threshold"] = edge >= settings.arbitrage.min_edge
                scan_snapshot.append(entry)

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
        finally:
            # Advance the rotation cursor for next cycle. cursor_out is only
            # populated if iter_active_markets ran to completion (i.e. the
            # for loop above wasn't aborted by an exception partway
            # through) — if it's empty, keep next_cursor unchanged so the
            # next cycle retries the same starting position.
            next_cursor = cursor_out.get("next", next_cursor)
            try:
                _write_scan_snapshot(scan_snapshot)
            except Exception:
                logger.exception("Failed to write scan snapshot for dashboard")

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
