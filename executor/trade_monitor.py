"""
Triarch — Trade Monitor.

Vigila los tickets MT5 abiertos por el bot y detecta cuando cierran (SL/TP/manual).
Actualiza la SQLite con pnl_money, closed_at_utc, closed_price, status, y notifica al
RiskManager para que actualice consec_losses, daily_pnl, etc.

Cómo identifica trades del bot:
  - filtra por `magic_number` (el de la estrategia que abrió el trade)
  - el comment del trade incluye `triarch:STRATEGY:signal_id`

Lifecycle de un signal en la DB:
  PLACED  ─► (orden colocada, pendiente fill)
   │
   ▼
  FILLED  ─► (posición abierta en MT5)
   │
   ├─► CLOSED_TP1   (precio tocó TP1)
   ├─► CLOSED_TP2   (TP2 alcanzado — solo si gestionamos parcial; v1 cierra todo en TP1)
   ├─► CLOSED_SL    (stop loss tocado)
   └─► CLOSED_MANUAL (cerraste a mano en MT5)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from audit.store import AuditStore
from data_layer.mt5_client import MT5_AVAILABLE, MT5Client
from executor.auto import MAGIC_NUMBERS
from risk.manager import RiskManager
from signals.schema import Signal, SignalStatus

# Tolerancia para detectar TP/SL hits — % del rango entry-SL
HIT_TOLERANCE = 0.05  # 5%


class TradeMonitor:
    """
    Polling-based trade monitor. Llama a `poll()` desde el orchestrator cada tick.

    No hace nada si MT5 no está disponible.
    """

    def __init__(
        self,
        mt5_client: MT5Client,
        store: AuditStore,
        risk: RiskManager,
    ) -> None:
        self.mt5_client = mt5_client
        self.store = store
        self.risk = risk
        # Magic numbers que el bot usa — invertido por estrategia
        self._our_magics = set(MAGIC_NUMBERS.values())

    def poll(self) -> None:
        """Una pasada del monitor: refresh tickets abiertos + detecta cierres."""
        if not MT5_AVAILABLE:
            return
        import MetaTrader5 as mt5  # type: ignore[import-not-found]

        # ─── Step 1: signals que pensamos están abiertos según la DB ───
        open_signals = self._open_signals_in_db()
        if not open_signals:
            return

        # ─── Step 2: posiciones MT5 actuales (filtradas por nuestros magics) ───
        positions = mt5.positions_get() or ()
        open_tickets = {p.ticket for p in positions if p.magic in self._our_magics}

        # ─── Step 3: para cada signal en la DB que pensamos abierto ───
        for sig in open_signals:
            ticket = sig.mt5_ticket
            if ticket is None:
                continue

            if ticket in open_tickets:
                # Sigue abierto. Si todavía está PLACED, refresh a FILLED + filled_price.
                if sig.status == SignalStatus.PLACED:
                    pos = next((p for p in positions if p.ticket == ticket), None)
                    if pos:
                        sig.status = SignalStatus.FILLED
                        sig.filled_price = float(pos.price_open)
                        self.store.save_signal(sig)
                        logger.info(
                            f"Trade FILLED: ticket={ticket} {sig.symbol} "
                            f"@ {sig.filled_price:.5f}"
                        )
                continue

            # ─── Ya no aparece en posiciones abiertas → cerró ───
            self._close_signal(sig)

    # ─────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────
    def _open_signals_in_db(self) -> list[Signal]:
        """Signals que pensamos están abiertos: status PLACED o FILLED, con ticket."""
        rows = []
        for status in (SignalStatus.PLACED.value, SignalStatus.FILLED.value):
            rows.extend(
                r
                for r in self.store.list_signals(limit=500)
                if r["status"] == status and r["mt5_ticket"] is not None
            )
        # Reconstruir Signal a partir del dict
        out: list[Signal] = []
        from signals.schema import Confidence, Direction, SignalStatus as SS
        for r in rows:
            try:
                out.append(
                    Signal(
                        signal_id=r["signal_id"],
                        timestamp_utc=datetime.fromisoformat(r["timestamp_utc"]),
                        symbol=r["symbol"],
                        timeframe=r["timeframe"],
                        strategy=r["strategy"],
                        family=r["family"],
                        direction=Direction(r["direction"]),
                        entry=r["entry"],
                        stop_loss=r["stop_loss"],
                        take_profit_1=r["take_profit_1"],
                        take_profit_2=r["take_profit_2"],
                        score=r["score"],
                        confidence=Confidence(r["confidence"]),
                        risk_pts=r["risk_pts"],
                        reward_pts_tp1=abs(r["take_profit_1"] - r["entry"]),
                        rr_ratio=r["rr_ratio"],
                        atr_at_signal=r["atr_at_signal"],
                        status=SS(r["status"]),
                        mt5_ticket=r["mt5_ticket"],
                        placed_at_utc=(
                            datetime.fromisoformat(r["placed_at_utc"]) if r["placed_at_utc"] else None
                        ),
                        filled_price=r["filled_price"],
                    )
                )
            except Exception as e:  # noqa: BLE001
                logger.warning(f"No pude reconstruir signal {r['signal_id']}: {e}")
        return out

    def _close_signal(self, sig: Signal) -> None:
        """El ticket ya no está abierto → buscar el deal de cierre y registrar."""
        import MetaTrader5 as mt5  # type: ignore[import-not-found]

        # Buscamos los deals de este position en las últimas 7 días.
        # En MT5: cada operación (open + close) genera un "deal".
        from_dt = (sig.placed_at_utc or sig.timestamp_utc) - timedelta(hours=1)
        to_dt = datetime.now(timezone.utc) + timedelta(minutes=5)

        deals = mt5.history_deals_get(from_dt, to_dt, position=sig.mt5_ticket)
        if deals is None or len(deals) == 0:
            # Fallback: buscar por magic + symbol en el rango de tiempo
            deals = mt5.history_deals_get(from_dt, to_dt) or ()
            deals = tuple(d for d in deals if d.position_id == sig.mt5_ticket)

        if not deals:
            logger.warning(
                f"Ticket {sig.mt5_ticket} cerró pero no encontré deals — marco CLOSED_MANUAL sin pnl"
            )
            sig.status = SignalStatus.CLOSED_MANUAL
            sig.closed_at_utc = datetime.now(timezone.utc)
            self.store.save_signal(sig)
            return

        # Sumar profit + commission + swap de los deals (el de cierre tiene el pnl)
        # En MT5, el deal de OUT (cierre) tiene entry=DEAL_ENTRY_OUT y profit positivo/negativo.
        total_profit = sum(d.profit for d in deals)
        total_commission = sum(getattr(d, "commission", 0.0) for d in deals)
        total_swap = sum(getattr(d, "swap", 0.0) for d in deals)
        net_pnl = total_profit + total_commission + total_swap

        # Identificar el deal de cierre (DEAL_ENTRY_OUT)
        out_deal = next(
            (d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT), None
        )
        closed_price = out_deal.price if out_deal else None
        closed_time = (
            datetime.fromtimestamp(out_deal.time, tz=timezone.utc)
            if out_deal else datetime.now(timezone.utc)
        )

        # Detectar SL/TP por proximidad
        new_status = SignalStatus.CLOSED_MANUAL
        if closed_price is not None and sig.stop_loss and sig.take_profit_1:
            sl_dist = abs(closed_price - sig.stop_loss)
            tp1_dist = abs(closed_price - sig.take_profit_1)
            tol = sig.risk_pts * HIT_TOLERANCE
            if sl_dist <= tol and net_pnl <= 0:
                new_status = SignalStatus.CLOSED_SL
            elif tp1_dist <= tol and net_pnl > 0:
                new_status = SignalStatus.CLOSED_TP1
            elif sig.take_profit_2 and abs(closed_price - sig.take_profit_2) <= tol:
                new_status = SignalStatus.CLOSED_TP2

        sig.status = new_status
        sig.closed_price = closed_price
        sig.closed_at_utc = closed_time
        sig.pnl_money = net_pnl
        if closed_price is not None and sig.filled_price is not None:
            from signals.schema import Direction as D
            direction_mult = 1 if sig.direction == D.LONG else -1
            sig.pnl_pts = (closed_price - sig.filled_price) * direction_mult

        self.store.save_signal(sig)

        # Notificar al risk manager — liberar el active_trade y actualizar contadores
        self.risk.on_trade_close(sig.symbol, pnl_money=net_pnl, now=closed_time)

        emoji = "🟢" if net_pnl > 0 else "🔴" if net_pnl < 0 else "⚪"
        logger.info(
            f"{emoji} Trade closed: {sig.symbol} {sig.strategy} "
            f"ticket={sig.mt5_ticket} status={new_status.value} "
            f"pnl={net_pnl:+.2f} (close@{closed_price})"
        )
