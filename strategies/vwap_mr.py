"""
Triarch — VWAP Mean Reversion strategy.

Familia: mean.

Lógica:
  - Calcula VWAP intraday + ATR.
  - Si la última vela cierra > vwap + N*ATR  → SHORT (esperando reversión a VWAP).
  - Si la última vela cierra < vwap - N*ATR  → LONG.
  - SL: al lado opuesto del extremo (high/low de la barra trigger) + buffer ATR.
  - TP1: vuelta a VWAP.
  - TP2: VWAP - 0.3*deviation extra (ligera continuación).

Filtros (anti-trend protection):
  - Skipped si las EMAs están MUY alineadas (regime trending claro).
  - Score más alto si la desviación es grande pero el rango ATR no es explosivo.

Risk:
  - SL puede salir muy chico si la barra trigger es pequeña — minimo SL = 0.5*ATR.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class VWAPMeanReversionStrategy(Strategy):
    name = "VWAP_MR"
    family = "mean"

    def __init__(
        self,
        deviation_atr: float = 1.5,
        min_sl_atr: float = 0.5,
        rr_target: float = 1.5,
        rr_target_tp2: float = 2.5,
        skip_strong_trend_atr: float = 1.0,
    ) -> None:
        self.deviation_atr = deviation_atr
        self.min_sl_atr = min_sl_atr
        self.rr_target = rr_target
        self.rr_target_tp2 = rr_target_tp2
        self.skip_strong_trend_atr = skip_strong_trend_atr

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 50:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        last = df.iloc[-1]
        atr = last.get("atr_14", np.nan)
        vwap = last.get("vwap", np.nan)
        if pd.isna(atr) or atr <= 0 or pd.isna(vwap):
            return self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"), None

        close = last["close"]
        deviation = close - vwap
        deviation_in_atr = deviation / atr

        # ─── Filtro anti-trend: si las EMAs están MUY separadas, no operamos MR ───
        ema_9 = last.get("ema_9", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if not pd.isna(ema_9) and not pd.isna(ema_50):
            ema_spread = abs(ema_9 - ema_50) / atr
            if ema_spread > self.skip_strong_trend_atr:
                return (
                    self._make_eval(
                        ctx, detected=False, blocked_by="strong_trend",
                        blocked_detail=f"ema_spread {ema_spread:.2f} > {self.skip_strong_trend_atr}",
                    ),
                    None,
                )

        # ─── Detección setup ───
        direction: Direction | None = None
        if deviation_in_atr >= self.deviation_atr:
            direction = Direction.SHORT      # precio muy arriba → reversión bajista
        elif deviation_in_atr <= -self.deviation_atr:
            direction = Direction.LONG       # precio muy abajo → reversión alcista
        else:
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="no_deviation",
                    blocked_detail=f"dev={deviation_in_atr:.2f} ATR",
                ),
                None,
            )

        # ─── Niveles ───
        entry = close
        if direction == Direction.LONG:
            sl_raw = last["low"] - 0.1 * atr
            risk_pts = entry - sl_raw
            if risk_pts < self.min_sl_atr * atr:
                stop_loss = entry - self.min_sl_atr * atr
                risk_pts = entry - stop_loss
            else:
                stop_loss = sl_raw
            take_profit_1 = vwap                                    # vuelta a VWAP
            take_profit_2 = vwap + 0.3 * abs(deviation)             # ligera continuación
        else:
            sl_raw = last["high"] + 0.1 * atr
            risk_pts = sl_raw - entry
            if risk_pts < self.min_sl_atr * atr:
                stop_loss = entry + self.min_sl_atr * atr
                risk_pts = stop_loss - entry
            else:
                stop_loss = sl_raw
            take_profit_1 = vwap
            take_profit_2 = vwap - 0.3 * abs(deviation)

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        reward_pts_tp1 = abs(take_profit_1 - entry)
        if reward_pts_tp1 <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="zero_reward"), None
        rr_ratio = reward_pts_tp1 / risk_pts

        # ─── Score ───
        # Mayor desviación = mejor (clip 0..3 ATR → 0..1)
        deviation_strength = min(abs(deviation_in_atr) / 3.0, 1.0)
        # RSI extremo es bonus (oversold/overbought confirman MR)
        rsi = last.get("rsi_14", 50.0)
        if pd.isna(rsi):
            rsi_bonus = 0.0
        else:
            if direction == Direction.LONG and rsi < 30:
                rsi_bonus = (30 - rsi) / 30
            elif direction == Direction.SHORT and rsi > 70:
                rsi_bonus = (rsi - 70) / 30
            else:
                rsi_bonus = 0.0
        score = float(np.clip(0.4 + 0.4 * deviation_strength + 0.2 * rsi_bonus, 0.0, 1.0))
        confidence = Confidence.HIGH if score >= 0.7 else Confidence.MEDIUM if score >= 0.5 else Confidence.LOW

        signal = Signal(
            symbol=ctx.symbol_cfg.name,
            timeframe=ctx.symbol_cfg.timeframe,
            strategy=self.name,
            family=self.family,
            direction=direction,
            entry=float(entry),
            stop_loss=float(stop_loss),
            take_profit_1=float(take_profit_1),
            take_profit_2=float(take_profit_2),
            score=score,
            confidence=confidence,
            risk_pts=float(risk_pts),
            reward_pts_tp1=float(reward_pts_tp1),
            rr_ratio=float(rr_ratio),
            atr_at_signal=float(atr),
            features={
                "vwap": float(vwap),
                "deviation_in_atr": float(deviation_in_atr),
                "rsi_14": float(rsi) if not pd.isna(rsi) else None,
                "ema_9": float(ema_9) if not pd.isna(ema_9) else None,
                "ema_50": float(ema_50) if not pd.isna(ema_50) else None,
            },
        )
        return (
            self._make_eval(
                ctx, detected=True, direction=direction, score=score,
                proposed_entry=float(entry), emitted_signal_id=signal.signal_id,
            ),
            signal,
        )
