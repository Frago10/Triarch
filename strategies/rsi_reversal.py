"""
Triarch — RSI_REVERSAL strategy.

Familia: mean.

Concepto:
  Reversión a la media basada en RSI: cuando el RSI sale de zona extrema
  (sobreventa < 30 → recompra al pasar 30; sobrecompra > 70 → recorta al bajar de 70)
  Y la vela actual confirma con una vela "de reversión" (martillo / shooting star
  rudimentario: cuerpo pequeño + mecha en dirección contraria).

  Esta strat es deliberadamente CONTRA-TENDENCIA. Solo opera en activos de
  perfil "calidad" o "scalper" con confluencia que confirme la reversión,
  para no chocar con strats de tendencia.

Lógica (long; short simétrico):
  1. RSI vela anterior < 30 (sobreventa).
  2. RSI vela actual > 32 (saliendo de sobreventa).
  3. close > open (vela alcista).
  4. La mecha inferior es >= 1.5 × el cuerpo (rechazo de mínimos = martillo).
  5. close < ema_50 (estamos en la parte baja de un swing más grande).

Niveles:
  - Entry: close.
  - SL: low de la vela actual - 0.1*ATR (debajo del mínimo del martillo).
  - TP1: entry + 1.5 × risk (reversión modesta, no buscamos giros macro).

Notas:
  · Win rate suele ser alto (>55%) pero RR bajo (1.2-1.5). Es el aporte de
    "WR alto" al mix de cada activo, sin romper la regla de RR mínimo.
  · No usar como única estrategia: la confluencia con strats de momentum
    filtra los falsos rebotes.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class RSIReversalStrategy(Strategy):
    name = "RSI_REVERSAL"
    family = "mean"

    def __init__(
        self,
        rsi_oversold: float = 30.0,
        rsi_exit_long: float = 32.0,
        rsi_overbought: float = 70.0,
        rsi_exit_short: float = 68.0,
        wick_to_body_min: float = 1.5,
        rr_target: float = 1.5,
        sl_buffer_atr: float = 0.1,
    ) -> None:
        self.rsi_oversold = rsi_oversold
        self.rsi_exit_long = rsi_exit_long
        self.rsi_overbought = rsi_overbought
        self.rsi_exit_short = rsi_exit_short
        self.wick_to_body_min = wick_to_body_min
        self.rr_target = rr_target
        self.sl_buffer_atr = sl_buffer_atr

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 40:
            return (
                self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"),
                None,
            )

        last = df.iloc[-1]
        prev = df.iloc[-2]
        atr = last.get("atr_14", np.nan)
        rsi_now = last.get("rsi_14", np.nan)
        rsi_prev = prev.get("rsi_14", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if any(pd.isna(x) for x in (atr, rsi_now, rsi_prev, ema_50)) or atr <= 0:
            return (
                self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"),
                None,
            )

        o = float(last["open"])
        c = float(last["close"])
        h = float(last["high"])
        l = float(last["low"])
        body = abs(c - o)
        body = max(body, 1e-12)
        upper_wick = h - max(c, o)
        lower_wick = min(c, o) - l

        # ─── Long martillo (rebote desde oversold) ───
        long_setup = (
            rsi_prev < self.rsi_oversold
            and rsi_now > self.rsi_exit_long
            and c > o
            and (lower_wick / body) >= self.wick_to_body_min
            and c < ema_50
        )
        # ─── Short shooting-star (rechazo desde overbought) ───
        short_setup = (
            rsi_prev > self.rsi_overbought
            and rsi_now < self.rsi_exit_short
            and c < o
            and (upper_wick / body) >= self.wick_to_body_min
            and c > ema_50
        )

        if long_setup:
            direction = Direction.LONG
            entry = c
            sl = l - self.sl_buffer_atr * atr
            risk_pts = entry - sl
            wick_ratio = lower_wick / body
        elif short_setup:
            direction = Direction.SHORT
            entry = c
            sl = h + self.sl_buffer_atr * atr
            risk_pts = sl - entry
            wick_ratio = upper_wick / body
        else:
            return (
                self._make_eval(
                    ctx,
                    detected=False,
                    blocked_by="no_reversal",
                    blocked_detail=f"rsi_prev={rsi_prev:.1f} rsi_now={rsi_now:.1f}",
                ),
                None,
            )

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        cfg_min_rr = ctx.symbol_cfg.risk.min_rr_ratio
        rr_eff = max(self.rr_target, cfg_min_rr)
        if direction is Direction.LONG:
            tp1 = entry + rr_eff * risk_pts
            tp2 = entry + (rr_eff + 0.8) * risk_pts
        else:
            tp1 = entry - rr_eff * risk_pts
            tp2 = entry - (rr_eff + 0.8) * risk_pts
        rr_ratio = abs(tp1 - entry) / risk_pts

        # ─── Score ───
        wick_score = float(min((wick_ratio - self.wick_to_body_min) / 2.0 + 0.5, 1.0))
        if direction is Direction.LONG:
            rsi_score = float(min((self.rsi_oversold - rsi_prev) / 10 + 0.5, 1.0))
        else:
            rsi_score = float(min((rsi_prev - self.rsi_overbought) / 10 + 0.5, 1.0))
        rsi_score = max(rsi_score, 0.0)
        score = float(np.clip(0.30 + 0.40 * wick_score + 0.20 * rsi_score, 0.0, 1.0))
        confidence = (
            Confidence.HIGH
            if score >= 0.7
            else Confidence.MEDIUM if score >= 0.5 else Confidence.LOW
        )

        signal = Signal(
            symbol=ctx.symbol_cfg.name,
            timeframe=ctx.symbol_cfg.timeframe,
            strategy=self.name,
            family=self.family,
            direction=direction,
            entry=float(entry),
            stop_loss=float(sl),
            take_profit_1=float(tp1),
            take_profit_2=float(tp2),
            score=score,
            confidence=confidence,
            risk_pts=float(risk_pts),
            reward_pts_tp1=float(abs(tp1 - entry)),
            rr_ratio=float(rr_ratio),
            atr_at_signal=float(atr),
            features={
                "rsi_prev": float(rsi_prev),
                "rsi_now": float(rsi_now),
                "wick_to_body": float(wick_ratio),
            },
        )
        return (
            self._make_eval(
                ctx,
                detected=True,
                direction=direction,
                score=score,
                proposed_entry=float(entry),
                emitted_signal_id=signal.signal_id,
            ),
            signal,
        )
