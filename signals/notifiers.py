"""
Triarch — notifiers.

V1: solo logger + opcional Telegram.
V2: Telegram con botones inline para APPROVAL.
V2.1: Discord webhook.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

import httpx
from loguru import logger

from config.settings import TriarchSettings, get_settings
from signals.schema import Signal


class Notifier(ABC):
    @abstractmethod
    def notify(self, signal: Signal, mode: str) -> None:
        ...


class LoggerNotifier(Notifier):
    """Notifier de respaldo — solo loguea."""

    def notify(self, signal: Signal, mode: str) -> None:
        logger.info(f"[{mode}] {signal.short_repr()}")


class TelegramNotifier(Notifier):
    """Notifier Telegram (HTTP API)."""

    def __init__(self, settings: TriarchSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.token = self.settings.telegram_bot_token
        self.chat = self.settings.telegram_chat_id
        self.enabled = bool(self.token and self.chat)

    def notify(self, signal: Signal, mode: str) -> None:
        if not self.enabled:
            logger.debug("Telegram no configurado — skipping")
            return

        text = (
            f"🤖 *Triarch — {mode}*\n"
            f"`{signal.symbol}` {signal.timeframe}  *{signal.direction.value}*\n"
            f"Strategy: `{signal.strategy}`\n"
            f"Entry: `{signal.entry:.5f}`\n"
            f"SL: `{signal.stop_loss:.5f}`\n"
            f"TP1: `{signal.take_profit_1:.5f}`\n"
            f"R:R `{signal.rr_ratio:.2f}`  Score `{signal.score:.2f}`  "
            f"Conf `{signal.confidence.value}`"
        )
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = httpx.post(
                url,
                json={"chat_id": self.chat, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Telegram falló: {e}")


def build_default_notifiers() -> list[Notifier]:
    s = get_settings()
    out: list[Notifier] = [LoggerNotifier()]
    if s.telegram_bot_token and s.telegram_chat_id:
        out.append(TelegramNotifier(s))
    return out
