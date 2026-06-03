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


def http_request_ssl_tolerant(method: str, url: str, **kwargs) -> httpx.Response:
    """
    Hace una petición HTTP tolerante a entornos que interceptan SSL (antivirus,
    proxy corporativo, OneDrive/Windows con cert store incompleto).

    Intenta primero con verificación normal; si falla por un problema de
    CERTIFICADO/SSL, reintenta UNA vez sin verificación (verify=False) y avisa.
    No silencia errores de red reales (timeouts, DNS): esos se propagan.
    """
    try:
        return httpx.request(method, url, **kwargs)
    except httpx.ConnectError as e:
        msg = str(e).upper()
        if "CERTIFICATE" in msg or "SSL" in msg:
            logger.warning(
                "SSL no verificable en este entorno (interceptación de certificado). "
                "Reintentando sin verificación — OK para la API de Telegram."
            )
            return httpx.request(method, url, verify=False, **kwargs)
        raise


class Notifier(ABC):
    @abstractmethod
    def notify(self, signal: Signal, mode: str) -> None: ...

    def status(self, text: str) -> None:
        """Mensaje de estado libre (arranque, latido, resúmenes). Default: no-op."""
        return


class LoggerNotifier(Notifier):
    """Notifier de respaldo — solo loguea."""

    def notify(self, signal: Signal, mode: str) -> None:
        logger.info(f"[{mode}] {signal.short_repr()}")

    def status(self, text: str) -> None:
        logger.info(f"[STATUS] {text}")


class TelegramNotifier(Notifier):
    """Notifier Telegram (HTTP API)."""

    def __init__(self, settings: TriarchSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.token = self.settings.telegram_bot_token
        self.chat = self.settings.telegram_chat_id
        self.enabled = bool(self.token and self.chat)

    def _send(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        try:
            r = http_request_ssl_tolerant(
                "POST",
                url,
                json={"chat_id": self.chat, "text": text, "parse_mode": "Markdown"},
                timeout=10,
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Telegram falló: {e}")

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
        self._send(text)

    def status(self, text: str) -> None:
        if not self.enabled:
            return
        self._send(text)


def build_default_notifiers() -> list[Notifier]:
    s = get_settings()
    out: list[Notifier] = [LoggerNotifier()]
    if s.telegram_bot_token and s.telegram_chat_id:
        out.append(TelegramNotifier(s))
    return out
