"""
Triarch — KELTNER_BREAK strategy.

Familia: trend.

Concepto:
  Breakout sobre Keltner Channel (banda central EMA20 ± 2*ATR14) con
  confirmación de momentum (RSI > 55 en long, < 45 en short).

  Por qué Keltner y no Bollinger para esto: las bandas Keltner son ATR-based,
  más estables cuando la volatilidad cambia. Bollinger se ensancha y comprime
  por stdev del precio → más falsos breakouts en mercados volátiles como oro
  o índices. Keltner respira con el ATR → señal más limpia.

  Es el complemento simétrico a BB_MR (que opera en reversiones de Bollinger).

Lógica (long; short simétrico):
  1. close > kc_upper (rotura de la banda superior).
  2. RSI > 55 (momentum confirma).
  3. close > ema_50 (filtro macro).
  4. Cuerpo de la vela alcista y > 30% del rango.

Niveles:
  - Entry: close.
  - SL: kc_mid (EMA20 — el centro del canal; si la rotura es real, no debería volver ahí).
  - TP1: entry + 1.8 × risk (objetivo ambicioso, los breakouts buenos corren).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class KeltnerBreakStrategy(Strategy):
    name = "KELTNER_BREAK"
    family = "trend"

    def __init__(
        self,
        rsi_long_min: float = 55.0,
        rsi_short_max: float = 45.0,
        min_body_pct: float = 0.30,
        rr_target: float = 1.8,
    ) -> None:
        self.rsi_long_min = rsi_long_min
        self.rsi_short_max = rsi_short_max
        self.min_body_pct = min_body_pct
        self.rr_target = rr_target

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 60:
            return (
                self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"),
                None,
            )

        last = df.iloc[-1]
        atr = last.get("atr_14", np.nan)
        kc_upper = last.get("kc_upper", np.nan)
        kc_lower = last.get("kc_lower", np.nan)
        kc_mid = last.get("kc_mid", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        rsi = last.get("rsi_14", np.nan)
        if any(pd.isna(x) for x in (atr, kc_upper, kc_lower, kc_mid, ema_50, rsi)) or atr <= 0:
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

        # ─── Long ───
        if (
            close > kc_upper
            and rsi > self.rsi_long_min
            and close > ema_50
            and close > open_
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.LONG
            entry = close
            sl = float(kc_mid)
            risk_pts = entry - sl
        # ─── Short ───
        elif (
            close < kc_lower
            and rsi < self.rsi_short_max
            and close < ema_50
            and close < open_
            and body_pct >= self.min_body_pct
        ):
            direction = Direction.SHORT
            entry = close
            sl = float(kc_mid)
            risk_pts = sl - entry
        else:
            return (
                self._make_eval(
                    ctx,
                    detected=False,
                    blocked_by="no_keltner_break",
                    blocked_detail=f"rsi={rsi:.1f} body={body_pct:.2f}",
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
        if direction is Direction.LONG:
            momentum = (rsi - 50) / 50  # 0..1 above 50
        else:
            momentum = (50 - rsi) / 50
        momentum = float(np.clip(momentum, 0.0, 1.0))
        body_score = min(body_pct / 0.7, 1.0)
        score = float(np.clip(0.35 + 0.35 * momentum + 0.20 * body_score, 0.0, 1.0))
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
                "kc_upper": float(kc_upper),
                "kc_mid": float(kc_mid),
                "kc_lower": float(kc_lower),
                "rsi_14": float(rsi),
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
