"""
Triarch — exporta OHLC + indicadores precalculados a JSON compacto.

Genera un archivo JSON por activo en `data/ohlc/{symbol}.json` (raíz, donde
GitHub Pages lo sirve) con un formato deliberadamente compacto para que el
backtester de JavaScript en el browser pueda cargarlo rápido.

Formato del JSON:
{
  "symbol": "EURUSD",
  "timeframe": "M5",
  "session": {"start": "06:30", "end": "17:00"},
  "min_rr": 0.8,
  "strategies": ["SCALPER", "BB_MR", ...],
  "columns": ["t","o","h","l","c","ema9","ema20","ema21","ema50","ema200",
              "atr","rsi","bb_up","bb_lo","kc_up","kc_mid","kc_lo",
              "dc_up","dc_lo","dc_mid","macd","macd_sig","macd_hist","vwap"],
  "rows": [
      [unix_ms, o, h, l, c, ema9, ema20, ..., vwap],
      ...
  ]
}

Por qué precalcular indicadores en Python:
  · El motor JS no tiene que portar pandas/numpy.
  · Es ~10x más rápido cargar números ya calculados que recalcular en JS.
  · Garantiza paridad con el backtest Python (mismos números → mismos trades).

Uso:
    python -m scripts.export_ohlc                       # los 3 activos
    python -m scripts.export_ohlc --symbol EURUSD
    python -m scripts.export_ohlc --years 2             # recorta a los últimos 2 años

Una vez generados, el frontend estático puede correr backtests en cualquier
rango temporal sin volver a tocar Python. Cada vez que se descargue histórico
nuevo: corre este script + git push.
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import REPO_ROOT, get_settings, get_symbols
from engine.indicators import add_default_indicators, opening_range

HISTORY_DIR = REPO_ROOT / "data_cache" / "history"
DEFAULT_OUT_DIR = REPO_ROOT / "data" / "ohlc"
MIRROR_OUT_DIR = REPO_ROOT / "docs" / "data" / "ohlc"


def _clean_number(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    # Recortar a 6 decimales — suficiente para precios y reduce tamaño JSON.
    return round(f, 6)


COLS = [
    "t", "o", "h", "l", "c",
    "ema9", "ema20", "ema21", "ema50", "ema200",
    "atr", "rsi",
    "bb_up", "bb_lo",
    "kc_up", "kc_mid", "kc_lo",
    "dc_up", "dc_lo", "dc_mid",
    "macd", "macd_sig", "macd_hist",
    "vwap",
    "or_up", "or_lo",
]

PARQUET_TO_KEY = {
    "time": "t", "open": "o", "high": "h", "low": "l", "close": "c",
    "ema_9": "ema9", "ema_20": "ema20", "ema_21": "ema21",
    "ema_50": "ema50", "ema_200": "ema200",
    "atr_14": "atr", "rsi_14": "rsi",
    "bb_upper": "bb_up", "bb_lower": "bb_lo",
    "kc_upper": "kc_up", "kc_mid": "kc_mid", "kc_lower": "kc_lo",
    "dc_upper": "dc_up", "dc_lower": "dc_lo", "dc_mid": "dc_mid",
    "macd": "macd", "macd_signal": "macd_sig", "macd_hist": "macd_hist",
    "vwap": "vwap",
    "or_high": "or_up", "or_low": "or_lo",
}


def export_symbol(name: str, years: int | None = None) -> Path | None:
    symbols = get_symbols()
    if name not in symbols:
        logger.error(f"Symbol no conocido: {name}. Disponibles: {list(symbols)}")
        return None
    cfg = symbols[name]

    parquet_path = HISTORY_DIR / f"{cfg.name}_{cfg.timeframe}.parquet"
    if not parquet_path.exists():
        logger.error(
            f"No hay histórico en {parquet_path.name}. Corre scripts.fetch_history primero."
        )
        return None

    df = pd.read_parquet(parquet_path).sort_values("time").reset_index(drop=True)
    if years is not None and years > 0:
        cutoff = datetime.now(timezone.utc) - timedelta(days=365 * years)
        df = df[df["time"] >= pd.Timestamp(cutoff)].reset_index(drop=True)
    if df.empty:
        logger.error(f"{name}: histórico vacío tras filtros.")
        return None

    logger.info(f"▶  Exportando {name} {cfg.timeframe} — {len(df)} velas")

    df = add_default_indicators(df)
    df = opening_range(df, minutes=15).reset_index(drop=True)

    rows: list[list] = []
    for _, r in df.iterrows():
        # Timestamp en milisegundos epoch UTC (lo que espera JS Date)
        t_ms = int(pd.Timestamp(r["time"]).tz_localize(None).value // 1_000_000) \
            if pd.Timestamp(r["time"]).tz is None \
            else int(pd.Timestamp(r["time"]).value // 1_000_000)
        row = [t_ms]
        for col_key in COLS[1:]:
            # Buscar la columna original que mapea a este key
            origin = None
            for parquet_col, key in PARQUET_TO_KEY.items():
                if key == col_key:
                    origin = parquet_col
                    break
            if origin is None or origin not in df.columns:
                row.append(None)
            else:
                row.append(_clean_number(r[origin]))
        rows.append(row)

    payload = {
        "symbol": cfg.name,
        "timeframe": cfg.timeframe,
        "session": {
            "start": cfg.session_utc.start,
            "end": cfg.session_utc.end,
        },
        "min_rr": cfg.risk.min_rr_ratio,
        "max_trades_per_day": cfg.risk.max_trades_per_day,
        "strategies": list(cfg.strategies),
        "confluence": {
            "min_signals": cfg.confluence.min_signals if cfg.confluence else 2,
            "min_families": cfg.confluence.min_families if cfg.confluence else 2,
            "min_combined_score": cfg.confluence.min_combined_score if cfg.confluence else 0.0,
        },
        "from": rows[0][0] if rows else None,
        "to": rows[-1][0] if rows else None,
        "columns": COLS,
        "rows": rows,
    }

    out_path = DEFAULT_OUT_DIR / f"{cfg.name}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # JSON compacto sin indentación → reduce ~30% el tamaño.
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    out_path.write_text(body, encoding="utf-8")

    # Mirror a /docs/data/ohlc/ por consistencia con export_web.
    try:
        MIRROR_OUT_DIR.mkdir(parents=True, exist_ok=True)
        (MIRROR_OUT_DIR / f"{cfg.name}.json").write_text(body, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[export_ohlc] No se pudo escribir mirror /docs: {exc}")

    size_mb = out_path.stat().st_size / 1_048_576
    logger.info(
        f"   ✔  {out_path}  ·  {len(rows)} velas  ·  {size_mb:.2f} MB"
    )
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporta OHLC + indicadores precalculados a JSON para el backtester JS."
    )
    parser.add_argument("--symbol", help="Un solo activo (default: todos).")
    parser.add_argument("--years", type=int, default=None,
                        help="Recortar a los últimos N años (default: todo el histórico).")
    args = parser.parse_args()

    settings = get_settings()
    logger.add(settings.log_file, rotation="50 MB", level=settings.log_level)

    symbols = get_symbols()
    targets = [args.symbol] if args.symbol else list(symbols.keys())

    written = []
    for sym in targets:
        out = export_symbol(sym, years=args.years)
        if out:
            written.append(out)

    # Manifest — la web lo lee para saber qué activos están disponibles
    if written:
        manifest = {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "symbols": [p.stem for p in written],
        }
        man_path = DEFAULT_OUT_DIR / "manifest.json"
        man_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        try:
            MIRROR_OUT_DIR.mkdir(parents=True, exist_ok=True)
            (MIRROR_OUT_DIR / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception:
            pass
        logger.info(f"[export_ohlc] Manifest escrito: {man_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
