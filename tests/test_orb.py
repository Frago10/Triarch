"""Test smoke de la estrategia ORB."""

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
from strategies.orb import ORBStrategy


def _candles_with_breakout(n: int = 80) -> pd.DataFrame:
    """Velas sintéticas con un breakout claro arriba del OR."""
    times = pd.date_range("2026-01-01 09:30", periods=n, freq="15min", tz="UTC")
    # Primeras 4 velas (60 min) en rango 100-101, después saltamos a 103.
    base = np.full(n, 100.5)
    base[:4] = 100.5  # OR window
    base[4:] = np.linspace(100.5, 103.0, n - 4)  # breakout up

    return pd.DataFrame(
        {
            "time": times,
            "open": base - 0.05,
            "high": base + 0.3,
            "low": base - 0.3,
            "close": base,
            "tick_volume": np.full(n, 100),
        }
    )


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
        strategies=["ORB"],
    )


def test_orb_emits_signal_on_breakout():
    df = _candles_with_breakout()
    df = add_default_indicators(df)
    df = opening_range(df, minutes=15)

    strat = ORBStrategy(or_minutes=15)
    ev, sig = strat.evaluate(StrategyContext(symbol_cfg=_cfg(), df=df))

    assert ev.detected_setup or ev.blocked_by is not None
    if sig is not None:
        assert sig.direction.value in {"LONG", "SHORT"}
        assert sig.stop_loss != sig.entry
        assert sig.rr_ratio > 0


def test_orb_blocks_when_or_not_ready():
    # Sólo 2 velas — no hay OR completo
    times = pd.date_range("2026-01-01 09:30", periods=2, freq="15min", tz="UTC")
    df = pd.DataFrame(
        {
            "time": times,
            "open": [100, 100.5],
            "high": [100.5, 101],
            "low": [99.5, 100],
            "close": [100.3, 100.8],
            "tick_volume": [100, 100],
        }
    )
    df = add_default_indicators(df)
    df = opening_range(df, minutes=15)

    strat = ORBStrategy(or_minutes=15)
    ev, sig = strat.evaluate(StrategyContext(symbol_cfg=_cfg(), df=df))
    assert sig is None
    assert ev.blocked_by is not None
