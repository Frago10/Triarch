"""
Triarch — SCALPER strategy.

Diseñada principalmente para USDJPY en M5/M1. Filosofía:
  • Muchas operaciones pequeñas, RR moderado (1.2-1.5)
  • SL/TP definidos en múltiplos de ATR para adaptarse a la volatilidad
  • Entradas en pull-backs hacia EMA9 mientras EMA9 > EMA21 (tendencia corta)
  • Filtro de mínima volatilidad: ATR > N pips, evita ranges muertos
  • Filtro de horario: respeta cfg.session_utc

La idea es rentabilidad a escala: muchos trades semanales con win rate
medio-alto y costo pequeño por operación.
"""
from __future__ import annotations

from datetime import datetime, timezone

from signals.schema import Confidence, Direction, Signal, SignalStatus
from strategies.base import Strategy, StrategyContext


class ScalperStrategy(Strategy):
    name = "SCALPER"
    family = "trend"

    # Parámetros (afinables vía features futuras / símbolo)
    atr_min_pips: float = 5.0       # filtro de volatilidad mínima (en "pips" del par)
    sl_atr_mult: float = 1.0        # SL = entry - 1.0 * ATR
    tp_atr_mult: float = 1.4        # TP1 = entry + 1.4 * ATR  → RR ≈ 1.4
    score_base: float = 0.55

    def evaluate(self, ctx: StrategyContext):
        df = ctx.df
        cfg = ctx.symbol_cfg

        if len(df) < 50:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ─── Filtro de sesión ───
        bar_time = last["time"]
        if isinstance(bar_time, datetime):
            bt = bar_time
        else:
            bt = bar_time.to_pydatetime()
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        s, e = cfg.session_utc.to_times()
        cur_t = bt.time()
        in_window = (s <= cur_t <= e) if s <= e else (cur_t >= s or cur_t <= e)
        if not in_window:
            return self._make_eval(ctx, detected=False, blocked_by="out_of_window"), None

        # ─── Filtro de volatilidad ───
        atr_val = float(last.get("atr_14") or 0)
        if atr_val <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="atr_unavailable"), None

        # Para FX major, 1 pip ≈ 0.01 en USDJPY; para resto 0.0001. Usamos un
        # umbral relativo al precio para portabilidad.
        price = float(last["close"])
        rel_atr = atr_val / price
        if rel_atr < 0.0005:  # < 5 pips equivalentes
            return self._make_eval(ctx, detected=False, blocked_by="atr_too_low"), None

        # ─── Lógica direccional ───
        ema9 = float(last.get("ema_9") or 0)
        ema21 = float(last.get("ema_21") or 0)
        prev_close = float(prev["close"])
        if ema9 <= 0 or ema21 <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="ema_unavailable"), None

        # Long: tendencia corta alcista + pull-back a EMA9
        long_setup = (
            ema9 > ema21
            and prev_close < ema9          # vela previa por debajo de EMA9
            and price > ema9               # cierre actual por encima → reentrada
        )
        # Short: simétrico
        short_setup = (
            ema9 < ema21
            and prev_close > ema9
            and price < ema9
        )

        if not (long_setup or short_setup):
            return self._make_eval(ctx, detected=False, blocked_by="no_pullback"), None

        direction = Direction.LONG if long_setup else Direction.SHORT
        if direction == Direction.LONG:
            entry = price
            sl = entry - self.sl_atr_mult * atr_val
            tp1 = entry + self.tp_atr_mult * atr_val
        else:
            entry = price
            sl = entry + self.sl_atr_mult * atr_val
            tp1 = entry - self.tp_atr_mult * atr_val

        risk_pts = abs(entry - sl)
        reward_pts = abs(entry - tp1)
        rr = reward_pts / risk_pts if risk_pts > 0 else 0
        if rr < cfg.risk.min_rr_ratio:
            return (
                self._make_eval(
                    ctx, detected=True, direction=direction, proposed_entry=entry,
                    blocked_by="below_min_rr", blocked_detail=f"rr={rr:.2f}",
                ),
                None,
            )

        # Score: base + bonus por separación EMA y RSI saludable
        rsi_val = float(last.get("rsi_14") or 50)
        rsi_bonus = 0.0
        if direction == Direction.LONG and 50 < rsi_val < 70:
            rsi_bonus = 0.1
        elif direction == Direction.SHORT and 30 < rsi_val < 50:
            rsi_bonus = 0.1
        ema_sep = abs(ema9 - ema21) / price
        ema_bonus = min(0.15, ema_sep * 200)  # más separación = más conviction
        score = min(1.0, self.score_base + rsi_bonus + ema_bonus)

        sig = Signal(
            symbol=cfg.name,
            timeframe=cfg.timeframe,
            strategy=self.name,
            family=self.family,
            direction=direction,
            entry=entry,
            stop_loss=sl,
            take_profit_1=tp1,
            take_profit_2=None,
            score=score,
            confidence=Confidence.MEDIUM if score < 0.75 else Confidence.HIGH,
            risk_pts=risk_pts,
            reward_pts_tp1=reward_pts,
            rr_ratio=rr,
            atr_at_signal=atr_val,
            status=SignalStatus.NEW,
            features={
                "ema9": ema9, "ema21": ema21, "rsi": rsi_val,
                "rel_atr": rel_atr, "ema_sep": ema_sep,
            },
        )
        ev = self._make_eval(
            ctx, detected=True, direction=direction,
            proposed_entry=entry, score=score,
            emitted_signal_id=sig.signal_id,
        )
        return ev, sig
