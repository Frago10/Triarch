"""
Triarch — DONCHIAN_BREAK strategy.

Familia: structural.

Concepto:
  Variante moderna del Turtle Trading. Compra cuando la vela actual rompe
  el máximo de las últimas N velas (excluyendo la actual), con confirmación
  por momentum (close por encima de EMA50) y un filtro mínimo de volatilidad.

  Es el complemento "estructural" perfecto a EMA_MOMENTUM (trend) y
  PULLBACK_TREND (trend): donde estas dos esperan retrocesos, DONCHIAN_BREAK
  se sube a movimientos que ya están corriendo.

Lógica (long; short simétrico):
  1. Hay un Donchian de período N (default 20).
  2. close > dc_upper (la vela actual cerró por encima del máximo previo).
  3. Filtro de tendencia: close > ema_50 (no comprar breakouts contra-tendencia).
  4. Filtro de volatilidad: atr > 0.5 × promedio_atr_50 (evita rangos muertos).
  5. El cuerpo de la vela debe ser alcista y > 40% del rango (fuerza confirmada).

Niveles:
  - Entry: close.
  - SL: mid del Donchian del momento (dc_mid) o close - 1.5×ATR, el más cercano.
    → SL estructural: el centro del canal previo es donde la idea se rompe.
  - TP1: entry + rr_target × risk (rr_target = max(2.0, cfg.min_rr)).

Por qué añadirla:
  · Captura los movimientos grandes que las strats de pullback se pierden.
  · Family "structural" diversifica la confluencia.
  · Especialmente útil en XAUUSD y NAS100 (instrumentos con runs largos).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class DonchianBreakStrategy(Strategy):
    name = "DONCHIAN_BREAK"
    family = "structural"

    def __init__(
        self,
        min_body_pct: float = 0.40,
        min_atr_ratio: float = 0.5,
        rr_target: float = 2.0,
        sl_atr_max: float = 1.5,
    ) -> None:
        self.min_body_pct = min_body_pct
        self.min_atr_ratio = min_atr_ratio
        self.rr_target = rr_target
        self.sl_atr_max = sl_atr_max

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 70:
            return (
                self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"),
                None,
            )

        last = df.iloc[-1]
        atr = last.get("atr_14", np.nan)
        dc_upper = last.get("dc_upper", np.nan)
        dc_lower = last.get("dc_lower", np.nan)
        dc_mid = last.get("dc_mid", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if any(pd.isna(x) for x in (atr, dc_upper, dc_lower, dc_mid, ema_50)) or atr <= 0:
            return (
                self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"),
                None,
            )

        # Filtro de volatilidad: ATR actual vs media reciente
        atr_avg = df["atr_14"].tail(50).mean()
        if atr_avg <= 0 or atr / atr_avg < self.min_atr_ratio:
            return self._make_eval(ctx, detected=False, blocked_by="atr_too_low"), None

        close = float(last["close"])
        open_ = float(last["open"])
        high = float(last["high"])
        low = float(last["low"])
        rng = max(high - low, 1e-12)
        body_pct = abs(close - open_) / rng

        # ─── Long breakout ───
        if (
            close > dc_upper
            and close > ema_50
            and close > open_
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.LONG
            entry = close
            # SL estructural: el más cerca entre dc_mid y close-1.5*ATR
            sl_atr = entry - self.sl_atr_max * atr
            sl = max(dc_mid, sl_atr)
            risk_pts = entry - sl
        # ─── Short breakout ───
        elif (
            close < dc_lower
            and close < ema_50
            and close < open_
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.SHORT
            entry = close
            sl_atr = entry + self.sl_atr_max * atr
            sl = min(dc_mid, sl_atr)
            risk_pts = sl - entry
        else:
            return (
                self._make_eval(
                    ctx,
                    detected=False,
                    blocked_by="no_breakout",
                    blocked_detail=(
                        f"close={close:.5f} dc_up={dc_upper:.5f} "
                        f"dc_lo={dc_lower:.5f} body={body_pct:.2f}"
                    ),
                ),
                None,
            )

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        cfg_min_rr = ctx.symbol_cfg.risk.min_rr_ratio
        rr_eff = max(self.rr_target, cfg_min_rr)
        if direction is Direction.LONG:
            tp1 = entry + rr_eff * risk_pts
            tp2 = entry + (rr_eff + 1.0) * risk_pts
        else:
            tp1 = entry - rr_eff * risk_pts
            tp2 = entry - (rr_eff + 1.0) * risk_pts
        rr_ratio = abs(tp1 - entry) / risk_pts

        # ─── Score ───
        # Premia: ruptura grande (% sobre el canal), cuerpo fuerte, volatilidad sana.
        if direction is Direction.LONG:
            break_strength = (close - dc_upper) / atr
        else:
            break_strength = (dc_lower - close) / atr
        break_score = min(max(break_strength, 0.0), 1.0)
        body_score = min(body_pct / 0.8, 1.0)
        vol_score = min(atr / atr_avg / 1.5, 1.0)
        score = float(
            np.clip(0.30 + 0.30 * break_score + 0.25 * body_score
                    + 0.15 * vol_score, 0.0, 1.0)
        )
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
                "dc_upper": float(dc_upper),
                "dc_lower": float(dc_lower),
                "dc_mid": float(dc_mid),
                "break_strength_atr": float(break_strength),
                "body_pct": float(body_pct),
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
