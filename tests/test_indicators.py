"""Tests básicos de indicators."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engine.indicators import atr, ema, opening_range, rsi, sma


def _synthetic_candles(n: int = 100, freq: str = "15min") -> pd.DataFrame:
    rng = np.random.default_rng(42)
    times = pd.date_range("2026-01-01 09:00", periods=n, freq=freq, tz="UTC")
    base = 100 + np.cumsum(rng.standard_normal(n))
    high = base + rng.uniform(0.1, 0.5, n)
    low = base - rng.uniform(0.1, 0.5, n)
    close = base + rng.uniform(-0.2, 0.2, n)
    return pd.DataFrame(
        {
            "time": times,
            "open": base,
            "high": high,
            "low": low,
            "close": close,
            "tick_volume": rng.integers(50, 500, n),
        }
    )


def test_ema_length():
    df = _synthetic_candles()
    out = ema(df["close"], 9)
    assert len(out) == len(df)
    assert not out.iloc[-1] != out.iloc[-1]  # not NaN


def test_atr_positive():
    df = _synthetic_candles()
    out = atr(df, 14)
    assert (out.dropna() > 0).all()


def test_rsi_range():
    df = _synthetic_candles()
    out = rsi(df["close"], 14)
    assert ((out >= 0) & (out <= 100)).all()


def test_opening_range_creates_columns():
    df = _synthetic_candles(n=80, freq="15min")
    out = opening_range(df, minutes=15)
    assert "or_high" in out.columns
    assert "or_low" in out.columns
    assert "or_complete" in out.columns
    # Cada día tiene un OR
    assert out["or_high"].notna().any()
