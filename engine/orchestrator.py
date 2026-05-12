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

from datetime import datetime, timezone

from loguru import logger

from audit.obsidian_writer import ObsidianWriter
from audit.store import AuditStore
from config.runtime import get_take_trades
from config.settings import ExecutionMode, SymbolConfig, TriarchSettings, get_settings, get_symbols
from confluence.filter import ConfluenceConfig, ConfluenceFilter
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
        self.confluence = ConfluenceFilter(
            ConfluenceConfig(
                min_signals=self.settings.triarch_confluence_min_signals,
                min_families=self.settings.triarch_confluence_min_families,
                min_combined_score=self.settings.triarch_confluence_min_score,
            )
        )
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

        for name, cfg in self.symbols.items():
            try:
                self._tick_symbol(cfg)
            except Exception as e:  # noqa: BLE001
                logger.exception(f"Error en tick {name}: {e}")

    def _tick_symbol(self, cfg: SymbolConfig) -> None:
        df = self.mt5_client.get_rates(
            broker_symbol=cfg.broker_symbol,
            timeframe=cfg.timeframe,
            n_bars=300,
        )
        if df.empty:
            logger.debug(f"{cfg.name}: no hay velas")
            return

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

        if not signals:
            return

        # Confluence
        decision = self.confluence.filter(signals)
        if not decision.accepted:
            for s in decision.rejected_signals or signals:
                s.status = SignalStatus.REJECTED_CONFLUENCE
                s.reject_reason = decision.reason
                self.store.save_signal(s)
            logger.info(f"{cfg.name}: confluencia rechazó — {decision.reason}")
            return

        chosen = decision.chosen_signal
        assert chosen is not None

        # Risk
        rd = self.risk.can_take_signal(chosen, now=datetime.now(timezone.utc))
        if not rd.accepted:
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
