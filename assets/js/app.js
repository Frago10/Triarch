/* ═══════════════════════════════════════════════════════════════
   TRIARCH — frontend estático (vanilla JS)
   ─── Carga JSON desde ./data/state.json (con fallback a sample.json)
   ─── Renderiza las 5 pestañas con filtros y export .txt
   ═══════════════════════════════════════════════════════════════ */

const DATA_URLS = ['./data/state.json', './data/sample.json'];

/* ─── Diccionarios de presentación amigable ─── */
const STATUS_FRIENDLY = {
    NEW:                 ['Emitida, esperando ejecución',      'blue'],
    APPROVED:            ['Aprobada por ti',                   'green'],
    REJECTED_HUMAN:      ['Rechazada por ti',                  'red'],
    REJECTED_RISK:       ['Rechazada por gestión de riesgo',   'red'],
    REJECTED_CONFLUENCE: ['Sin confluencia entre estrategias', 'orange'],
    PLACED:              ['Orden enviada al broker',           'blue'],
    FAILED:              ['Falló al enviar al broker',         'red'],
    FILLED:              ['Posición abierta',                  'blue'],
    CLOSED_TP1:          ['Cerrada en take-profit',            'green'],
    CLOSED_TP2:          ['Cerrada en take-profit (TP2)',      'green'],
    CLOSED_SL:           ['Cerrada en stop-loss',              'red'],
    CLOSED_MANUAL:       ['Cerrada manualmente',               'gray'],
};

const REJECT_FRIENDLY = {
    no_signals: 'Ninguna estrategia detectó setup',
    direction_tie: 'Empate en dirección entre estrategias',
    min_signals: 'Solo una estrategia detectó setup (se piden al menos dos)',
    min_families: 'Setups de la misma familia (falta diversidad)',
    score: 'Puntuación combinada insuficiente',
    kill_switch: 'Kill switch global activado',
    consec_losses: 'Demasiadas pérdidas consecutivas',
    daily_cap: 'Se alcanzó el tope diario de pérdida',
    max_trades: 'Se alcanzó el máximo de trades del día',
    out_of_window: 'Fuera del horario operativo del activo',
    news_block: 'Bloqueado por evento de noticias',
    active_trade: 'Ya hay un trade abierto en este activo',
    rr_too_low: 'Relación riesgo/beneficio por debajo del mínimo',
    slippage_guard: 'Slippage demasiado alto respecto al ATR',
    not_enough_bars: 'No hay suficientes velas para evaluar',
    atr_unavailable: 'Indicador ATR aún no disponible',
    ema_unavailable: 'Indicadores EMA aún no disponibles',
    atr_too_low: 'Mercado sin volatilidad suficiente',
    no_pullback: 'No hubo retroceso claro a la media',
    below_min_rr: 'RR proyectado por debajo del mínimo',
    trend_too_weak: 'Tendencia corta demasiado débil (rango)',
};

function friendlyStatus(raw) {
    if (!raw) return ['—', 'gray'];
    return STATUS_FRIENDLY[raw] || [raw, 'gray'];
}

function friendlyReject(raw) {
    if (!raw) return '';
    const key = raw.split(':')[0].trim().toLowerCase();
    const base = REJECT_FRIENDLY[key];
    if (!base) return raw;
    const detail = raw.includes(':') ? raw.split(':').slice(1).join(':').trim() : '';
    return base + (detail ? `  (${detail})` : '');
}

function friendlyDate(tsStr) {
    if (!tsStr) return '';
    const d = new Date(tsStr);
    if (isNaN(d)) return tsStr;
    const now = new Date();
    const dayDiff = Math.floor((now - d) / (1000 * 60 * 60 * 24));
    const hh = String(d.getUTCHours()).padStart(2, '0');
    const mm = String(d.getUTCMinutes()).padStart(2, '0');
    if (dayDiff === 0) return `Hoy ${hh}:${mm} UTC`;
    if (dayDiff === 1) return `Ayer ${hh}:${mm} UTC`;
    if (dayDiff > 1 && dayDiff < 7) {
        return d.toLocaleString('es-ES', { weekday: 'short', day: '2-digit', month: 'short', timeZone: 'UTC' })
            + `, ${hh}:${mm} UTC`;
    }
    return d.toLocaleString('es-ES', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'UTC' })
        + `, ${hh}:${mm} UTC`;
}

function fmt(n, decimals = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function fmtSigned(n, decimals = 2) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    const s = Number(n).toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals, signDisplay: 'always' });
    return s;
}
function fmtPct(n) {
    if (n === null || n === undefined || Number.isNaN(n)) return '—';
    return (Number(n) * 100).toFixed(1) + '%';
}

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
const html = (s) => {
    const div = document.createElement('div');
    div.innerHTML = s;
    return div.firstElementChild;
};

function pill(text, color = 'gray') {
    return `<span class="pill pill-${color}">${text}</span>`;
}
function dot(color = 'gray') {
    return `<span class="dot dot-${color}"></span>`;
}
function kpi(label, value, sub) {
    return `<div class="kpi">
        <div class="label">${label}</div>
        <div class="value">${value}</div>
        ${sub ? `<div class="sub">${sub}</div>` : ''}
    </div>`;
}

/* ═══════════════ State global ═══════════════ */
let STATE = null;

async function loadState() {
    for (const url of DATA_URLS) {
        try {
            const res = await fetch(url, { cache: 'no-store' });
            if (res.ok) {
                const data = await res.json();
                console.log(`[triarch] loaded ${url}`);
                return { data, source: url };
            }
        } catch (e) { /* fall through */ }
    }
    throw new Error('No se pudo cargar ningún archivo de datos.');
}

/* ═══════════════ Splash ═══════════════ */
function setupSplash() {
    const splash = $('#splash');
    const btn = $('#splash-enter');
    if (sessionStorage.getItem('triarch_intro_done') === '1') {
        splash.classList.add('hidden');
        return;
    }
    btn.addEventListener('click', () => {
        splash.classList.add('hidden');
        sessionStorage.setItem('triarch_intro_done', '1');
    });
}

/* ═══════════════ Tabs ═══════════════ */
function setupTabs() {
    $$('.tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const target = tab.dataset.tab;
            $$('.tab').forEach(t => t.classList.toggle('active', t === tab));
            $$('.tab-panel').forEach(p => p.classList.toggle('active', p.dataset.panel === target));
        });
    });
    $$('.subtab').forEach(tab => {
        tab.addEventListener('click', () => {
            const group = tab.dataset.subgroup;
            const target = tab.dataset.subtab;
            $$(`.subtab[data-subgroup="${group}"]`).forEach(t => t.classList.toggle('active', t === tab));
            $$(`.subtab-panel[data-subgroup="${group}"]`).forEach(p =>
                p.classList.toggle('active', p.dataset.subtab === target));
            $$(`.subtab-panel[data-subgroup="${group}"]`).forEach(p =>
                p.style.display = (p.dataset.subtab === target) ? '' : 'none');
        });
    });
}

/* ═══════════════ Render Sidebar ═══════════════ */
function renderSidebar(data) {
    const s = data.settings || {};
    const acc = data.account;

    const envColor = (s.env === 'demo') ? 'green' : 'orange';
    $('#side-env').innerHTML = `${dot(envColor)} ${(s.env || 'demo').toUpperCase()}`;

    if (acc) {
        const delta = acc.equity - acc.balance;
        const c = delta >= 0 ? 'green' : 'red';
        $('#side-account').innerHTML = `
            <div class="value">${dot('green')} #${acc.login}</div>
            <div class="side-mini">${acc.server || ''}</div>
            <div class="side-mini" style="margin-top:8px">Equity: <b>${fmt(acc.equity)} ${acc.currency || 'USD'}</b></div>
            <div class="side-mini">P/L flotante: ${pill(fmtSigned(delta), c)}</div>
        `;
    } else {
        $('#side-account').innerHTML = `<div class="value">${dot('red')} Desconectada</div>
            <div class="side-mini">Conecta MT5 en local y exporta el estado.</div>`;
    }

    const ks = !!s.kill;
    $('#side-kill').innerHTML = `
        <div class="value">${dot(ks ? 'red' : 'gray')} ${ks ? 'ACTIVADO — sin operar' : 'Apagado (normal)'}</div>
        <div class="side-mini">Setear <code>TRIARCH_KILL=1</code> en .env para activar</div>
    `;
}

/* ═══════════════ Render Header ═══════════════ */
function renderHeader(data) {
    const s = data.settings || {};
    $('#header-subtitle').innerHTML = `
        Entorno <b>${(s.env || 'demo').toUpperCase()}</b> ·
        Modo defecto <b>${s.default_mode || 'SIGNAL_ONLY'}</b> ·
        Confluencia defecto ${s.conf_min_signals ?? 2} señales /
        ${s.conf_min_families ?? 2} familias /
        score ≥ ${s.conf_min_score ?? 0.5}
    `;
    if (data.meta && data.meta.generated_at) {
        $('#header-stamp').textContent = `Estado generado: ${friendlyDate(data.meta.generated_at)}`;
    }
}

/* ═══════════════ Tab 1 — Inicio ═══════════════ */
function renderHome(data) {
    const acc = data.account;
    if (acc) {
        const delta = acc.equity - acc.balance;
        $('#home-account-metrics').innerHTML = `
            <div class="metric"><div class="label">Balance</div><div class="value">${fmt(acc.balance)} ${acc.currency}</div></div>
            <div class="metric"><div class="label">Equity</div><div class="value">${fmt(acc.equity)} ${acc.currency}
                <span class="${delta >= 0 ? 'pos' : 'neg'}" style="font-size:.85rem;margin-left:6px">${fmtSigned(delta)}</span></div></div>
            <div class="metric"><div class="label">Margen libre</div><div class="value">${fmt(acc.free_margin)} ${acc.currency}</div></div>
            <div class="metric"><div class="label">Apalancamiento</div><div class="value">1:${acc.leverage}</div></div>
        `;
    } else {
        $('#home-account-metrics').innerHTML = `<div class="banner">⚠ Cuenta MT5 no conectada en el snapshot.</div>`;
    }

    /* KPIs 24h */
    const signals = data.signals || [];
    const since24 = Date.now() - 24 * 3600 * 1000;
    const last24 = signals.filter(r => new Date(r.timestamp_utc).getTime() >= since24);
    const nTotal = last24.length;
    const nTaken = last24.filter(r => ['PLACED', 'FILLED', 'APPROVED'].includes(r.status)).length;
    const nRej = last24.filter(r => (r.status || '').startsWith('REJECTED') || r.status === 'FAILED').length;
    const nClo = last24.filter(r => (r.status || '').startsWith('CLOSED')).length;
    const pnl24 = last24.reduce((s, r) => s + (r.pnl_money || 0), 0);

    $('#home-kpis').innerHTML = `
        ${kpi('Señales totales', String(nTotal))}
        ${kpi('Tomadas', String(nTaken), 'ejecutadas o aprobadas')}
        ${kpi('Rechazadas', String(nRej), 'por risk / confluencia / etc.')}
        ${kpi('Cerradas', String(nClo), 'TP o SL alcanzado')}
        ${kpi('P/L (USD)', fmtSigned(pnl24), 'trades cerrados 24h')}
    `;

    /* Tarjetas por activo */
    const syms = data.symbols || {};
    const container = $('#home-assets');
    container.innerHTML = '';
    Object.entries(syms).forEach(([name, cfg]) => {
        const liveTake = cfg.take_trades_live ?? cfg.take_trades;
        const modeLbl = liveTake ? cfg.mode : 'SIGNAL_ONLY';
        const indColor = liveTake ? 'green' : 'gray';
        const last = signals.find(s => s.symbol === name);
        let lastLine = '';
        if (last) {
            lastLine = `<div class="side-mini" style="margin-top:10px">
                Última: ${friendlyDate(last.timestamp_utc)}<br>
                ${last.strategy} ${last.direction} @ <code>${last.entry}</code>
            </div>`;
        }
        container.appendChild(html(`
            <div class="card">
                <h4>${dot(indColor)} ${name}</h4>
                <div class="side-mini">${cfg.broker_symbol} · ${cfg.timeframe} · ${cfg.profile}</div>
                <div style="margin-top:10px">${pill(modeLbl, liveTake ? 'accent' : 'gray')}</div>
                ${lastLine}
            </div>
        `));
    });
}

/* ═══════════════ Tab 2 — Vivo & Control ═══════════════ */
function renderLive(data) {
    const acc = data.account;
    if (acc) {
        const delta = acc.equity - acc.balance;
        $('#live-account-metrics').innerHTML = `
            <div class="metric"><div class="label">Balance</div><div class="value">${fmt(acc.balance)} ${acc.currency}</div></div>
            <div class="metric"><div class="label">Equity</div><div class="value">${fmt(acc.equity)} ${acc.currency}
                <span class="${delta >= 0 ? 'pos' : 'neg'}" style="font-size:.85rem;margin-left:6px">${fmtSigned(delta)}</span></div></div>
            <div class="metric"><div class="label">Margen usado</div><div class="value">${fmt(acc.margin)} ${acc.currency}</div></div>
            <div class="metric"><div class="label">Margen libre</div><div class="value">${fmt(acc.free_margin)} ${acc.currency}</div></div>
            <div class="metric"><div class="label">Apalancamiento</div><div class="value">1:${acc.leverage}</div></div>
        `;
        $('#live-account-caption').textContent =
            `Cuenta ${acc.login} · servidor ${acc.server} · titular ${acc.name || ''}`;
    } else {
        $('#live-account-metrics').innerHTML = `<div class="banner">⚠ Cuenta MT5 no presente en el snapshot.</div>`;
    }

    const syms = data.symbols || {};
    const signals = data.signals || [];
    const container = $('#live-assets');
    container.innerHTML = '';
    Object.entries(syms).forEach(([name, cfg]) => {
        const liveTake = cfg.take_trades_live ?? cfg.take_trades;
        const effective = liveTake ? cfg.mode : 'SIGNAL_ONLY (forzado)';
        const last = signals.find(s => s.symbol === name);
        let lastBlock = '<div class="side-mini">Aún sin señales registradas para este activo.</div>';
        if (last) {
            const [stText, stColor] = friendlyStatus(last.status);
            const rej = friendlyReject(last.reject_reason);
            lastBlock = `
                <div style="margin-top:10px"><b>Última señal:</b> ${friendlyDate(last.timestamp_utc)} ·
                    ${last.strategy} · <b>${last.direction}</b> @ <code>${last.entry}</code> ·
                    RR <code>${fmt(last.rr_ratio)}</code> · score <code>${fmt(last.score)}</code>
                </div>
                <div style="margin-top:8px">${pill(stText, stColor)}</div>
                ${rej ? `<div class="side-mini">Motivo: ${rej}</div>` : ''}
            `;
        }
        container.appendChild(html(`
            <div class="card-bordered">
                <div class="card-head">
                    <div>
                        <h3>${name}</h3>
                        <div>
                            <b>${cfg.broker_symbol}</b> · ${cfg.description || ''}<br>
                            ${pill(cfg.profile, 'accent')}${pill(cfg.timeframe, 'gray')}
                            ${pill(`sesión ${cfg.session_start || ''}–${cfg.session_end || ''} UTC`, 'gray')}
                        </div>
                    </div>
                    <div style="text-align:right">
                        <label class="toggle" title="Solo lectura — el toggle real vive en config/runtime.yaml">
                            <input type="checkbox" ${liveTake ? 'checked' : ''} disabled>
                            <span class="toggle-track"></span>
                            <span class="toggle-label">Trades reales en MT5</span>
                        </label>
                        <div style="margin-top:8px">Modo efectivo: ${pill(effective, liveTake ? 'green' : 'orange')}</div>
                    </div>
                </div>
                ${lastBlock}
            </div>
        `));
    });
}

/* ═══════════════ Tab 3 — Decisiones ═══════════════ */
function renderDecisions(data) {
    const syms = data.symbols || {};
    const allStrats = [...new Set(Object.values(syms).flatMap(c => c.strategies || []))].sort();

    const sel = $('#dec-symbol');
    sel.innerHTML = '<option value="">(todos)</option>' +
        Object.keys(syms).map(s => `<option>${s}</option>`).join('');
    $('#dec-strategy').innerHTML = '<option value="">(todas)</option>' +
        allStrats.map(s => `<option>${s}</option>`).join('');

    function applyFilters() {
        const symF = sel.value;
        const stratF = $('#dec-strategy').value;
        const statusF = $('#dec-status').value;
        const dirF = $('input[name="dec-dir"]:checked').value;
        const days = parseInt($('#dec-days').value, 10) || 30;
        const since = Date.now() - days * 24 * 3600 * 1000;

        let rows = (data.signals || []).filter(r => new Date(r.timestamp_utc).getTime() >= since);
        if (symF) rows = rows.filter(r => r.symbol === symF);
        if (stratF) rows = rows.filter(r => r.strategy === stratF);
        if (dirF !== 'all') rows = rows.filter(r => r.direction === dirF);
        if (statusF === 'taken') rows = rows.filter(r => ['PLACED', 'FILLED', 'APPROVED'].includes(r.status));
        else if (statusF === 'rejected') rows = rows.filter(r => (r.status || '').startsWith('REJECTED') || r.status === 'FAILED');
        else if (statusF === 'closed') rows = rows.filter(r => (r.status || '').startsWith('CLOSED'));
        else if (statusF === 'new') rows = rows.filter(r => r.status === 'NEW');

        const nTaken = rows.filter(r => ['PLACED', 'FILLED', 'APPROVED'].includes(r.status)).length;
        const nRej = rows.filter(r => (r.status || '').startsWith('REJECTED') || r.status === 'FAILED').length;
        const nClo = rows.filter(r => (r.status || '').startsWith('CLOSED')).length;

        $('#dec-kpis').innerHTML = `
            ${kpi('Encontradas', String(rows.length))}
            ${kpi('Tomadas', String(nTaken))}
            ${kpi('Rechazadas', String(nRej))}
            ${kpi('Cerradas', String(nClo))}
        `;

        const wrap = $('#dec-table-wrap');
        if (!rows.length) {
            wrap.innerHTML = `<div class="empty">
                <div class="emoji">🔍</div>
                <div>Sin decisiones para esos filtros.</div>
                <div class="mini">Probá ampliar el rango de días o aflojar los filtros.</div>
            </div>`;
            $('#dec-download').style.display = 'none';
            return;
        }
        const tbody = rows.map(r => {
            const [stText] = friendlyStatus(r.status);
            const pnl = r.pnl_money;
            const pnlClass = pnl > 0 ? 'pos' : (pnl < 0 ? 'neg' : '');
            return `<tr>
                <td>${friendlyDate(r.timestamp_utc)}</td>
                <td>${r.symbol || ''}</td>
                <td>${r.strategy || ''}</td>
                <td>${r.direction || ''}</td>
                <td class="num">${r.entry ?? ''}</td>
                <td class="num">${r.stop_loss ?? ''}</td>
                <td class="num">${r.take_profit_1 ?? ''}</td>
                <td class="num">${fmt(r.rr_ratio)}</td>
                <td class="num">${fmt(r.score)}</td>
                <td>${stText}</td>
                <td>${friendlyReject(r.reject_reason)}</td>
                <td class="num ${pnlClass}">${pnl == null ? '—' : fmtSigned(pnl)}</td>
            </tr>`;
        }).join('');
        wrap.innerHTML = `<div class="table-wrap"><table>
            <thead><tr>
                <th>Fecha</th><th>Activo</th><th>Estrategia</th><th>Dirección</th>
                <th>Entry</th><th>SL</th><th>TP1</th><th>RR</th>
                <th>Score</th><th>Estado</th><th>Motivo</th><th>PnL (USD)</th>
            </tr></thead>
            <tbody>${tbody}</tbody>
        </table></div>`;

        /* download .txt */
        $('#dec-download').style.display = '';
        $('#dec-download').onclick = () => {
            const header =
                '='.repeat(72) + '\n' +
                'Triarch — historial de decisiones\n' +
                'Generado: ' + new Date().toISOString().replace('T', ' ').slice(0, 19) + '\n' +
                `Filtros:  activo=${symF || '(todos)'}  estrategia=${stratF || '(todas)'}  ` +
                `estado=${statusF || '(todos)'}  dirección=${dirF}  últimos_días=${days}\n` +
                `Total decisiones: ${rows.length}\n` +
                '='.repeat(72) + '\n\n';
            const body = rows.map(r => {
                const [stText] = friendlyStatus(r.status);
                const rej = friendlyReject(r.reject_reason);
                const pnlStr = (typeof r.pnl_money === 'number') ? fmtSigned(r.pnl_money) + ' USD' : 'n/a';
                return `[${friendlyDate(r.timestamp_utc)}]  ${r.symbol}  ${r.strategy}  ${r.direction}\n` +
                       `  entry=${r.entry}  SL=${r.stop_loss}  TP1=${r.take_profit_1}\n` +
                       `  RR=${fmt(r.rr_ratio)}  score=${fmt(r.score)}  PnL=${pnlStr}\n` +
                       `  Estado: ${stText}` + (rej ? ` — Motivo: ${rej}` : '') + '\n\n';
            }).join('');
            const blob = new Blob([header + body], { type: 'text/plain' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = `triarch_decisiones_${symF || 'ALL'}_${new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14)}.txt`;
            a.click();
        };
    }

    /* listeners radio (custom) */
    $$('input[name="dec-dir"]').forEach(input => {
        input.addEventListener('change', applyFilters);
    });
    ['change', 'input'].forEach(ev => {
        ['#dec-symbol', '#dec-strategy', '#dec-status', '#dec-days'].forEach(s => {
            $(s).addEventListener(ev, applyFilters);
        });
    });
    applyFilters();
}

/* ═══════════════ Tab 4 — Backtesting ═══════════════ */
/* Recalcula métricas desde un trade_log filtrado por rango temporal.
   Devuelve el mismo shape que el backtest_result original, para que el
   render existente lo consuma sin cambios. */
function recomputeMetricsFromLog(original, fromTs, toTs) {
    const log = (original.trade_log || []).filter(t => {
        const ts = new Date(t.time).getTime();
        if (fromTs && ts < fromTs) return false;
        if (toTs && ts > toTs) return false;
        return true;
    });
    if (!log.length) {
        return {
            ...original,
            trades: 0,
            note: 'Sin trades en el rango temporal seleccionado.',
            trade_log: [],
            equity_curve: [],
            by_strategy: {},
        };
    }
    const returns = log.map(t => t.pnl_r);
    const wins = returns.filter(r => r > 0);
    const losses = returns.filter(r => r < 0);
    const grossWin = wins.reduce((s, x) => s + x, 0);
    const grossLoss = -losses.reduce((s, x) => s + x, 0);
    const expectancy = returns.reduce((s, x) => s + x, 0) / returns.length;
    const mean = expectancy;
    const variance = returns.reduce((s, x) => s + (x - mean) ** 2, 0) / Math.max(returns.length - 1, 1);
    const sd = Math.sqrt(variance);
    const sharpe = sd > 0 ? (mean / sd) * Math.sqrt(252) : 0;
    const downsideSd = (() => {
        if (losses.length < 2) return 0;
        const m = losses.reduce((s, x) => s + x, 0) / losses.length;
        const v = losses.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(losses.length - 1, 1);
        return Math.sqrt(v);
    })();
    const sortino = downsideSd > 0 ? (mean / downsideSd) * Math.sqrt(252) : 0;
    const sqn = sd > 0 ? Math.sqrt(returns.length) * mean / sd : 0;
    let cum = 0, peak = 0, maxDd = 0;
    const equity = log.map(t => {
        cum += t.pnl_r;
        peak = Math.max(peak, cum);
        maxDd = Math.max(maxDd, peak - cum);
        return { time: t.time, cum_r: cum };
    });
    /* by_strategy */
    const byStrat = {};
    log.forEach(t => {
        const k = t.strategy;
        if (!byStrat[k]) byStrat[k] = { trades: 0, total_r: 0 };
        byStrat[k].trades++;
        byStrat[k].total_r += t.pnl_r;
    });
    Object.values(byStrat).forEach(v => {
        v.expectancy_r = v.total_r / v.trades;
        v.total_r = Math.round(v.total_r * 1000) / 1000;
        v.expectancy_r = Math.round(v.expectancy_r * 1000) / 1000;
    });
    /* streaks */
    let curW = 0, curL = 0, longW = 0, longL = 0;
    returns.forEach(r => {
        if (r > 0) { curW++; longW = Math.max(longW, curW); curL = 0; }
        else if (r < 0) { curL++; longL = Math.max(longL, curL); curW = 0; }
    });
    /* trades per week */
    const ts = log.map(t => new Date(t.time).getTime());
    const spanDays = (Math.max(...ts) - Math.min(...ts)) / (1000 * 86400);
    const tradesPerWeek = spanDays > 0 ? (log.length / (spanDays / 7)) : log.length;

    return {
        ...original,
        trades: log.length,
        win_rate: wins.length / log.length,
        profit_factor: grossLoss > 0 ? grossWin / grossLoss : (grossWin > 0 ? Infinity : 0),
        expectancy_r: expectancy,
        sharpe_ratio: sharpe,
        sortino_ratio: sortino,
        sqn: sqn,
        max_drawdown_r: maxDd,
        avg_win_r: wins.length ? wins.reduce((s, x) => s + x, 0) / wins.length : 0,
        avg_loss_r: losses.length ? losses.reduce((s, x) => s + x, 0) / losses.length : 0,
        longest_win_streak: longW,
        longest_loss_streak: longL,
        trades_per_week_avg: Math.round(tradesPerWeek * 100) / 100,
        by_strategy: byStrat,
        equity_curve: equity,
        trade_log: log,
        note: '',
    };
}

let BT_BASE_RESULTS = [];  /* snapshot original sin filtrar */

function renderBacktest(data) {
    BT_BASE_RESULTS = data.backtest_results || [];
    const container = $('#bt-results');
    if (!BT_BASE_RESULTS.length) {
        container.innerHTML = `<div class="empty">
            <div class="emoji">📊</div>
            <div>Aún no hay un backtest exportado.</div>
            <div class="mini">Corre <code>python -m scripts.backtest</code> + <code>scripts.export_web</code> y vuelve a cargar.</div>
        </div>`;
        return;
    }

    /* Determinar el rango temporal completo (de TODOS los trade_log unidos) */
    const allTs = BT_BASE_RESULTS
        .flatMap(r => r.trade_log || [])
        .map(t => new Date(t.time).getTime())
        .filter(n => !isNaN(n));
    const minTs = allTs.length ? Math.min(...allTs) : null;
    const maxTs = allTs.length ? Math.max(...allTs) : null;

    /* Llenar el selector de activos */
    const sel = $('#bt-symbol-filter');
    sel.innerHTML = '<option value="">(todos)</option>' +
        BT_BASE_RESULTS.map(r => `<option>${r.symbol}</option>`).join('');

    /* Set defaults en los date inputs si están vacíos */
    if (minTs && !$('#bt-from').value) $('#bt-from').value = new Date(minTs).toISOString().slice(0, 10);
    if (maxTs && !$('#bt-to').value) $('#bt-to').value = new Date(maxTs).toISOString().slice(0, 10);

    function applyBtFilters() {
        const fromVal = $('#bt-from').value;
        const toVal = $('#bt-to').value;
        const symF = $('#bt-symbol-filter').value;
        const fromTs = fromVal ? new Date(fromVal + 'T00:00:00Z').getTime() : null;
        const toTs = toVal ? new Date(toVal + 'T23:59:59Z').getTime() : null;

        let filtered = BT_BASE_RESULTS;
        if (symF) filtered = filtered.filter(r => r.symbol === symF);
        const isFullRange = (!fromTs || fromTs <= minTs) && (!toTs || toTs >= maxTs);
        if (!isFullRange) {
            filtered = filtered.map(r => r.error ? r : recomputeMetricsFromLog(r, fromTs, toTs));
        }
        drawBacktestResults(filtered);
    }

    /* Listeners */
    ['#bt-from', '#bt-to', '#bt-symbol-filter'].forEach(s =>
        $(s).addEventListener('change', applyBtFilters));
    $('#bt-reset').addEventListener('click', () => {
        if (minTs) $('#bt-from').value = new Date(minTs).toISOString().slice(0, 10);
        if (maxTs) $('#bt-to').value = new Date(maxTs).toISOString().slice(0, 10);
        $('#bt-symbol-filter').value = '';
        applyBtFilters();
    });
    $$('#bt-preset-row [data-bt-preset]').forEach(btn => {
        btn.addEventListener('click', () => {
            const preset = btn.dataset.btPreset;
            const today = new Date();
            let from;
            if (preset === '1m') from = new Date(today.getTime() - 30 * 86400e3);
            else if (preset === '3m') from = new Date(today.getTime() - 90 * 86400e3);
            else if (preset === '6m') from = new Date(today.getTime() - 180 * 86400e3);
            else if (preset === 'ytd') from = new Date(today.getFullYear(), 0, 1);
            else if (preset === '1y') from = new Date(today.getTime() - 365 * 86400e3);
            else if (preset === 'all' && minTs) from = new Date(minTs);
            if (from) $('#bt-from').value = from.toISOString().slice(0, 10);
            $('#bt-to').value = today.toISOString().slice(0, 10);
            applyBtFilters();
        });
    });

    applyBtFilters();
}

function drawBacktestResults(results) {
    const container = $('#bt-results');

    /* tabla resumen */
    const summary = results.map(r => {
        if (r.error || (r.trades || 0) === 0) {
            return `<tr>
                <td>${r.symbol || ''}</td><td>0</td><td>—</td><td>—</td><td>—</td>
                <td>—</td><td>—</td><td>—</td><td>—</td><td>—</td>
                <td>${r.error || r.note || ''}</td>
            </tr>`;
        }
        const pf = r.profit_factor === Infinity ? '∞' : fmt(r.profit_factor);
        return `<tr>
            <td><b>${r.symbol}</b></td>
            <td class="num">${r.trades}</td>
            <td class="num">${fmtPct(r.win_rate)}</td>
            <td class="num">${pf}</td>
            <td class="num ${r.expectancy_r >= 0 ? 'pos' : 'neg'}">${fmtSigned(r.expectancy_r, 3)}</td>
            <td class="num">${fmt(r.sharpe_ratio)}</td>
            <td class="num">${fmt(r.sortino_ratio)}</td>
            <td class="num">${fmt(r.sqn)}</td>
            <td class="num">${fmt(r.max_drawdown_r)}</td>
            <td class="num">${r.trades_per_week_avg}</td>
            <td></td>
        </tr>`;
    }).join('');

    let detailsHtml = '';
    results.forEach(r => {
        if (r.error) {
            detailsHtml += `<details class="card-bordered"><summary>❌ ${r.symbol} — sin datos</summary>
                <div class="banner">${r.error}</div></details>`;
            return;
        }
        if ((r.trades || 0) === 0) {
            detailsHtml += `<details class="card-bordered"><summary>⚠ ${r.symbol} — 0 trades</summary>
                <div class="banner">${r.note || ''}</div></details>`;
            return;
        }
        const pf = r.profit_factor === Infinity ? '∞' : fmt(r.profit_factor);
        const id = `chart-${r.symbol}-${Math.random().toString(36).slice(2, 8)}`;
        const kpis = `<div class="kpi-grid">
            ${kpi('Trades', String(r.trades))}
            ${kpi('Win rate', fmtPct(r.win_rate))}
            ${kpi('Profit factor', pf)}
            ${kpi('Expectancy', fmtSigned(r.expectancy_r, 3) + ' R')}
            ${kpi('Sharpe', fmt(r.sharpe_ratio))}
            ${kpi('Sortino', fmt(r.sortino_ratio))}
            ${kpi('SQN', fmt(r.sqn))}
            ${kpi('Max DD', fmt(r.max_drawdown_r) + ' R')}
            ${kpi('Avg win', fmtSigned(r.avg_win_r) + ' R')}
            ${kpi('Avg loss', fmtSigned(r.avg_loss_r) + ' R')}
            ${kpi('Rachas (W/L)', `+${r.longest_win_streak ?? 0} / -${r.longest_loss_streak ?? 0}`)}
            ${kpi('Trades/sem', String(r.trades_per_week_avg ?? '—'))}
        </div>`;

        let byStratHtml = '';
        if (r.by_strategy) {
            const rows = Object.entries(r.by_strategy).map(([k, v]) => `
                <tr>
                    <td>${k}</td>
                    <td class="num">${v.trades}</td>
                    <td class="num ${v.expectancy_r >= 0 ? 'pos' : 'neg'}">${fmtSigned(v.expectancy_r, 3)}</td>
                    <td class="num ${v.total_r >= 0 ? 'pos' : 'neg'}">${fmtSigned(v.total_r, 2)}</td>
                </tr>`).join('');
            byStratHtml = `<h4>Por estrategia</h4>
                <div class="table-wrap"><table>
                    <thead><tr><th>Estrategia</th><th>Trades</th><th>Expectancy (R)</th><th>Total (R)</th></tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }

        let logHtml = '';
        if (r.trade_log && r.trade_log.length) {
            const rows = r.trade_log.map(t => `<tr>
                <td>${friendlyDate(t.time)}</td>
                <td>${t.strategy || ''}</td>
                <td>${t.direction || ''}</td>
                <td class="num">${t.entry ?? ''}</td>
                <td class="num">${t.sl ?? ''}</td>
                <td class="num">${t.tp1 ?? ''}</td>
                <td class="num">${fmt(t.rr_planned)}</td>
                <td class="num">${fmt(t.score)}</td>
                <td>${t.outcome || ''}</td>
                <td class="num">${t.bars_held ?? ''}</td>
                <td class="num ${t.pnl_r >= 0 ? 'pos' : 'neg'}">${fmtSigned(t.pnl_r, 2)}</td>
            </tr>`).join('');
            logHtml = `<h4>Trade log</h4>
                <div class="table-wrap" style="max-height:360px"><table>
                    <thead><tr>
                        <th>Fecha</th><th>Estrategia</th><th>Dirección</th><th>Entry</th>
                        <th>SL</th><th>TP1</th><th>RR plan</th><th>Score</th>
                        <th>Resultado</th><th>Velas</th><th>PnL (R)</th>
                    </tr></thead>
                    <tbody>${rows}</tbody>
                </table></div>`;
        }

        detailsHtml += `<details class="card-bordered" id="det-${r.symbol}">
            <summary style="cursor:pointer;font-weight:700">
                📈 ${r.symbol} · ${r.trades} trades · WR ${fmtPct(r.win_rate)} ·
                E ${fmtSigned(r.expectancy_r, 3)}R · Sharpe ${fmt(r.sharpe_ratio)}
            </summary>
            ${kpis}
            <div class="chart-wrap"><canvas id="${id}" height="120"></canvas></div>
            <div class="section-caption">Curva de equity en múltiplos de R (riesgo por trade).</div>
            ${byStratHtml}
            ${logHtml}
        </details>`;

        /* draw chart on expand */
        setTimeout(() => {
            const det = $(`#det-${r.symbol}`);
            if (!det) return;
            det.addEventListener('toggle', () => {
                if (det.open && !det.dataset.charted) {
                    drawEquity(id, r.equity_curve || []);
                    det.dataset.charted = '1';
                }
            });
        }, 0);
    });

    container.innerHTML = `
        <h3 class="section-title">Comparativa de activos</h3>
        <div class="table-wrap"><table>
            <thead><tr>
                <th>Activo</th><th>Trades</th><th>Win rate</th><th>Profit factor</th>
                <th>Expectancy (R)</th><th>Sharpe</th><th>Sortino</th><th>SQN</th>
                <th>Max DD (R)</th><th>Trades/sem</th><th>Nota</th>
            </tr></thead>
            <tbody>${summary}</tbody>
        </table></div>
        <div style="margin-top:18px">${detailsHtml}</div>
        <div style="margin-top:14px">
            <button class="btn" id="bt-download">⬇ Descargar resumen .txt</button>
        </div>
    `;

    $('#bt-download').onclick = () => {
        let txt = '='.repeat(72) + '\n' +
            'Triarch — resumen backtest\n' +
            'Generado: ' + new Date().toISOString().replace('T', ' ').slice(0, 19) + '\n' +
            '='.repeat(72) + '\n\n';
        results.forEach(r => {
            if (r.error) { txt += `${r.symbol}: ERROR ${r.error}\n\n`; return; }
            if (!r.trades) { txt += `${r.symbol}: 0 trades. ${r.note || ''}\n\n`; return; }
            const pf = r.profit_factor === Infinity ? '∞' : fmt(r.profit_factor);
            txt += `${r.symbol}\n` +
                `  trades=${r.trades}  WR=${fmtPct(r.win_rate)}  PF=${pf}\n` +
                `  E=${fmtSigned(r.expectancy_r, 3)}R  Sharpe=${fmt(r.sharpe_ratio)}  Sortino=${fmt(r.sortino_ratio)}\n` +
                `  SQN=${fmt(r.sqn)}  maxDD=${fmt(r.max_drawdown_r)}R  trades/sem=${r.trades_per_week_avg}\n\n`;
        });
        const blob = new Blob([txt], { type: 'text/plain' });
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `triarch_backtest_${new Date().toISOString().replace(/[-:T.]/g, '').slice(0, 14)}.txt`;
        a.click();
    };
}

/* ─── Equity chart (Canvas, sin libs) ─── */
function drawEquity(canvasId, points) {
    const c = document.getElementById(canvasId);
    if (!c || !points.length) return;
    const ctx = c.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const w = c.parentElement.clientWidth - 28;
    const h = 220;
    c.width = w * dpr; c.height = h * dpr;
    c.style.width = w + 'px'; c.style.height = h + 'px';
    ctx.scale(dpr, dpr);

    const ys = points.map(p => p.cum_r);
    const xs = points.map((_, i) => i);
    const minY = Math.min(...ys), maxY = Math.max(...ys);
    const padY = (maxY - minY) * 0.1 || 1;
    const yMin = minY - padY, yMax = maxY + padY;
    const padL = 50, padR = 12, padT = 12, padB = 26;
    const plotW = w - padL - padR;
    const plotH = h - padT - padB;

    /* grid */
    ctx.strokeStyle = 'rgba(255,255,255,0.06)';
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i++) {
        const y = padT + (plotH * i) / 4;
        ctx.beginPath(); ctx.moveTo(padL, y); ctx.lineTo(padL + plotW, y); ctx.stroke();
        const val = yMax - ((yMax - yMin) * i) / 4;
        ctx.fillStyle = 'rgba(160,160,170,0.7)';
        ctx.font = '11px Inter, sans-serif';
        ctx.fillText(val.toFixed(1) + 'R', 6, y + 4);
    }

    /* fill */
    ctx.beginPath();
    ctx.moveTo(padL, padT + plotH);
    points.forEach((p, i) => {
        const x = padL + (plotW * i) / (points.length - 1 || 1);
        const y = padT + plotH - ((p.cum_r - yMin) / (yMax - yMin)) * plotH;
        ctx.lineTo(x, y);
    });
    ctx.lineTo(padL + plotW, padT + plotH);
    ctx.closePath();
    const grad = ctx.createLinearGradient(0, padT, 0, padT + plotH);
    grad.addColorStop(0, 'rgba(239, 68, 68, 0.40)');
    grad.addColorStop(1, 'rgba(239, 68, 68, 0.02)');
    ctx.fillStyle = grad; ctx.fill();

    /* line */
    ctx.beginPath();
    points.forEach((p, i) => {
        const x = padL + (plotW * i) / (points.length - 1 || 1);
        const y = padT + plotH - ((p.cum_r - yMin) / (yMax - yMin)) * plotH;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.strokeStyle = '#ef4444';
    ctx.lineWidth = 2;
    ctx.stroke();
}

/* ═══════════════ Tab 5 — Datos ═══════════════ */
function renderData(data) {
    const syms = Object.keys(data.symbols || {});

    /* Signals raw */
    const fillSelect = (sel, withTodos = true) => {
        sel.innerHTML = (withTodos ? '<option value="">(todos)</option>' : '') +
            syms.map(s => `<option>${s}</option>`).join('');
    };
    fillSelect($('#sig-symbol'));
    fillSelect($('#evals-symbol'));

    function renderSignalsRaw() {
        const f = $('#sig-symbol').value;
        const rows = (data.signals || []).filter(r => !f || r.symbol === f).slice(0, 500);
        const wrap = $('#sig-table-wrap');
        if (!rows.length) {
            wrap.innerHTML = `<div class="empty"><div class="emoji">📭</div>
                <div>Aún no hay señales en la base.</div></div>`;
            return;
        }
        const cols = ['timestamp_utc', 'symbol', 'strategy', 'direction', 'entry',
            'stop_loss', 'take_profit_1', 'rr_ratio', 'score', 'confidence',
            'status', 'reject_reason', 'pnl_money'];
        const head = cols.map(c => `<th>${c}</th>`).join('');
        const body = rows.map(r => `<tr>${cols.map(c => {
            const v = r[c];
            const cls = (c === 'pnl_money' && typeof v === 'number') ? (v >= 0 ? 'pos' : 'neg') : '';
            return `<td class="num ${cls}">${v == null ? '' : v}</td>`;
        }).join('')}</tr>`).join('');
        wrap.innerHTML = `<div class="table-wrap"><table>
            <thead><tr>${head}</tr></thead><tbody>${body}</tbody>
        </table></div>`;
    }

    function renderEvalsRaw() {
        const f = $('#evals-symbol').value;
        const rows = (data.evals || []).filter(r => !f || r.symbol === f).slice(0, 500);
        const wrap = $('#evals-table-wrap');
        if (!rows.length) {
            wrap.innerHTML = `<div class="empty"><div class="emoji">📭</div>
                <div>Aún no hay evaluaciones registradas.</div></div>`;
            return;
        }
        const cols = Object.keys(rows[0]);
        const head = cols.map(c => `<th>${c}</th>`).join('');
        const body = rows.map(r => `<tr>${cols.map(c =>
            `<td>${r[c] == null ? '' : r[c]}</td>`).join('')}</tr>`).join('');
        wrap.innerHTML = `<div class="table-wrap"><table>
            <thead><tr>${head}</tr></thead><tbody>${body}</tbody>
        </table></div>`;
    }

    function renderStats() {
        const since30 = Date.now() - 30 * 24 * 3600 * 1000;
        const rows = (data.signals || []).filter(r => new Date(r.timestamp_utc).getTime() >= since30);
        if (!rows.length) {
            $('#stats-by-sym').innerHTML = `<div class="empty"><div class="emoji">📭</div>
                <div>Sin datos para los últimos 30 días.</div></div>`;
            $('#stats-by-strat').innerHTML = '';
            return;
        }
        const agg = {};
        rows.forEach(r => {
            const k = r.symbol;
            if (!agg[k]) agg[k] = { n: 0, score: 0, rr: 0 };
            agg[k].n++;
            agg[k].score += r.score || 0;
            agg[k].rr += r.rr_ratio || 0;
        });
        const symHtml = Object.entries(agg).map(([k, v]) => `<tr>
            <td>${k}</td>
            <td class="num">${v.n}</td>
            <td class="num">${(v.score / v.n).toFixed(3)}</td>
            <td class="num">${(v.rr / v.n).toFixed(3)}</td>
        </tr>`).join('');
        $('#stats-by-sym').innerHTML = `<h4>Por activo</h4>
            <div class="table-wrap"><table>
                <thead><tr><th>Symbol</th><th>Señales</th><th>Avg score</th><th>Avg RR</th></tr></thead>
                <tbody>${symHtml}</tbody>
            </table></div>`;

        const agg2 = {};
        rows.forEach(r => {
            const k = `${r.symbol}||${r.strategy}`;
            agg2[k] = (agg2[k] || 0) + 1;
        });
        const stratHtml = Object.entries(agg2).map(([k, n]) => {
            const [sym, st] = k.split('||');
            return `<tr><td>${sym}</td><td>${st}</td><td class="num">${n}</td></tr>`;
        }).join('');
        $('#stats-by-strat').innerHTML = `<h4>Por activo × estrategia</h4>
            <div class="table-wrap"><table>
                <thead><tr><th>Symbol</th><th>Strategy</th><th>Señales</th></tr></thead>
                <tbody>${stratHtml}</tbody>
            </table></div>`;
    }

    $('#sig-symbol').addEventListener('change', renderSignalsRaw);
    $('#evals-symbol').addEventListener('change', renderEvalsRaw);

    renderSignalsRaw();
    renderEvalsRaw();
    renderStats();
}

/* ═══════════════ Boot ═══════════════ */
async function boot() {
    setupSplash();
    setupTabs();
    try {
        const { data, source } = await loadState();
        STATE = data;
        if (source.endsWith('sample.json')) {
            $('#data-source-banner').style.display = '';
        }
        renderSidebar(data);
        renderHeader(data);
        renderHome(data);
        renderLive(data);
        renderDecisions(data);
        renderBacktest(data);
        renderData(data);
    } catch (e) {
        console.error(e);
        document.querySelector('.main').innerHTML = `
            <div class="banner">
                ⚠ No se pudo cargar el archivo de estado.<br>
                Genera <code>docs/data/state.json</code> con
                <code>python -m scripts.export_web</code> o copia el archivo de muestra.
            </div>
        `;
    }
}

document.addEventListener('DOMContentLoaded', boot);
