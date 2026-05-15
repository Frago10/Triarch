# Triarch Bot

> Bot de trading sistemático sobre **MetaTrader 5**, multi-activo (NAS100, XAUUSD, EURUSD), multi-estrategia con capa de confluencia y 3 modos de ejecución por activo.

**Vault note:** [[../../../01 - Projects/Proyecto - Triarch Bot (MT5 Multi-Asset)]]

## ¿Por qué "Triarch"?

- **3 activos** — NAS100, XAUUSD, EURUSD
- **3 modos de ejecución** — SIGNAL_ONLY, APPROVAL, AUTO (configurable por activo)
- **3 capas de aprendizaje** — postmortem LLM → ML clásico → RL

## Filosofía

Este bot está construido sobre las lecciones documentadas en el vault, especialmente las de [[../../../03 - Resources/Trading/Roybot/Roybot - Lecciones para nuestro bot|Roybot]] y [[../../../03 - Resources/Trading/Bots y Algos/Lecciones para nuestro sistema|Bots y Algos]]:

1. **Multi-estrategia con confluencia** > una sola estrategia mágica.
2. **Risk manager con caps duros** es lo que diferencia un bot serio de un script de juguete.
3. **Audit trail forense** — cada decisión queda registrada (incluyendo rechazos).
4. **Empezar simple** — 1 estrategia, después 3, después 5+.
5. **No saltar de fase** sin métricas pre-definidas que se cumplan.

## Estructura del repo

```
triarch/
├── config/             # settings, symbols mapping
├── data_layer/         # MT5 client, candles, cache
├── engine/             # indicators, régimen, orchestrator
├── strategies/         # ORB, VWAP_MR, EMA_MOMENTUM, ...
├── confluence/         # filtro min-señales + min-familias
├── risk/               # RiskManager, lock-outs, caps
├── executor/           # SIGNAL_ONLY / APPROVAL / AUTO
├── signals/            # schema Pydantic + notifiers
├── audit/              # SQLite + writer Obsidian
├── learning/           # postmortem LLM, features, ML, RL
├── dashboard/          # Streamlit
├── scripts/            # entrypoints (run_live, backtest, etc.)
├── tests/              # pytest
└── docs/               # setup-mt5-demo, architecture
```

## Setup rápido

### Requisitos

- Windows (MetaTrader 5 solo corre en Windows; el paquete Python `MetaTrader5` requiere Windows también)
- Python 3.11+
- Terminal MetaTrader 5 instalada y con cuenta demo activa

### Instalación

```powershell
cd "03 - Resources\Data Engineering\Python\triarch"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
# Edita .env con tus credenciales MT5 demo
```

### Test de conexión

```powershell
python -m scripts.connect_mt5
```

Si todo va bien verás el balance de la cuenta y velas recientes de los 3 activos.

### Cómo abrir cuenta demo MT5

Ver [`docs/setup-mt5-demo.md`](docs/setup-mt5-demo.md) — guía paso a paso (broker, descarga, crear demo, anotar credenciales).

## Modos de ejecución

| Modo | Comportamiento | Uso típico |
|---|---|---|
| **SIGNAL_ONLY** | Detecta setups, escribe a SQLite, manda notificación. **No coloca órdenes.** | Fase MVP, validación inicial |
| **APPROVAL** | Detecta setup, manda notificación con botones (Telegram). **Coloca orden solo si confirmas.** | Trading semi-asistido |
| **AUTO** | Detecta setup → valida con risk manager → coloca orden con SL fijo. | Producción tras pasar criterios |

Configurable **por activo** en `config/symbols.yaml`:

```yaml
NAS100:
  mode: SIGNAL_ONLY
XAUUSD:
  mode: APPROVAL
EURUSD:
  mode: AUTO
```

## Risk manager — reglas duras

Heredadas de Roybot (ver [[../../../03 - Resources/Trading/Roybot/Roybot - Risk management]]):

| Regla | Default |
|---|---|
| SL obligatorio | siempre |
| R:R mínimo | 1.5 |
| Daily loss cap (% equity) | 2% |
| Consec losses cap | 3 |
| Max trades / día / activo | 5 |
| Slippage filter | rechazar si ATR-deviation > 1.5× |
| Kill switch global | env var `TRIARCH_KILL=1` |

## Capa de aprendizaje (3 niveles)

### v1 — Postmortem LLM en Obsidian
Cada domingo, `learning/postmortem.py` lee SQLite y genera una nota markdown en `wiki/postmortems/YYYY-WW.md` del vault. Resume: trades de la semana, qué estrategia perform mal, en qué régimen, propuestas de ajuste.

### v2 — ML clásico (XGBoost)
Cada signal escribe sus **features** (ATR, vol ratio, hora, régimen, ema_alignment, etc.) a la SQLite. Modelo XGBoost entrenado offline filtra señales con prob baja antes de emisión.

### v4+ — RL sobre el ejecutor
Agente RL que aprende cuándo entrar dado el state. Solo después de tener histórico ≥1 año real.

## Plan iterativo

Ver [[../../../01 - Projects/Proyecto - Triarch Bot (MT5 Multi-Asset)|nota de proyecto]] sección "Plan iterativo".

| Versión | Qué incluye | ETA |
|---|---|---|
| v0 | Setup, scaffold, conexión MT5 | semana 1 |
| v1 | ORB + risk + SIGNAL_ONLY + dashboard | semana 2-3 |
| v2 | 3 estrategias + confluencia + APPROVAL + AUTO | semana 4-6 |
| v3 | Postmortem LLM + features + régimen | semana 7-9 |
| v4 | ML filter + capital real 25% | mes 4+ |
| v5+ | RL exploratorio | mes 6+ |

## Cómo correr

```powershell
# Test de conexión MT5
python -m scripts.connect_mt5

# Loop principal en SIGNAL_ONLY (modo MVP)
python -m scripts.run_live

# Dashboard
streamlit run dashboard/app.py

# Backtest
python -m scripts.backtest --symbol XAUUSD --tf M15 --from 2024-01-01

# Postmortem manual
python -m learning.postmortem --week 2026-W18

# Tests
pytest
```

## Notas para Claude (CLAUDE.md)

Cuando ayudes a iterar este bot:

1. **Lee primero** [[../../../03 - Resources/Trading/Roybot/MOC - Roybot]] — toda la filosofía del approach.
2. **Antes de añadir estrategias**, valida que las existentes pasaron los criterios de promoción.
3. **Nunca elimines** una regla del risk manager sin nota en la bitácora del proyecto.
4. **Cada feature relevante** se documenta como nota en el vault — el vault es la memoria del proyecto.
5. **Cualquier cambio que afecte performance** requiere backtest comparativo before/after.

## Disclaimer

Este es un proyecto **personal de investigación y construcción**. Operar mercados financieros conlleva riesgo de pérdida. El bot empieza estrictamente en cuenta demo y solo pasa a capital real después de cumplir criterios numéricos pre-definidos. Las decisiones de capital son responsabilidad del operador.

## Licencia

Privado — uso personal de Frago.
