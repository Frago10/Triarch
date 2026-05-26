/* ═══════════════════════════════════════════════════════════════
   TRIARCH — Backtester en JavaScript puro

   Porta las estrategias y métricas del Python (scripts/backtest.py)
   al browser. Los indicadores vienen YA precalculados desde Python
   (scripts/export_ohlc.py), así que aquí solo aplicamos reglas
   por vela + resolución de trades + métricas.

   Estrategias portadas (paridad con Python registry):
     · EMA_MOMENTUM
     · PULLBACK_TREND
     · DONCHIAN_BREAK
     · KELTNER_BREAK
     · MACD_CROSS
     · RSI_REVERSAL
     · VWAP_MR
     · BB_MR
     · ORB
     · SCALPER

   Uso:
     const result = runBacktest({
         ohlc:         payloadJson,   // cargado de data/ohlc/{symbol}.json
         strategies:   ['EMA_MOMENTUM', 'PULLBACK_TREND', ...],
         confluence:   { min_signals: 2, min_families: 2, min_combined_score: 1.0 },
         minRR:        1.5,
         maxTradesDay: 8,
         fromTs:       Date.UTC(2025, 0, 1),
         toTs:         Date.now(),
     });
   ═══════════════════════════════════════════════════════════════ */

/* ─── Utilidad: convertir filas comprimidas a objetos por nombre ─── */
function rowToBar(row, columns) {
    const b = {};
    for (let i = 0; i < columns.length; i++) {
        b[columns[i]] = row[i];
    }
    return b;
}

/* ─── Filtro de sesión "HH:MM" → minuto del día UTC ─── */
function hhmmToMin(hhmm) {
    const [h, m] = hhmm.split(':').map(Number);
    return h * 60 + m;
}
function inSession(tsMs, startMin, endMin) {
    const d = new Date(tsMs);
    const mod = d.getUTCHours() * 60 + d.getUTCMinutes();
    return startMin <= endMin
        ? (mod >= startMin && mod <= endMin)
        : (mod >= startMin || mod <= endMin);
}
function dateKeyUTC(tsMs) {
    const d = new Date(tsMs);
    return `${d.getUTCFullYear()}-${d.getUTCMonth()}-${d.getUTCDate()}`;
}

/* ─── Familias (para confluencia min_families) ─── */
const STRAT_FAMILY = {
    EMA_MOMENTUM:   'trend',
    PULLBACK_TREND: 'trend',
    KELTNER_BREAK:  'trend',
    MACD_CROSS:     'trend',
    SCALPER:        'trend',
    DONCHIAN_BREAK: 'structural',
    ORB:            'opening',
    VWAP_MR:        'mean',
    BB_MR:          'mean',
    RSI_REVERSAL:   'mean',
};

/* ═══════════════ STRATEGIES ═══════════════
   Cada strategy recibe (bar, prev, atr, ctx) y devuelve {direction, entry, sl, tp1, score} o null.
*/
const STRATEGIES = {

    /* ─── EMA_MOMENTUM ─── */
    EMA_MOMENTUM(bar, prev, atr, df, idx, cfg) {
        if (idx < 60) return null;
        const { c, o, h, l, ema9, ema21, ema50 } = bar;
        if ([atr, ema9, ema21, ema50].some(v => v == null) || atr <= 0) return null;

        const lookback = 5;
        const slopeBar = df[idx - lookback];
        if (!slopeBar || slopeBar.ema21 == null) return null;
        const slope = ema21 - slopeBar.ema21;
        const slopeAtr = slope / atr;

        let direction = null;
        if (ema9 > ema21 && ema21 > ema50 && slopeAtr > 0.05) direction = 'LONG';
        else if (ema9 < ema21 && ema21 < ema50 && slopeAtr < -0.05) direction = 'SHORT';
        else return null;

        let touched, bounced, distance;
        if (direction === 'LONG') {
            touched = l <= ema21 + 0.1 * atr;
            bounced = c > ema21;
            distance = c - ema21;
        } else {
            touched = h >= ema21 - 0.1 * atr;
            bounced = c < ema21;
            distance = ema21 - c;
        }
        if (!(touched && bounced)) return null;
        if (distance / atr > 0.5) return null;

        const recent = df.slice(Math.max(0, idx - 9), idx + 1);
        let sl, risk;
        if (direction === 'LONG') {
            const swingLow = Math.min(...recent.map(b => b.l));
            sl = Math.min(ema50 - 0.2 * atr, swingLow - 0.1 * atr);
            risk = c - sl;
        } else {
            const swingHigh = Math.max(...recent.map(b => b.h));
            sl = Math.max(ema50 + 0.2 * atr, swingHigh + 0.1 * atr);
            risk = sl - c;
        }
        if (risk <= 0) return null;
        const rrEff = Math.max(1.5, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const slopeStrength = Math.min(Math.abs(slopeAtr) * 4, 1);
        const pullPrec = 1 - Math.min(distance / (0.5 * atr), 1);
        const score = Math.max(0, Math.min(1, 0.35 + 0.4 * slopeStrength + 0.25 * pullPrec));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── PULLBACK_TREND ─── */
    PULLBACK_TREND(bar, prev, atr, df, idx, cfg) {
        if (idx < 60) return null;
        const { c, o, h, l, ema9, ema20, ema50 } = bar;
        if ([atr, ema9, ema20, ema50].some(v => v == null) || atr <= 0) return null;

        const rng = Math.max(h - l, 1e-12);
        const bodyPct = Math.abs(c - o) / rng;
        const macroDist = (c - ema50) / atr;

        let direction = null, sl, risk;
        if (macroDist > 0.2 && ema9 > ema20 && l <= ema20 + 0.3 * atr
            && c > o && c > ema20 && bodyPct >= 0.30) {
            direction = 'LONG';
            sl = l - 0.2 * atr;
            risk = c - sl;
        } else if (macroDist < -0.2 && ema9 < ema20 && h >= ema20 - 0.3 * atr
            && c < o && c < ema20 && bodyPct >= 0.30) {
            direction = 'SHORT';
            sl = h + 0.2 * atr;
            risk = sl - c;
        } else return null;

        if (risk <= 0) return null;
        const rrEff = Math.max(1.6, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const macroStr = Math.min(Math.abs(macroDist) / 1.5, 1);
        const bodyStr = Math.min(bodyPct / 0.7, 1);
        const pullPrec = 1 - Math.min(Math.abs(c - ema20) / (0.3 * atr), 1);
        const score = Math.max(0, Math.min(1, 0.30 + 0.30 * macroStr + 0.25 * bodyStr + 0.15 * pullPrec));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── DONCHIAN_BREAK ─── */
    DONCHIAN_BREAK(bar, prev, atr, df, idx, cfg) {
        if (idx < 70) return null;
        const { c, o, h, l, dc_up, dc_lo, dc_mid, ema50 } = bar;
        if ([atr, dc_up, dc_lo, dc_mid, ema50].some(v => v == null) || atr <= 0) return null;

        const atrSlice = df.slice(Math.max(0, idx - 49), idx + 1)
            .map(b => b.atr).filter(v => v != null);
        if (!atrSlice.length) return null;
        const atrAvg = atrSlice.reduce((s, v) => s + v, 0) / atrSlice.length;
        if (atrAvg <= 0 || atr / atrAvg < 0.5) return null;

        const rng = Math.max(h - l, 1e-12);
        const bodyPct = Math.abs(c - o) / rng;

        let direction = null, sl, risk, breakStr;
        if (c > dc_up && c > ema50 && c > o && bodyPct >= 0.40) {
            direction = 'LONG';
            sl = Math.max(dc_mid, c - 1.5 * atr);
            risk = c - sl;
            breakStr = (c - dc_up) / atr;
        } else if (c < dc_lo && c < ema50 && c < o && bodyPct >= 0.40) {
            direction = 'SHORT';
            sl = Math.min(dc_mid, c + 1.5 * atr);
            risk = sl - c;
            breakStr = (dc_lo - c) / atr;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(2.0, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;
        const bs = Math.max(0, Math.min(1, breakStr));
        const bds = Math.min(bodyPct / 0.8, 1);
        const vs = Math.min(atr / atrAvg / 1.5, 1);
        const score = Math.max(0, Math.min(1, 0.30 + 0.30 * bs + 0.25 * bds + 0.15 * vs));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── KELTNER_BREAK ─── */
    KELTNER_BREAK(bar, prev, atr, df, idx, cfg) {
        if (idx < 60) return null;
        const { c, o, h, l, kc_up, kc_lo, kc_mid, ema50, rsi } = bar;
        if ([atr, kc_up, kc_lo, kc_mid, ema50, rsi].some(v => v == null) || atr <= 0) return null;

        const rng = Math.max(h - l, 1e-12);
        const bodyPct = Math.abs(c - o) / rng;

        let direction = null, sl, risk;
        if (c > kc_up && rsi > 55 && c > ema50 && c > o && bodyPct >= 0.30) {
            direction = 'LONG'; sl = kc_mid; risk = c - sl;
        } else if (c < kc_lo && rsi < 45 && c < ema50 && c < o && bodyPct >= 0.30) {
            direction = 'SHORT'; sl = kc_mid; risk = sl - c;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(1.8, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const momentum = direction === 'LONG'
            ? Math.max(0, Math.min(1, (rsi - 50) / 50))
            : Math.max(0, Math.min(1, (50 - rsi) / 50));
        const bodyStr = Math.min(bodyPct / 0.7, 1);
        const score = Math.max(0, Math.min(1, 0.35 + 0.35 * momentum + 0.20 * bodyStr));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── MACD_CROSS ─── */
    MACD_CROSS(bar, prev, atr, df, idx, cfg) {
        if (idx < 40 || !prev) return null;
        const { c, macd, macd_sig, macd_hist, ema50 } = bar;
        const macdPrev = prev.macd, sigPrev = prev.macd_sig, histPrev = prev.macd_hist;
        if ([atr, macd, macd_sig, macd_hist, macdPrev, sigPrev, histPrev, ema50]
            .some(v => v == null) || atr <= 0) return null;

        const strength = Math.abs(macd - macd_sig) / atr;
        const longCross = macdPrev <= sigPrev && macd > macd_sig && histPrev <= 0 && macd_hist > 0;
        const shortCross = macdPrev >= sigPrev && macd < macd_sig && histPrev >= 0 && macd_hist < 0;

        let direction = null, sl, risk;
        if (longCross && c > ema50 && strength > 0.05) {
            direction = 'LONG';
            const recentLow = Math.min(...df.slice(Math.max(0, idx - 4), idx + 1).map(b => b.l));
            sl = recentLow - 0.2 * atr;
            risk = c - sl;
        } else if (shortCross && c < ema50 && strength > 0.05) {
            direction = 'SHORT';
            const recentHigh = Math.max(...df.slice(Math.max(0, idx - 4), idx + 1).map(b => b.h));
            sl = recentHigh + 0.2 * atr;
            risk = sl - c;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(1.5, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const cs = Math.min(strength / 0.3, 1);
        const hs = Math.min(Math.abs(macd_hist) / atr / 0.1, 1);
        const score = Math.max(0, Math.min(1, 0.35 + 0.35 * cs + 0.20 * hs));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── RSI_REVERSAL ─── */
    RSI_REVERSAL(bar, prev, atr, df, idx, cfg) {
        if (idx < 40 || !prev) return null;
        const { c, o, h, l, rsi, ema50 } = bar;
        const rsiPrev = prev.rsi;
        if ([atr, rsi, rsiPrev, ema50].some(v => v == null) || atr <= 0) return null;

        const body = Math.max(Math.abs(c - o), 1e-12);
        const upperWick = h - Math.max(c, o);
        const lowerWick = Math.min(c, o) - l;

        let direction = null, sl, risk, wickRatio;
        if (rsiPrev < 30 && rsi > 32 && c > o && (lowerWick / body) >= 1.5 && c < ema50) {
            direction = 'LONG';
            sl = l - 0.1 * atr;
            risk = c - sl;
            wickRatio = lowerWick / body;
        } else if (rsiPrev > 70 && rsi < 68 && c < o && (upperWick / body) >= 1.5 && c > ema50) {
            direction = 'SHORT';
            sl = h + 0.1 * atr;
            risk = sl - c;
            wickRatio = upperWick / body;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(1.5, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const wickScore = Math.max(0, Math.min(1, (wickRatio - 1.5) / 2 + 0.5));
        const rsiScore = Math.max(0, Math.min(1, direction === 'LONG'
            ? (30 - rsiPrev) / 10 + 0.5
            : (rsiPrev - 70) / 10 + 0.5));
        const score = Math.max(0, Math.min(1, 0.30 + 0.40 * wickScore + 0.20 * rsiScore));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── VWAP_MR ───  Paridad 1:1 con strategies/vwap_mr.py */
    VWAP_MR(bar, prev, atr, df, idx, cfg) {
        if (idx < 50) return null;
        const { c, o, h, l, vwap, ema9, ema50 } = bar;
        if ([atr, vwap].some(v => v == null) || atr <= 0) return null;

        const dev = c - vwap;
        const devAtr = dev / atr;

        // Filtro anti-trend: si EMAs muy separadas, no opera MR
        if (ema9 != null && ema50 != null) {
            const emaSpread = Math.abs(ema9 - ema50) / atr;
            if (emaSpread > 1.0) return null;
        }

        // Trigger: desviación >= 1.5 ATR del VWAP
        let direction = null, sl, risk;
        if (devAtr >= 1.5) {
            direction = 'SHORT';
            sl = h + 0.2 * atr;
            // Min SL = 0.5*ATR
            if ((sl - c) < 0.5 * atr) sl = c + 0.5 * atr;
            risk = sl - c;
        } else if (devAtr <= -1.5) {
            direction = 'LONG';
            sl = l - 0.2 * atr;
            if ((c - sl) < 0.5 * atr) sl = c - 0.5 * atr;
            risk = c - sl;
        } else return null;
        if (risk <= 0) return null;

        // TP1 = vuelta al VWAP (o respeta min RR)
        const naturalTp = vwap;
        const naturalRr = Math.abs(naturalTp - c) / risk;
        const rrEff = Math.max(naturalRr, Math.max(1.5, cfg.minRR));
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const extremity = Math.min(Math.abs(devAtr) / 3.0, 1);
        const score = Math.max(0, Math.min(1, 0.45 + 0.35 * extremity));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── BB_MR ─── */
    BB_MR(bar, prev, atr, df, idx, cfg) {
        if (idx < 40 || !prev) return null;
        const { c, o, h, l, bb_up, bb_lo, ema50, rsi } = bar;
        if ([atr, bb_up, bb_lo, ema50, rsi].some(v => v == null) || atr <= 0) return null;

        let direction = null, sl, risk;
        // Toca banda inferior y cierra dentro = posible reversion long
        if (l <= bb_lo && c > bb_lo && rsi < 35 && c > o) {
            direction = 'LONG'; sl = l - 0.15 * atr; risk = c - sl;
        } else if (h >= bb_up && c < bb_up && rsi > 65 && c < o) {
            direction = 'SHORT'; sl = h + 0.15 * atr; risk = sl - c;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(1.2, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const rsiScore = Math.min(Math.abs(rsi - 50) / 30, 1);
        const score = Math.max(0, Math.min(1, 0.35 + 0.40 * rsiScore));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── ORB ─── */
    ORB(bar, prev, atr, df, idx, cfg) {
        if (idx < 50) return null;
        const { c, o, h, l, or_up, or_lo } = bar;
        if ([atr, or_up, or_lo].some(v => v == null) || atr <= 0) return null;

        let direction = null, sl, risk;
        if (c > or_up && c > o) {
            direction = 'LONG'; sl = or_lo - 0.25 * atr; risk = c - sl;
        } else if (c < or_lo && c < o) {
            direction = 'SHORT'; sl = or_up + 0.25 * atr; risk = sl - c;
        } else return null;
        if (risk <= 0) return null;
        const rrEff = Math.max(1.5, cfg.minRR);
        const tp1 = direction === 'LONG' ? c + rrEff * risk : c - rrEff * risk;

        const breakStr = direction === 'LONG'
            ? Math.min((c - or_up) / atr, 1)
            : Math.min((or_lo - c) / atr, 1);
        const score = Math.max(0, Math.min(1, 0.45 + 0.40 * breakStr));
        return { direction, entry: c, sl, tp1, score, risk };
    },

    /* ─── SCALPER ─── */
    SCALPER(bar, prev, atr, df, idx, cfg) {
        if (idx < 50 || !prev) return null;
        const { c, o, h, l, ema9, ema21 } = bar;
        if ([atr, ema9, ema21].some(v => v == null) || atr <= 0 || c <= 0) return null;
        const relAtr = atr / c;
        if (relAtr < 0.0003) return null;
        const emaSepRel = Math.abs(ema9 - ema21) / c;
        if (emaSepRel < 0.0002) return null;

        const trendUp = ema9 > ema21;
        const trendDn = ema9 < ema21;
        const prevC = prev.c;

        let direction = null, sl, risk;
        // Pullback: precio cruza de vuelta la EMA9 en la dirección de tendencia
        if (trendUp && prevC < ema9 && c > ema9) {
            direction = 'LONG'; sl = c - 1.0 * atr; risk = c - sl;
        } else if (trendDn && prevC > ema9 && c < ema9) {
            direction = 'SHORT'; sl = c + 1.0 * atr; risk = sl - c;
        } else {
            // Continuación: precio entre EMA9 y EMA21
            const between = (c >= Math.min(ema9, ema21) && c <= Math.max(ema9, ema21));
            const distEma9 = Math.abs(c - ema9) / atr;
            if (between && distEma9 < 0.6) {
                if (trendUp) { direction = 'LONG'; sl = c - 1.0 * atr; risk = c - sl; }
                else if (trendDn) { direction = 'SHORT'; sl = c + 1.0 * atr; risk = sl - c; }
            }
        }
        if (!direction || risk <= 0) return null;
        const tp1 = direction === 'LONG' ? c + 0.85 * atr : c - 0.85 * atr;
        const score = 0.58;
        return { direction, entry: c, sl, tp1, score, risk };
    },
};

/* ─── Resolución de un trade — busca SL/TP en las siguientes velas ─── */
function resolveTrade(sig, futureBars, maxBars = 200) {
    const risk = Math.abs(sig.entry - sig.sl);
    if (risk <= 0) return { outcome: 'INVALID', barsHeld: 0, pnlR: 0 };
    const slice = futureBars.slice(0, maxBars);
    for (let i = 0; i < slice.length; i++) {
        const b = slice[i];
        if (sig.direction === 'LONG') {
            const hitSL = b.l <= sig.sl;
            const hitTP = b.h >= sig.tp1;
            if (hitSL) return { outcome: 'SL', barsHeld: i + 1, pnlR: -1.0 };
            if (hitTP) {
                const reward = Math.abs(sig.tp1 - sig.entry);
                return { outcome: 'TP', barsHeld: i + 1, pnlR: reward / risk };
            }
        } else {
            const hitSL = b.h >= sig.sl;
            const hitTP = b.l <= sig.tp1;
            if (hitSL) return { outcome: 'SL', barsHeld: i + 1, pnlR: -1.0 };
            if (hitTP) {
                const reward = Math.abs(sig.tp1 - sig.entry);
                return { outcome: 'TP', barsHeld: i + 1, pnlR: reward / risk };
            }
        }
    }
    const lastClose = slice.length ? slice[slice.length - 1].c : sig.entry;
    const pnlPts = sig.direction === 'LONG' ? (lastClose - sig.entry) : (sig.entry - lastClose);
    return { outcome: 'TIMEOUT', barsHeld: slice.length, pnlR: pnlPts / risk };
}

/* ─── Confluence filter (min_signals + min_families + min_combined_score) ─── */
function applyConfluence(sigs, cfg) {
    if (!sigs.length) return null;
    // Filtrar a la misma dirección dominante
    const long = sigs.filter(s => s.direction === 'LONG');
    const short = sigs.filter(s => s.direction === 'SHORT');
    const winners = long.length > short.length ? long
        : short.length > long.length ? short : [];
    if (!winners.length) return null;
    const minSig = cfg.confluence?.min_signals ?? 2;
    const minFam = cfg.confluence?.min_families ?? 2;
    const minScore = cfg.confluence?.min_combined_score ?? 1.0;

    if (winners.length < minSig) return null;
    const families = new Set(winners.map(s => STRAT_FAMILY[s.strategy] || 'other'));
    if (families.size < minFam) return null;
    const combinedScore = winners.reduce((s, x) => s + x.score, 0);
    if (combinedScore < minScore) return null;

    // Elegir la de mejor score
    return winners.reduce((best, x) => (x.score > best.score ? x : best), winners[0]);
}

/* ─── Métricas ─── */
function computeMetrics(trades, symbolName, tf, profile) {
    if (!trades.length) {
        return {
            symbol: symbolName, timeframe: tf, profile,
            trades: 0, note: 'Sin trades en el rango seleccionado.',
            trade_log: [], equity_curve: [],
        };
    }
    const returns = trades.map(t => t.pnl_r);
    const wins = returns.filter(r => r > 0);
    const losses = returns.filter(r => r < 0);
    const grossWin = wins.reduce((s, x) => s + x, 0);
    const grossLoss = -losses.reduce((s, x) => s + x, 0);
    const expectancy = returns.reduce((s, x) => s + x, 0) / returns.length;
    const mean = expectancy;
    const variance = returns.reduce((s, x) => s + (x - mean) ** 2, 0) / Math.max(returns.length - 1, 1);
    const sd = Math.sqrt(variance);
    const sharpe = sd > 0 ? (mean / sd) * Math.sqrt(252) : 0;
    let downSd = 0;
    if (losses.length >= 2) {
        const m = losses.reduce((s, x) => s + x, 0) / losses.length;
        const v = losses.reduce((s, x) => s + (x - m) ** 2, 0) / Math.max(losses.length - 1, 1);
        downSd = Math.sqrt(v);
    }
    const sortino = downSd > 0 ? (mean / downSd) * Math.sqrt(252) : 0;
    const sqn = sd > 0 ? Math.sqrt(returns.length) * mean / sd : 0;

    let cum = 0, peak = 0, maxDd = 0;
    const equity = trades.map(t => {
        cum += t.pnl_r;
        peak = Math.max(peak, cum);
        maxDd = Math.max(maxDd, peak - cum);
        return { time: t.time, cum_r: cum };
    });

    let curW = 0, curL = 0, longW = 0, longL = 0;
    returns.forEach(r => {
        if (r > 0) { curW++; longW = Math.max(longW, curW); curL = 0; }
        else if (r < 0) { curL++; longL = Math.max(longL, curL); curW = 0; }
    });

    const byStrat = {};
    trades.forEach(t => {
        const k = t.strategy;
        if (!byStrat[k]) byStrat[k] = { trades: 0, total_r: 0 };
        byStrat[k].trades++;
        byStrat[k].total_r += t.pnl_r;
    });
    Object.values(byStrat).forEach(v => {
        v.expectancy_r = +(v.total_r / v.trades).toFixed(4);
        v.total_r = +v.total_r.toFixed(4);
    });

    const ts = trades.map(t => new Date(t.time).getTime());
    const spanDays = (Math.max(...ts) - Math.min(...ts)) / 86400000;
    const tradesPerWeek = spanDays > 0 ? (trades.length / (spanDays / 7)) : trades.length;

    return {
        symbol: symbolName, timeframe: tf, profile,
        trades: trades.length,
        wins: wins.length,
        losses: losses.length,
        win_rate: +(wins.length / trades.length).toFixed(4),
        profit_factor: grossLoss > 0 ? +(grossWin / grossLoss).toFixed(3) : (grossWin > 0 ? Infinity : 0),
        expectancy_r: +expectancy.toFixed(4),
        sharpe_ratio: +sharpe.toFixed(3),
        sortino_ratio: +sortino.toFixed(3),
        sqn: +sqn.toFixed(3),
        max_drawdown_r: +maxDd.toFixed(3),
        avg_win_r: wins.length ? +(grossWin / wins.length).toFixed(4) : 0,
        avg_loss_r: losses.length ? +(-grossLoss / losses.length).toFixed(4) : 0,
        longest_win_streak: longW,
        longest_loss_streak: longL,
        trades_per_week_avg: +tradesPerWeek.toFixed(2),
        by_strategy: byStrat,
        trade_log: trades.map(t => ({
            time: t.time,
            strategy: t.strategy,
            direction: t.direction,
            entry: t.entry,
            sl: t.sl,
            tp1: t.tp1,
            rr_planned: t.rr_planned,
            score: t.score,
            outcome: t.outcome,
            bars_held: t.bars_held,
            pnl_r: +t.pnl_r.toFixed(4),
        })),
        equity_curve: equity,
    };
}

/* ═══════════════ runBacktest — entry point ═══════════════ */
function runBacktest(options) {
    const { ohlc, strategies, confluence, minRR, maxTradesDay, fromTs, toTs } = options;
    const cols = ohlc.columns;
    const bars = ohlc.rows.map(row => rowToBar(row, cols));

    // Recortar por rango temporal
    const filtered = bars.filter(b => {
        if (fromTs && b.t < fromTs) return false;
        if (toTs && b.t > toTs) return false;
        return true;
    });
    if (filtered.length < 100) {
        return computeMetrics([], ohlc.symbol, ohlc.timeframe, ohlc.profile || 'balanced');
    }

    const sessStart = hhmmToMin(ohlc.session.start);
    const sessEnd = hhmmToMin(ohlc.session.end);
    const cfg = { minRR, confluence };

    const trades = [];
    const tradesByDay = {};
    const warmup = 100;

    for (let i = warmup; i < filtered.length - 1; i++) {
        const bar = filtered[i];
        const prev = filtered[i - 1];
        const atr = bar.atr;

        // Cada strategy emite señal o null
        const sigs = [];
        for (const stratName of strategies) {
            const fn = STRATEGIES[stratName];
            if (!fn) continue;
            try {
                const s = fn(bar, prev, atr, filtered, i, cfg);
                if (s) sigs.push({ ...s, strategy: stratName });
            } catch (e) {
                /* skip */
            }
        }
        if (!sigs.length) continue;

        const chosen = applyConfluence(sigs, cfg);
        if (!chosen) continue;

        // Filtro sesión
        if (!inSession(bar.t, sessStart, sessEnd)) continue;

        // Filtro RR
        const rr = Math.abs(chosen.tp1 - chosen.entry) / Math.abs(chosen.entry - chosen.sl);
        if (rr < minRR) continue;

        // Cap diario
        const dk = dateKeyUTC(bar.t);
        if ((tradesByDay[dk] || 0) >= maxTradesDay) continue;
        tradesByDay[dk] = (tradesByDay[dk] || 0) + 1;

        // Resolver trade en las próximas 250 velas
        const future = filtered.slice(i + 1, i + 251);
        if (!future.length) break;
        const outcome = resolveTrade(chosen, future);

        trades.push({
            time: new Date(bar.t).toISOString(),
            strategy: chosen.strategy,
            direction: chosen.direction,
            entry: chosen.entry,
            sl: chosen.sl,
            tp1: chosen.tp1,
            rr_planned: rr,
            score: chosen.score,
            outcome: outcome.outcome,
            bars_held: outcome.barsHeld,
            pnl_r: outcome.pnlR,
        });
    }

    return computeMetrics(trades, ohlc.symbol, ohlc.timeframe, ohlc.profile || 'balanced');
}

/* Export al global window para que app.js lo use */
window.TriarchBT = { runBacktest, STRATEGIES, STRAT_FAMILY };
