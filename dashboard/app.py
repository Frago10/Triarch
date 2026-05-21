"""
Triarch — Streamlit dashboard (UI v3 — splash + sidebar + tabs nuevas).

Estructura visual:
  · Splash de bienvenida (1 sola vez por sesión)
  · Sidebar branded: logo, env, cuenta, kill switch, atajos
  · Tabs top-level (5):
        🏠 Inicio        — resumen ejecutivo del día
        🎯 Vivo & Control — cuenta MT5 + tarjeta por activo + switches
        🧠 Decisiones    — por qué SÍ / por qué NO con filtros + download .txt
        📊 Backtesting   — correr backtest por rango + KPIs + equity curve
        📦 Datos        — sub-tabs Signals / Evals / Stats (vista cruda)

Mantiene TODA la funcionalidad de la versión anterior; cambia presentación.

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

st.set_page_config(
    page_title="Triarch",
    layout="wide",
    page_icon="🤖",
    initial_sidebar_state="expanded",
)

# ═══════════════════════════════════════════════════════════════
#  CSS GLOBAL — paleta y componentes
# ═══════════════════════════════════════════════════════════════
st.markdown(
    """
    <style>
    :root {
        --tri-card-bg: rgba(38, 39, 48, 0.55);
        --tri-card-border: rgba(120, 120, 140, 0.22);
        --tri-card-border-hi: rgba(120, 120, 140, 0.40);
        --tri-accent: #5eead4;            /* cyan/teal */
        --tri-accent-2: #a78bfa;          /* violeta suave */
        --tri-accent-soft: rgba(94, 234, 212, 0.12);
        --tri-text-muted: #9ca3af;
        --tri-text-dim: #6b7280;
    }

    /* ─── Cards ─── */
    .triarch-card {
        background: var(--tri-card-bg);
        border: 1px solid var(--tri-card-border);
        border-radius: 14px;
        padding: 18px 20px;
        margin-bottom: 14px;
        backdrop-filter: blur(4px);
        transition: border-color 200ms ease, transform 200ms ease;
    }
    .triarch-card:hover { border-color: var(--tri-card-border-hi); }
    .triarch-card h3, .triarch-card h4 { margin: 0 0 6px 0; }

    /* ─── Pills de estado ─── */
    .triarch-pill {
        display: inline-flex; align-items: center; gap: 6px;
        padding: 3px 11px; border-radius: 999px;
        font-size: 0.78rem; font-weight: 600;
        margin-right: 6px;
        letter-spacing: 0.01em;
    }
    .pill-green  { background: rgba(34, 197, 94, 0.15);  color: #86efac;
                   border: 1px solid rgba(34, 197, 94, 0.30); }
    .pill-blue   { background: rgba(59, 130, 246, 0.15); color: #93c5fd;
                   border: 1px solid rgba(59, 130, 246, 0.30); }
    .pill-orange { background: rgba(249, 115, 22, 0.15); color: #fdba74;
                   border: 1px solid rgba(249, 115, 22, 0.30); }
    .pill-red    { background: rgba(239, 68, 68, 0.15);  color: #fca5a5;
                   border: 1px solid rgba(239, 68, 68, 0.30); }
    .pill-gray   { background: rgba(120, 120, 120, 0.15);color: #d1d5db;
                   border: 1px solid rgba(120, 120, 120, 0.30); }
    .pill-accent { background: var(--tri-accent-soft);   color: var(--tri-accent);
                   border: 1px solid rgba(94, 234, 212, 0.30); }

    /* ─── Dots (indicadores chicos) ─── */
    .triarch-dot {
        display: inline-block; width: 8px; height: 8px;
        border-radius: 50%; margin-right: 6px; vertical-align: middle;
    }
    .dot-green  { background: #22c55e; box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.18); }
    .dot-red    { background: #ef4444; box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.18); }
    .dot-orange { background: #f97316; box-shadow: 0 0 0 3px rgba(249, 115, 22, 0.18); }
    .dot-gray   { background: #6b7280; box-shadow: 0 0 0 3px rgba(120, 120, 120, 0.18); }

    /* ─── KPI grid ─── */
    .triarch-kpi-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(155px, 1fr));
        gap: 12px;
        margin: 12px 0;
    }
    .triarch-kpi {
        background: var(--tri-card-bg);
        border: 1px solid var(--tri-card-border);
        border-radius: 12px;
        padding: 14px 16px;
        transition: transform 200ms ease, border-color 200ms ease;
    }
    .triarch-kpi:hover { transform: translateY(-2px); border-color: var(--tri-card-border-hi); }
    .triarch-kpi .label {
        font-size: 0.72rem; color: var(--tri-text-muted);
        text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
    }
    .triarch-kpi .value { font-size: 1.45rem; font-weight: 700; margin-top: 6px; }
    .triarch-kpi .sub   { font-size: 0.78rem; color: var(--tri-text-muted); margin-top: 2px; }

    /* ─── Header gradient ─── */
    .triarch-header {
        padding: 20px 26px;
        border-radius: 16px;
        background: linear-gradient(135deg,
            rgba(94, 234, 212, 0.10), rgba(167, 139, 250, 0.06));
        border: 1px solid rgba(94, 234, 212, 0.18);
        margin-bottom: 20px;
    }
    .triarch-header .title { margin: 0; font-size: 1.7rem; font-weight: 800; letter-spacing: 0.02em; }
    .triarch-header .title .accent {
        background: linear-gradient(135deg, var(--tri-accent), var(--tri-accent-2));
        -webkit-background-clip: text; background-clip: text; color: transparent;
    }
    .triarch-header .subtitle { color: var(--tri-text-muted); margin-top: 6px; font-size: 0.92rem; }

    /* ─── Splash / Intro ─── */
    .triarch-splash {
        max-width: 760px;
        margin: 60px auto 30px auto;
        padding: 44px 44px 36px 44px;
        border-radius: 24px;
        background: linear-gradient(135deg,
            rgba(94, 234, 212, 0.07), rgba(167, 139, 250, 0.05));
        border: 1px solid rgba(94, 234, 212, 0.20);
        text-align: center;
        backdrop-filter: blur(6px);
    }
    .triarch-splash .brand {
        font-size: 3.2rem; font-weight: 900; letter-spacing: 0.05em;
        background: linear-gradient(135deg, var(--tri-accent), var(--tri-accent-2));
        -webkit-background-clip: text; background-clip: text; color: transparent;
        margin: 0;
    }
    .triarch-splash .tag {
        color: var(--tri-text-muted); margin-top: 10px;
        font-size: 1.05rem; line-height: 1.5;
    }
    .triarch-splash .points {
        margin: 28px auto 0 auto; max-width: 540px; text-align: left;
        display: grid; gap: 10px;
    }
    .triarch-splash .point {
        display: flex; align-items: flex-start; gap: 12px;
        padding: 12px 14px; border-radius: 12px;
        background: rgba(38, 39, 48, 0.5);
        border: 1px solid var(--tri-card-border);
    }
    .triarch-splash .point .icon { font-size: 1.3rem; line-height: 1.3; }
    .triarch-splash .point .text { color: #d1d5db; font-size: 0.92rem; line-height: 1.5; }
    .triarch-splash .point .text b { color: var(--tri-accent); }

    /* ─── Sidebar branding ─── */
    .triarch-side-brand {
        font-size: 1.6rem; font-weight: 900; letter-spacing: 0.06em;
        background: linear-gradient(135deg, var(--tri-accent), var(--tri-accent-2));
        -webkit-background-clip: text; background-clip: text; color: transparent;
        text-align: center; margin: 4px 0 2px 0;
    }
    .triarch-side-tag { text-align: center; color: var(--tri-text-muted);
                        font-size: 0.78rem; letter-spacing: 0.04em;
                        text-transform: uppercase; margin-bottom: 18px; }
    .triarch-side-block {
        background: var(--tri-card-bg);
        border: 1px solid var(--tri-card-border);
        border-radius: 12px;
        padding: 12px 14px;
        margin-bottom: 10px;
    }
    .triarch-side-block .label {
        font-size: 0.7rem; color: var(--tri-text-muted);
        text-transform: uppercase; letter-spacing: 0.06em; font-weight: 600;
    }
    .triarch-side-block .value { font-size: 0.95rem; margin-top: 4px; }

    /* ─── Mini-rows en cards ─── */
    .triarch-mini { font-size: 0.78rem; color: var(--tri-text-muted); margin-top: 4px; }

    /* ─── Empty states ─── */
    .triarch-empty {
        text-align: center; padding: 30px 20px;
        border: 1px dashed var(--tri-card-border);
        border-radius: 14px; color: var(--tri-text-muted);
    }
    .triarch-empty .emoji { font-size: 2rem; opacity: 0.7; }

    /* ─── Hide Streamlit chrome no esencial ─── */
    footer { visibility: hidden; }
    #MainMenu { visibility: hidden; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ═══════════════════════════════════════════════════════════════
#  Estado global / cache
# ═══════════════════════════════════════════════════════════════
settings = get_settings()
symbols = get_symbols()
store = AuditStore()


# ─── Helpers de presentación amigable ─────────────────────────
STATUS_FRIENDLY: dict[str, tuple[str, str]] = {
    "NEW":                 ("Emitida, esperando ejecución",      "blue"),
    "APPROVED":            ("Aprobada por ti",                   "green"),
    "REJECTED_HUMAN":      ("Rechazada por ti",                  "red"),
    "REJECTED_RISK":       ("Rechazada por gestión de riesgo",   "red"),
    "REJECTED_CONFLUENCE": ("Sin confluencia entre estrategias", "orange"),
    "PLACED":              ("Orden enviada al broker",           "blue"),
    "FAILED":              ("Falló al enviar al broker",         "red"),
    "FILLED":              ("Posición abierta",                  "blue"),
    "CLOSED_TP1":          ("Cerrada en take-profit",            "green"),
    "CLOSED_TP2":          ("Cerrada en take-profit (TP2)",      "green"),
    "CLOSED_SL":           ("Cerrada en stop-loss",              "red"),
    "CLOSED_MANUAL":       ("Cerrada manualmente",               "gray"),
}

REJECT_REASON_FRIENDLY: dict[str, str] = {
    "no_signals":              "Ninguna estrategia detectó setup",
    "direction_tie":           "Empate en dirección entre estrategias",
    "min_signals":             "Solo una estrategia detectó setup (se piden al menos dos)",
    "min_families":            "Setups de la misma familia (falta diversidad)",
    "score":                   "Puntuación combinada insuficiente",
    "kill_switch":             "Kill switch global activado",
    "consec_losses":           "Demasiadas pérdidas consecutivas",
    "daily_cap":               "Se alcanzó el tope diario de pérdida",
    "max_trades":              "Se alcanzó el máximo de trades del día",
    "out_of_window":           "Fuera del horario operativo del activo",
    "news_block":              "Bloqueado por evento de noticias",
    "active_trade":            "Ya hay un trade abierto en este activo",
    "rr_too_low":              "Relación riesgo/beneficio por debajo del mínimo",
    "slippage_guard":          "Slippage demasiado alto respecto al ATR",
    "not_enough_bars":         "No hay suficientes velas para evaluar",
    "atr_unavailable":         "Indicador ATR aún no disponible",
    "ema_unavailable":         "Indicadores EMA aún no disponibles",
    "atr_too_low":             "Mercado sin volatilidad suficiente",
    "no_pullback":             "No hubo retroceso claro a la media",
    "below_min_rr":            "RR proyectado por debajo del mínimo",
    "trend_too_weak":          "Tendencia corta demasiado débil (rango)",
}


def friendly_reject_reason(raw: str | None) -> str:
    if not raw:
        return ""
    key = raw.split(":", 1)[0].strip().lower()
    base = REJECT_REASON_FRIENDLY.get(key)
    if not base:
        return raw
    detail = raw.split(":", 1)[1].strip() if ":" in raw else ""
    return base + (f"  ({detail})" if detail else "")


def friendly_status(raw: str | None) -> tuple[str, str]:
    if not raw:
        return ("—", "gray")
    return STATUS_FRIENDLY.get(raw, (raw, "gray"))


def friendly_date(ts_str: str | None) -> str:
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


def dot(color: str = "gray") -> str:
    return f'<span class="triarch-dot dot-{color}"></span>'


def kpi(label: str, value: str, sub: str | None = None) -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="triarch-kpi">'
        f'<div class="label">{label}</div>'
        f'<div class="value">{value}</div>{sub_html}</div>'
    )


# ─── MT5 client (cacheado) ────────────────────────────────────
@st.cache_resource(show_spinner=False)
def _get_mt5_client() -> tuple[MT5Client | None, str]:
    if not MT5_AVAILABLE:
        return None, "El paquete MetaTrader5 no está disponible (¿no estás en Windows?)."
    client = MT5Client()
    if not client.initialize():
        return None, "No se pudo conectar al terminal MT5. Revisa que esté abierto y .env esté completo."
    return client, "ok"


# ═══════════════════════════════════════════════════════════════
#  SPLASH / INTRO — se muestra una sola vez por sesión
# ═══════════════════════════════════════════════════════════════
if "intro_done" not in st.session_state:
    st.session_state["intro_done"] = False

if not st.session_state["intro_done"]:
    st.markdown(
        f"""
        <div class="triarch-splash">
            <div class="brand">TRIARCH</div>
            <div class="tag">
                Bot sistemático sobre MetaTrader 5 — multi-activo, multi-estrategia,
                con auditoría forense de cada decisión.
            </div>
            <div class="points">
                <div class="point">
                    <div class="icon">🎯</div>
                    <div class="text"><b>3 activos</b> con perfiles distintos:
                    NAS100 (índice), XAUUSD (calidad), EURUSD (scalper).</div>
                </div>
                <div class="point">
                    <div class="icon">🧠</div>
                    <div class="text"><b>5 estrategias</b> con confluencia configurable
                    por activo: ORB, EMA_MOMENTUM, VWAP_MR, BB_MR, SCALPER.</div>
                </div>
                <div class="point">
                    <div class="icon">🔒</div>
                    <div class="text"><b>3 modos de ejecución</b>: solo señal,
                    aprobación humana, o automático — toggle live por activo.</div>
                </div>
                <div class="point">
                    <div class="icon">📊</div>
                    <div class="text"><b>Backtesting integrado</b> con Sharpe, Sortino,
                    SQN, equity curve y trade log filtrable.</div>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    c1, c2, c3 = st.columns([1, 1, 1])
    with c2:
        if st.button("Entrar al bot  →", use_container_width=True, type="primary"):
            st.session_state["intro_done"] = True
            st.rerun()
    st.stop()


# ═══════════════════════════════════════════════════════════════
#  SIDEBAR
# ═══════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown('<div class="triarch-side-brand">TRIARCH</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="triarch-side-tag">MT5 multi-asset bot</div>',
        unsafe_allow_html=True,
    )

    # Estado de entorno
    env_color = "green" if settings.triarch_env.value == "demo" else "orange"
    st.markdown(
        f'<div class="triarch-side-block">'
        f'<div class="label">Entorno</div>'
        f'<div class="value">{dot(env_color)} {settings.triarch_env.value.upper()}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Estado cuenta MT5 (resumen)
    client, msg = _get_mt5_client()
    info = client.account_info() if client else None
    if info is None:
        st.markdown(
            f'<div class="triarch-side-block">'
            f'<div class="label">Cuenta MT5</div>'
            f'<div class="value">{dot("red")} Desconectada</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        eq_delta = info.equity - info.balance
        eq_color = "green" if eq_delta >= 0 else "red"
        st.markdown(
            f'<div class="triarch-side-block">'
            f'<div class="label">Cuenta MT5</div>'
            f'<div class="value">{dot("green")} #{info.login}</div>'
            f'<div class="triarch-mini">{info.server}</div>'
            f'<div class="triarch-mini" style="margin-top:8px">'
            f'Equity: <b>{info.equity:,.2f} {info.currency}</b></div>'
            f'<div class="triarch-mini">'
            f'P/L flotante: <span class="pill-{eq_color}" '
            f'style="padding:1px 6px;border-radius:6px">{eq_delta:+,.2f}</span></div>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # Kill switch info
    kill_active = bool(settings.triarch_kill)
    ks_color = "red" if kill_active else "gray"
    ks_text = "ACTIVADO — sin operar" if kill_active else "Apagado (normal)"
    st.markdown(
        f'<div class="triarch-side-block">'
        f'<div class="label">Kill switch global</div>'
        f'<div class="value">{dot(ks_color)} {ks_text}</div>'
        f'<div class="triarch-mini">Setear TRIARCH_KILL=1 en .env para activar</div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # Atajos
    st.markdown(
        f'<div class="triarch-side-block">'
        f'<div class="label">Atajos</div>'
        f'<div class="triarch-mini" style="margin-top:6px">'
        f'<code>python -m scripts.diagnose_mt5</code></div>'
        f'<div class="triarch-mini">'
        f'<code>python -m scripts.fetch_history</code></div>'
        f'<div class="triarch-mini">'
        f'<code>python -m scripts.backtest</code></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    st.markdown(
        '<div class="triarch-mini" style="text-align:center;margin-top:18px">'
        'v0.3 · UI v3</div>',
        unsafe_allow_html=True,
    )


# ═══════════════════════════════════════════════════════════════
#  HEADER
# ═══════════════════════════════════════════════════════════════
st.markdown(
    f"""
    <div class="triarch-header">
        <div class="title">🤖 <span class="accent">TRIARCH</span> Bot</div>
        <div class="subtitle">
            Entorno <b>{settings.triarch_env.value.upper()}</b> ·
            Modo defecto <b>{settings.triarch_default_mode.value}</b> ·
            Confluencia defecto {settings.triarch_confluence_min_signals}
            señales / {settings.triarch_confluence_min_families} familias /
            score ≥ {settings.triarch_confluence_min_score}
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


tab_home, tab_live, tab_dec, tab_bt, tab_data = st.tabs(
    ["🏠  Inicio", "🎯  Vivo & Control", "🧠  Decisiones", "📊  Backtesting", "📦  Datos"]
)


# ═══════════════════════════════════════════════════════════════
#  TAB 1 — INICIO  (resumen ejecutivo)
# ═══════════════════════════════════════════════════════════════
with tab_home:
    st.markdown("### Resumen del día")
    st.caption("Vista rápida de lo que está pasando ahora mismo.")

    # KPIs de cuenta
    if info is not None:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Balance", f"{info.balance:,.2f} {info.currency}")
        c2.metric("Equity", f"{info.equity:,.2f} {info.currency}",
                  delta=f"{info.equity - info.balance:+,.2f}")
        c3.metric("Margen libre", f"{info.free_margin:,.2f} {info.currency}")
        c4.metric("Apalancamiento", f"1:{info.leverage}")
    else:
        st.warning(f"⚠  {msg}")

    st.markdown("---")

    # Conteos del día (últimas 24h)
    since_24h = datetime.now(timezone.utc) - timedelta(hours=24)
    rows_24h = store.list_signals(since=since_24h, limit=5000)
    if rows_24h:
        df24 = pd.DataFrame(rows_24h)
        n_total = len(df24)
        n_taken = ((df24["status"].isin(["PLACED", "FILLED", "APPROVED"])).sum())
        n_rejected = (df24["status"].str.startswith("REJECTED")).sum() + (df24["status"] == "FAILED").sum()
        n_closed = (df24["status"].str.startswith("CLOSED")).sum()
        pnl_24h = df24["pnl_money"].fillna(0).sum() if "pnl_money" in df24.columns else 0.0
    else:
        n_total = n_taken = n_rejected = n_closed = 0
        pnl_24h = 0.0

    st.markdown("**Actividad últimas 24 horas**")
    pnl_color = "green" if pnl_24h >= 0 else "red"
    grid = (
        '<div class="triarch-kpi-grid">'
        + kpi("Señales totales", str(n_total))
        + kpi("Tomadas", str(n_taken), "ejecutadas o aprobadas")
        + kpi("Rechazadas", str(n_rejected), "por risk / confluencia / etc.")
        + kpi("Cerradas", str(n_closed), "TP o SL alcanzado")
        + kpi("P/L (USD)", f"{pnl_24h:+,.2f}", "trades cerrados 24h")
        + '</div>'
    )
    st.markdown(grid, unsafe_allow_html=True)

    st.markdown("---")

    # Estado por activo (resumen 1 línea + dot)
    st.markdown("**Estado de cada activo**")
    cols = st.columns(len(symbols))
    for col, (name, cfg) in zip(cols, symbols.items()):
        with col:
            live_take = get_take_trades(name, default=cfg.take_trades)
            recent = store.list_signals(symbol=name, limit=1)
            mode_lbl = cfg.mode.value if live_take else "SIGNAL_ONLY"
            ind_color = "green" if live_take else "gray"
            last_line = ""
            if recent:
                r = recent[0]
                last_line = (
                    f'<div class="triarch-mini" style="margin-top:8px">'
                    f'Última: {friendly_date(r.get("timestamp_utc"))}<br>'
                    f'{r.get("strategy")} {r.get("direction")} @ <code>{r.get("entry")}</code>'
                    f'</div>'
                )
            st.markdown(
                f'<div class="triarch-card">'
                f'<h4>{dot(ind_color)} {name}</h4>'
                f'<div class="triarch-mini">{cfg.broker_symbol} · {cfg.timeframe} · {cfg.profile}</div>'
                f'<div style="margin-top:8px">{pill(mode_lbl, "accent" if live_take else "gray")}</div>'
                f'{last_line}'
                f'</div>',
                unsafe_allow_html=True,
            )

    st.markdown(" ")
    st.caption("Para tomar acciones (toggles, filtros) ir a las otras pestañas.")


# ═══════════════════════════════════════════════════════════════
#  TAB 2 — VIVO & CONTROL
# ═══════════════════════════════════════════════════════════════
with tab_live:
    st.subheader("Cuenta conectada")
    if info is None:
        st.warning(f"⚠  {msg}")
    else:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Balance",        f"{info.balance:,.2f} {info.currency}")
        c2.metric("Equity",         f"{info.equity:,.2f} {info.currency}",
                  delta=f"{info.equity - info.balance:+,.2f}")
        c3.metric("Margen usado",   f"{info.margin:,.2f} {info.currency}")
        c4.metric("Margen libre",   f"{info.free_margin:,.2f} {info.currency}")
        c5.metric("Apalancamiento", f"1:{info.leverage}")
        st.caption(
            f"Cuenta **{info.login}** · servidor **{info.server}** · titular **{info.name}**"
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
                    f"{pill(cfg.profile, 'accent')}{pill(cfg.timeframe, 'gray')}"
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


# ═══════════════════════════════════════════════════════════════
#  TAB 3 — DECISIONES
# ═══════════════════════════════════════════════════════════════
def _row_to_human_block(r: dict) -> str:
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

    # KPIs rápidos arriba de la tabla
    n_taken = sum(1 for r in rows if r.get("status") in {"PLACED", "FILLED", "APPROVED"})
    n_rej   = sum(1 for r in rows if (r.get("status") or "").startswith("REJECTED") or r.get("status") == "FAILED")
    n_clo   = sum(1 for r in rows if (r.get("status") or "").startswith("CLOSED"))
    grid = (
        '<div class="triarch-kpi-grid">'
        + kpi("Encontradas", str(len(rows)))
        + kpi("Tomadas",    str(n_taken))
        + kpi("Rechazadas", str(n_rej))
        + kpi("Cerradas",   str(n_clo))
        + '</div>'
    )
    st.markdown(grid, unsafe_allow_html=True)

    if rows:
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
        st.markdown(
            '<div class="triarch-empty">'
            '<div class="emoji">🔍</div>'
            '<div>Sin decisiones para esos filtros.</div>'
            '<div class="triarch-mini">Probá ampliar el rango de días o aflojar los filtros.</div>'
            '</div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════
#  TAB 4 — BACKTESTING
# ═══════════════════════════════════════════════════════════════
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
        from scripts.backtest import backtest_symbol

        from_dt = datetime.combine(from_d, datetime.min.time()).replace(tzinfo=timezone.utc)
        to_dt = datetime.combine(to_d, datetime.max.time()).replace(tzinfo=timezone.utc)

        results = []
        prog = st.progress(0.0, text="Corriendo backtest…")
        for i, sym in enumerate(sel_symbols, start=1):
            cfg = symbols[sym]
            prog.progress(i / max(1, len(sel_symbols)), text=f"Procesando {sym}…")
            res = backtest_symbol(cfg, settings, from_date=from_dt, to_date=to_dt)
            results.append(res)
        prog.empty()
        st.session_state["bt_results"] = results

    results = st.session_state.get("bt_results")
    if results:
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

                eq = r.get("equity_curve") or []
                if eq:
                    df_eq = pd.DataFrame(eq)
                    df_eq["time"] = pd.to_datetime(df_eq["time"])
                    st.line_chart(df_eq.set_index("time")["cum_r"],
                                  height=240, use_container_width=True)
                    st.caption("Curva de equity en múltiplos de R (riesgo por trade).")

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
        st.markdown(
            '<div class="triarch-empty">'
            '<div class="emoji">📊</div>'
            '<div>Aún no has corrido un backtest.</div>'
            '<div class="triarch-mini">Configurá los filtros arriba y presioná «Correr backtest».</div>'
            '</div>',
            unsafe_allow_html=True,
        )


# ═══════════════════════════════════════════════════════════════
#  TAB 5 — DATOS  (sub-tabs Signals / Evals / Stats)
# ═══════════════════════════════════════════════════════════════
with tab_data:
    sub_signals, sub_evals, sub_stats = st.tabs(
        ["📈  Signals (cruda)", "🔍  Evals (audit trail)", "📦  Stats (agregados)"]
    )

    # ─── Signals raw ───
    with sub_signals:
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
            st.markdown(
                '<div class="triarch-empty"><div class="emoji">📭</div>'
                '<div>Aún no hay señales en la base.</div></div>',
                unsafe_allow_html=True,
            )

    # ─── Evals ───
    with sub_evals:
        st.subheader("Audit trail — cada evaluación de estrategia")
        st.caption(
            "Toda evaluación por vela queda registrada aquí, incluyendo las que no produjeron señal."
        )
        sym_filter_ev = st.selectbox("Activo", ["(todos)"] + list(symbols.keys()), key="evals_sym")
        rows = store.list_evals(
            symbol=None if sym_filter_ev == "(todos)" else sym_filter_ev,
            limit=500,
        )
        if rows:
            df = pd.DataFrame(rows)
            st.dataframe(df, use_container_width=True)
        else:
            st.markdown(
                '<div class="triarch-empty"><div class="emoji">📭</div>'
                '<div>Aún no hay evaluaciones registradas.</div></div>',
                unsafe_allow_html=True,
            )

    # ─── Stats ───
    with sub_stats:
        st.subheader("Agregados de los últimos 30 días")
        since30 = datetime.now(timezone.utc) - timedelta(days=30)
        rows = store.list_signals(since=since30, limit=10_000)
        if not rows:
            st.markdown(
                '<div class="triarch-empty"><div class="emoji">📭</div>'
                '<div>Sin datos para los últimos 30 días.</div></div>',
                unsafe_allow_html=True,
            )
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
