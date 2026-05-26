"""
Triarch — indicadores técnicos.

Implementaciones desde primeros principios sobre pandas. No dependemos de TA-Lib
para mantener portabilidad. Para volumen serio, en v2 evaluamos `pandas-ta`.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential moving average."""
    return series.ewm(span=period, adjust=False).mean()


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(period).mean()


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """
    Average True Range. Espera columnas high, low, close.
    """
    h, l, c = df["high"], df["low"], df["close"]
    prev_c = c.shift(1)
    tr = pd.concat([(h - l), (h - prev_c).abs(), (l - prev_c).abs()], axis=1).max(
        axis=1
    )
    return tr.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(span=period, adjust=False).mean()
    avg_loss = loss.ewm(span=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50.0)


def vwap(df: pd.DataFrame, group_by_day: bool = True) -> pd.Series:
    """
    Volume-weighted average price. Si `group_by_day`, resetea por día (intra-day VWAP).
    Espera columnas: time, high, low, close, tick_volume.
    """
    typical = (df["high"] + df["low"] + df["close"]) / 3.0
    vol = df["tick_volume"]
    if group_by_day:
        day = df["time"].dt.date
        cum_vol = vol.groupby(day).cumsum()
        cum_pv = (typical * vol).groupby(day).cumsum()
    else:
        cum_vol = vol.cumsum()
        cum_pv = (typical * vol).cumsum()
    return cum_pv / cum_vol.replace(0, np.nan)


def bollinger(
    series: pd.Series, period: int = 20, stdev_mult: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands. Devuelve DataFrame con columnas mid, upper, lower, width."""
    mid = series.rolling(period).mean()
    sd = series.rolling(period).std()
    upper = mid + stdev_mult * sd
    lower = mid - stdev_mult * sd
    width = (upper - lower) / mid
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "width": width})


def opening_range(df: pd.DataFrame, minutes: int = 15) -> pd.DataFrame:
    """
    Calcula el opening range del día (primeros `minutes` minutos por día).
    Devuelve DataFrame con columnas: or_high, or_low, or_complete (bool).

    Espera df ordenado y con columna `time` (UTC).
    """
    df = df.copy()
    df["date"] = df["time"].dt.date
    df["minute_of_day"] = df["time"].dt.hour * 60 + df["time"].dt.minute

    or_rows: list[dict] = []
    for day, group in df.groupby("date", sort=False):
        first_min = group["minute_of_day"].iloc[0]
        cutoff = first_min + minutes
        or_window = group[group["minute_of_day"] < cutoff]
        if len(or_window) == 0:
            continue
        or_high = or_window["high"].max()
        or_low = or_window["low"].min()
        or_rows.append({"date": day, "or_high": or_high, "or_low": or_low})

    or_df = (
        pd.DataFrame(or_rows).set_index("date")
        if or_rows
        else pd.DataFrame(columns=["or_high", "or_low"])
    )

    df = df.merge(or_df, left_on="date", right_index=True, how="left")
    df["or_complete"] = df["minute_of_day"] >= (
        df.groupby("date")["minute_of_day"].transform("min") + minutes
    )
    return df.drop(columns=["date", "minute_of_day"])


def keltner(
    df: pd.DataFrame, ema_period: int = 20, atr_period: int = 14, atr_mult: float = 2.0
) -> pd.DataFrame:
    """
    Keltner Channels — banda central EMA + bandas a ±atr_mult × ATR.
    Más estables que Bollinger en mercados con volatilidad cambiante porque
    el ancho lo dicta el ATR (volatilidad real) en vez del stdev del precio.
    """
    mid = ema(df["close"], ema_period)
    a = atr(df, atr_period)
    upper = mid + atr_mult * a
    lower = mid - atr_mult * a
    width = (upper - lower) / mid
    return pd.DataFrame({"mid": mid, "upper": upper, "lower": lower, "width": width})


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """
    Donchian Channels — máximo y mínimo de las últimas `period` velas (excluyendo
    la actual para evitar look-ahead). Base de Turtle Trading.
    """
    high = df["high"].rolling(period).max().shift(1)
    low = df["low"].rolling(period).min().shift(1)
    mid = (high + low) / 2.0
    return pd.DataFrame({"upper": high, "lower": low, "mid": mid})


def macd(
    series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    """
    MACD clásico — diff de EMA rápida y lenta, más su línea de señal.
    """
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    sig_line = ema(macd_line, signal)
    hist = macd_line - sig_line
    return pd.DataFrame({"macd": macd_line, "signal": sig_line, "hist": hist})


def add_default_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Añade en su sitio el set de indicadores por defecto."""
    df = df.copy()
    df["ema_9"] = ema(df["close"], 9)
    df["ema_20"] = ema(df["close"], 20)
    df["ema_21"] = ema(df["close"], 21)
    df["ema_50"] = ema(df["close"], 50)
    df["ema_200"] = ema(df["close"], 200)
    df["atr_14"] = atr(df, 14)
    df["rsi_14"] = rsi(df["close"], 14)
    bb = bollinger(df["close"], 20, 2.0)
    df["bb_mid"] = bb["mid"]
    df["bb_upper"] = bb["upper"]
    df["bb_lower"] = bb["lower"]
    df["bb_width"] = bb["width"]
    # ─── Keltner Channels (ATR-based, complementa BB) ───
    kc = keltner(df, ema_period=20, atr_period=14, atr_mult=2.0)
    df["kc_mid"] = kc["mid"]
    df["kc_upper"] = kc["upper"]
    df["kc_lower"] = kc["lower"]
    df["kc_width"] = kc["width"]
    # ─── Donchian Channels (breakouts estructurales) ───
    dc = donchian(df, period=20)
    df["dc_upper"] = dc["upper"]
    df["dc_lower"] = dc["lower"]
    df["dc_mid"] = dc["mid"]
    # ─── MACD ───
    m = macd(df["close"])
    df["macd"] = m["macd"]
    df["macd_signal"] = m["signal"]
    df["macd_hist"] = m["hist"]
    if "tick_volume" in df.columns:
        df["vwap"] = vwap(df)
    return df
