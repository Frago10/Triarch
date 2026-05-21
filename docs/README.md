# Triarch — Front-end estático (GitHub Pages)

Este directorio contiene el **dashboard web** del bot Triarch, listo para hostear
en **GitHub Pages** sin backend. Es 100 % HTML/CSS/JS estático con diseño
"Crimson Black" (rojo y negro). Replica visualmente las 5 pestañas de la versión
Streamlit y consume datos exportados a JSON.

## Estructura

```
docs/
├── index.html              ← entrada (la URL pública)
├── .nojekyll               ← desactiva Jekyll en GitHub Pages
├── assets/
│   ├── css/styles.css      ← sistema de diseño completo
│   └── js/app.js           ← lógica del front (tabs, filtros, export .txt)
└── data/
    ├── sample.json         ← datos demo (la web funciona out-of-the-box)
    └── state.json          ← (opcional) snapshot real del bot
                              generado por `python -m scripts.export_web`

architecture.md             ← documentación técnica del bot (no parte del front)
setup-mt5-demo.md           ← guía para abrir cuenta demo MT5
```

## Cómo funciona el dato

El front intenta cargar **`./data/state.json`** primero y, si no existe, cae a
**`./data/sample.json`**. Esto te permite:

- Subir la web sin datos reales y que ya se vea bien (con `sample.json`).
- Generar `state.json` en local con el bot y volver a desplegar.

La web muestra un banner si está usando `sample.json`.

## Generar el `state.json` real

Desde la raíz del proyecto (donde está `pyproject.toml`), con el venv activado:

```powershell
python -m scripts.export_web
```

Opciones:

```
--signals-limit 2000      # más historial
--evals-limit 1000
--no-mt5                  # omite la conexión a MT5 (solo SQLite)
--out docs/data/state.json
```

Para que la pestaña **Backtesting** muestre algo, primero genera el cache:

```powershell
python -m scripts.backtest --out data_cache/backtest_last.json
python -m scripts.export_web
```

## Hostear en GitHub Pages

1. Sube el repo a GitHub.
2. En el repo: **Settings → Pages**.
3. Source: **Deploy from a branch**.
4. Branch: **main**  /  Folder: **/docs**.
5. Guarda. En 1–2 minutos la web vivirá en
   `https://<tu-usuario>.github.io/<repo>/`.

`.nojekyll` está presente, así GitHub Pages no procesa el contenido como Jekyll.

## Flujo de actualización recomendado

```powershell
# 1) refrescar histórico (si quieres recomputar backtest)
python -m scripts.fetch_history --years 1

# 2) correr backtest y cachear (opcional pero recomendado)
python -m scripts.backtest --out data_cache/backtest_last.json

# 3) exportar snapshot completo a docs/data/state.json
python -m scripts.export_web

# 4) commit + push → GitHub Pages re-deploya solo
git add docs/
git commit -m "chore(web): refresh snapshot"
git push
```

## Diferencias con la versión Streamlit

| Capacidad | Streamlit local | Web estática (este `/docs`) |
|---|---|---|
| Vista de cuenta MT5            | Real-time | Snapshot del último export |
| Tarjetas por activo            | ✅ | ✅ |
| Toggle "Trades reales"         | ✅ persiste a runtime.yaml | 👁 sólo lectura |
| Historial de decisiones        | ✅ filtros live | ✅ filtros client-side |
| Export decisiones a `.txt`     | ✅ | ✅ (Blob en navegador) |
| Backtesting on-demand          | ✅ corre `backtest_symbol` | 👁 muestra cache previo |
| Curva de equity                | ✅ st.line_chart | ✅ Canvas vanilla |
| Trade log                      | ✅ | ✅ |
| Datos crudos (Signals/Evals/Stats) | ✅ | ✅ |

La parte interactiva crítica (toggles, correr backtest, run_live) **sigue
viviendo en local**: GitHub Pages no puede correr Python, MT5 ni escribir a
disco. La web es la **capa de visualización pública**.

## Privacidad

Antes de exportar y pushear `state.json` a un repo público, revisa el contenido —
incluye número de cuenta, balance y servidor MT5. Si no querés exponerlo:

- Mantén el repo privado y usa GitHub Pages privado (planes Pro+).
- O exporta con `--no-mt5` (quita el bloque `account`).
- O edita `scripts/export_web.py` para enmascarar `login` y `balance`.
