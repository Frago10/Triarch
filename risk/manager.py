"""
Triarch — Risk Manager.

Heredado del esqueleto en [[Roybot - Risk management]] del vault.
Extendido para multi-activo y para emitir Eval rejection events.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timezone
from enum import Enum
from typing import Iterable

from config.settings import SymbolConfig
from signals.schema import Signal


class LockReason(str, Enum):
    NONE = "none"
    KILL_SWITCH = "kill_switch"
    CONSEC_LOSSES = "consec_losses"
    DAILY_CAP = "daily_cap"
    MAX_TRADES = "max_trades"
    OUT_OF_WINDOW = "out_of_window"
    NEWS_BLOCK = "news_block"
    ACTIVE_TRADE = "active_trade"
    RR_TOO_LOW = "rr_too_low"
    SLIPPAGE_GUARD = "slippage_guard"


@dataclass
class SymbolRiskState:
    """Estado dinámico de risk **por activo**."""

    symbol: str
    daily_pnl: float = 0.0
    consec_losses: int = 0
    trades_today: int = 0
    high_water_mark: float = 0.0
    active_trade: bool = False
    last_session_date: date | None = None
    locked: bool = False
    lock_reason: LockReason = LockReason.NONE

    def reset_session(self, today: date) -> None:
        """Llamar al inicio del día para resetear contadores diarios."""
        self.daily_pnl = 0.0
        self.consec_losses = 0
        self.trades_today = 0
        self.active_trade = False
        self.locked = False
        self.lock_reason = LockReason.NONE
        self.last_session_date = today


@dataclass
class RiskDecision:
    accepted: bool
    reason: LockReason
    detail: str = ""

    @classmethod
    def ok(cls) -> "RiskDecision":
        return cls(accepted=True, reason=LockReason.NONE)

    @classmethod
    def block(cls, reason: LockReason, detail: str = "") -> "RiskDecision":
        return cls(accepted=False, reason=reason, detail=detail)


class RiskManager:
    """
    Risk manager **por símbolo**. Mantiene un estado por activo y aplica
    los lock-outs heredados de Roybot.

    Uso:
        rm = RiskManager(symbols=load_symbols(), kill_switch=False, account_equity=10000)
        decision = rm.can_take_signal(signal, now=datetime.utcnow())
        if decision.accepted:
            ...
        rm.on_trade_close(symbol, pnl_money=...)
    """

    def __init__(
        self,
        symbols: dict[str, SymbolConfig],
        kill_switch: bool = False,
        account_equity: float = 10_000.0,
    ) -> None:
        self.symbols = symbols
        self.kill_switch = kill_switch
        self.account_equity = account_equity
        self.state: dict[str, SymbolRiskState] = {
            name: SymbolRiskState(symbol=name) for name in symbols
        }

    # ─────────────────────────────────────────────────────
    # API pública
    # ─────────────────────────────────────────────────────
    def can_take_signal(
        self,
        signal: Signal,
        now: datetime | None = None,
    ) -> RiskDecision:
        """Decide si una señal puede ser tomada. Devuelve RiskDecision."""
        if now is None:
            now = datetime.now(timezone.utc)

        if self.kill_switch:
            return RiskDecision.block(LockReason.KILL_SWITCH, "Kill switch global activado")

        if signal.symbol not in self.symbols:
            return RiskDecision.block(LockReason.NONE, f"Símbolo desconocido: {signal.symbol}")

        cfg = self.symbols[signal.symbol]
        st = self.state[signal.symbol]

        # Reset diario si cambió el día
        self._ensure_session(st, now)

        # Lock-outs en orden de prioridad
        if st.active_trade:
            return RiskDecision.block(LockReason.ACTIVE_TRADE, "Ya hay trade activo en este activo")

        if not self._in_window(now, cfg):
            return RiskDecision.block(
                LockReason.OUT_OF_WINDOW,
                f"Fuera de ventana {cfg.session_utc.start}-{cfg.session_utc.end} UTC",
            )

        max_daily_loss_money = -abs(self.account_equity * cfg.risk.max_daily_loss_pct / 100.0)
        if st.daily_pnl <= max_daily_loss_money:
            return RiskDecision.block(
                LockReason.DAILY_CAP,
                f"Daily loss cap alcanzado: {st.daily_pnl:.2f} <= {max_daily_loss_money:.2f}",
            )

        if st.consec_losses >= cfg.risk.max_consec_losses:
            return RiskDecision.block(
                LockReason.CONSEC_LOSSES,
                f"Pérdidas consecutivas: {st.consec_losses}",
            )

        if st.trades_today >= cfg.risk.max_trades_per_day:
            return RiskDecision.block(
                LockReason.MAX_TRADES,
                f"Cap de trades hoy: {st.trades_today}/{cfg.risk.max_trades_per_day}",
            )

        if signal.rr_ratio < cfg.risk.min_rr_ratio:
            return RiskDecision.block(
                LockReason.RR_TOO_LOW,
                f"R:R {signal.rr_ratio:.2f} < min {cfg.risk.min_rr_ratio}",
            )

        # Slippage filter — sólo aplica si el signal tiene atr_deviation calculado
        if signal.atr_deviation is not None:
            from config.settings import get_settings  # lazy
            max_slip = get_settings().risk_max_slippage_atr
            if signal.atr_deviation > max_slip:
                return RiskDecision.block(
                    LockReason.SLIPPAGE_GUARD,
                    f"ATR deviation {signal.atr_deviation:.2f} > {max_slip}",
                )

        return RiskDecision.ok()

    def on_trade_open(self, symbol: str, now: datetime | None = None) -> None:
        st = self.state[symbol]
        self._ensure_session(st, now)
        st.active_trade = True

    def on_trade_close(self, symbol: str, pnl_money: float, now: datetime | None = None) -> None:
        st = self.state[symbol]
        self._ensure_session(st, now)
        st.daily_pnl += pnl_money
        st.trades_today += 1
        if pnl_money > 0:
            st.consec_losses = 0
            st.high_water_mark = max(st.high_water_mark, st.daily_pnl)
        else:
            st.consec_losses += 1
        st.active_trade = False

    def _ensure_session(self, st: SymbolRiskState, now: datetime | None) -> None:
        """Garantiza que el state está en la sesión del día actual (UTC)."""
        if now is None:
            now = datetime.now(timezone.utc)
        today = now.date()
        if st.last_session_date != today:
            st.reset_session(today)

    def snapshot(self) -> dict[str, dict]:
        """Para el dashboard. Devuelve estado actual por activo."""
        out: dict[str, dict] = {}
        for name, st in self.state.items():
            out[name] = {
                "daily_pnl": st.daily_pnl,
                "consec_losses": st.consec_losses,
                "trades_today": st.trades_today,
                "high_water_mark": st.high_water_mark,
                "active_trade": st.active_trade,
                "locked": st.locked,
                "lock_reason": st.lock_reason.value,
            }
        return out

    # ─────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────
    def _in_window(self, now: datetime, cfg: SymbolConfig) -> bool:
        start, end = cfg.session_utc.to_times()
        t = now.time()
        # Si end < start, ventana cruza medianoche (no aplica acá pero por completitud)
        if end < start:
            return t >= start or t <= end
        return start <= t <= end


__all__ = [
    "RiskManager",
    "RiskDecision",
    "LockReason",
    "SymbolRiskState",
]
