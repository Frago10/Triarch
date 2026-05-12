"""Tests del Risk Manager."""
from __future__ import annotations

from datetime import datetime, time as dtime, timezone

import pytest

from config.settings import (
    ExecutionMode,
    PositionSizing,
    RiskOverride,
    SessionWindow,
    SymbolConfig,
)
from risk.manager import LockReason, RiskManager
from signals.schema import Confidence, Direction, Signal


def _cfg(name: str = "XAUUSD") -> SymbolConfig:
    return SymbolConfig(
        name=name,
        broker_symbol=name,
        family="commodity",
        timeframe="M15",
        mode=ExecutionMode.SIGNAL_ONLY,
        session_utc=SessionWindow(start="00:00", end="23:59"),
        risk=RiskOverride(
            max_daily_loss_pct=2.0,
            max_consec_losses=3,
            max_trades_per_day=5,
            min_rr_ratio=1.5,
        ),
        position_sizing=PositionSizing(),
        strategies=["ORB"],
    )


def _signal(symbol: str = "XAUUSD", rr: float = 2.0) -> Signal:
    return Signal(
        symbol=symbol,
        timeframe="M15",
        strategy="ORB",
        family="opening",
        direction=Direction.LONG,
        entry=2000.0,
        stop_loss=1995.0,
        take_profit_1=2010.0,
        take_profit_2=2015.0,
        score=0.7,
        confidence=Confidence.MEDIUM,
        risk_pts=5.0,
        reward_pts_tp1=10.0,
        rr_ratio=rr,
    )


def test_accepts_valid_signal():
    rm = RiskManager(symbols={"XAUUSD": _cfg()})
    decision = rm.can_take_signal(_signal())
    assert decision.accepted, decision.detail


def test_blocks_low_rr():
    rm = RiskManager(symbols={"XAUUSD": _cfg()})
    decision = rm.can_take_signal(_signal(rr=1.0))
    assert not decision.accepted
    assert decision.reason == LockReason.RR_TOO_LOW


def test_blocks_after_consec_losses():
    rm = RiskManager(symbols={"XAUUSD": _cfg()})
    for _ in range(3):
        rm.on_trade_close("XAUUSD", pnl_money=-10.0)
    decision = rm.can_take_signal(_signal())
    assert not decision.accepted
    assert decision.reason == LockReason.CONSEC_LOSSES


def test_blocks_after_daily_cap():
    rm = RiskManager(symbols={"XAUUSD": _cfg()}, account_equity=1000.0)
    # 2% de 1000 = 20 USD. Pongamos -25.
    rm.on_trade_close("XAUUSD", pnl_money=-25.0)
    decision = rm.can_take_signal(_signal())
    assert not decision.accepted
    assert decision.reason == LockReason.DAILY_CAP


def test_kill_switch_blocks_everything():
    rm = RiskManager(symbols={"XAUUSD": _cfg()}, kill_switch=True)
    decision = rm.can_take_signal(_signal())
    assert not decision.accepted
    assert decision.reason == LockReason.KILL_SWITCH


def test_blocks_active_trade():
    rm = RiskManager(symbols={"XAUUSD": _cfg()})
    rm.on_trade_open("XAUUSD")
    decision = rm.can_take_signal(_signal())
    assert not decision.accepted
    assert decision.reason == LockReason.ACTIVE_TRADE


def test_blocks_out_of_window():
    cfg = _cfg()
    cfg.session_utc = SessionWindow(start="08:00", end="10:00")
    rm = RiskManager(symbols={"XAUUSD": cfg})
    # 14:00 UTC fuera de ventana
    when = datetime(2026, 5, 5, 14, 0, tzinfo=timezone.utc)
    decision = rm.can_take_signal(_signal(), now=when)
    assert not decision.accepted
    assert decision.reason == LockReason.OUT_OF_WINDOW


def test_session_resets_daily():
    rm = RiskManager(symbols={"XAUUSD": _cfg()})
    today = datetime(2026, 5, 5, 12, 0, tzinfo=timezone.utc)
    rm.on_trade_close("XAUUSD", pnl_money=-10.0, now=today)
    # cambio de día
    next_day = datetime(2026, 5, 6, 12, 0, tzinfo=timezone.utc)
    decision = rm.can_take_signal(_signal(), now=next_day)
    # Debería aceptar — daily contadores reseteados
    assert decision.accepted
    assert rm.state["XAUUSD"].daily_pnl == 0.0
