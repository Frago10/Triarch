"""
Triarch — Orchestrator.

El bucle principal:
  1. Para cada activo configurado:
     a. Lee velas recientes desde MT5.
     b. Añade indicadores.
     c. Para cada estrategia: evaluate() → (Eval, Signal | None).
     d. Audit: guarda Eval en SQLite.
     e. Confluencia: filtra entre señales del mismo activo/timestamp.
     f. Risk: si pasa, decide si tomar.
     g. Executor: SIGNAL_ONLY / APPROVAL / AUTO.
     h. Notifiers: avisan según modo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from loguru import logger

from audit.obsidian_writer import ObsidianWriter
from audit.store import AuditStore
from config.runtime import get_take_trades
from config.settings import (
    ExecutionMode,
    SymbolConfig,
    TriarchSettings,
    get_settings,
    get_symbols,
)
from confluence.filter import ConfluenceFilter, build_confluence_for
from data_layer.mt5_client import MT5Client
from engine.indicators import add_default_indicators, opening_range
from executor.factory import build_executor
from executor.sizing import calc_lot_risk_pct
from executor.trade_monitor import TradeMonitor
from risk.manager import RiskManager
from signals.notifiers import Notifier, build_default_notifiers
from signals.schema import Signal, SignalStatus
from strategies.base import StrategyContext
from strategies.registry import build_strategies


class Orchestrator:
    def __init__(
        self,
        mt5_client: MT5Client,
        settings: TriarchSettings | None = None,
    ) -> None:
        self.mt5_client = mt5_client
        self.settings = settings or get_settings()
        self.symbols = get_symbols()
        # Confluencia por activo: el perfil scalper usa una permisiva, el
        # quality una exigente. Ver confluence.build_confluence_for.
        self.confluence_by_symbol: dict[str, ConfluenceFilter] = {
            name: build_confluence_for(cfg, self.settings)
            for name, cfg in self.symbols.items()
        }
        self.store = AuditStore()
        self.writer = ObsidianWriter(self.settings.obsidian_vault_path)
        self.notifiers: list[Notifier] = build_default_notifiers()

        # Equity inicial — se actualiza en cada tick desde MT5
        info = self.mt5_client.account_info()
        equity = info.equity if info else 10_000.0
        self.risk = RiskManager(
            symbols=self.symbols,
            kill_switch=bool(self.settings.triarch_kill),
            account_equity=equity,
        )

        # Trade monitor — vigila tickets abiertos y registra cierres
        self.monitor = TradeMonitor(
            mt5_client=self.mt5_client,
            store=self.store,
            risk=self.risk,
        )

        # Última vela CERRADA ya procesada por símbolo. Evita re-evaluar la vela
        # en formación en cada tick (lo que generaba miles de rechazos duplicados
        # y desajustaba el live respecto al backtest, que usa velas completas).
        self._last_bar: dict[str, object] = {}
        self._tick_count = 0

        # ─── Visibilidad por Telegram ───────────────────────────────────────
        # Contadores de actividad para el latido/resumen periódico. Sirven para
        # confirmar que el bot "está captando algo" aunque no dispare trades
        # (que con confluencia 2/2 puede pasar varias horas seguidas).
        self._activity = {
            "setups": 0,            # señales crudas que emitió alguna strat
            "passed_confluence": 0,  # pasaron el filtro de confluencia
            "rejected_confluence": 0,
            "rejected_risk": 0,
            "signals_emitted": 0,    # notificadas (SIGNAL_ONLY)
            "orders_placed": 0,      # órdenes reales colocadas (AUTO)
        }
        self._started_at = datetime.now(timezone.utc)
        self._last_status_at: datetime | None = None
        # Cada cuántos minutos mandar el resumen de actividad a Telegram.
        # Override con env TELEGRAM_STATUS_EVERY_MIN. 0 = desactiva el latido.
        import os
        try:
            self._status_every_min = int(os.getenv("TELEGRAM_STATUS_EVERY_MIN", "120"))
        except ValueError:
            self._status_every_min = 120

    # ─────────────────────────────────────────────────────
    # Notificaciones de estado (Telegram + log)
    # ─────────────────────────────────────────────────────
    def _broadcast_status(self, text: str) -> None:
        for n in self.notifiers:
            try:
                n.status(text)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"status notifier {type(n).__name__} falló: {e}")

    def send_startup_status(self) -> None:
        """Avisa por Telegram que el bot arrancó y qué está vigilando."""
        lines = ["🟢 *Triarch arrancó* — vigilando mercado:"]
        for name, cfg in self.symbols.items():
            live = get_take_trades(name, default=cfg.take_trades)
            eff = cfg.mode.value if live else "SIGNAL_ONLY"
            tag = "🤖 ejecuta órdenes" if (live and cfg.mode is ExecutionMode.AUTO) else "🔔 solo señal"
            lines.append(
                f"`{name}` {cfg.timeframe} · {cfg.session_utc.start}-{cfg.session_utc.end} UTC · {eff} · {tag}"
            )
        lines.append("_Recibirás aquí cada señal que pase confluencia + risk._")
        self._broadcast_status("\n".join(lines))
        self._last_status_at = datetime.now(timezone.utc)

    def _maybe_send_status(self) -> None:
        """Latido periódico: confirma que el bot sigue vivo y captando setups."""
        if self._status_every_min <= 0:
            return
        now = datetime.now(timezone.utc)
        ref = self._last_status_at or self._started_at
        if now - ref < timedelta(minutes=self._status_every_min):
            return
        a = self._activity
        last_bars = ", ".join(
            f"{s} {str(t)[11:16]}" for s, t in self._last_bar.items()
        ) or "—"
        text = (
            "💓 *Triarch sigue vivo*\n"
            f"Últimas {self._status_every_min} min de actividad:\n"
            f"· setups vistos: `{a['setups']}`\n"
            f"· pasaron confluencia: `{a['passed_confluence']}`\n"
            f"· rechazos confluencia/risk: `{a['rejected_confluence']}`/`{a['rejected_risk']}`\n"
            f"· señales notificadas: `{a['signals_emitted']}`  · órdenes (oro): `{a['orders_placed']}`\n"
            f"· últimas velas: {last_bars}"
        )
        self._broadcast_status(text)
        # Resetear contadores de la ventana
        for k in self._activity:
            self._activity[k] = 0
        self._last_status_at = now

    # ─────────────────────────────────────────────────────
    # Tick: evalúa todos los activos una vez
    # ─────────────────────────────────────────────────────
    def tick(self) -> None:
        # Refresh equity para risk calcs
        info = self.mt5_client.account_info()
        if info:
            self.risk.account_equity = info.equity

        if self.risk.kill_switch:
            logger.warning("Kill switch global activado — saltando tick.")
            return

        # Primero: refresh de trades abiertos (detecta cierres SL/TP/manual)
        try:
            self.monitor.poll()
        except Exception as e:  # noqa: BLE001
            logger.exception(f"TradeMonitor falló: {e}")

        self._tick_count += 1
        for name, cfg in self.symbols.items():
            try:
                self._tick_symbol(cfg)
            except Exception as e:  # noqa: BLE001
                logger.exception(f"Error en tick {name}: {e}")

        # Heartbeat cada ~20 ticks para confirmar que el loop sigue vivo aunque
        # no haya señales (útil para detectar si el proceso murió silenciosamente).
        if self._tick_count % 20 == 1:
            last_bars = ", ".join(
                f"{s}={str(t)[:16]}" for s, t in self._last_bar.items()
            ) or "sin velas aún"
            logger.info(f"[heartbeat] tick #{self._tick_count} vivo · últimas velas: {last_bars}")

        # Latido/resumen a Telegram (cada TELEGRAM_STATUS_EVERY_MIN minutos).
        self._maybe_send_status()

    def _tick_symbol(self, cfg: SymbolConfig) -> None:
        df = self.mt5_client.get_rates(
            broker_symbol=cfg.broker_symbol,
            timeframe=cfg.timeframe,
            n_bars=300,
        )
        if df.empty or len(df) < 62:
            logger.debug(f"{cfg.name}: velas insuficientes ({len(df)})")
            return

        # ─── EVALUAR SOLO VELAS CERRADAS ───
        # La última fila de MT5 es la vela EN FORMACIÓN (cambia cada tick). El
        # backtest usa velas completas; para que el live coincida y para no
        # re-emitir/rechazar la misma vela en cada tick, descartamos la vela en
        # formación y evaluamos la última CERRADA, UNA sola vez por vela.
        df = df.iloc[:-1].reset_index(drop=True)
        last_closed_time = df.iloc[-1]["time"]
        if self._last_bar.get(cfg.name) == last_closed_time:
            return  # esta vela cerrada ya se procesó en un tick anterior
        self._last_bar[cfg.name] = last_closed_time

        df = add_default_indicators(df)
        df = opening_range(df, minutes=15)

        strategies = build_strategies(cfg.strategies)
        ctx = StrategyContext(symbol_cfg=cfg, df=df)

        signals: list[Signal] = []
        for strat in strategies:
            ev, sig = strat.evaluate(ctx)
            self.store.save_eval(ev)
            if sig:
                signals.append(sig)

        # Log de visibilidad: vela nueva evaluada + cuántas strats dispararon.
        if signals:
            self._activity["setups"] += len(signals)
            fired = ", ".join(f"{s.strategy}/{s.direction.value}" for s in signals)
            logger.info(
                f"{cfg.name}: vela {str(last_closed_time)[:16]} → "
                f"{len(signals)} setup(s): {fired}"
            )
        else:
            logger.debug(f"{cfg.name}: vela {str(last_closed_time)[:16]} → sin setups")

        if not signals:
            return

        # Confluence (por activo)
        confluence = self.confluence_by_symbol.get(cfg.name)
        if confluence is None:
            confluence = build_confluence_for(cfg, self.settings)
            self.confluence_by_symbol[cfg.name] = confluence
        decision = confluence.filter(signals)
        if not decision.accepted:
            self._activity["rejected_confluence"] += 1
            for s in decision.rejected_signals or signals:
                s.status = SignalStatus.REJECTED_CONFLUENCE
                s.reject_reason = decision.reason
                self.store.save_signal(s)
            logger.info(f"{cfg.name}: confluencia rechazó — {decision.reason}")
            return

        chosen = decision.chosen_signal
        assert chosen is not None
        self._activity["passed_confluence"] += 1

        # Risk
        rd = self.risk.can_take_signal(chosen, now=datetime.now(timezone.utc))
        if not rd.accepted:
            self._activity["rejected_risk"] += 1
            chosen.status = SignalStatus.REJECTED_RISK
            chosen.reject_reason = f"{rd.reason.value}: {rd.detail}"
            self.store.save_signal(chosen)
            logger.info(f"{cfg.name}: risk rechazó — {chosen.reject_reason}")
            return

        # ─── Switch live: si take_trades=False → forzar SIGNAL_ONLY ───
        live_take = get_take_trades(cfg.name, default=cfg.take_trades)
        effective_mode = cfg.mode if live_take else ExecutionMode.SIGNAL_ONLY
        if effective_mode is not cfg.mode:
            logger.debug(
                f"{cfg.name}: take_trades=False → modo efectivo SIGNAL_ONLY "
                f"(yaml mode={cfg.mode.value})"
            )
        # Reflejar el modo efectivo en el ctx del executor mediante una copia ligera
        cfg_effective = cfg.model_copy(update={"mode": effective_mode})

        # Sizing — sólo si vamos a colocar orden
        if effective_mode is ExecutionMode.AUTO:
            lot = calc_lot_risk_pct(chosen, cfg_effective, self.mt5_client)
            chosen.features["lot"] = lot

        # Executor
        executor = build_executor(cfg_effective, self.mt5_client)
        result = executor.place(chosen)
        chosen.status = result.new_status
        if result.mt5_ticket:
            chosen.mt5_ticket = result.mt5_ticket
            chosen.placed_at_utc = datetime.now(timezone.utc)
        if not result.success:
            chosen.reject_reason = result.message
            logger.error(f"{cfg.name}: executor falló — {result.message}")

        self.store.save_signal(chosen)

        # Notifiers
        for n in self.notifiers:
            try:
                n.notify(chosen, mode=effective_mode.value)
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Notifier {type(n).__name__} falló: {e}")

        if result.success and effective_mode is ExecutionMode.AUTO:
            self.risk.on_trade_open(cfg.name)
            self._activity["orders_placed"] += 1
        else:
            self._activity["signals_emitted"] += 1
