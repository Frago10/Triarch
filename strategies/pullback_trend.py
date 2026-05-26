"""
Triarch — PULLBACK_TREND strategy.

Familia: trend.

Concepto:
  Complementa a EMA_MOMENTUM con un perfil ligeramente más permisivo.
  Mientras EMA_MOMENTUM exige alineación 9>21>50 estricta + slope fuerte +
  pullback PRECISO a la EMA21, PULLBACK_TREND opera sobre EMA20 (más ágil)
  y acepta pullbacks "amplios" siempre que el precio rebote en la misma vela.

Lógica (long; short simétrico):
  1. Tendencia macro: close > ema_50 (long). El gap close-ema_50 debe ser > 0.2*ATR
     (descarta rangos pegados a la media).
  2. EMA rápida alineada con la lenta: ema_9 > ema_20 (long).
  3. La vela actual hizo un retroceso: low <= ema_20 + 0.3*ATR (tocó la media).
  4. Cierre alcista y por encima de la EMA20: close > open AND close > ema_20.
  5. Filtro de cuerpo: cuerpo de la vela >= 30% del rango (señal de fuerza).

Niveles:
  - Entry: close de la vela actual.
  - SL: low de la vela - 0.2*ATR  (más ajustado que EMA_MOMENTUM → más trades).
  - TP1: entry + rr_target * risk_pts (rr_target = max(1.6, cfg.min_rr)).
  - TP2: entry + (rr_target + 1.0) * risk_pts.

Por qué añadirla:
  · Genera 2–4× más señales que EMA_MOMENTUM en el mismo histórico.
  · La confluencia con EMA_MOMENTUM filtra los falsos positivos.
  · Útil para que NASDAQ y EURUSD (que pedían más trades) tengan flujo.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class PullbackTrendStrategy(Strategy):
    name = "PULLBACK_TREND"
    family = "trend"

    def __init__(
        self,
        min_macro_dist_atr: float = 0.2,
        pullback_tolerance_atr: float = 0.3,
        min_body_pct: float = 0.30,
        rr_target: float = 1.6,
        sl_buffer_atr: float = 0.2,
    ) -> None:
        self.min_macro_dist_atr = min_macro_dist_atr
        self.pullback_tolerance_atr = pullback_tolerance_atr
        self.min_body_pct = min_body_pct
        self.rr_target = rr_target
        self.sl_buffer_atr = sl_buffer_atr

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 60:
            return (
                self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"),
                None,
            )

        last = df.iloc[-1]
        atr = last.get("atr_14", np.nan)
        ema_9 = last.get("ema_9", np.nan)
        ema_20 = last.get("ema_20", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if any(pd.isna(x) for x in (atr, ema_9, ema_20, ema_50)) or atr <= 0:
            return (
                self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"),
                None,
            )

        close = float(last["close"])
        open_ = float(last["open"])
        high = float(last["high"])
        low = float(last["low"])
        rng = max(high - low, 1e-12)
        body_pct = abs(close - open_) / rng

        macro_dist = (close - ema_50) / atr  # >0 long, <0 short

        # ─── Long setup ───
        if (
            macro_dist > self.min_macro_dist_atr
            and ema_9 > ema_20
            and low <= ema_20 + self.pullback_tolerance_atr * atr
            and close > open_
            and close > ema_20
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.LONG
            sl = low - self.sl_buffer_atr * atr
            entry = close
            risk_pts = entry - sl
        # ─── Short setup ───
        elif (
            macro_dist < -self.min_macro_dist_atr
            and ema_9 < ema_20
            and high >= ema_20 - self.pullback_tolerance_atr * atr
            and close < open_
            and close < ema_20
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.SHORT
            sl = high + self.sl_buffer_atr * atr
            entry = close
            risk_pts = sl - entry
        else:
            return (
                self._make_eval(
                    ctx,
                    detected=False,
                    blocked_by="no_pullback",
                    blocked_detail=f"macro={macro_dist:.2f} body={body_pct:.2f}",
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
        # Premia fuerza macro + cuerpo + cercanía al ema_20.
        macro_strength = min(abs(macro_dist) / 1.5, 1.0)
        body_strength = min(body_pct / 0.7, 1.0)
        pull_precision = 1.0 - min(
            abs(close - ema_20) / (self.pullback_tolerance_atr * atr), 1.0
        )
        score = float(
            np.clip(0.30 + 0.30 * macro_strength + 0.25 * body_strength
                    + 0.15 * pull_precision, 0.0, 1.0)
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
                "macro_dist_atr": float(macro_dist),
                "body_pct": float(body_pct),
                "ema_20": float(ema_20),
                "ema_50": float(ema_50),
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
