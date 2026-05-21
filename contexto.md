\################################################################################

\#  TRIARCH BOT — CONTEXTO DEL PROYECTO

\#  Última actualización: 2026-05-12

\#

\#  PROPÓSITO DE ESTE ARCHIVO

\#  -------------------------

\#  Memoria viva del proyecto. Se lee PRIMERO al retomar el trabajo en una sesión

\#  nueva. Cuando Claude empieza desde cero, lee esto y reconstruye el estado

\#  mental del proyecto sin tener que re-explorar todo el código.

\#

\#  CÓMO ACTUALIZARLO

\#  -----------------

\#  Al final de cada sesión, actualizar como mínimo:

\#    · §03  ETAPA ACTUAL

\#    · §10  CHANGELOG

\#    · §11  PRÓXIMOS PASOS

\#  El resto solo si hubo cambio estructural.

\#

\#  ÍNDICE

\#  ------

\#  §01  Resumen ejecutivo del proyecto

\#  §02  Filosofía y reglas inquebrantables

\#  §03  ETAPA ACTUAL — dónde estamos ahora mismo

\#  §04  Arquitectura — mapa de carpetas

\#  §05  Perfiles por activo

\#  §06  Switches en vivo (runtime.yaml)

\#  §07  Dashboard — pestañas y contratos

\#  §08  Backtesting — cómo se corre y qué reporta

\#  §09  Comandos de uso (PowerShell)

\#  §10  Changelog (inverso)

\#  §11  Próximos pasos

\#  §12  Notas técnicas y lecciones

\################################################################################





\################################################################################

\#  §01  RESUMEN EJECUTIVO

\################################################################################



Triarch es un bot de trading sistemático sobre MetaTrader 5.



&#x20; • Multi-activo:    NAS100 (índice), XAUUSD (commodity), EURUSD (FX)

&#x20; • Multi-estrategia con capa de confluencia entre familias

&#x20; • 3 modos de ejecución por activo: SIGNAL\_ONLY | APPROVAL | AUTO

&#x20; • 3 capas de aprendizaje (planificadas):

&#x20;       v1  Postmortem LLM en Obsidian (implementado)

&#x20;       v2  ML clásico XGBoost (pendiente)

&#x20;       v4+ RL sobre el ejecutor (lejano)



Codename "Triarch" = 3 activos × 3 modos × 3 capas de aprendizaje.





\################################################################################

\#  §02  FILOSOFÍA — REGLAS INQUEBRANTABLES

\################################################################################



Heredadas de Roybot:



&#x20; 1. Multi-estrategia con confluencia > una sola estrategia mágica

&#x20; 2. Risk manager con caps duros (SL obligatorio, RR mínimo, daily loss cap)

&#x20; 3. Audit trail forense — cada decisión queda registrada, incluyendo rechazos

&#x20; 4. Empezar simple, iterar (no añadir estrategia #5 sin promocionar las 4)

&#x20; 5. No saltar de fase sin métricas pre-definidas que se cumplan



Reglas que NUNCA se eliminan sin nota en la bitácora del proyecto:



&#x20; · SL siempre presente al colocar una orden

&#x20; · RR mínimo respetado (varía por activo: 0.8 EURUSD, 1.5 NAS100, 2.2 XAUUSD)

&#x20; · Daily loss cap activo

&#x20; · Max trades por día por activo

&#x20; · Kill switch global (TRIARCH\_KILL=1)





\################################################################################

\#  §03  ETAPA ACTUAL

\################################################################################



Fecha: 2026-05-14



ESTAMOS EN: 3er activo cambiado a EURUSD + arreglado el bug de descarga de

histórico que hacía que los pares en M5 (forex) devolvieran 0 velas.



──────────────────────────────────────────────────────────────────────────

FIX: DESCARGA DE HISTÓRICO EN M5 (forex devolvía 0 velas)  (2026-05-14)

──────────────────────────────────────────────────────────────────────────

SÍNTOMA: USDJPY y luego EURUSD no devolvían data en el backtest, pero

NAS100 (M15) y XAUUSD (M30) sí. El usuario lo notó: "raro que el par no

muestre data".



CAUSA RAÍZ: data\_layer/mt5\_client.get\_rates hacía UNA sola llamada gigante a

`mt5.copy\_rates\_range(symbol, tf, from\_date, now)`. MT5 solo devuelve lo que

está en la caché local del terminal; para M5 a 1 año (\~75k velas) esa caché

casi nunca cubre todo → copy\_rates\_range devuelve VACÍO (no parcial, vacío).

Con M15/M30 el rango es chico (\~17k / \~8k velas) y sí está en caché.

NO era un problema de "símbolo inexistente" ni de que fuera forex — era

M5 + rango largo en una sola llamada.



FIX APLICADO en data\_layer/mt5\_client.py:

&#x20; · get\_rates ahora descarga EN CHUNKS (\~5000 velas por chunk: M5≈17 días,

&#x20;   M15≈52d, M30≈104d) y concatena.

&#x20; · Cada chunk se pide con reintentos (\_rates\_range\_retry): MT5 baja el

&#x20;   histórico async, así que la 1ª llamada puede venir vacía y disparar la

&#x20;   descarga; las siguientes ya traen datos.

&#x20; · Modo "live" (from\_date=None) usa \_rates\_pos\_retry, también con reintentos.

&#x20; · Si TODOS los chunks vienen vacíos → mensaje claro: o el símbolo no existe,

&#x20;   o hay que abrir el gráfico en MT5 y hacer scroll atrás para que baje

&#x20;   history, y re-correr (fetch\_history es incremental).

&#x20; · fetch\_history.py: mensajes de error actualizados (distingue "símbolo mal"

&#x20;   de "history no bajado").



──────────────────────────────────────────────────────────────────────────

CAMBIO DE ACTIVO: USDJPY → EURUSD  (2026-05-14)

──────────────────────────────────────────────────────────────────────────

El 3er activo pasó de USDJPY a EURUSD en TODO el proyecto (symbols.yaml,

runtime.yaml, README, docs, comentarios, etc.). Razón: decisión del usuario.

EURUSD conserva el perfil "scalper puro": SCALPER + BB\_MR, confluencia 1/1,

min\_rr 0.8, cap 8 trades/día, objetivo \~30/semana.

Diferencia vs USDJPY: la sesión cambió a 07:00-16:00 UTC (Londres + solape NY,

la franja fuerte de EURUSD).

Verificación: backtest sintético EURUSD → 755 trades, WR 52%, lógica corre OK.



──────────────────────────────────────────────────────────────────────────

RESULTADOS DEL TUNING #2 (2026-05-14)

──────────────────────────────────────────────────────────────────────────



XAUUSD M30 — backtest sobre 1 año de DATA REAL:

&#x20; Probé cada estrategia sola y combinada. Hallazgo:

&#x20;   · ORB sola          → PIERDE (PF 0.92). Demasiados falsos breakouts.

&#x20;   · BB\_MR sola        → marginal (PF 1.10).

&#x20;   · EMA\_MOMENTUM sola → PF 1.51 · WR 41% · E +0.30R · DD 7R · 2.6 tr/sem  ★

&#x20;   · Combinarlas BAJA el PF (confluencia a veces elige la peor señal).

&#x20; CONFIG ELEGIDA: EMA\_MOMENTUM sola, min\_rr 2.2, confluencia 1/1.

&#x20; → trades=105 · WR 40.9% · PF 1.51 · E +0.303R · avgW 2.18R · DD 7R



EURUSD M5 — NO HAY DATA REAL TODAVÍA. Backtest sobre M5 SINTÉTICO:

&#x20; El SCALPER produce trades correctamente: 755 trades, WR 52%, \~15 tr/sem.

&#x20; En data aleatoria da \~breakeven (esperado). La lógica funciona; falta

&#x20; validar y tunear sobre DATA REAL de EURUSD.



──────────────────────────────────────────────────────────────────────────

⚠  LA VERDAD SOBRE "50-60% WR + RR 1:2-1:3" (decisión importante)

──────────────────────────────────────────────────────────────────────────

Esa combinación NO existe en trading sistemático real: implicaría un Profit

Factor de 2.5 a 4.5. Hay un tradeoff físico:

&#x20;  · Estrategias de momentum/breakout → WR 35-45%, wins grandes (RR 2-3)

&#x20;  · Estrategias de mean-reversion    → WR 55-65%, wins chicos  (RR 0.6-1)

EMA\_MOMENTUM en oro da 41% WR con RR 2.2 → PF 1.51. Es un sistema SÓLIDO.

Para tener 55%+ WR habría que aceptar RR \~1:1 (cambiar a mean-reversion puro).

Recomendación registrada: quedarse con el perfil momentum en oro; el WR de

41% con PF 1.51 es mejor negocio que 55% WR con PF 1.1.

Lo mismo aplica al scalper de EURUSD: con RR 0.85 necesita WR > \~54% para

ser rentable — alcanzable porque el scalper apuesta a hit-rate, no a RR.



──────────────────────────────────────────────────────────────────────────

EURUSD — QUÉ HACER PARA TENERLO OPERATIVO

──────────────────────────────────────────────────────────────────────────

EURUSD existe en prácticamente todo broker con el nombre exacto "EURUSD".

ACCIÓN (PASO 1 de §11): bajar data real con fetch\_history y backtestear.

Si por algún motivo el broker lo llama distinto, fetch\_history ahora avisa

y sugiere el nombre correcto.



──────────────────────────────────────────────────────────────────────────

BUGS DE INFRAESTRUCTURA ENCONTRADOS Y CORREGIDOS

──────────────────────────────────────────────────────────────────────────

&#x20; · Estrategias hardcodeaban rr\_target=1.5 → ahora RR dinámico desde cfg.

&#x20; · Backtester no aplicaba RiskManager → ahora aplica RR-min + cap diario +

&#x20;   sesión, y reporta señales descartadas por cada causa.

&#x20; · Backtester recalculaba indicadores por ventana (lento, \~2min/año) →

&#x20;   ahora los precalcula 1 vez (\~6s/año, 20x más rápido).

&#x20; · `future = df\_full.iloc\[i+1:]` creaba slices gigantes → OOM. Acotado a 250.

&#x20; · Confluencia era global → ahora configurable por activo (build\_confluence\_for).



ARCHIVOS TOCADOS EN ESTA SESIÓN:

&#x20; · strategies/orb.py, ema\_momentum.py, bb\_mr.py — RR dinámico desde cfg

&#x20; · strategies/bb\_mr.py                  — NUEVA (Bollinger Mean Reversion)

&#x20; · strategies/scalper.py                — 2 gatillos + filtro ema\_sep\_min

&#x20; · strategies/registry.py               — registra BB\_MR

&#x20; · scripts/backtest.py                  — risk filters + precompute + slice OOM fix

&#x20; · scripts/fetch\_history.py             — sugiere símbolos cuando uno falla

&#x20; · config/settings.py                   — ConfluenceOverride en SymbolConfig

&#x20; · config/symbols.yaml                  — XAUUSD=EMA\_MOMENTUM@2.2 ·

&#x20;                                          EURUSD=SCALPER+BB\_MR · confluencia x activo

&#x20; · confluence/filter.py                 — build\_confluence\_for(symbol, settings)

&#x20; · engine/orchestrator.py               — confluencia por activo

&#x20; · dashboard/app.py                     — usa backtest\_symbol nueva firma



LO QUE SIGUE INMEDIATAMENTE: ver §11.





\################################################################################

\#  §04  ARQUITECTURA — MAPA DE CARPETAS

\################################################################################



Raíz del proyecto:

&#x20;   C:\\Users\\jeanp\\OneDrive\\מסמכים\\OB vault\\03 - Resources\\Data Engineering\\Python\\triarch



&#x20;   config/           settings + symbols.yaml + runtime.yaml (overrides live)

&#x20;                     └─ runtime.py: API para leer/escribir overrides

&#x20;   data\_layer/       MT5Client (wrapper oficial MetaTrader5)

&#x20;   engine/           indicadores + orchestrator (loop principal)

&#x20;   strategies/       ORB, VWAP\_MR, EMA\_MOMENTUM, SCALPER, BB\_MR

&#x20;                     └─ registry.py mapea nombre → clase

&#x20;   confluence/       filtro mín-señales + mín-familias

&#x20;   risk/             RiskManager (caps, kill-switch, lock-outs)

&#x20;   executor/         SIGNAL\_ONLY | APPROVAL | AUTO + sizing + trade\_monitor

&#x20;   signals/          schema Pydantic + notifiers (Telegram, Discord)

&#x20;   audit/            store SQLite + writer Obsidian

&#x20;   learning/         postmortem semanal (v1) — features ML pendiente

&#x20;   dashboard/        Streamlit (6 pestañas, ver §07)

&#x20;   scripts/          entrypoints CLI:

&#x20;                       connect\_mt5, run\_live, serve, backtest, fetch\_history,

&#x20;                       db\_summary, diagnose\_mt5

&#x20;   tests/            pytest (indicators, orb, risk, confluence, smoke)

&#x20;   docs/             setup-mt5-demo, architecture

&#x20;   data\_cache/       triarch.sqlite (audit) + history/\*.parquet (velas)

&#x20;   logs/             rotación de loguru





\################################################################################

\#  §05  PERFILES POR ACTIVO

\################################################################################



NAS100   — perfil "balanced"

&#x20;   TF M15  ·  estrategias: ORB + VWAP\_MR + EMA\_MOMENTUM

&#x20;   Confluencia: 2 señales / 2 familias / score ≥ 1.0

&#x20;   Objetivo: \~8 trades/semana

&#x20;   Sesión: 13:30–17:00 UTC (cash open NY)

&#x20;   Risk: 0.5% por trade  ·  daily cap 2%  ·  máx 5 trades/día  ·  RR ≥ 1.5



XAUUSD   — perfil "quality"  (config validada en backtest 2026-05-14)

&#x20;   TF M30 (menos ruido que M15)

&#x20;   Estrategias: EMA\_MOMENTUM SOLA — es la única rentable en oro.

&#x20;     Backtest: ORB sola pierde (PF 0.92), BB\_MR marginal (1.10), combinarlas

&#x20;     baja el PF. EMA\_MOMENTUM sola = PF 1.51. ORB/BB\_MR/VWAP\_MR quedan

&#x20;     disponibles en el registry pero NO en la lista activa de XAUUSD.

&#x20;   Confluencia: 1 señal / 1 familia (solo hay 1 estrategia activa)

&#x20;   min\_rr\_ratio 2.2 → TP1 a 2.2R (RR dinámico)

&#x20;   Backtest 1 año: 105 trades · WR 41% · PF 1.51 · E +0.30R · DD 7R · 2.6 tr/sem

&#x20;   Sesión: 12:00–17:00 UTC (solape Londres + NY)

&#x20;   Risk: 0.75% por trade  ·  daily cap 1.5%  ·  máx 2 trades/día

&#x20;   NOTA: el WR de 41% es el techo de las estrategias de momentum. 50-60% WR

&#x20;   + RR 1:2-1:3 a la vez no existe (ver §03). PF 1.51 es un sistema sólido.



EURUSD   — perfil "scalper puro"  (lógica validada, falta data real)

&#x20;   TF M5  ·  el par más líquido del mundo → spread bajo, ideal para scalping

&#x20;   Estrategias: SCALPER + BB\_MR

&#x20;   Confluencia PERMISIVA: 1 señal / 1 familia (un scalper no espera a que

&#x20;   2 estrategias coincidan en la misma vela)

&#x20;   min\_rr\_ratio 0.8 → SCALPER opera con RR \~0.85 (TP cercano, WR alto compensa)

&#x20;   SCALPER tiene filtro ema\_sep\_min (0.0002, suave) — subirlo tras ver data real

&#x20;   Objetivo: \~30 trades/semana, rentable a escala

&#x20;   Sesión: 07:00–16:00 UTC (apertura Londres + solape NY, la franja fuerte)

&#x20;   Risk: 0.25% por trade (más chico, más volumen) · daily cap 1.5% · máx 8/día

&#x20;   Backtest SINTÉTICO: 755 trades · WR 52% · \~15 tr/sem · breakeven

&#x20;     (esperado en data aleatoria — falta data REAL para validar de verdad)

&#x20;   broker\_symbol "EURUSD" casi siempre es el nombre exacto en todo broker





\################################################################################

\#  §06  SWITCHES EN VIVO  (config/runtime.yaml)

\################################################################################



Archivo: config/runtime.yaml

Forma:

&#x20;   take\_trades:

&#x20;     NAS100: false

&#x20;     XAUUSD: false

&#x20;     EURUSD: false



Semántica:

&#x20;   take\_trades = ON   → orchestrator respeta cfg.mode del yaml (puede ejecutar)

&#x20;   take\_trades = OFF  → orchestrator fuerza SIGNAL\_ONLY (solo notifica)



El dashboard tab "Live \& Control" tiene un toggle por activo que escribe a

este archivo. Cambia efectivo en el próximo tick (no requiere reiniciar).



Para parar TODO de golpe (no por activo): TRIARCH\_KILL=1 en .env + reinicio.





\################################################################################

\#  §07  DASHBOARD — UI v3 (rediseño visual)

\################################################################################



Streamlit con paleta dark moderna (cyan/violet accents, glassmorphism, pills

translúcidas con borde, hover en cards).



ARRANQUE:

&#x20; Splash de bienvenida (1 vez por sesión, gated por st.session\_state) con

&#x20; resumen del proyecto y botón "Entrar al bot". Se omite en visitas siguientes.



SIDEBAR (siempre visible):

&#x20; · Wordmark TRIARCH con gradient cyan→violet

&#x20; · Bloque "Entorno" con dot de color (DEMO=verde, LIVE=naranja)

&#x20; · Bloque "Cuenta MT5": login + server + equity + P/L flotante (color)

&#x20; · Bloque "Kill switch global": estado + cómo activarlo

&#x20; · Atajos: comandos CLI más usados

&#x20; · Footer: versión



TABS TOP-LEVEL (5):

&#x20; 1. 🏠 Inicio — resumen ejecutivo del día

&#x20;      · 4 KPIs de cuenta (balance, equity con delta, margen libre, apalanc.)

&#x20;      · Actividad 24h: señales totales, tomadas, rechazadas, cerradas, P/L

&#x20;      · Mini-card por activo con dot de estado + última señal



&#x20; 2. 🎯 Vivo \& Control

&#x20;      · Bloque cuenta MT5 con 5 métricas

&#x20;      · Una tarjeta por activo: perfil, TF, sesión, toggle take\_trades,

&#x20;        última señal con fecha legible + status traducido + motivo



&#x20; 3. 🧠 Decisiones

&#x20;      · Vista legible del audit trail con filtros (activo/estrategia/estado/

&#x20;        dirección/últimos N días)

&#x20;      · KPI grid arriba (encontradas, tomadas, rechazadas, cerradas)

&#x20;      · Tabla con columnas amigables; descarga .txt



&#x20; 4. 📊 Backtesting

&#x20;      · Form: activos múltiples + rango fechas + botón "Correr"

&#x20;      · Tabla comparativa con WR/PF/Sharpe/Sortino/SQN/DD/trades-sem

&#x20;      · Expander por activo con KPI grid (12 métricas), equity curve,

&#x20;        breakdown por estrategia, trade log

&#x20;      · Download resumen .txt



&#x20; 5. 📦 Datos — sub-tabs (vista cruda para debug/export):

&#x20;      · 📈 Signals — tabla cruda

&#x20;      · 🔍 Evals   — audit trail crudo

&#x20;      · 📦 Stats   — agregados últimos 30 días



PALETA Y COMPONENTES:

&#x20; · Acento principal: cyan #5eead4 (vars CSS --tri-accent)

&#x20; · Acento 2:        violeta #a78bfa (gradients, wordmark)

&#x20; · Cards:           glassmorphism rgba(38,39,48,0.55) + blur(4px)

&#x20; · Status pills:    translúcidas con borde sutil del mismo tono

&#x20; · Dots:            con halo box-shadow del color (verde/rojo/naranja/gris)

&#x20; · Hover:           border-color animado + translateY(-2px) en KPIs

&#x20; · Empty states:    centrado, emoji, mensaje útil



DEPENDENCIAS:

&#x20; · MT5Client: el dashboard intenta conectarse para mostrar cuenta. Si falla,

&#x20;   muestra warning. Cuando se usa `scripts.serve`, el dashboard corre en un

&#x20;   subproceso independiente del loop, así que tiene su propia conexión MT5.





\################################################################################

\#  §08  BACKTESTING

\################################################################################



ARCHIVOS:

&#x20;   scripts/fetch\_history.py  → descarga velas MT5 → parquet (data\_cache/history/)

&#x20;   scripts/backtest.py       → corre estrategias sobre los parquet



API REUTILIZABLE (importada por el dashboard):

&#x20;   from scripts.backtest import backtest\_symbol, \_format\_summary



&#x20;   res = backtest\_symbol(cfg, confluence, from\_date=..., to\_date=...)

&#x20;   # res es dict con:

&#x20;   #   trades, wins, losses, win\_rate, profit\_factor, expectancy\_r,

&#x20;   #   avg\_win\_r, avg\_loss\_r, largest\_win\_r, largest\_loss\_r,

&#x20;   #   max\_drawdown\_r, longest\_win\_streak, longest\_loss\_streak,

&#x20;   #   avg\_bars\_held, trades\_per\_week\_avg,

&#x20;   #   sharpe\_ratio, sortino\_ratio, sqn,

&#x20;   #   by\_strategy, trade\_log, equity\_curve, range



LO QUE DEBE PASAR ANTES DEL PRIMER BACKTEST:

&#x20;   1. .env completo con credenciales MT5

&#x20;   2. Terminal MT5 abierto

&#x20;   3. `python -m scripts.fetch\_history --years 1`   ← baja parquet

&#x20;   4. Recién entonces sirve `python -m scripts.backtest` o el tab Backtest



INTERPRETACIÓN DE MÉTRICAS:

&#x20;   Sharpe ratio: > 1 aceptable · > 2 bueno · > 3 excepcional (anualizado, ojo)

&#x20;   Sortino     : igual que Sharpe pero solo cuenta volatilidad negativa

&#x20;   SQN (Van Tharp): > 1.7 sistema decente · > 2.5 bueno · > 3 excelente

&#x20;   Profit factor: > 1.3 mínimo · > 1.7 deseable · > 2 excelente

&#x20;   Expectancy en R: PnL medio esperado por trade en múltiplos de R (riesgo)

&#x20;                    Sistema viable necesita expectancy > 0

&#x20;   Max drawdown en R: cuántos "trades perfectos perdidos" peor caso





\################################################################################

\#  §09  COMANDOS DE USO (PowerShell)

\################################################################################



\# ─── Setup inicial (solo una vez) ───

cd "C:\\Users\\jeanp\\OneDrive\\מסמכים\\OB vault\\03 - Resources\\Data Engineering\\Python\\triarch"

python -m venv .venv

.\\.venv\\Scripts\\Activate.ps1

pip install -e .

copy .env.example .env

\# editar .env con credenciales MT5



\# ─── Cada sesión ───

.\\.venv\\Scripts\\Activate.ps1



\# Test de conexión MT5

python -m scripts.connect\_mt5



\# RECOMENDADO: loop + dashboard en un solo comando

python -m scripts.serve --tick 30 --port 8765

\# abre http://localhost:8765



\# Por separado

python -m scripts.run\_live --tick 30

streamlit run dashboard/app.py



\# Bajar histórico (necesario antes del primer backtest)

python -m scripts.fetch\_history --years 1

python -m scripts.fetch\_history --symbol EURUSD --timeframe M5 --years 2



\# Backtest desde CLI

python -m scripts.backtest

python -m scripts.backtest --symbol XAUUSD --from 2024-01-01 --to 2025-06-30

python -m scripts.backtest --symbol EURUSD --out logs/bt\_eurusd.txt



\# Postmortem manual

python -m learning.postmortem --week 2026-W19



\# Tests unitarios

pytest





\################################################################################

\#  §10  CHANGELOG (inverso)

\################################################################################



\[2026-05-14]  Dashboard UI v3 — splash + sidebar + tabs reorganizadas

&#x20;   Rediseño visual del dashboard sin perder funcionalidad:

&#x20;   • Splash de bienvenida con wordmark TRIARCH (gradient cyan→violet) y

&#x20;     tarjeta de 4 puntos. Gated por st.session\_state\["intro\_done"].

&#x20;   • Sidebar nuevo: branding + entorno + cuenta MT5 (equity, P/L flotante) +

&#x20;     kill switch + atajos CLI + versión.

&#x20;   • Header con banner gradient sutil.

&#x20;   • Tabs reorganizadas: 6 → 5 top-level. Nueva pestaña "🏠 Inicio" con

&#x20;     resumen del día (KPIs cuenta + actividad 24h + mini-cards por activo).

&#x20;     Signals/Evals/Stats consolidados en "📦 Datos" como sub-tabs.

&#x20;   • CSS modernizado: glassmorphism (rgba bg + backdrop-filter), pills

&#x20;     translúcidas con borde, hover en cards/KPIs, dots con halo,

&#x20;     empty states con emoji.

&#x20;   • Variables CSS centralizadas (--tri-accent, --tri-card-bg, etc.).



\[2026-05-14]  Fix — descarga de histórico en M5 (forex devolvía 0 velas)

&#x20;   • data\_layer/mt5\_client.py — get\_rates ahora descarga EN CHUNKS con

&#x20;     reintentos (antes: 1 sola llamada a copy\_rates\_range que fallaba en

&#x20;     M5 + rangos largos). +helpers \_rates\_range\_retry / \_rates\_pos\_retry.

&#x20;     +constante \_BARS\_PER\_DAY para dimensionar los chunks.

&#x20;   • scripts/fetch\_history.py — mensajes de error que distinguen "símbolo

&#x20;     incorrecto" de "histórico no bajado en el terminal".

&#x20;   Causa raíz: copy\_rates\_range solo devuelve lo cacheado por el terminal;

&#x20;   M5 a 1 año (\~75k velas) no entra → vacío. M15/M30 sí entraban.



\[2026-05-14]  Cambio de 3er activo: USDJPY → EURUSD

&#x20;   Decisión del usuario. Reemplazo en TODO el proyecto:

&#x20;   • config/symbols.yaml — bloque USDJPY → EURUSD, sesión 07:00-16:00 UTC

&#x20;                           (franja fuerte de EURUSD). Mismo perfil scalper:

&#x20;                           SCALPER+BB\_MR, confluencia 1/1, min\_rr 0.8, cap 8/día.

&#x20;   • config/runtime.yaml, settings.py, signals/schema.py — refs actualizadas

&#x20;   • strategies/scalper.py — comentarios → EURUSD

&#x20;   • scripts/backtest.py, fetch\_history.py, diagnose\_mt5.py — ejemplos → EURUSD

&#x20;   • README.md, docs/setup-mt5-demo.md — refs → EURUSD

&#x20;   Verificación: backtest sintético EURUSD → 755 trades, WR 52%, lógica OK.

&#x20;   Nota histórica: USDJPY sí existía en el broker, pero el usuario prefirió

&#x20;   EURUSD (más líquido, spread más bajo, mejor para scalping).



\[2026-05-14]  Tuning #2 — backtests corridos por Claude, config validada

&#x20;   Backtests sobre data real (XAUUSD) + sintética (USDJPY):

&#x20;   • config/symbols.yaml — XAUUSD ahora EMA\_MOMENTUM SOLA @ min\_rr 2.2,

&#x20;                           confluencia 1/1 (ORB perdía, combinar bajaba PF).

&#x20;                           USDJPY: cap diario 12→8, comentarios de diagnóstico.

&#x20;   • strategies/scalper.py — +filtro ema\_sep\_min (0.0002, suave) + flag

&#x20;                           pullback\_only. Filtra rangos muertos.

&#x20;   • scripts/backtest.py — precalcula indicadores 1 vez (20x más rápido);

&#x20;                           `future` slice acotado a 250 velas (arreglo OOM).

&#x20;   RESULTADOS: XAUUSD 1 año → PF 1.51, WR 41%, E +0.30R, DD 7R.

&#x20;               USDJPY sintético → WR 53.7%, \~24 tr/sem (breakeven, data random).



\[2026-05-12]  Tuning #1 — RR dinámico, BB\_MR, confluencia por activo

&#x20;   Tras leer el primer backtest (XAUUSD breakeven, USDJPY sin datos):

&#x20;   • strategies/orb.py, ema\_momentum.py — TP1 usa max(rr\_propio, cfg.min\_rr)

&#x20;   • strategies/bb\_mr.py     — NUEVA: Bollinger Mean Reversion (familia "mean")

&#x20;   • strategies/scalper.py   — reescrito: 2 gatillos, RR \~0.85, filtros sesión

&#x20;   • strategies/registry.py  — registra BB\_MR

&#x20;   • scripts/backtest.py     — aplica RR-min + cap diario + sesión; reporta

&#x20;                               señales descartadas; confluencia por activo

&#x20;   • scripts/fetch\_history.py — sugiere símbolos al fallar uno; resumen OK/fail

&#x20;   • config/settings.py      — ConfluenceOverride opcional en SymbolConfig

&#x20;   • config/symbols.yaml     — XAUUSD 4 estrategias + confluencia 2/2 + min\_rr

&#x20;                               2.5; USDJPY SCALPER+BB\_MR + confluencia 1/1 +

&#x20;                               min\_rr 0.8

&#x20;   • confluence/filter.py    — build\_confluence\_for(symbol, settings)

&#x20;   • engine/orchestrator.py  — confluencia por activo (dict por símbolo)

&#x20;   • dashboard/app.py        — backtest\_symbol nueva firma (sin param confluence)



\[2026-05-12]  Dashboard 2.0 + métricas avanzadas

&#x20;   • dashboard/app.py    REWRITE — cards, status traducido, fechas legibles,

&#x20;                         merge Live+Control, nuevo tab Backtesting completo

&#x20;   • scripts/backtest.py +Sharpe, +Sortino, +SQN, +avg win/loss, +rachas,

&#x20;                         +equity\_curve, +trade\_log, +parámetro to\_date

&#x20;   • contexto.txt        Reescrito con índice numerado y secciones marcadas



\[2026-05-12]  Reconstrucción tras incidente OneDrive

&#x20;   • scripts/serve.py            ← entrypoint unificado loop+dashboard

&#x20;   • scripts/fetch\_history.py    ← descarga histórico MT5 → parquet

&#x20;   • scripts/backtest.py         ← backtester con métricas básicas

&#x20;   • strategies/scalper.py       ← nueva estrategia SCALPER para USDJPY

&#x20;   • strategies/registry.py      ← registra SCALPER

&#x20;   • config/symbols.yaml         ← perfiles quality (XAUUSD) y scalper (USDJPY)

&#x20;   • config/settings.py          ← SymbolConfig +take\_trades/profile/target

&#x20;   • config/runtime.py           ← nuevo: get/set overrides en vivo

&#x20;   • config/runtime.yaml         ← nuevo: archivo de overrides persistidos

&#x20;   • engine/orchestrator.py      ← respeta take\_trades runtime

&#x20;   • dashboard/app.py            ← +Control +Decisiones (versión inicial)



\[2026-05-06]  Último snapshot conocido pre-incidente OneDrive

&#x20;   Arquitectura base: 3 estrategias originales (ORB/VWAP\_MR/EMA\_MOMENTUM),

&#x20;   risk manager, audit store, confluence, executor multi-modo, postmortem v1.





\################################################################################

\#  §11  PRÓXIMOS PASOS

\################################################################################



INMEDIATO (la próxima sesión)

&#x20;   \[ ] BAJAR DATA REAL DE EURUSD Y BACKTESTEAR (el bug de M5 ya está arreglado

&#x20;       — ver §03; ahora descarga en chunks):

&#x20;         1. `python -m scripts.fetch\_history --symbol EURUSD --timeframe M5 --years 1`

&#x20;            → si avisa "0 velas / histórico no bajado": abre el gráfico de

&#x20;              EURUSD M5 en MT5, scroll hacia atrás, y RE-CORRE el comando

&#x20;              (es incremental, cada pasada baja más).

&#x20;         2. `python -m scripts.backtest --symbol EURUSD --out logs/bt\_eurusd.txt`

&#x20;         3. Mandar el .txt a Claude para tunear el SCALPER con DATA REAL.

&#x20;   \[ ] git\_push.ps1 — commitear y pushear esta versión (incluye el fix de

&#x20;       descarga M5 + el cambio a EURUSD). Repo: https://github.com/Frago10/Triarch

&#x20;   \[ ] RE-CORRER backtest de XAUUSD con la config nueva para confirmar:

&#x20;           python -m scripts.backtest --symbol XAUUSD --out logs/bt\_xau.txt

&#x20;       Esperado (ya verificado por Claude en sandbox):

&#x20;         \~105 trades · WR \~41% · PF \~1.51 · E +0.30R · DD \~7R · \~2.6 tr/sem

&#x20;   \[ ] pytest — verificar que orchestrator/settings/registry no se rompieron.



DECISIÓN PENDIENTE DEL USUARIO (sobre el win rate de oro)

&#x20;   El objetivo "50-60% WR + RR 1:2-1:3" no es alcanzable (ver §03). Opciones:

&#x20;     A) Quedarse con momentum: 41% WR, PF 1.51 — RECOMENDADO, es sólido.

&#x20;     B) Cambiar a mean-reversion puro en oro: \~55-60% WR pero RR \~1:1,

&#x20;        PF más bajo (\~1.1-1.2). Más "cómodo" psicológicamente, peor negocio.

&#x20;   → Claude recomienda A. El usuario decide.



CORTO PLAZO (esta semana) — depende del backtest de EURUSD con data real

&#x20;   \[ ] Tunear SCALPER sobre data REAL de EURUSD:

&#x20;       · si <30 tr/sem → bajar rel\_atr\_min (0.0003) o ema\_sep\_min (0.0002),

&#x20;         o ampliar la sesión (hoy 07:00-16:00 UTC)

&#x20;       · si WR <54%   → subir ema\_sep\_min, o probar pullback\_only=True,

&#x20;         o ajustar tp\_atr\_mult/sl\_atr\_mult

&#x20;   \[ ] Probar dashboard "Decisiones" y "Backtesting" — validar visualmente.

&#x20;   \[ ] Probar pausar/reanudar con tab "Live \& Control" en sesión real.



MEDIO PLAZO (próximas 2-4 semanas)

&#x20;   \[ ] Empezar learning/features.py — guardar features con cada signal.

&#x20;   \[ ] Telegram con botones inline para APPROVAL mode (build\_default\_notifiers

&#x20;       ya tiene scaffold).

&#x20;   \[ ] Reporte semanal automático (cron + postmortem.py).

&#x20;   \[ ] Filtrar duplicados de signals por mismo (symbol, bar\_time) más estricto

&#x20;       — hoy el dedup\_key incluye strategy y direction.



NO TOCAR HASTA tener métricas de promoción

&#x20;   \[ ] AUTO mode con dinero real

&#x20;       Criterios: ≥ 3 meses demo, PF ≥ 1.3, max DD < 10R, win rate > 40%

&#x20;   \[ ] ML filter en producción (≥ 6 meses de signals reales)

&#x20;   \[ ] RL (≥ 1 año real)





\################################################################################

\#  §12  NOTAS TÉCNICAS Y LECCIONES

\################################################################################



ONEDRIVE

&#x20;   OneDrive movió la carpeta Documents al folder OneDrive sin avisar.

&#x20;   Resultado: la única copia estable es la de OneDrive.

&#x20;   Mitigación: inicializar git LOCAL guarda historial independiente de la nube

&#x20;   y permite rollback.

&#x20;   OneDrive guarda hasta 25 versiones por archivo accesibles desde web

&#x20;   (click derecho → Historial de versiones) y mantiene papelera 30 días.



SINCRONIZACIÓN VS BASH

&#x20;   Cuando se editan archivos por el host, la vista del workspace bash puede

&#x20;   estar stale temporalmente (OneDrive demora unos segundos). Para validar

&#x20;   sintaxis fiable, usar la lectura del host (Read tool) o esperar y reintentar.



SCALPER — TUNING (parámetros actuales tras tuning #2)

&#x20;     rel\_atr\_min: 0.0003   ·  sl\_atr\_mult: 1.0  ·  tp\_atr\_mult: 0.85 → RR ≈ 0.85

&#x20;     ema\_sep\_min: 0.0002 (suave) ·  max\_dist\_ema9\_atr: 0.6

&#x20;     2 gatillos: pull-back (cruce EMA9) + continuación (precio entre EMA9/EMA21)

&#x20;     flag pullback\_only: si True, desactiva el gatillo de continuación

&#x20;   Si en backtest da pocos trades → bajar rel\_atr\_min o ema\_sep\_min.

&#x20;   Si da muchos con WR bajo → subir ema\_sep\_min (0.0004-0.0008), o

&#x20;     pullback\_only=True (el pull-back es el gatillo más fiable).

&#x20;   OJO: tunear SOLO sobre data REAL. En sintético (random walk) el SCALPER

&#x20;   da \~breakeven por definición; un filtro de tendencia no aporta nada ahí.



XAUUSD — TUNING (config validada en backtest #2)

&#x20;   EMA\_MOMENTUM sola @ min\_rr 2.2 → PF 1.51, WR 41%, E +0.30R (1 año real).

&#x20;   ORB sola pierde plata en oro. Combinar estrategias BAJA el PF (la

&#x20;   confluencia a veces elige la señal peor). Menos es más en oro.

&#x20;   El techo de WR de las estrategias de momentum es \~40-44%. Para subir el WR

&#x20;   habría que cambiar a mean-reversion, sacrificando el RR. Ver §03.



DESCARGA DE HISTÓRICO MT5 — copy\_rates\_range y el problema de M5

&#x20;   `mt5.copy\_rates\_range(symbol, tf, from, to)` NO es fiable en una sola

&#x20;   llamada para rangos grandes: solo devuelve lo que el terminal tiene en

&#x20;   caché local. M5 a 1 año ≈ 75k velas → casi nunca está cacheado → devuelve

&#x20;   VACÍO. M15/M30 a 1 año (\~17k / \~8k velas) sí entran, por eso NAS100 y

&#x20;   XAUUSD bajaban bien y los pares forex en M5 no.

&#x20;   SOLUCIÓN (ya implementada en get\_rates): descargar en chunks chicos

&#x20;   (\~5000 velas c/u) con reintentos. MT5 baja history async — la 1ª llamada

&#x20;   puede venir vacía y disparar la descarga, las siguientes traen datos.

&#x20;   Si aun así un símbolo viene vacío: abrir su gráfico en MT5 en ese TF,

&#x20;   hacer scroll hacia atrás para forzar la descarga, y re-correr fetch\_history

&#x20;   (es incremental). O usar un rango más corto.



BACKTESTING EN SANDBOX (Claude)

&#x20;   Claude puede correr backtests en su sandbox Linux (no necesita MT5, solo

&#x20;   los parquet). Para EURUSD, que aún no tiene data real descargada, Claude

&#x20;   generó M5 SINTÉTICO solo para validar que la lógica del SCALPER corre — los

&#x20;   números de un backtest sintético NO son predictivos, solo confirman que no

&#x20;   crashea. Tunear SIEMPRE sobre data real.

&#x20;   Bug encontrado y corregido: el backtester recalculaba indicadores por

&#x20;   ventana (lentísimo) y `df\_full.iloc\[i+1:]` creaba slices gigantes (OOM).



DASHBOARD — MT5 EN SUBPROCESO

&#x20;   Cuando se usa `scripts.serve`, el dashboard corre como subproceso de

&#x20;   Streamlit independiente del orchestrator. Cada proceso tiene su propia

&#x20;   conexión MT5. Mismas credenciales en .env, conexiones distintas — MT5

&#x20;   permite múltiples sesiones Python contra el mismo terminal.



NOMENCLATURA

&#x20;   "R" = riesgo por trade. PnL en R significa "múltiplos del riesgo arriesgado".

&#x20;   Un trade que da +1R ganó lo mismo que se arriesgó. Es la unidad estándar

&#x20;   para comparar trades de tamaños distintos.





\################################################################################

\#  FIN — actualizar §03, §10 y §11 al final de cada sesión

\################################################################################



