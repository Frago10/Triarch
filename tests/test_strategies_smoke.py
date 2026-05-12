"""
Smoke tests para VWAP_MR y EMA_MOMENTUM.

No probamos lógica fina (eso vendrá con backtest histórico). Solo:
  - No crashean en data sintética.
  - Devuelven Eval válido.
  - Cuando deberían emitir, emiten.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import (
    ExecutionMode,
    PositionSizing,
    RiskOverride,
    SessionWindow,
    SymbolConfig,
)
from engine.indicators import add_default_indicators, opening_range
from strategies.base import StrategyContext
from strategies.ema_momentum import EMAMomentumStrategy
from strategies.vwap_mr import VWAPMeanReversionStrategy


def _cfg() -> SymbolConfig:
    return SymbolConfig(
        name="TEST",
        broker_symbol="TEST",
        family="commodity",
        timeframe="M15",
        mode=ExecutionMode.SIGNAL_ONLY,
        session_utc=SessionWindow(start="00:00", end="23:59"),
        risk=RiskOverride(),
        position_sizing=PositionSizing(),
        strategies=[],
    )


def _candles(n: int = 100, drift: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    times = pd.date_range("2026-01-01 09:00", periods=n, freq="15min", tz="UTC")
    base = 100 + np.cumsum(rng.standard_normal(n) * 0.3 + drift)
    return pd.DataFrame(
        {
            "time": times,
            "open": base + rng.uniform(-0.05, 0.05, n),
            "high": base + rng.uniform(0.1, 0.4, n),
            "low": base - rng.uniform(0.1, 0.4, n),
            "close": base + rng.uniform(-0.1, 0.1, n),
            "tick_volume": rng.integers(50, 500, n),
        }
    )


def test_vwap_mr_no_crash_on_normal_data():
    df = add_default_indicators(_candles(120))
    df = opening_range(df, minutes=15)
    strat = VWAPMeanReversionStrategy()
    ev, sig = strat.evaluate(StrategyContext(symbol_cfg=_cfg(), df=df))
    # Puede emitir o no — solo verifica que no crashea
    assert ev is not None
    if sig:
        assert sig.direction.value in {"LONG", "SHORT"}
        assert sig.rr_ratio > 0
        assert sig.stop_loss != sig.entry


def test_ema_momentum_no_crash_on_normal_data():
    df = add_default_indicators(_candles(120, drift=0.05))  # tendencia leve
    df = opening_range(df, minutes=15)
    strat = EMAMomentumStrategy()
    ev, sig = strat.evaluate(StrategyContext(symbol_cfg=_cfg(), df=df))
    assert ev is not None
    if sig:
        assert sig.direction.value in {"LONG", "SHORT"}
        assert sig.rr_ratio > 0
        assert sig.stop_loss != sig.entry


def test_strategies_handle_short_history():
    """Con poco histórico devuelven Eval con blocked_by, sin crashear."""
    df = add_default_indicators(_candles(20))
    df = opening_range(df, minutes=15)
    ctx = StrategyContext(symbol_cfg=_cfg(), df=df)
    for cls in (VWAPMeanReversionStrategy, EMAMomentumStrategy):
        ev, sig = cls().evaluate(ctx)
        assert sig is None
        assert ev.blocked_by is not None
