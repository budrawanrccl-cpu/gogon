"""Entry point: python -m gmgn.main

Polls gmgn.ai for newly-created tokens, checks each one's recent tagged
"smart money" wallet activity against the configured thresholds, and raises
an alert for anything that passes. Read-only: this bot never places trades.
"""
from __future__ import annotations

import signal as signal_module
import time

from gmgn.client import GmgnApiError, GmgnClient
from gmgn.config import load_settings
from gmgn.logger import setup_logging
from gmgn.notifier import Notifier
from gmgn.screener import SmartMoneyScreener
from gmgn.storage import SeenCache, SignalJournal

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    logger.info(
        "Starting gmgn.ai smart-money screener | chain=%s | poll_interval=%ds",
        settings.chain,
        settings.poll_interval_seconds,
    )
    logger.info("Read-only: this bot only screens and alerts, it never places trades.")

    client = GmgnClient(settings.api)
    screener = SmartMoneyScreener(settings.screener)
    notifier = Notifier(settings.notify)
    seen = SeenCache(settings.seen_cache_path)
    journal = SignalJournal(settings.signals_journal_path)

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    while not _stop:
        cycle_start = time.time()
        signals_found = 0

        try:
            candidates = client.get_new_pairs(settings.chain, limit=settings.new_pairs_limit)
            logger.info("Fetched %d candidate token(s) from gmgn.ai", len(candidates))

            for stats in candidates:
                if _stop:
                    break
                try:
                    activities = client.get_token_activities(
                        settings.chain, stats.address, limit=settings.activities_limit
                    )
                except GmgnApiError:
                    logger.exception("Failed to fetch activity for token %s", stats.address)
                    continue

                signal = screener.evaluate(stats, activities)
                if signal is None:
                    continue

                journal.record(signal)
                signals_found += 1

                if seen.should_alert(signal.address, settings.notify.cooldown_minutes):
                    notifier.send(signal)
                    seen.mark(signal.address)
                else:
                    logger.info(
                        "Signal for %s (%s) still in cooldown, logged but not re-alerted",
                        signal.symbol or signal.address,
                        signal.address,
                    )

            logger.info(
                "Cycle complete: scanned %d token(s), %d signal(s) found",
                len(candidates),
                signals_found,
            )
        except GmgnApiError:
            logger.exception("gmgn.ai API error during scan cycle; continuing")
        except Exception:
            logger.exception("Unhandled error during scan cycle; continuing")

        elapsed = time.time() - cycle_start
        remaining = max(0.0, settings.poll_interval_seconds - elapsed)
        # Sleep in small increments so Ctrl+C is responsive.
        while remaining > 0 and not _stop:
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    logger.info("Screener stopped.")


if __name__ == "__main__":
    run()
