"""Entry point: python -m crypto_bot.main

Live/paper trading loop: each cycle, fetch the latest closed candles, run
the same `strategy.evaluate()` used by the backtester, and act on the
result through the risk manager. Paper mode (default) never calls the
exchange's order-placement endpoints.
"""
from __future__ import annotations

import signal as signal_module
import time

from crypto_bot.config import load_settings
from crypto_bot.exchange import build_exchange, fetch_recent_bars, only_closed_bars, place_market_order
from crypto_bot.journal import TradeJournal
from crypto_bot.logger import setup_logging
from crypto_bot.models import Position
from crypto_bot.risk import RiskManager
from crypto_bot.strategy import DonchianBreakoutStrategy, DonchianConfig

_stop = False


def _request_stop(signum, frame):
    global _stop
    _stop = True


def _lookback_needed(cfg: DonchianConfig) -> int:
    periods = [cfg.entry_period, cfg.exit_period, cfg.atr_period]
    if cfg.trend_filter_ema_period:
        periods.append(cfg.trend_filter_ema_period)
    return max(periods) + 5


def run() -> None:
    settings = load_settings()
    logger = setup_logging()

    mode = "LIVE" if settings.exchange.live_trading else "PAPER"
    logger.info(
        "Starting crypto bot | symbol=%s timeframe=%s mode=%s",
        settings.symbol,
        settings.timeframe,
        mode,
    )
    if settings.exchange.live_trading:
        logger.warning(
            "*** LIVE TRADING ENABLED *** Real orders will be placed with real funds. "
            "Ctrl+C to stop between cycles."
        )
    else:
        logger.info("Running in PAPER TRADING mode — no real orders will be sent.")

    exchange = build_exchange(settings.exchange)
    strategy = DonchianBreakoutStrategy(settings.strategy)
    risk = RiskManager(settings.risk)
    journal = TradeJournal()
    position: Position | None = None

    min_bars = _lookback_needed(settings.strategy)
    fetch_limit = max(200, min_bars * 3)

    signal_module.signal(signal_module.SIGINT, _request_stop)
    signal_module.signal(signal_module.SIGTERM, _request_stop)

    while not _stop:
        cycle_start = time.time()
        try:
            bars = fetch_recent_bars(exchange, settings.symbol, settings.timeframe, limit=fetch_limit)
            bars = only_closed_bars(exchange, bars, settings.timeframe)

            if len(bars) < min_bars:
                logger.warning("Not enough closed bars yet (%d/%d) — waiting.", len(bars), min_bars)
            else:
                i = len(bars) - 1
                ind = strategy.precompute(bars)
                sig, new_stop = strategy.evaluate(bars, ind, i, position)

                if sig is not None and sig.action == "EXIT_LONG" and position is not None:
                    exit_price = sig.price
                    if settings.exchange.live_trading:
                        order = place_market_order(exchange, settings.symbol, "sell", position.size)
                        exit_price = float(order.get("average") or order.get("price") or exit_price)
                    trade = risk.record_close(settings.symbol, exit_price, bars[i].timestamp, sig.reason)
                    journal.record(settings.symbol, strategy.name, sig, mode, size=position.size)
                    logger.info(
                        "EXIT %s @ %.6g (%s) pnl=$%.2f",
                        settings.symbol,
                        exit_price,
                        sig.reason,
                        trade.pnl_usd if trade else 0.0,
                    )
                    position = None

                elif sig is not None and sig.action == "ENTER_LONG" and position is None:
                    allowed, reason = risk.can_open(settings.symbol)
                    if not allowed:
                        logger.info("Signal ENTER_LONG rejected by risk manager: %s", reason)
                    else:
                        size = risk.position_size(sig.price, sig.stop_price)
                        notional = size * sig.price
                        if size <= 0 or notional < settings.risk.min_order_size_usd:
                            logger.info(
                                "Signal ENTER_LONG too small to trade (size=%.8g, notional=$%.2f)",
                                size,
                                notional,
                            )
                        else:
                            entry_price = sig.price
                            if settings.exchange.live_trading:
                                order = place_market_order(exchange, settings.symbol, "buy", size)
                                entry_price = float(order.get("average") or order.get("price") or entry_price)
                            position = Position(
                                symbol=settings.symbol,
                                side="LONG",
                                entry_price=entry_price,
                                size=size,
                                stop_price=sig.stop_price,
                                opened_at=bars[i].timestamp,
                            )
                            risk.record_open(settings.symbol, position)
                            journal.record(settings.symbol, strategy.name, sig, mode, size=size)
                            logger.info(
                                "ENTER %s @ %.6g size=%.8g stop=%.6g (%s)",
                                settings.symbol,
                                entry_price,
                                size,
                                sig.stop_price,
                                sig.reason,
                            )

                elif position is not None and new_stop is not None:
                    if new_stop > position.stop_price:
                        logger.info(
                            "Trailing stop for %s updated: %.6g -> %.6g",
                            settings.symbol,
                            position.stop_price,
                            new_stop,
                        )
                    position.stop_price = new_stop

                last_close = bars[i].close
                unrealized = (last_close - position.entry_price) * position.size if position else 0.0
                risk.mark_unrealized(unrealized)

                logger.info(
                    "Cycle complete: last_close=%.6g position=%s equity=$%.2f drawdown=%.1f%%",
                    last_close,
                    f"{position.size:.6g}@{position.entry_price:.6g}" if position else "flat",
                    risk.current_equity,
                    risk.drawdown_pct * 100,
                )

                if risk.halted_for_drawdown:
                    logger.warning(
                        "Max drawdown kill switch active (%.1f%%) — no new entries. "
                        "Existing positions still manage their own stops.",
                        risk.drawdown_pct * 100,
                    )
                if risk.daily_loss_limit_hit:
                    logger.warning(
                        "Daily loss limit hit (realized_pnl_today=$%.2f) — no new entries until UTC midnight.",
                        risk.realized_pnl_today,
                    )

        except Exception:
            logger.exception("Unhandled error during trading cycle; continuing")

        elapsed = time.time() - cycle_start
        remaining = max(0.0, settings.polling_interval_seconds - elapsed)
        while remaining > 0 and not _stop:
            step = min(1.0, remaining)
            time.sleep(step)
            remaining -= step

    logger.info("Bot stopped.")


if __name__ == "__main__":
    run()
