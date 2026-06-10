"""
Triarch — sweep de calibración por activo.

Corre variantes de configuración (estrategias, sesión, time-stop, RR, caps)
sobre el histórico real y reporta métricas globales + validación walk-forward
(in-sample vs out-of-sample, split en --split, default 2026-02-01).

El split NO re-corre el backtest: divide el trade_log por fecha, que es
equivalente (los trades son independientes del punto de corte) y ~3x más rápido.

Uso:
    python -m scripts.sweep --symbol XAUUSD
    python -m scripts.sweep --symbol EURUSD --out logs/sweep_eur.txt
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from config.settings import get_settings, get_symbols

SPLIT_DEFAULT = "2026-02-01"

# ─────────────────────────────────────────────────────────
# Variantes por activo. Cada variante = nombre + dict de overrides anidados.
# `risk` y `confluence` se mergean campo a campo sobre la config del yaml.
# ─────────────────────────────────────────────────────────
VARIANTS: dict[str, list[tuple[str, dict]]] = {
    "NAS100": [
        ("A_base(actual)", {}),
        ("B_hold12(3h)", {"risk": {"max_hold_bars": 12}}),
        ("C_hold8(2h)", {"risk": {"max_hold_bars": 8}}),
        ("D_hold16(4h)", {"risk": {"max_hold_bars": 16}}),
        ("E_orb_hold12", {
            "risk": {"max_hold_bars": 12},
            "strategies": ["ORB", "DONCHIAN_BREAK", "PULLBACK_TREND",
                           "KELTNER_BREAK", "EMA_MOMENTUM", "VWAP_MR"],
        }),
        ("F_ses_cash_hold12", {
            "risk": {"max_hold_bars": 12},
            "session_utc": {"start": "13:30", "end": "17:00"},
        }),
    ],
    "XAUUSD": [
        # Ronda 2 — el hold corto en M30 mató el edge (PF<=1.10). Probar:
        #   · holds intermedios en M30 (6-8h, intradía pero con aire)
        #   · M15 con holds 1.5-3h (granularidad fina para trades cortos)
        ("A_base(actual)", {}),
        ("I_hold12(6h)", {"risk": {"max_hold_bars": 12}}),
        ("J_hold16(8h)", {"risk": {"max_hold_bars": 16}}),
        ("K_M15_hold8(2h)", {"timeframe": "M15", "risk": {"max_hold_bars": 8}}),
        ("L_M15_hold12(3h)", {"timeframe": "M15", "risk": {"max_hold_bars": 12}}),
        ("M_M15_hold8_rr1.8", {
            "timeframe": "M15",
            "risk": {"max_hold_bars": 8, "min_rr_ratio": 1.8},
        }),
        ("N_M15_hold8_cap2", {
            "timeframe": "M15",
            "risk": {"max_hold_bars": 8, "max_trades_per_day": 2},
        }),
    ],
    "EURUSD": [
        ("A_base(actual)", {}),
        ("B_hold18(1.5h)", {"risk": {"max_hold_bars": 18}}),
        ("C_noPullback_hold18", {
            "risk": {"max_hold_bars": 18},
            "strategies": ["EMA_MOMENTUM", "SCALPER", "MACD_CROSS",
                           "VWAP_MR", "RSI_REVERSAL"],
        }),
        ("D_meanBB_hold18", {
            "risk": {"max_hold_bars": 18},
            "strategies": ["EMA_MOMENTUM", "SCALPER", "MACD_CROSS",
                           "VWAP_MR", "RSI_REVERSAL", "BB_MR"],
        }),
        ("E_hold24(2h)", {"risk": {"max_hold_bars": 24}}),
    ],
}


def _apply_overrides(cfg, ov: dict):
    """model_copy con merge anidado para risk/confluence/session_utc."""
    update: dict = {}
    if "risk" in ov:
        update["risk"] = cfg.risk.model_copy(update=ov["risk"])
    if "confluence" in ov and cfg.confluence is not None:
        update["confluence"] = cfg.confluence.model_copy(update=ov["confluence"])
    if "session_utc" in ov:
        update["session_utc"] = cfg.session_utc.model_copy(update=ov["session_utc"])
    if "strategies" in ov:
        update["strategies"] = ov["strategies"]
    if "timeframe" in ov:
        update["timeframe"] = ov["timeframe"]
    return cfg.model_copy(update=update)


def _seg_metrics(trades: list[dict]) -> dict:
    """PF / expectancy / WR / total sobre un subconjunto del trade_log."""
    if not trades:
        return {"n": 0, "pf": 0.0, "e": 0.0, "wr": 0.0, "tot": 0.0}
    rets = [t["pnl_r"] for t in trades]
    gw = sum(r for r in rets if r > 0)
    gl = -sum(r for r in rets if r < 0)
    pf = gw / gl if gl > 0 else math.inf
    wr = sum(1 for r in rets if r > 0) / len(rets)
    return {
        "n": len(rets),
        "pf": round(pf, 2) if math.isfinite(pf) else 99.0,
        "e": round(sum(rets) / len(rets), 3),
        "wr": round(wr, 3),
        "tot": round(sum(rets), 1),
    }


def run_sweep(symbol: str, split_iso: str) -> list[dict]:
    from scripts.backtest import backtest_symbol

    settings = get_settings()
    cfg0 = get_symbols()[symbol]
    split = split_iso  # comparación lexicográfica sobre ISO strings funciona

    rows: list[dict] = []
    for name, ov in VARIANTS[symbol]:
        cfg = _apply_overrides(cfg0, ov)
        res = backtest_symbol(cfg, settings)
        if res.get("error") or not res.get("trades"):
            rows.append({"variant": name, "error": res.get("error", "0 trades")})
            logger.warning(f"  {name}: {res.get('error', '0 trades')}")
            continue
        log = res["trade_log"]
        is_seg = _seg_metrics([t for t in log if t["time"] < split])
        oos_seg = _seg_metrics([t for t in log if t["time"] >= split])
        rows.append({
            "variant": name,
            "trades": res["trades"],
            "wr": res["win_rate"],
            "pf": res["profit_factor"],
            "e": res["expectancy_r"],
            "dd": res["max_drawdown_r"],
            "tr_wk": res["trades_per_week_avg"],
            "bars": res["avg_bars_held"],
            "sharpe": res["sharpe_ratio"],
            "is": is_seg,
            "oos": oos_seg,
        })
        logger.info(
            f"  {name}: {res['trades']}tr WR{res['win_rate']:.0%} PF{res['profit_factor']:.2f} "
            f"E{res['expectancy_r']:+.3f} DD{res['max_drawdown_r']:.1f} bars{res['avg_bars_held']:.1f} "
            f"| IS PF{is_seg['pf']} OOS PF{oos_seg['pf']}"
        )
    return rows


def _fmt(rows: list[dict], symbol: str, split: str) -> str:
    out = [f"=== SWEEP {symbol} (split walk-forward: {split}) ==="]
    hdr = f"{'variant':<22} {'tr':>4} {'WR':>5} {'PF':>5} {'E(R)':>6} {'DD':>5} {'t/wk':>5} {'bars':>5} | {'IS_PF':>5} {'IS_n':>4} | {'OOS_PF':>6} {'OOS_n':>5}"
    out.append(hdr)
    out.append("-" * len(hdr))
    for r in rows:
        if "error" in r:
            out.append(f"{r['variant']:<22} ERROR: {r['error']}")
            continue
        out.append(
            f"{r['variant']:<22} {r['trades']:>4} {r['wr']:>5.0%} {r['pf']:>5.2f} "
            f"{r['e']:>+6.3f} {r['dd']:>5.1f} {r['tr_wk']:>5.1f} {r['bars']:>5.1f} | "
            f"{r['is']['pf']:>5.2f} {r['is']['n']:>4} | {r['oos']['pf']:>6.2f} {r['oos']['n']:>5}"
        )
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Sweep de calibración Triarch")
    parser.add_argument("--symbol", required=True, choices=list(VARIANTS.keys()))
    parser.add_argument("--split", default=SPLIT_DEFAULT)
    parser.add_argument("--out", help="Archivo de salida (txt o json)")
    args = parser.parse_args()

    rows = run_sweep(args.symbol, args.split)
    report = _fmt(rows, args.symbol, args.split)
    print(report)
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.suffix == ".json":
            p.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
        else:
            p.write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
