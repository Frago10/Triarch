"""
Triarch — pipeline único para refrescar el sitio estático.

Equivale a correr a mano:
    python -m scripts.fetch_history       (opcional con --refresh)
    python -m scripts.backtest --out data_cache/backtest_last.json
    python -m scripts.export_ohlc
    python -m scripts.export_web

Uso típico (flujo recomendado tras cambios en strats o config):
    python -m scripts.refresh_web
        → genera OHLC + state.json y deja todo listo para git push.

    python -m scripts.refresh_web --fetch    (también baja histórico nuevo)

    python -m scripts.refresh_web --skip-backtest   (más rápido, solo exports)

Lo que hace cada paso:
  1. (opcional)  fetch_history   — descarga velas frescas desde MT5.
  2. (opcional)  backtest        — corre los 3 activos sobre el histórico
                                   y guarda data_cache/backtest_last.json,
                                   que el frontend muestra como "snapshot".
  3.             export_ohlc     — vuelca OHLC + indicadores a data/ohlc/.
                                   Esto es lo que permite que la web corra
                                   backtests interactivos en cualquier rango.
  4.             export_web      — vuelca audit trail (signals/evals/account)
                                   a data/state.json para el dashboard.

Tras correr este script:
    git add data/ docs/
    git commit -m "data: refresh OHLC + state"
    git push
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKTEST_OUT = REPO_ROOT / "data_cache" / "backtest_last.json"


def step_fetch(years: int) -> bool:
    try:
        from scripts.fetch_history import main as fh_main
    except ImportError as exc:
        logger.error(f"[refresh_web] No se pudo importar fetch_history: {exc}")
        return False
    logger.info(f"▶  fetch_history --years {years}")
    old_argv = sys.argv
    sys.argv = ["fetch_history", "--years", str(years)]
    try:
        rc = fh_main()
        return rc == 0
    except SystemExit as e:
        return (e.code or 0) == 0
    except Exception as exc:  # noqa: BLE001
        logger.error(f"[refresh_web] fetch_history falló: {exc}")
        return False
    finally:
        sys.argv = old_argv


def step_backtest() -> bool:
    try:
        from config.settings import get_settings, get_symbols
        from scripts.backtest import backtest_symbol
    except ImportError as exc:
        logger.error(f"[refresh_web] No se pudo importar backtest: {exc}")
        return False

    settings = get_settings()
    symbols = get_symbols()
    results = []
    for name, cfg in symbols.items():
        logger.info(f"▶  backtest {name} {cfg.timeframe}")
        try:
            res = backtest_symbol(cfg, settings)
            results.append(res)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"[refresh_web] backtest {name} explotó: {exc}")
            results.append({"symbol": name, "error": str(exc)})

    BACKTEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    BACKTEST_OUT.write_text(
        json.dumps(results, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(f"   ✔  {BACKTEST_OUT}")
    return True


def step_export_ohlc(years: int | None) -> bool:
    try:
        from scripts.export_ohlc import export_symbol
        from config.settings import get_symbols
    except ImportError as exc:
        logger.error(f"[refresh_web] No se pudo importar export_ohlc: {exc}")
        return False
    syms = list(get_symbols().keys())
    written = []
    for s in syms:
        out = export_symbol(s, years=years)
        if out:
            written.append(out)
    if not written:
        logger.warning("[refresh_web] export_ohlc: ningún archivo generado.")
        return False
    # Manifest
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "symbols": [p.stem for p in written],
    }
    for base in [REPO_ROOT / "data" / "ohlc", REPO_ROOT / "docs" / "data" / "ohlc"]:
        try:
            base.mkdir(parents=True, exist_ok=True)
            (base / "manifest.json").write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[refresh_web] manifest en {base} falló: {exc}")
    return True


def step_export_web() -> bool:
    try:
        from scripts.export_web import export_state
    except ImportError as exc:
        logger.error(f"[refresh_web] No se pudo importar export_web: {exc}")
        return False
    export_state(include_mt5=False)   # estado sin MT5 (account = None) para el sitio público
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Refresca todo el sitio estático del Triarch.")
    parser.add_argument("--fetch", action="store_true",
                        help="También baja histórico fresco desde MT5.")
    parser.add_argument("--years", type=int, default=2,
                        help="Años de histórico (default 2).")
    parser.add_argument("--skip-backtest", action="store_true",
                        help="No re-correr el backtest snapshot (más rápido).")
    parser.add_argument("--skip-ohlc", action="store_true",
                        help="No re-exportar OHLC (rara vez útil).")
    args = parser.parse_args()

    if args.fetch:
        if not step_fetch(args.years):
            logger.warning("[refresh_web] fetch_history falló; continuando con la caché existente.")

    if not args.skip_backtest:
        step_backtest()
    else:
        logger.info("[refresh_web] skip backtest snapshot")

    if not args.skip_ohlc:
        step_export_ohlc(years=args.years)
    else:
        logger.info("[refresh_web] skip export_ohlc")

    step_export_web()

    logger.info("[refresh_web] HECHO. Siguiente paso:")
    logger.info("    git add data/ docs/")
    logger.info("    git commit -m 'data: refresh OHLC + state'")
    logger.info("    git push")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
