"""
Triarch — SCALPER strategy.

Diseñada para EURUSD en M5/M1. Filosofía:
  • Muchas operaciones, win rate ALTO, RR moderado-bajo (~0.8-1.0)
  • "Sumar de a pocos": TP cercano que se toca seguido; SL con algo más de aire
  • Solo opera A FAVOR de la tendencia corta (EMA9 vs EMA21)
  • Dos gatillos de entrada (más setups que la versión anterior):
        1. Pull-back: precio cruza de vuelta la EMA9 en la dirección de tendencia
        2. Continuación: precio descansa entre EMA9 y EMA21 sin romper estructura
  • Filtros: volatilidad mínima (ATR relativo) + horario de sesión

Rentabilidad a escala: muchos trades chicos con win rate medio-alto.
El RR sale ~0.85 — para ser rentable necesita WR > ~54%.
"""
from __future__ import annotations

from datetime import datetime, timezone

from signals.schema import Confidence, Direction, Signal, SignalStatus
from strategies.base import Strategy, StrategyContext


class ScalperStrategy(Strategy):
    name = "SCALPER"
    family = "trend"

    # Parámetros (afinables)
    rel_atr_min: float = 0.0003     # filtro de volatilidad mínima (ATR / precio)
    sl_atr_mult: float = 1.0        # SL = entry ∓ 1.0 * ATR
    tp_atr_mult: float = 0.85       # TP1 = entry ± 0.85 * ATR  → RR ≈ 0.85
    score_base: float = 0.58
    max_dist_ema9_atr: float = 0.6  # para continuación: qué tan lejos de EMA9 acepta
    ema_sep_min: float = 0.0002     # separación mínima EMA9/EMA21 (relativa) →
                                    # filtra rangos muertos. Valor SUAVE por
                                    # defecto: subirlo (ej. 0.0004-0.0008) tras
                                    # ver el backtest sobre DATA REAL de EURUSD.
                                    # En data sintética un filtro fuerte no
                                    # aporta (no hay tendencias que filtrar).
    pullback_only: bool = False     # si True, ignora el gatillo de continuación

    def evaluate(self, ctx: StrategyContext):
        df = ctx.df
        cfg = ctx.symbol_cfg

        if len(df) < 50:
            return self._make_eval(ctx, detected=False, blocked_by="not_enough_bars"), None

        last = df.iloc[-1]
        prev = df.iloc[-2]

        # ─── Filtro de sesión ───
        bar_time = last["time"]
        bt = bar_time if isinstance(bar_time, datetime) else bar_time.to_pydatetime()
        if bt.tzinfo is None:
            bt = bt.replace(tzinfo=timezone.utc)
        s, e = cfg.session_utc.to_times()
        cur_t = bt.time()
        in_window = (s <= cur_t <= e) if s <= e else (cur_t >= s or cur_t <= e)
        if not in_window:
            return self._make_eval(ctx, detected=False, blocked_by="out_of_window"), None

        # ─── Filtro de volatilidad ───
        atr_val = float(last.get("atr_14") or 0)
        price = float(last["close"])
        if atr_val <= 0 or price <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="atr_unavailable"), None
        rel_atr = atr_val / price
        if rel_atr < self.rel_atr_min:
            return self._make_eval(ctx, detected=False, blocked_by="atr_too_low"), None

        # ─── Tendencia corta ───
        ema9 = float(last.get("ema_9") or 0)
        ema21 = float(last.get("ema_21") or 0)
        if ema9 <= 0 or ema21 <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="ema_unavailable"), None

        prev_close = float(prev["close"])
        trend_up = ema9 > ema21
        trend_dn = ema9 < ema21

        # ─── Filtro de fuerza de tendencia ───
        # Si EMA9 y EMA21 están casi pegadas, el mercado está en rango → los
        # pull-backs no tienen continuación. Exigimos separación mínima.
        ema_sep_rel = abs(ema9 - ema21) / price
        if ema_sep_rel < self.ema_sep_min:
            return self._make_eval(ctx, detected=False, blocked_by="trend_too_weak"), None

        # ─── Gatillo 1: pull-back (cruce de vuelta a EMA9) ───
        long_pullback = trend_up and prev_close < ema9 and price > ema9
        short_pullback = trend_dn and prev_close > ema9 and price < ema9

        # ─── Gatillo 2: continuación (precio descansa entre EMA9 y EMA21) ───
        dist_ema9 = abs(price - ema9) / atr_val
        long_cont = (
            trend_up and price > ema21 and price <= ema9
            and dist_ema9 <= self.max_dist_ema9_atr
        )
        short_cont = (
            trend_dn and price < ema21 and price >= ema9
            and dist_ema9 <= self.max_dist_ema9_atr
        )

        if self.pullback_only:
            long_cont = short_cont = False
        long_setup = long_pullback or long_cont
        short_setup = short_pullback or short_cont

        if not (long_setup or short_setup):
            return self._make_eval(ctx, detected=False, blocked_by="no_pullback"), None
        # Si por algún borde se activan ambos, no operamos (ambiguo)
        if long_setup and short_setup:
            return self._make_eval(ctx, detected=False, blocked_by="ambiguous"), None

        direction = Direction.LONG if long_setup else Direction.SHORT
        trigger = (
            "pullback" if (long_pullback or short_pullback) else "continuation"
        )

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

        # OJO: el scalper acepta RR < 1 a propósito. El gate de cfg.risk.min_rr_ratio
        # se aplica fuera (orchestrator/backtester). EURUSD tiene min_rr bajo.
        if rr <= 0:
            return self._make_eval(ctx, detected=False, blocked_by="invalid_risk"), None

        # ─── Score ───
        rsi_val = float(last.get("rsi_14") or 50)
        rsi_bonus = 0.0
        if direction == Direction.LONG and 48 < rsi_val < 68:
            rsi_bonus = 0.1
        elif direction == Direction.SHORT and 32 < rsi_val < 52:
            rsi_bonus = 0.1
        ema_sep = abs(ema9 - ema21) / price
        ema_bonus = min(0.15, ema_sep * 200)
        trigger_bonus = 0.05 if trigger == "pullback" else 0.0  # pull-back algo más fiable
        score = min(1.0, self.score_base + rsi_bonus + ema_bonus + trigger_bonus)

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
                "trigger": trigger, "dist_ema9_atr": dist_ema9,
            },
        )
        ev = self._make_eval(
            ctx, detected=True, direction=direction,
            proposed_entry=entry, score=score,
            emitted_signal_id=sig.signal_id,
        )
        return ev, sig
