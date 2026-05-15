"""
Triarch — EMA Momentum strategy.

Familia: trend.

Lógica (long; short es simétrico):
  1. Las EMAs deben estar alineadas: ema_9 > ema_21 > ema_50 (long).
  2. La pendiente de la ema_21 debe ser positiva (sube en las últimas 5 barras).
  3. La barra actual debe ser un PULLBACK que toque o cruce la ema_21 desde arriba
     pero cierre POR ENCIMA de ella (rebote confirmado).
  4. La distancia close-ema_21 debe ser pequeña (< 0.5*ATR) — entrada cerca del soporte dinámico.

Niveles:
  - Entry: close.
  - SL: max( ema_50 - 0.2*ATR ; swing low de las últimas 10 barras - 0.1*ATR ).
  - TP1: entry + 1.5 * risk_pts
  - TP2: entry + 2.5 * risk_pts

Score:
  - Más alto si la pendiente es fuerte y el pullback es preciso (close ~ ema_21).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class EMAMomentumStrategy(Strategy):
    name = "EMA_MOMENTUM"
    family = "trend"

    def __init__(
        self,
        slope_lookback: int = 5,
        max_pullback_atr: float = 0.5,
        rr_target: float = 1.5,
        rr_target_tp2: float = 2.5,
        sl_atr_buffer: float = 0.2,
    ) -> None:
        self.slope_lookback = slope_lookback
        self.max_pullback_atr = max_pullback_atr
        self.rr_target = rr_target
        self.rr_target_tp2 = rr_target_tp2
        self.sl_atr_buffer = sl_atr_buffer

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 60:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        last = df.iloc[-1]
        atr = last.get("atr_14", np.nan)
        ema_9 = last.get("ema_9", np.nan)
        ema_21 = last.get("ema_21", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if any(pd.isna(x) or (x is not None and x != x) for x in (atr, ema_9, ema_21, ema_50)):
            return self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"), None
        if atr <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="atr_zero"), None

        close = last["close"]
        # ─── Alineamiento + pendiente ───
        long_alignment = ema_9 > ema_21 > ema_50
        short_alignment = ema_9 < ema_21 < ema_50

        # Pendiente de ema_21 — diff entre la actual y la de hace `slope_lookback` barras
        if len(df) <= self.slope_lookback:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars_slope"), None
        slope = ema_21 - df["ema_21"].iloc[-1 - self.slope_lookback]
        slope_in_atr = slope / atr if atr > 0 else 0.0

        direction: Direction | None = None
        if long_alignment and slope_in_atr > 0.05:
            direction = Direction.LONG
        elif short_alignment and slope_in_atr < -0.05:
            direction = Direction.SHORT
        else:
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="no_alignment",
                    blocked_detail=f"long={long_alignment} short={short_alignment} slope={slope_in_atr:.3f}",
                ),
                None,
            )

        # ─── Detección de pullback a ema_21 ───
        # El pullback es válido si:
        #   - LONG: low de la barra <= ema_21 (tocó la EMA) Y close > ema_21 (rebote)
        #   - SHORT: high >= ema_21 Y close < ema_21
        if direction == Direction.LONG:
            touched = last["low"] <= ema_21 + 0.1 * atr
            bounced = close > ema_21
            distance = close - ema_21
        else:
            touched = last["high"] >= ema_21 - 0.1 * atr
            bounced = close < ema_21
            distance = ema_21 - close

        if not (touched and bounced):
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="no_pullback",
                    blocked_detail=f"touched={touched} bounced={bounced}",
                ),
                None,
            )

        if distance / atr > self.max_pullback_atr:
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="entry_too_far",
                    blocked_detail=f"distance/atr={distance/atr:.2f} > {self.max_pullback_atr}",
                ),
                None,
            )

        # ─── Niveles ───
        # RR efectivo: respeta cfg.risk.min_rr_ratio del símbolo si es más alto
        cfg_min_rr = ctx.symbol_cfg.risk.min_rr_ratio
        rr_target_eff = max(self.rr_target, cfg_min_rr)
        rr_target_tp2_eff = max(self.rr_target_tp2, rr_target_eff + 1.0)

        # Swing low/high reciente
        recent = df.tail(10)
        if direction == Direction.LONG:
            swing_low = recent["low"].min()
            sl_candidate = min(ema_50 - self.sl_atr_buffer * atr, swing_low - 0.1 * atr)
            entry = close
            risk_pts = entry - sl_candidate
            stop_loss = sl_candidate
            take_profit_1 = entry + rr_target_eff * risk_pts
            take_profit_2 = entry + rr_target_tp2_eff * risk_pts
        else:
            swing_high = recent["high"].max()
            sl_candidate = max(ema_50 + self.sl_atr_buffer * atr, swing_high + 0.1 * atr)
            entry = close
            risk_pts = sl_candidate - entry
            stop_loss = sl_candidate
            take_profit_1 = entry - rr_target_eff * risk_pts
            take_profit_2 = entry - rr_target_tp2_eff * risk_pts

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        rr_ratio = abs(take_profit_1 - entry) / risk_pts

        # ─── Score ───
        slope_strength = min(abs(slope_in_atr) * 4, 1.0)            # 0..1
        pullback_precision = 1.0 - min(distance / (self.max_pullback_atr * atr), 1.0)  # close al ema21 = 1
        score = float(np.clip(0.35 + 0.4 * slope_strength + 0.25 * pullback_precision, 0.0, 1.0))
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
            reward_pts_tp1=float(abs(take_profit_1 - entry)),
            rr_ratio=float(rr_ratio),
            atr_at_signal=float(atr),
            features={
                "ema_9": float(ema_9),
                "ema_21": float(ema_21),
                "ema_50": float(ema_50),
                "slope_in_atr": float(slope_in_atr),
                "pullback_distance_atr": float(distance / atr),
            },
        )
        return (
            self._make_eval(
                ctx, detected=True, direction=direction, score=score,
                proposed_entry=float(entry), emitted_signal_id=signal.signal_id,
            ),
            signal,
        )
