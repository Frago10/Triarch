"""
Triarch — Streamlit dashboard.

Pestañas:
  - Live & Control : estado de cuenta MT5 + tarjeta por activo con switch
  - Decisiones     : por qué SÍ / por qué NO (filtros, fechas legibles, download .txt)
  - Backtesting    : correr backtest por rango + tabla KPIs + equity curve
  - Signals        : tabla cruda
  - Evals          : audit trail crudo
  - Stats          : agregados

Uso:
    streamlit run dashboard/app.py
    # o combinado con el loop:
    python -m scripts.serve --tick 30 --port 8765
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from audit.store import AuditStore
from config.runtime import get_take_trades, set_take_trades
from config.settings import get_settings, get_symbols
from data_layer.mt5_client import MT5_AVAILABLE, MT5Client

st.set_page_config(page_title="Triarch", layout="wide", page_icon="🤖")

# ─────────────────────────────────────────────────────────
# Estilo (CSS ligero para tarjetas + pills de status)
# ─────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
      .triarch-card {
        background: rgba(38, 39, 48, 0.55);
        border: 1px solid rgba(120, 120, 140, 0.25);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
      }
      .triarch-card h3 { margin-top: 0; margin-bottom: 6px; }
      .triarch-pill {
        display: inline-block;
        padding: 3px 10px;
        border-radius: 999px;
        font-size: 0.80rem;
        font-weight: 600;
        margin-right: 6px;
      }
      .pill-green  { background: #1f5d3a; color: #b8f1cd; }
      .pill-blue   { background: #1f3a5d; color: #b8d6f1; }
      .pill-orange { background: #5d4a1f; color: #f1d9b8; }
      .pill-red    { background: #5d1f1f; color: #f1b8b8; }
      .pill-gray   { background: #3a3a3a; color: #cccccc; }
      .triarch-mini {
        font-size: 0.78rem;
        color: #aaa;
        margin-top: 2px;
      }
      .triarch-kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
        gap: 10px;
        margin: 10px 0;
      }
      .triarch-kpi {
        background: rgba(38, 39, 48, 0.55);
        border: 1px solid rgba(120, 120, 140, 0.25);
        border-radius: 10px;
        padding: 10px 12px;
      }
      .triarch-kpi .label { font-size: 0.78rem; color: #aaa; }
      .triarch-kpi .value { font-size: 1.35rem; font-weight: 700; }
    </style>
    """,
    unsafe_allow_html=True,
)

settings = get_settings()
symbols = get_symbols()
store = AuditStore()


# ─────────────────────────────────────────────────────────
# Helpers de presentación amigable
# ─────────────────────────────────────────────────────────
STATUS_FRIENDLY: dict[str, tuple[str, str]] = {
    "NEW":                 ("Emitida, esperando ejecución",           "blue"),
    "APPROVED":            ("Aprobada por ti",                         "green"),
    "REJECTED_HUMAN":      ("Rechazada por ti",                        "red"),
    "REJECTED_RISK":       ("Rechazada por gestión de riesgo",         "red"),
    "REJECTED_CONFLUENCE": ("Sin confluencia entre estrategias",       "orange"),
    "PLACED":              ("Orden enviada al broker",                 "blue"),
    "FAILED":              ("Falló al enviar al broker",               "red"),
    "FILLED":              ("Posición abierta",                        "blue"),
    "CLOSED_TP1":          ("Cerrada en take-profit",                  "green"),
    "CLOSED_TP2":          ("Cerrada en take-profit (TP2)",            "green"),
    "CLOSED_SL":           ("Cerrada en stop-loss",                    "red"),
    "CLOSED_MANUAL":       ("Cerrada manualmente",                     "gray"),
}

REJECT_REASON_FRIENDLY: dict[str, str] = {
    # Confluencia
    "no_signals":              "Ninguna estrategia detectó setup",
    "direction_tie":           "Empate en dirección entre estrategias (long vs short)",
    "min_signals":             "Solo una estrategia detectó setup (se piden al menos dos)",
    "min_families":            "Setups de la misma familia (falta diversidad)",
    "score":                   "Puntuación combinada insuficiente",
    # Risk
    "kill_switch":             "Kill switch global activado",
    "consec_losses":           "Demasiadas pérdidas consecutivas",
    "daily_cap":               "Se alcanzó el tope diario de pérdida",
    "max_trades":              "Se alcanzó el máximo de trades del día",
    "out_of_window":           "Fuera del horario operativo del activo",
    "news_block":              "Bloqueado por evento de noticias",
    "active_trade":            "Ya hay un trade abierto en este activo",
    "rr_too_low":              "Relación riesgo/beneficio por debajo del mínimo",
    "slippage_guard":          "Slippage demasiado alto respecto al ATR",
    # Estrategias internas
    "not_enough_bars":         "No hay suficientes velas para evaluar",
    "atr_unavailable":         "Indicador ATR aún no disponible",
    "ema_unavailable":         "Indicadores EMA aún no disponibles",
    "atr_too_low":             "Mercado sin volatilidad suficiente",
    "no_pullback":             "No hubo retroceso claro a la media",
    "below_min_rr":            "RR proyectado por debajo del mínimo",
}


def friendly_reject_reason(raw: str | None) -> str:
    """Traduce reasons crudos tipo 'min_signals:1<2' a frases legibles."""
    if not raw:
        return ""
    key = raw.split(":", 1)[0].strip().lower()
    base = REJECT_REASON_FRIENDLY.get(key)
    if not base:
        return raw  # fallback: deja el crudo
    detail = raw.split(":", 1)[1].strip() if ":" in raw else ""
    return f"{base}" + (f"  ({detail})" if detail else "")


def friendly_status(raw: str | None) -> tuple[str, str]:
    """Devuelve (texto, color) según status."""
    if not raw:
        return ("—", "gray")
    return STATUS_FRIENDLY.get(raw, (raw, "gray"))


def friendly_date(ts_str: str | None) -> str:
    """ISO → 'Hoy 14:30 UTC', 'Ayer 09:45', 'Lun 12 may 14:30', '12 may 2024 14:30'."""
    if not ts_str:
        return ""
    try:
        dt = pd.to_datetime(ts_str, utc=True)
    except Exception:
        return ts_str
    now = pd.Timestamp.now(tz="UTC")
    delta_days = (now.date() - dt.date()).days
    if delta_days == 0:
        return f"Hoy {dt.strftime('%H:%M')} UTC"
    if delta_days == 1:
        return f"Ayer {dt.strftime('%H:%M')} UTC"
    if 0 < delta_days < 7:
        return dt.strftime("%a %d %b, %H:%M UTC").capitalize()
    return dt.strftime("%d %b %Y, %H:%M UTC")


def pill(text: str, color: str = "gray") -> str:
    return f'<span class="triarch-pill pill-{color}">{text}</span>'


def kpi(label: str, value: str) -> str:
    return f'<div class="triarch-kpi"><div class="label">{label}</div><div class="value">{value}</div></div>'


# ─────────────────────────────────────────────────────────
# Conexión a MT5 (cacheada por sesión Streamlit)
# ─────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_mt5_client() -> tuple[MT5Client | None, str]:
    """Inicializa MT5 una sola vez por sesión del dashboard. Si falla, devuelve None + mensaje."""
    if not MT5_AVAILABLE:
        return None, "El paquete MetaTrader5 no está disponible (¿no estás en Windows?)."
    client = MT5Client()
    if not client.initialize():
        return None, "No se pudo conectar al terminal MT5. Revisa que esté abierto y .env esté completo."
    return client, "ok"


# ─────────────────────────────────────────────────────────
# Header
# ─────────────────────────────────────────────────────────
st.title("🤖  Triarch — MT5 Multi-Asset Bot")
st.caption(
    f"Entorno **{settings.triarch_env.value.upper()}**  ·  "
    f"Modo por defecto **{settings.triarch_default_mode.value}**  ·  "
    f"Confluencia mín: {settings.triarch_confluence_min_signals} señales / "
    f"{settings.triarch_confluence_min_families} familias / score ≥ "
    f"{settings.triarch_confluence_min_score}"
)

tab_live, tab_dec, tab_bt, tab_signals, tab_evals, tab_stats = st.tabs(
    ["🔴 Live & Control", "🧠 Decisiones", "📊 Backtesting",
     "📈 Signals", "🔍 Evals", "📦 Stats"]
)


# ═════════════════════════════════════════════════════════
# TAB 1 — Live & Control (cuenta MT5 + tarjeta por activo + switches)
# ═════════════════════════════════════════════════════════
with tab_live:
    # ─── Bloque cuenta MT5 ───
    st.subheader("Cuenta conectada")
    client, msg = _get_mt5_client()
    info = client.account_info() if client else None
    if info is None:
        st.warning(f"⚠  {msg}")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Balance",       f"{info.balance:,.2f} {info.currency}")
        c2.metric("Equity",        f"{info.equity:,.2f} {info.currency}",
                  delta=f"{info.equity - info.balance:+,.2f}")
        c3.metric("Margen usado",  f"{info.margin:,.2f} {info.currency}")
        c4.metric("Margen libre",  f"{info.free_margin:,.2f} {info.currency}")
        c5.metric("Apalancamiento", f"1:{info.leverage}")
        st.caption(
            f"Cuenta **{info.login}**  ·  servidor **{info.server}**  ·  titular **{info.name}**"
        )

    st.markdown("---")
    st.subheader("Activos")
    st.caption(
        "Cada tarjeta resume el estado de un activo. El switch **Trades reales en MT5** "
        "controla si el bot solo manda señales o si ejecuta órdenes; cambia efectivo en "
        "el próximo tick. Se persiste en `config/runtime.yaml`."
    )

    for name, cfg in symbols.items():
        with st.container(border=True):
            head_a, head_b = st.columns([3, 2])
            with head_a:
                st.markdown(f"### {name}")
                st.markdown(
                    f"**{cfg.broker_symbol}** · {cfg.description}<br>"
                    f"{pill(cfg.profile, 'blue')}{pill(cfg.timeframe, 'gray')}"
                    f"{pill(f'sesión {cfg.session_utc.start}–{cfg.session_utc.end} UTC', 'gray')}",
                    unsafe_allow_html=True,
                )
            with head_b:
                current = get_take_trades(name, default=cfg.take_trades)
                new = st.toggle(
                    "Trades reales en MT5",
                    value=current,
                    key=f"toggle_{name}",
                    help=(
                        "ON → respeta el modo del yaml (puede ejecutar AUTO). "
                        "OFF → solo manda señales, no ejecuta."
                    ),
                )
                if new != current:
                    set_take_trades(name, new)
                    st.toast(f"{name}: trades reales = {new}", icon="✅")
                effective_label = cfg.mode.value if new else "SIGNAL_ONLY (forzado)"
                st.markdown(
                    f"Modo efectivo: {pill(effective_label, 'green' if new else 'orange')}",
                    unsafe_allow_html=True,
                )

            # Última señal de este activo
            recent = store.list_signals(symbol=name, limit=1)
            if recent:
                r = recent[0]
                st_text, st_color = friendly_status(r.get("status"))
                rej = friendly_reject_reason(r.get("reject_reason"))
                line = (
                    f"**Última señal:** {friendly_date(r.get('timestamp_utc'))} · "
                    f"{r.get('strategy')} · **{r.get('direction')}** @ `{r.get('entry')}` · "
                    f"RR `{r.get('rr_ratio'):.2f}` · score `{r.get('score'):.2f}`"
                )
                st.markdown(line)
                st.markdown(pill(st_text, st_color), unsafe_allow_html=True)
                if rej:
                    st.caption(f"Motivo: {rej}")
            else:
                st.info("Aún sin señales registradas para este activo.")

    st.markdown("---")
    st.subheader("Kill switch global")
    st.caption(
        "Para parar TODO de golpe: setea `TRIARCH_KILL=1` en `.env` y reinicia el "
        "proceso. El orchestrator chequea esto en cada tick y omite cualquier ejecución."
    )


# ═════════════════════════════════════════════════════════
# TAB 2 — Decisiones (legible, filtros, download .txt)
# ═════════════════════════════════════════════════════════
def _row_to_human_block(r: dict) -> str:
    """Bloque txt legible para download."""
    st_text, _ = friendly_status(r.get("status"))
    rej = friendly_reject_reason(r.get("reject_reason"))
    pnl = r.get("pnl_money")
    pnl_str = f"{pnl:+.2f} USD" if isinstance(pnl, (int, float)) else "n/a"
    rr = r.get("rr_ratio")
    score = r.get("score")
    rr_str = f"{rr:.2f}" if isinstance(rr, (int, float)) else "?"
    score_str = f"{score:.2f}" if isinstance(score, (int, float)) else "?"
    return (
        f"[{friendly_date(r.get('timestamp_utc'))}]  "
        f"{r.get('symbol')}  {r.get('strategy')}  {r.get('direction')}\n"
        f"  entry={r.get('entry')}  SL={r.get('stop_loss')}  TP1={r.get('take_profit_1')}\n"
        f"  RR={rr_str}  score={score_str}  PnL={pnl_str}\n"
        f"  Estado: {st_text}" + (f" — Motivo: {rej}" if rej else "") + "\n\n"
    )


with tab_dec:
    st.subheader("Por qué SÍ / por qué NO")
    st.caption(
        "Vista legible del audit trail. Pensada para revisar el día a día sin "
        "tener que descifrar códigos técnicos."
    )

    f1, f2, f3, f4 = st.columns([2, 2, 2, 2])
    with f1:
        sym_filter = st.selectbox("Activo", ["(todos)"] + list(symbols.keys()), key="dec_sym")
    with f2:
        all_strats = sorted({s for cfg in symbols.values() for s in cfg.strategies})
        strat_filter = st.selectbox("Estrategia", ["(todas)"] + all_strats, key="dec_strat")
    with f3:
        status_buckets = ["(todos)", "✅ Tomadas", "❌ Rechazadas", "🏁 Cerradas", "🆕 Pendientes"]
        status_filter = st.selectbox("Estado", status_buckets, key="dec_status")
    with f4:
        days = st.number_input("Últimos N días", min_value=1, max_value=365, value=30, step=1, key="dec_days")

    direction_filter = st.radio(
        "Dirección", ["(todas)", "LONG", "SHORT"], horizontal=True, key="dec_dir"
    )

    since = datetime.now(timezone.utc) - timedelta(days=int(days))
    rows = store.list_signals(
        symbol=None if sym_filter == "(todos)" else sym_filter,
        since=since,
        limit=5000,
    )

    if strat_filter != "(todas)":
        rows = [r for r in rows if r.get("strategy") == strat_filter]
    if direction_filter != "(todas)":
        rows = [r for r in rows if r.get("direction") == direction_filter]
    if status_filter != "(todos)":
        if status_filter.startswith("✅"):
            rows = [r for r in rows if r.get("status") in {"PLACED", "FILLED", "APPROVED"}]
        elif status_filter.startswith("❌"):
            rows = [r for r in rows if (r.get("status") or "").startswith("REJECTED") or r.get("status") == "FAILED"]
        elif status_filter.startswith("🏁"):
            rows = [r for r in rows if (r.get("status") or "").startswith("CLOSED")]
        elif status_filter.startswith("🆕"):
            rows = [r for r in rows if r.get("status") == "NEW"]

    st.markdown(f"**{len(rows)}** decisiones encontradas con esos filtros.")

    if rows:
        # Construir DF presentable
        view_rows = []
        for r in rows:
            st_text, _ = friendly_status(r.get("status"))
            view_rows.append({
                "Fecha": friendly_date(r.get("timestamp_utc")),
                "Activo": r.get("symbol"),
                "Estrategia": r.get("strategy"),
                "Dirección": r.get("direction"),
                "Entry": r.get("entry"),
                "SL": r.get("stop_loss"),
                "TP1": r.get("take_profit_1"),
                "RR": round(r.get("rr_ratio") or 0, 2),
                "Score": round(r.get("score") or 0, 2),
                "Estado": st_text,
                "Motivo": friendly_reject_reason(r.get("reject_reason")),
                "PnL (USD)": r.get("pnl_money"),
            })
        df_view = pd.DataFrame(view_rows)
        st.dataframe(df_view, use_container_width=True, hide_index=True)

        header = (
            "=" * 72 + "\n"
            f"Triarch — historial de decisiones\n"
            f"Generado: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
            f"Filtros:  activo={sym_filter}  estrategia={strat_filter}  "
            f"estado={status_filter}  dirección={direction_filter}  últimos_días={days}\n"
            f"Total decisiones: {len(rows)}\n"
            + "=" * 72 + "\n\n"
        )
        body = "".join(_row_to_human_block(r) for r in rows)
        fname = (
            f"triarch_decisiones_"
            f"{sym_filter if sym_filter != '(todos)' else 'ALL'}_"
            f"{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt"
        )
        st.download_button(
            "⬇  Descargar como .txt",
            data=header + body,
            file_name=fname,
            mime="text/plain",
        )
    else:
        st.info("Sin decisiones para esos filtros.")


# ═════════════════════════════════════════════════════════
# TAB 3 — Backtesting (botón + rango fechas + KPIs + equity curve)
# ═════════════════════════════════════════════════════════
with tab_bt:
    st.subheader("Backtesting sobre histórico cacheado")
    st.caption(
        "Corre el motor completo (estrategias + confluencia) vela a vela sobre "
        "los parquet de `data_cache/history/`. Antes de correr aquí, baja histórico con "
        "`python -m scripts.fetch_history --years 1` en una terminal."
    )

    bt1, bt2, bt3 = st.columns([2, 2, 2])
    with bt1:
        sel_symbols = st.multiselect(
            "Activos",
            list(symbols.keys()),
            default=list(symbols.keys()),
            key="bt_syms",
        )
    with bt2:
        from_d = st.date_input(
            "Desde",
            value=date.today() - timedelta(days=365),
            key="bt_from",
        )
    with bt3:
        to_d = st.date_input(
            "Hasta",
            value=date.today(),
            key="bt_to",
        )

    run_bt = st.button("▶  Correr backtest", type="primary", use_container_width=True)

    if run_bt:
        # Import dentro del botón para que el coste de importar no se pague
        # mientras el usuario solo está mirando el resto del dashboard.
        from scripts.backtest import backtest_symbol

        from_dt = datetime.combine(from_d, datetime.min.time()).replace(tzinfo=timezone.utc)
        to_dt = datetime.combine(to_d, datetime.max.time()).replace(tzinfo=timezone.utc)

        results = []
        prog = st.progress(0.0, text="Corriendo backtest…")
        for i, sym in enumerate(sel_symbols, start=1):
            cfg = symbols[sym]
            prog.progress(i / max(1, len(sel_symbols)), text=f"Procesando {sym}…")
            # backtest_symbol arma su propia confluencia por activo
            res = backtest_symbol(cfg, settings, from_date=from_dt, to_date=to_dt)
            results.append(res)
        prog.empty()
        st.session_state["bt_results"] = results

    results = st.session_state.get("bt_results")
    if results:
        # ─── Resumen comparativo ───
        st.subheader("Comparativa de activos")
        summary_rows = []
        for r in results:
            if "error" in r or r.get("trades", 0) == 0:
                summary_rows.append({
                    "Activo": r.get("symbol"),
                    "Trades": 0,
                    "Win rate": "—",
                    "Profit factor": "—",
                    "Expectancy (R)": "—",
                    "Sharpe": "—",
                    "Sortino": "—",
                    "SQN": "—",
                    "Max DD (R)": "—",
                    "Trades/sem": "—",
                    "Nota": r.get("error") or r.get("note") or "",
                })
                continue
            pf = r["profit_factor"]
            summary_rows.append({
                "Activo": r["symbol"],
                "Trades": r["trades"],
                "Win rate": f"{r['win_rate']:.1%}",
                "Profit factor": (
                    "∞" if isinstance(pf, float) and pf == float("inf") else f"{pf:.2f}"
                ),
                "Expectancy (R)": f"{r['expectancy_r']:+.3f}",
                "Sharpe": f"{r['sharpe_ratio']:.2f}",
                "Sortino": f"{r['sortino_ratio']:.2f}",
                "SQN": f"{r['sqn']:.2f}",
                "Max DD (R)": f"{r['max_drawdown_r']:.2f}",
                "Trades/sem": f"{r['trades_per_week_avg']}",
                "Nota": "",
            })
        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        # ─── Detalle por activo ───
        for r in results:
            if "error" in r:
                with st.expander(f"❌ {r.get('symbol')} — sin datos"):
                    st.error(r["error"])
                continue
            if r.get("trades", 0) == 0:
                with st.expander(f"⚠ {r.get('symbol')} — 0 trades"):
                    st.warning(r.get("note", ""))
                continue

            with st.expander(
                f"📈 {r['symbol']}  ·  {r['trades']} trades  ·  "
                f"WR {r['win_rate']:.1%}  ·  E {r['expectancy_r']:+.3f}R  ·  "
                f"Sharpe {r['sharpe_ratio']:.2f}",
                expanded=False,
            ):
                # KPI grid
                kpis_html = "<div class='triarch-kpi-grid'>"
                kpis_html += kpi("Trades", str(r["trades"]))
                kpis_html += kpi("Win rate", f"{r['win_rate']:.1%}")
                pf = r["profit_factor"]
                kpis_html += kpi(
                    "Profit factor",
                    "∞" if isinstance(pf, float) and pf == float("inf") else f"{pf:.2f}",
                )
                kpis_html += kpi("Expectancy", f"{r['expectancy_r']:+.3f} R")
                kpis_html += kpi("Sharpe", f"{r['sharpe_ratio']:.2f}")
                kpis_html += kpi("Sortino", f"{r['sortino_ratio']:.2f}")
                kpis_html += kpi("SQN", f"{r['sqn']:.2f}")
                kpis_html += kpi("Max DD", f"{r['max_drawdown_r']:.2f} R")
                kpis_html += kpi("Avg win", f"{r['avg_win_r']:+.2f} R")
                kpis_html += kpi("Avg loss", f"{r['avg_loss_r']:+.2f} R")
                kpis_html += kpi(
                    "Rachas (W/L)",
                    f"+{r['longest_win_streak']} / -{r['longest_loss_streak']}",
                )
                kpis_html += kpi("Trades/semana", f"{r['trades_per_week_avg']}")
                kpis_html += "</div>"
                st.markdown(kpis_html, unsafe_allow_html=True)

                # Equity curve
                eq = r.get("equity_curve") or []
                if eq:
                    df_eq = pd.DataFrame(eq)
                    df_eq["time"] = pd.to_datetime(df_eq["time"])
                    st.line_chart(df_eq.set_index("time")["cum_r"],
                                  height=240, use_container_width=True)
                    st.caption("Curva de equity en múltiplos de R (riesgo por trade).")

                # Por estrategia
                by_s = r.get("by_strategy") or {}
                if by_s:
                    df_s = pd.DataFrame(by_s).T.reset_index().rename(
                        columns={"index": "Estrategia",
                                 "trades": "Trades",
                                 "expectancy_r": "Expectancy (R)",
                                 "total_r": "Total (R)"}
                    )
                    st.markdown("**Por estrategia**")
                    st.dataframe(df_s, use_container_width=True, hide_index=True)

                # Trade log
                tlog = r.get("trade_log") or []
                if tlog:
                    df_log = pd.DataFrame(tlog)
                    df_log["Fecha"] = df_log["time"].apply(friendly_date)
                    df_log = df_log.rename(columns={
                        "strategy": "Estrategia",
                        "direction": "Dirección",
                        "entry": "Entry",
                        "sl": "SL",
                        "tp1": "TP1",
                        "rr_planned": "RR plan",
                        "score": "Score",
                        "outcome": "Resultado",
                        "bars_held": "Velas",
                        "pnl_r": "PnL (R)",
                    })[["Fecha", "Estrategia", "Dirección", "Entry", "SL", "TP1",
                        "RR plan", "Score", "Resultado", "Velas", "PnL (R)"]]
                    st.markdown("**Trade log**")
                    st.dataframe(df_log, use_container_width=True, hide_index=True)

        # ─── Download del resumen completo ───
        from scripts.backtest import _format_summary
        from_dt = datetime.combine(from_d, datetime.min.time()).replace(tzinfo=timezone.utc)
        to_dt = datetime.combine(to_d, datetime.max.time()).replace(tzinfo=timezone.utc)
        txt = _format_summary(results, from_dt, to_dt)
        st.download_button(
            "⬇  Descargar resumen .txt",
            data=txt,
            file_name=f"triarch_backtest_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
        )
    else:
        st.info("Aún no has corrido un backtest. Configura filtros arriba y presiona el botón.")


# ═════════════════════════════════════════════════════════
# TAB 4 — Signals (tabla cruda, para debug)
# ═════════════════════════════════════════════════════════
with tab_signals:
    st.subheader("Tabla cruda de señales")
    st.caption("Vista sin traducciones — útil para debugging o exportar a otra herramienta.")
    sym_filter_raw = st.selectbox("Activo", ["(todos)"] + list(symbols.keys()), key="sig_sym")
    rows = store.list_signals(
        symbol=None if sym_filter_raw == "(todos)" else sym_filter_raw,
        limit=500,
    )
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(
            df[[
                "timestamp_utc", "symbol", "strategy", "direction",
                "entry", "stop_loss", "take_profit_1", "rr_ratio",
                "score", "confidence", "status", "reject_reason", "pnl_money",
            ]],
            use_container_width=True,
        )
    else:
        st.info("Aún no hay señales en la base.")


# ═════════════════════════════════════════════════════════
# TAB 5 — Evals (audit trail crudo)
# ═════════════════════════════════════════════════════════
with tab_evals:
    st.subheader("Audit trail — cada evaluación de estrategia")
    st.caption("Toda evaluación por vela queda registrada aquí, incluyendo las que no produjeron señal.")
    sym_filter_ev = st.selectbox("Activo", ["(todos)"] + list(symbols.keys()), key="evals_sym")
    rows = store.list_evals(
        symbol=None if sym_filter_ev == "(todos)" else sym_filter_ev,
        limit=500,
    )
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("Aún no hay evaluaciones registradas.")


# ═════════════════════════════════════════════════════════
# TAB 6 — Stats (agregados)
# ═════════════════════════════════════════════════════════
with tab_stats:
    st.subheader("Agregados de los últimos 30 días")
    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = store.list_signals(since=since, limit=10_000)
    if not rows:
        st.info("Sin datos para los últimos 30 días.")
    else:
        df = pd.DataFrame(rows)
        agg = df.groupby("symbol").agg(
            señales=("signal_id", "count"),
            avg_score=("score", "mean"),
            avg_rr=("rr_ratio", "mean"),
        ).round(3)
        st.markdown("**Por activo**")
        st.dataframe(agg, use_container_width=True)

        st.markdown("**Por activo × estrategia**")
        agg2 = df.groupby(["symbol", "strategy"]).size().reset_index(name="señales")
        st.dataframe(agg2, use_container_width=True, hide_index=True)
