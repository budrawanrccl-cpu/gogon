"""Alert dispatch: console log, and optionally Telegram / Discord."""
from __future__ import annotations

import logging

import requests

from gmgn.config import NotifyConfig
from gmgn.models import TokenSignal

logger = logging.getLogger("smartmoney.notifier")


def format_signal(signal: TokenSignal) -> str:
    s = signal.stats
    lines = [
        f"🚨 Smart money signal: {signal.symbol or signal.address} ({signal.chain})",
        f"Address: {signal.address}",
        f"Score: {signal.score}  |  Smart buys: {signal.smart_buy_24h} / sells: {signal.smart_sell_24h}  |  "
        f"Net: {signal.net_smart_buys:+d}",
        f"Liquidity: ${s.liquidity_usd:,.0f}  |  Market cap: ${s.market_cap_usd:,.0f}  |  "
        f"Holders: {s.holder_count}",
    ]
    for reason in signal.reasons:
        lines.append(f"  - {reason}")
    lines.append(f"https://gmgn.ai/{signal.chain}/token/{signal.address}")
    return "\n".join(lines)


class Notifier:
    def __init__(self, cfg: NotifyConfig):
        self.cfg = cfg

    def send(self, signal: TokenSignal) -> None:
        message = format_signal(signal)

        if self.cfg.console:
            logger.info("\n%s", message)

        if self.cfg.telegram_bot_token and self.cfg.telegram_chat_id:
            self._send_telegram(message)

        if self.cfg.discord_webhook_url:
            self._send_discord(message)

    def _send_telegram(self, message: str) -> None:
        url = f"https://api.telegram.org/bot{self.cfg.telegram_bot_token}/sendMessage"
        try:
            resp = requests.post(
                url,
                json={"chat_id": self.cfg.telegram_chat_id, "text": message},
                timeout=10,
            )
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to send Telegram alert")

    def _send_discord(self, message: str) -> None:
        try:
            resp = requests.post(self.cfg.discord_webhook_url, json={"content": message}, timeout=10)
            resp.raise_for_status()
        except requests.RequestException:
            logger.exception("Failed to send Discord alert")
