"""
Triarch — MACD_CROSS strategy.

Familia: trend.

Concepto:
  Estrategia clásica de momentum: MACD cruza su línea de señal en la última
  vela, y se valida con un filtro de tendencia macro. Variante "MACD trigger
  with trend filter" — gana señales cuando el momentum está acelerando.

  Diferencia clave con EMA_MOMENTUM y PULLBACK_TREND: MACD_CROSS no necesita
  un pullback explícito. Captura la VUELTA del momentum (cuando el histograma
  cambia de signo) → entradas más tempranas, a veces mejor precio.

Lógica (long; short simétrico):
  1. macd ahora > macd_signal, y en la vela anterior macd <= macd_signal
     (cruz alcista justo en esta vela).
  2. Filtro tendencia: close > ema_50 (no comprar cruces en bajadas).
  3. Filtro de fuerza: |macd - macd_signal| > 0.05 × ATR (el cruz tiene cuerpo).
  4. Histograma debe haber sido negativo y ahora positivo (real flip).

Niveles:
  - Entry: close.
  - SL: low de las últimas 5 velas - 0.2*ATR  (estructural reciente).
  - TP1: entry + 1.5 × risk_pts.

Notas:
  · Tiene tendencia a generar más señales que EMA_MOMENTUM en mercados
    con vaivenes (índices), por eso lo añadimos a NAS100 y EURUSD.
  · El filtro de "fuerza del cruz" en ATR evita las micro-cruces.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from signals.schema import Confidence, Direction, Eval, Signal
from strategies.base import Strategy, StrategyContext


class MACDCrossStrategy(Strategy):
    name = "MACD_CROSS"
    family = "trend"

    def __init__(
        self,
        min_cross_atr: float = 0.05,
        rr_target: float = 1.5,
        sl_buffer_atr: float = 0.2,
        sl_lookback: int = 5,
    ) -> None:
        self.min_cross_atr = min_cross_atr
        self.rr_target = rr_target
        self.sl_buffer_atr = sl_buffer_atr
        self.sl_lookback = sl_lookback

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
        macd_now = last.get("macd", np.nan)
        sig_now = last.get("macd_signal", np.nan)
        hist_now = last.get("macd_hist", np.nan)
        macd_prev = prev.get("macd", np.nan)
        sig_prev = prev.get("macd_signal", np.nan)
        hist_prev = prev.get("macd_hist", np.nan)
        ema_50 = last.get("ema_50", np.nan)
        if any(
            pd.isna(x)
            for x in (atr, macd_now, sig_now, hist_now, macd_prev, sig_prev, hist_prev, ema_50)
        ) or atr <= 0:
            return (
                self._make_eval(ctx, detected=False, blocked_by="indicators_not_ready"),
                None,
            )

        close = float(last["close"])
        cross_strength = abs(macd_now - sig_now) / atr

        long_cross = (
            macd_prev <= sig_prev
            and macd_now > sig_now
            and hist_prev <= 0
            and hist_now > 0
        )
        short_cross = (
            macd_prev >= sig_prev
            and macd_now < sig_now
            and hist_prev >= 0
            and hist_now < 0
        )

        if long_cross and close > ema_50 and cross_strength > self.min_cross_atr:
            direction = Direction.LONG
            entry = close
            recent_low = df["low"].tail(self.sl_lookback).min()
            sl = float(recent_low) - self.sl_buffer_atr * atr
            risk_pts = entry - sl
        elif short_cross and close < ema_50 and cross_strength > self.min_cross_atr:
            direction = Direction.SHORT
            entry = close
            recent_high = df["high"].tail(self.sl_lookback).max()
            sl = float(recent_high) + self.sl_buffer_atr * atr
            risk_pts = sl - entry
        else:
            return (
                self._make_eval(
                    ctx,
                    detected=False,
                    blocked_by="no_macd_cross",
                    blocked_detail=(
                        f"long={long_cross} short={short_cross} "
                        f"strength={cross_strength:.3f}"
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
        cross_score = float(min(cross_strength / 0.3, 1.0))  # >0.3 ATR = cruz fuerte
        hist_score = float(min(abs(hist_now) / atr / 0.1, 1.0))
        score = float(np.clip(0.35 + 0.35 * cross_score + 0.20 * hist_score, 0.0, 1.0))
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
                "macd": float(macd_now),
                "macd_signal": float(sig_now),
                "macd_hist": float(hist_now),
                "cross_strength_atr": float(cross_strength),
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
