"""
Triarch — ORB (Opening Range Breakout) strategy.

La más documentada en literatura, fácil de validar (Roybot la considera fundamental).

Lógica:
  1. Define un opening range = primeros N minutos de la sesión definida en symbols.yaml.
  2. Si la vela actual cierra por encima de OR-high → LONG.
  3. Si cierra por debajo de OR-low → SHORT.
  4. SL al lado opuesto del OR (con buffer ATR).
  5. TP1 = entry + R*risk_pts (R configurable, default 1.5).
  6. TP2 = entry + 2R*risk_pts.

Score: combinación de:
  - Magnitud del breakout vs ATR (mayor = mejor).
  - Cercanía del precio al cierre de OR (menor = mejor: rotura limpia).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine.indicators import opening_range
from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class ORBStrategy(Strategy):
    name = "ORB"
    family = "opening"

    def __init__(
        self,
        or_minutes: int = 15,
        rr_target: float = 1.5,
        rr_target_tp2: float = 2.5,
        sl_atr_buffer: float = 0.25,
    ) -> None:
        self.or_minutes = or_minutes
        self.rr_target = rr_target
        self.rr_target_tp2 = rr_target_tp2
        self.sl_atr_buffer = sl_atr_buffer

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 50:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        # Asegurar OR calculado
        if "or_high" not in df.columns:
            df = opening_range(df, minutes=self.or_minutes)

        last = df.iloc[-1]
        if pd.isna(last.get("or_high")) or pd.isna(last.get("or_low")):
            return (
                self._make_eval(ctx, detected=False, blocked_by="or_not_ready"),
                None,
            )

        if not last.get("or_complete", False):
            return (
                self._make_eval(ctx, detected=False, blocked_by="or_window_not_finished"),
                None,
            )

        atr = last.get("atr_14", np.nan)
        if pd.isna(atr) or atr <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="atr_not_ready"), None

        close = last["close"]
        or_high = last["or_high"]
        or_low = last["or_low"]
        or_range = or_high - or_low
        if or_range <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="or_range_zero"), None

        # ─── Detección de setup ───
        direction: Direction | None = None
        if close > or_high:
            direction = Direction.LONG
        elif close < or_low:
            direction = Direction.SHORT
        else:
            return (
                self._make_eval(ctx, detected=False, blocked_by="no_breakout"),
                None,
            )

        # ─── Cálculo de niveles ───
        if direction == Direction.LONG:
            entry = close
            stop_loss = or_low - self.sl_atr_buffer * atr
            risk_pts = entry - stop_loss
        else:
            entry = close
            stop_loss = or_high + self.sl_atr_buffer * atr
            risk_pts = stop_loss - entry

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        # RR efectivo: si el símbolo pide RR mínimo más alto que el default de la
        # estrategia, lo respetamos. Así XAUUSD con min_rr=2.5 obtiene TP1 a 2.5R.
        cfg_min_rr = ctx.symbol_cfg.risk.min_rr_ratio
        rr_target_eff = max(self.rr_target, cfg_min_rr)
        rr_target_tp2_eff = max(self.rr_target_tp2, rr_target_eff + 1.0)

        if direction == Direction.LONG:
            take_profit_1 = entry + rr_target_eff * risk_pts
            take_profit_2 = entry + rr_target_tp2_eff * risk_pts
        else:
            take_profit_1 = entry - rr_target_eff * risk_pts
            take_profit_2 = entry - rr_target_tp2_eff * risk_pts

        rr_ratio = abs(take_profit_1 - entry) / risk_pts

        # ─── Score (heurístico simple) ───
        # Magnitud del breakout vs ATR (clip 0..1)
        breakout_strength = min(abs(close - (or_high if direction == Direction.LONG else or_low)) / atr, 1.0)
        # Penaliza OR muy chico (puede ser noise)
        or_atr_ratio = min(or_range / atr, 1.5) / 1.5
        score = float(np.clip(0.4 + 0.4 * breakout_strength + 0.2 * or_atr_ratio, 0.0, 1.0))

        if score >= 0.7:
            confidence = Confidence.HIGH
        elif score >= 0.5:
            confidence = Confidence.MEDIUM
        else:
            confidence = Confidence.LOW

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
                "or_high": float(or_high),
                "or_low": float(or_low),
                "or_range": float(or_range),
                "or_atr_ratio": float(or_range / atr),
                "breakout_strength": float(breakout_strength),
                "ema_9": float(last.get("ema_9", np.nan)) if not pd.isna(last.get("ema_9", np.nan)) else None,
                "ema_21": float(last.get("ema_21", np.nan)) if not pd.isna(last.get("ema_21", np.nan)) else None,
                "rsi_14": float(last.get("rsi_14", np.nan)) if not pd.isna(last.get("rsi_14", np.nan)) else None,
            },
        )

        eval_obj = self._make_eval(
            ctx,
            detected=True,
            direction=direction,
            score=score,
            proposed_entry=float(entry),
            emitted_signal_id=signal.signal_id,
        )
        return eval_obj, signal
