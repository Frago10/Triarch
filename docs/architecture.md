# Triarch — Arquitectura técnica

> Versión 0.1, 2026-05-05. Inspirada en [[../../../Trading/Roybot/Roybot - Arquitectura técnica]] del vault.

## Vista de alto nivel

```
                ┌─────────────────────────────────────┐
                │         MT5 Terminal (Windows)       │
                └──────────────┬──────────────────────┘
                               │ paquete MetaTrader5
                               ▼
   ┌──────────────────────────────────────────────────────────┐
   │                    Triarch (Python)                       │
   │                                                            │
   │  scripts/run_live  ──►  Orchestrator.tick()  (cada 60s)   │
   │                              │                             │
   │            ┌─────────────────┼─────────────────┐           │
   │            ▼                 ▼                 ▼           │
   │     data_layer/         engine/           strategies/      │
   │     (MT5 client)     (indicators,         (ORB v1,        │
   │                      régimen, OR)         +VWAP_MR v2,    │
   │                                            +EMA_MOM v2)   │
   │            │                 │                 │           │
   │            └────────┬────────┴────────┬────────┘           │
   │                     ▼                 ▼                    │
   │              confluence/          risk/                    │
   │              (filtro min-σ,       (lock-outs,              │
   │               min-familias)       caps, window)            │
   │                     │                 │                    │
   │                     └────────┬────────┘                    │
   │                              ▼                              │
   │                        executor/                            │
   │                  (SIGNAL_ONLY/APPROVAL/AUTO)               │
   │                              │                              │
   │            ┌─────────────────┼─────────────────┐            │
   │            ▼                 ▼                 ▼            │
   │      audit/store         signals/         dashboard/        │
   │      (SQLite)            notifiers        (Streamlit)       │
   │            │             (Telegram,                         │
   │            ▼              Discord)                          │
   │      audit/obsidian_writer                                  │
   │            │                                                │
   └────────────┼────────────────────────────────────────────────┘
                ▼
       ┌────────────────────────┐
       │   Obsidian Vault        │
       │   - sessions/           │
       │   - postmortems/        │
       └────────────────────────┘
```

## Modulos

### `config/`
- `settings.py` — pydantic-settings + carga `symbols.yaml`. Singleton `get_settings()` y `get_symbols()`.
- `symbols.yaml` — config por activo (mode, sesión, risk overrides, sizing, estrategias).

### `data_layer/`
- `mt5_client.py` — wrapper sobre `MetaTrader5`. `MT5Client.session()` context manager. Mock-friendly cuando no hay MT5.
- `candles.py` (futuro) — caché y normalización multi-timeframe.

### `engine/`
- `indicators.py` — EMA/SMA/ATR/RSI/Bollinger/VWAP/Opening Range, todo en pandas.
- `regime.py` (v3) — detector de régimen.
- `orchestrator.py` — bucle principal `.tick()`.

### `strategies/`
- `base.py` — ABC con contrato `(StrategyContext) → (Eval, Signal | None)`.
- `orb.py` — primera estrategia (Opening Range Breakout).
- `registry.py` — mapping nombre → clase.

### `confluence/`
- `filter.py` — recibe lista de Signal, devuelve ConfluenceDecision (acepta/rechaza).

### `risk/`
- `manager.py` — RiskManager por símbolo. Lock-outs estilo Roybot. State machine.

### `executor/`
- `base.py` — ABC `Executor.place(signal) → ExecutionResult`.
- `signal_only.py` / `approval.py` / `auto.py` — modos.
- `factory.py` — construye executor según mode del activo.
- `sizing.py` — position sizing (risk_pct por defecto).

### `signals/`
- `schema.py` — Pydantic Signal y Eval.
- `notifiers.py` — Logger / Telegram / Discord.

### `audit/`
- `store.py` — SQLite. Tablas: `signals`, `evals`, `sessions`.
- `obsidian_writer.py` — escribe `wiki/triarch/sessions/YYYY-MM-DD.md` y `wiki/triarch/postmortems/YYYY-Www.md`.

### `learning/`
- `postmortem.py` — agrega SQLite + escribe nota md semanal con prompt para Claude.
- `features.py` (v2) — feature store por trade.
- `filter_ml.py` (v2) — XGBoost.
- `rl/` (v4+) — RL exploratorio.

### `dashboard/`
- `app.py` — Streamlit con pestañas Live / Signals / Evals / Stats.

## Flujo de un tick

1. `run_live` llama a `Orchestrator.tick()` cada 60s (configurable).
2. Refresca equity desde MT5.
3. Para cada símbolo en `symbols.yaml`:
   1. Lee 300 velas del timeframe configurado.
   2. Añade indicadores.
   3. Calcula opening range.
   4. Construye estrategias listadas.
   5. Cada estrategia devuelve (Eval, Signal | None) — el Eval siempre se guarda.
   6. Recolectamos las Signal no-None.
   7. Pasamos por `ConfluenceFilter` — descarta si no cumple min-σ/min-fam.
   8. Pasamos por `RiskManager.can_take_signal()` — respeta caps/window/RR.
   9. Si pasa: factory `build_executor(cfg)` según mode del activo.
   10. `executor.place(signal)` — devuelve ExecutionResult.
   11. Guardamos signal con su nuevo status.
   12. Notifiers (logger + Telegram si configurado).
   13. Si AUTO + success: `risk.on_trade_open(symbol)`.

## Lifecycle de un trade (cuando AUTO)

Para v1 (modo AUTO):
- `placed_at_utc` se llena al colocar la orden.
- El `mt5_ticket` queda en `signals.mt5_ticket`.
- Un job de polling (futuro: `executor/monitor.py`) verá si el ticket cerró por SL/TP/manual y actualizará `closed_at_utc`, `pnl_money`, `status`.
- Cuando cierra: `risk.on_trade_close(symbol, pnl)` actualiza contadores.

## Decisiones de diseño

### ¿Por qué Pydantic para signals?
- Validación automática (`rr_ratio > 0`).
- Serialización a JSON / SQLite trivial.
- Mejor DX en dashboard y tests.

### ¿Por qué SQLite en v1?
- Cero infra, file-based.
- Pandas + SQL queries cómodas.
- Para v3 con concurrencia más seria → Postgres.

### ¿Por qué un risk manager por símbolo?
- Cada activo tiene su propio régimen, su propia ventana, sus propios contadores.
- Si un activo se bloquea, los otros siguen.

### ¿Por qué magic numbers únicos por estrategia?
- Permite filtrar trades del bot vs trades manuales en el histórico de MT5.
- Permite saber qué estrategia abrió qué trade en post-mortem.

## Lo que NO está en v1 (para evitar over-engineering)

- ❌ News filter automático (calendario macro).
- ❌ Régimen de mercado (clustering / HMM).
- ❌ Multi-timeframe coordination (sólo M15 en v1).
- ❌ Trade monitor (ver SL/TP hits, mover SL a BE).
- ❌ Backtester completo (`scripts/backtest.py` viene en v1.5).
- ❌ Web frontend Next.js (sólo Streamlit en v1).
- ❌ ML filter / RL.

Cada uno tiene su lugar en el roadmap.
