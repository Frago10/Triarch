"""
Triarch — BB_MR (Bollinger-Band Mean Reversion).

Familia: mean.

Buenas para rangos. Filosofía: si la barra cierra fuera de la banda y la siguiente
vela hace un "inside bar" o un rechazo (mecha larga), apostamos al retorno a la
banda media. Pensada para gold y para complementar ORB cuando el mercado no
tiene tendencia clara.

Lógica (long; short es simétrico):
  1. La barra previa cerró por debajo de bb_lower (extremo bajista).
  2. La barra actual hace cierre POR ENCIMA de bb_lower (rechazo).
  3. RSI < 35 en la previa (sobreventa) — confirma extremo.
  4. bb_width >= mínimo (evitamos rangos demasiado angostos).

Niveles:
  • Entry: close actual.
  • SL: low previo - 0.25*ATR (debajo del extremo).
  • TP1: bb_mid    (objetivo: media).  RR target dinámico ≥ cfg.risk.min_rr_ratio.
  • TP2: bb_upper  (recorrido completo a la otra banda).

Score: combinación de profundidad del extremo (cuánto se metió en sobreventa)
y fuerza del rechazo (tamaño de la mecha respecto al cuerpo).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class BBMeanReversionStrategy(Strategy):
    name = "BB_MR"
    family = "mean"

    def __init__(
        self,
        rsi_oversold: float = 35.0,
        rsi_overbought: float = 65.0,
        min_bb_width: float = 0.005,   # 0.5% del precio mínimo
        sl_atr_buffer: float = 0.25,
        rr_target: float = 1.8,        # se sube si cfg.risk.min_rr_ratio es mayor
        rr_target_tp2: float = 3.0,
    ) -> None:
        self.rsi_oversold = rsi_oversold
        self.rsi_overbought = rsi_overbought
        self.min_bb_width = min_bb_width
        self.sl_atr_buffer = sl_atr_buffer
        self.rr_target = rr_target
        self.rr_target_tp2 = rr_target_tp2

    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        df = ctx.df
        if len(df) < 30:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        bb_upper = last.get("bb_upper", np.nan)
        bb_lower = last.get("bb_lower", np.nan)
        bb_mid = last.get("bb_mid", np.nan)
        bb_width = last.get("bb_width", np.nan)
        atr = last.get("atr_14", np.nan)
        rsi_prev = prev.get("rsi_14", np.nan)

        if any(pd.isna(x) for x in (bb_upper, bb_lower, bb_mid, bb_width, atr, rsi_prev)):
            return self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"), None
        if atr <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="atr_zero"), None
        if bb_width < self.min_bb_width:
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="bb_too_narrow",
                    blocked_detail=f"bb_width={bb_width:.5f}<{self.min_bb_width}",
                ),
                None,
            )

        close = float(last["close"])
        prev_close = float(prev["close"])

        # ─── Detección de setup ───
        direction: Direction | None = None
        if prev_close < bb_lower and close > bb_lower and rsi_prev < self.rsi_oversold:
            direction = Direction.LONG
        elif prev_close > bb_upper and close < bb_upper and rsi_prev > self.rsi_overbought:
            direction = Direction.SHORT
        else:
            return (
                self._make_eval(
                    ctx, detected=False, blocked_by="no_extreme_rejection",
                    blocked_detail=f"prev_close={prev_close:.5f}  bbL={bb_lower:.5f}  bbU={bb_upper:.5f}  rsi_prev={rsi_prev:.1f}",
                ),
                None,
            )

        # ─── Niveles ───
        cfg_min_rr = ctx.symbol_cfg.risk.min_rr_ratio
        rr_target_eff = max(self.rr_target, cfg_min_rr)
        rr_target_tp2_eff = max(self.rr_target_tp2, rr_target_eff + 1.0)

        if direction == Direction.LONG:
            sl = float(prev["low"]) - self.sl_atr_buffer * atr
            entry = close
            risk_pts = entry - sl
            tp1 = entry + rr_target_eff * risk_pts
            tp2 = entry + rr_target_tp2_eff * risk_pts
        else:
            sl = float(prev["high"]) + self.sl_atr_buffer * atr
            entry = close
            risk_pts = sl - entry
            tp1 = entry - rr_target_eff * risk_pts
            tp2 = entry - rr_target_tp2_eff * risk_pts

        if risk_pts <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        rr_ratio = abs(tp1 - entry) / risk_pts

        # ─── Score ───
        # Profundidad del extremo: cuánto se metió en sobreventa (más extremo = mejor)
        if direction == Direction.LONG:
            depth = max(0.0, (self.rsi_oversold - float(rsi_prev)) / self.rsi_oversold)
        else:
            depth = max(0.0, (float(rsi_prev) - self.rsi_overbought) / (100 - self.rsi_overbought))
        depth = float(min(depth, 1.0))

        # Fuerza del rechazo: mecha de la barra previa respecto al cuerpo
        body = abs(prev["close"] - prev["open"])
        wick = (
            (prev["close"] - prev["low"]) if direction == Direction.LONG
            else (prev["high"] - prev["close"])
        )
        wick_ratio = float(min(wick / max(body, 1e-9), 3.0) / 3.0)  # 0..1

        score = float(np.clip(0.35 + 0.4 * depth + 0.25 * wick_ratio, 0.0, 1.0))
        confidence = (
            Confidence.HIGH if score >= 0.7 else
            Confidence.MEDIUM if score >= 0.5 else
            Confidence.LOW
        )

        sig = Signal(
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
                "bb_upper": float(bb_upper),
                "bb_lower": float(bb_lower),
                "bb_mid": float(bb_mid),
                "bb_width": float(bb_width),
                "rsi_prev": float(rsi_prev),
                "depth": depth,
                "wick_ratio": wick_ratio,
            },
        )
        ev = self._make_eval(
            ctx, detected=True, direction=direction,
            score=score, proposed_entry=float(entry),
            emitted_signal_id=sig.signal_id,
        )
        return ev, sig
