"""
Triarch — wrapper sobre el paquete oficial `MetaTrader5`.

Toda interacción con MT5 pasa por aquí. El paquete `MetaTrader5` solo está
disponible en Windows; en otros sistemas, el import falla "soft" y el cliente
puede correr en modo MOCK para tests.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterator

import pandas as pd
from loguru import logger

from config.settings import TriarchSettings, get_settings

# El import oficial sólo existe en Windows.
try:
    import MetaTrader5 as mt5  # type: ignore[import-not-found]
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None  # type: ignore[assignment]
    MT5_AVAILABLE = False
    logger.warning(
        "MetaTrader5 package no disponible (¿no estás en Windows?). "
        "El cliente operará en modo MOCK."
    )


# Mapeo de timeframes string → constantes MT5
TIMEFRAMES: dict[str, int] = {}
if MT5_AVAILABLE:
    TIMEFRAMES = {
        "M1": mt5.TIMEFRAME_M1,
        "M5": mt5.TIMEFRAME_M5,
        "M15": mt5.TIMEFRAME_M15,
        "M30": mt5.TIMEFRAME_M30,
        "H1": mt5.TIMEFRAME_H1,
        "H4": mt5.TIMEFRAME_H4,
        "D1": mt5.TIMEFRAME_D1,
    }


@dataclass
class AccountInfo:
    login: int
    server: str
    name: str
    currency: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    leverage: int


@dataclass
class SymbolInfo:
    name: str
    bid: float
    ask: float
    spread: int
    digits: int
    trade_contract_size: float
    volume_min: float
    volume_max: float
    volume_step: float


class MT5Client:
    """Wrapper alrededor del paquete MetaTrader5."""

    def __init__(self, settings: TriarchSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self._initialized = False

    # ─────────────────────────────────────────────────────
    # Conexión
    # ─────────────────────────────────────────────────────
    def initialize(self) -> bool:
        """
        Conecta al terminal MT5 en 2 pasos:
          1. mt5.initialize() — sólo conecta al terminal abierto.
          2. mt5.login() — autentica con las credenciales.

        Hacerlo en 2 pasos da mejor diagnóstico que initialize(login=, password=, server=)
        que devuelve "IPC timeout" para muchas causas distintas.
        """
        if not MT5_AVAILABLE:
            logger.error("MetaTrader5 package no disponible — no se puede inicializar.")
            return False

        # ─── Paso 1: conectar al terminal ───
        init_kwargs: dict = {}
        if self.settings.mt5_path:
            init_kwargs["path"] = self.settings.mt5_path

        ok = mt5.initialize(**init_kwargs)
        if not ok:
            err = mt5.last_error()
            logger.error(
                f"mt5.initialize() falló — error {err}\n"
                f"  Causa probable:\n"
                f"  - Terminal MT5 no está abierto, o\n"
                f"  - El path al terminal.exe no es el que Python encuentra (set MT5_PATH en .env), o\n"
                f"  - 'Algo Trading' no habilitado (Tools → Options → Expert Advisors)"
            )
            return False

        terminal_info = mt5.terminal_info()
        if terminal_info:
            logger.info(
                f"Terminal MT5 conectado: {terminal_info.name} "
                f"build {terminal_info.build} (path={terminal_info.path})"
            )
            if not terminal_info.trade_allowed:
                logger.warning(
                    "⚠️  Trade NO permitido en el terminal. "
                    "Habilita 'Algo Trading' en Tools → Options → Expert Advisors."
                )

        # ─── Paso 2: login (sólo si hay credenciales) ───
        if self.settings.mt5_login and self.settings.mt5_password:
            login_ok = mt5.login(
                login=int(self.settings.mt5_login),
                password=self.settings.mt5_password,
                server=self.settings.mt5_server or None,
            )
            if not login_ok:
                err = mt5.last_error()
                logger.error(
                    f"mt5.login() falló — error {err}\n"
                    f"  Login configurado: {self.settings.mt5_login}\n"
                    f"  Server configurado: {self.settings.mt5_server!r}\n"
                    f"  Causas probables:\n"
                    f"  - Server name no exacto (ej 'ICMarkets-Demo' vs 'ICMarketsSC-Demo' vs 'ICMarkets-Demo01')\n"
                    f"  - Login/password incorrectos\n"
                    f"  - La cuenta es de otro broker (verifica en File → Login en MT5)\n"
                    f"  - La cuenta nunca se logueó en este terminal — abre MT5, File → Login,\n"
                    f"    introduce credenciales manualmente UNA vez y vuelve a correr el script."
                )
                mt5.shutdown()
                return False

        self._initialized = True
        info = self.account_info()
        if info:
            logger.info(
                f"MT5 logueado — login={info.login} server={info.server} "
                f"balance={info.balance:.2f} {info.currency} equity={info.equity:.2f}"
            )
        return True

    def shutdown(self) -> None:
        if MT5_AVAILABLE and self._initialized:
            mt5.shutdown()
            self._initialized = False
            logger.info("MT5 shutdown")

    @contextmanager
    def session(self) -> Iterator["MT5Client"]:
        """Context manager: with mt5_client.session() as c: ..."""
        if not self.initialize():
            raise RuntimeError("No se pudo conectar a MT5")
        try:
            yield self
        finally:
            self.shutdown()

    # ─────────────────────────────────────────────────────
    # Account / símbolos
    # ─────────────────────────────────────────────────────
    def account_info(self) -> AccountInfo | None:
        if not MT5_AVAILABLE:
            return None
        info = mt5.account_info()
        if info is None:
            return None
        return AccountInfo(
            login=info.login,
            server=info.server,
            name=info.name,
            currency=info.currency,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            leverage=info.leverage,
        )

    def symbol_info(self, broker_symbol: str) -> SymbolInfo | None:
        if not MT5_AVAILABLE:
            return None
        # Asegurar que el símbolo está en Market Watch
        if not mt5.symbol_select(broker_symbol, True):
            logger.warning(f"No se pudo seleccionar el símbolo {broker_symbol}")
            return None
        info = mt5.symbol_info(broker_symbol)
        tick = mt5.symbol_info_tick(broker_symbol)
        if info is None or tick is None:
            logger.warning(f"symbol_info devolvió None para {broker_symbol}")
            return None
        return SymbolInfo(
            name=info.name,
            bid=tick.bid,
            ask=tick.ask,
            spread=info.spread,
            digits=info.digits,
            trade_contract_size=info.trade_contract_size,
            volume_min=info.volume_min,
            volume_max=info.volume_max,
            volume_step=info.volume_step,
        )

    # ─────────────────────────────────────────────────────
    # Velas (candles)
    # ─────────────────────────────────────────────────────
    def get_rates(
        self,
        broker_symbol: str,
        timeframe: str = "M15",
        n_bars: int = 500,
        from_date: datetime | None = None,
    ) -> pd.DataFrame:
        """
        Obtiene las últimas `n_bars` velas. Si `from_date` se especifica, trae
        velas desde esa fecha hasta ahora (independiente de n_bars).
        Devuelve DataFrame con columnas: time, open, high, low, close, tick_volume, spread, real_volume.
        """
        if not MT5_AVAILABLE:
            logger.warning("MT5 no disponible — devolviendo DataFrame vacío")
            return pd.DataFrame()

        if timeframe not in TIMEFRAMES:
            raise ValueError(f"Timeframe no soportado: {timeframe}. Opciones: {list(TIMEFRAMES)}")

        tf = TIMEFRAMES[timeframe]
        if not mt5.symbol_select(broker_symbol, True):
            logger.warning(f"No se pudo seleccionar el símbolo {broker_symbol}")
            return pd.DataFrame()

        if from_date is not None:
            now = datetime.now(timezone.utc)
            rates = mt5.copy_rates_range(broker_symbol, tf, from_date, now)
        else:
            rates = mt5.copy_rates_from_pos(broker_symbol, tf, 0, n_bars)

        if rates is None or len(rates) == 0:
            logger.warning(f"copy_rates devolvió vacío para {broker_symbol} {timeframe}")
            return pd.DataFrame()

        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        return df

    # ─────────────────────────────────────────────────────
    # Posiciones (lectura)
    # ─────────────────────────────────────────────────────
    def positions(self, broker_symbol: str | None = None) -> list[dict]:
        if not MT5_AVAILABLE:
            return []
        positions = (
            mt5.positions_get(symbol=broker_symbol) if broker_symbol else mt5.positions_get()
        )
        if positions is None:
            return []
        return [pos._asdict() for pos in positions]


__all__ = [
    "MT5Client",
    "AccountInfo",
    "SymbolInfo",
    "MT5_AVAILABLE",
]
