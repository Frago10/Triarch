"""
Triarch — exporta el estado actual del bot a JSON estático para el front-end web.

Genera el archivo `docs/data/state.json` que el dashboard estático
(`docs/index.html`, servido desde GitHub Pages) consume para renderizar
las 5 pestañas (Inicio · Vivo & Control · Decisiones · Backtesting · Datos)
sin necesidad de un backend en producción.

Qué exporta:
  · settings        — env, default_mode, conf_min_*, kill switch
  · account         — info MT5 (balance, equity, margin, leverage, login, server)
                      → si MT5 no está conectado, se omite y la web lo indica.
  · symbols         — config de cada activo + estado live de take_trades
  · signals         — últimas N señales del audit trail (default 1000)
  · evals           — últimas N evaluaciones (default 500)
  · backtest_results — si existe `data_cache/backtest_last.json`, se incluye

Uso:
    python -m scripts.export_web
    python -m scripts.export_web --signals-limit 2000 --out docs/data/state.json
    python -m scripts.export_web --no-mt5     # omite la conexión MT5 (solo SQLite)

Flujo recomendado para GitHub Pages:
    1. python -m scripts.fetch_history --years 1     (una vez)
    2. python -m scripts.backtest --out data_cache/backtest_last.json
    3. python -m scripts.export_web
    4. git add docs/ && git commit -m "chore: refresh dashboard data" && git push
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from loguru import logger

from audit.store import AuditStore
from config.runtime import get_take_trades
from config.settings import get_settings, get_symbols

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "data" / "state.json"
BACKTEST_CACHE = REPO_ROOT / "data_cache" / "backtest_last.json"


def _clean(v):
    """Convierte NaN/Inf a None y datetime a iso. JSON friendly."""
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        return v
    if isinstance(v, (datetime,)):
        return v.isoformat()
    return v


def _row(d: dict) -> dict:
    return {k: _clean(v) for k, v in d.items()}


def export_state(
    signals_limit: int = 1000,
    evals_limit: int = 500,
    include_mt5: bool = True,
    out_path: Path = DEFAULT_OUT,
) -> dict:
    settings = get_settings()
    symbols = get_symbols()
    store = AuditStore()

    # ─── account info (opcional) ───
    account: dict | None = None
    if include_mt5:
        try:
            from data_layer.mt5_client import MT5_AVAILABLE, MT5Client
            if MT5_AVAILABLE:
                client = MT5Client()
                if client.initialize():
                    info = client.account_info()
                    if info is not None:
                        account = {
                            "login": info.login,
                            "server": info.server,
                            "name": info.name,
                            "currency": info.currency,
                            "balance": info.balance,
                            "equity": info.equity,
                            "margin": info.margin,
                            "free_margin": info.free_margin,
                            "leverage": info.leverage,
                        }
                    client.shutdown()
                else:
                    logger.warning("[export_web] No se pudo inicializar MT5; export sin account.")
            else:
                logger.info("[export_web] MetaTrader5 no disponible (¿no estás en Windows?). Export sin account.")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[export_web] Error consultando MT5: {exc}. Export sin account.")

    # ─── symbols (config + take_trades live) ───
    symbols_out: dict[str, dict] = {}
    for name, cfg in symbols.items():
        symbols_out[name] = {
            "broker_symbol": cfg.broker_symbol,
            "description": cfg.description,
            "profile": cfg.profile,
            "timeframe": cfg.timeframe,
            "mode": cfg.mode.value,
            "take_trades": cfg.take_trades,
            "take_trades_live": get_take_trades(name, default=cfg.take_trades),
            "session_start": cfg.session_utc.start,
            "session_end": cfg.session_utc.end,
            "strategies": list(cfg.strategies),
            "family": cfg.family,
            "target_trades_wk": cfg.target_trades_wk,
        }

    # ─── signals ───
    raw_signals = store.list_signals(limit=signals_limit)
    signals_out = [_row(r) for r in raw_signals]

    # ─── evals ───
    raw_evals = store.list_evals(limit=evals_limit)
    evals_out = [_row(r) for r in raw_evals]

    # ─── backtest results (si existe el cache) ───
    backtest_results: list = []
    if BACKTEST_CACHE.exists():
        try:
            backtest_results = json.loads(BACKTEST_CACHE.read_text(encoding="utf-8"))
            if isinstance(backtest_results, dict) and "results" in backtest_results:
                backtest_results = backtest_results["results"]
            logger.info(f"[export_web] Backtest cache cargado: {BACKTEST_CACHE.name}")
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[export_web] No se pudo leer {BACKTEST_CACHE}: {exc}")

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "is_sample": False,
            "signals_count": len(signals_out),
            "evals_count": len(evals_out),
        },
        "settings": {
            "env": settings.triarch_env.value,
            "default_mode": settings.triarch_default_mode.value,
            "conf_min_signals": settings.triarch_confluence_min_signals,
            "conf_min_families": settings.triarch_confluence_min_families,
            "conf_min_score": settings.triarch_confluence_min_score,
            "kill": bool(settings.triarch_kill),
        },
        "account": account,
        "symbols": symbols_out,
        "signals": signals_out,
        "evals": evals_out,
        "backtest_results": backtest_results,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )
    logger.info(
        f"[export_web] Escrito {out_path}  ·  "
        f"{len(signals_out)} signals  ·  {len(evals_out)} evals  ·  "
        f"{len(backtest_results)} backtest results  ·  "
        f"account={'yes' if account else 'no'}"
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Exporta estado del bot a docs/data/state.json para el front-end estático."
    )
    parser.add_argument("--signals-limit", type=int, default=1000,
                        help="N máximo de signals a exportar (default 1000).")
    parser.add_argument("--evals-limit", type=int, default=500,
                        help="N máximo de evals a exportar (default 500).")
    parser.add_argument("--no-mt5", action="store_true",
                        help="No intentar conectar a MT5 (solo SQLite).")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"Ruta de salida (default {DEFAULT_OUT}).")
    args = parser.parse_args()

    settings = get_settings()
    logger.add(settings.log_file, rotation="50 MB", level=settings.log_level)

    export_state(
        signals_limit=args.signals_limit,
        evals_limit=args.evals_limit,
        include_mt5=not args.no_mt5,
        out_path=args.out,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
