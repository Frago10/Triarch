"""
Triarch — descargador de histórico desde MT5.

Guarda las velas como parquet en `data_cache/history/{symbol}_{timeframe}.parquet`.
Permite acumular múltiples descargas (concatena y deduplica).

Uso:
    # Todos los activos de symbols.yaml, último año
    python -m scripts.fetch_history --years 1

    # Activo específico con ventana custom
    python -m scripts.fetch_history --symbol XAUUSD --timeframe M30 --from 2024-01-01

    # Sobreescribe TF del yaml
    python -m scripts.fetch_history --symbol EURUSD --timeframe M5 --years 2
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from loguru import logger

from config.settings import REPO_ROOT, get_symbols
from data_layer.mt5_client import MT5Client

HISTORY_DIR = REPO_ROOT / "data_cache" / "history"


def _parquet_path(symbol: str, timeframe: str) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    return HISTORY_DIR / f"{symbol}_{timeframe}.parquet"


def _suggest_symbols(client: MT5Client, broker_symbol: str) -> list[str]:
    """Busca en MT5 símbolos parecidos al pedido (mismo prefijo de 3 letras)."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except ImportError:
        return []
    all_syms = mt5.symbols_get()
    if not all_syms:
        return []
    prefix = broker_symbol[:3].upper()
    matches = [s.name for s in all_syms if prefix in s.name.upper()]
    return sorted(matches)[:15]


def fetch_one(
    client: MT5Client,
    name: str,
    broker_symbol: str,
    timeframe: str,
    from_date: datetime,
) -> int:
    """Descarga velas y mergea con cualquier histórico previo. Devuelve filas guardadas."""
    logger.info(f"⏬  {name} ({broker_symbol}) {timeframe} desde {from_date.date()} …")
    df = client.get_rates(
        broker_symbol=broker_symbol,
        timeframe=timeframe,
        from_date=from_date,
    )
    if df.empty:
        logger.warning(
            f"   ❌ {name}: MT5 devolvió 0 velas para '{broker_symbol}' {timeframe}."
        )
        suggestions = _suggest_symbols(client, broker_symbol)
        if suggestions and broker_symbol not in suggestions:
            # El símbolo NO existe con ese nombre exacto → problema de nombre.
            logger.warning(
                f"   💡 '{broker_symbol}' no existe, pero sí estos parecidos: {suggestions}\n"
                f"      → Edita 'broker_symbol' de {name} en config/symbols.yaml."
            )
        else:
            # El símbolo SÍ existe (o no se pudo verificar) → es history no bajado.
            # Típico en M5 + rangos largos: el terminal no tiene la caché.
            logger.warning(
                f"   💡 El símbolo parece existir, pero el terminal no tiene el "
                f"histórico {timeframe} bajado todavía.\n"
                f"      SOLUCIÓN: en MT5 abre el gráfico de {broker_symbol} en {timeframe}, "
                f"haz scroll hacia atrás\n"
                f"      hasta cargar el rango que quieres, y vuelve a correr este script.\n"
                f"      Es INCREMENTAL: cada pasada baja más histórico. También puedes\n"
                f"      probar un rango más corto (--years 1 en vez de 2)."
            )
        return 0

    df = df.sort_values("time").reset_index(drop=True)
    df["symbol"] = name
    df["timeframe"] = timeframe

    path = _parquet_path(name, timeframe)
    if path.exists():
        try:
            prev = pd.read_parquet(path)
            merged = pd.concat([prev, df], ignore_index=True)
            merged = merged.drop_duplicates(subset=["time"]).sort_values("time")
            merged = merged.reset_index(drop=True)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"   {name}: no se pudo mergear ({exc}); sobreescribo.")
            merged = df
    else:
        merged = df

    merged.to_parquet(path, index=False)
    logger.info(
        f"   {name}: {len(df)} velas nuevas — total {len(merged)} → {path.name}"
    )
    return len(df)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triarch — bajar histórico MT5 a parquet"
    )
    parser.add_argument(
        "--symbol", help="Símbolo único (default: todos los de symbols.yaml)"
    )
    parser.add_argument(
        "--timeframe",
        help="Override del TF (default: el del yaml por activo)",
    )
    parser.add_argument(
        "--years", type=int, default=1, help="Rango hacia atrás en años (default 1)"
    )
    parser.add_argument(
        "--from", dest="from_date", help="Fecha ISO YYYY-MM-DD (override de --years)"
    )
    args = parser.parse_args()

    if args.from_date:
        from_date = datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
    else:
        from_date = datetime.now(timezone.utc) - timedelta(days=365 * args.years)

    symbols = get_symbols()
    targets = {args.symbol: symbols[args.symbol]} if args.symbol else symbols
    if args.symbol and args.symbol not in symbols:
        logger.error(f"Símbolo {args.symbol} no está en symbols.yaml")
        return 1

    client = MT5Client()
    if not client.initialize():
        logger.error(
            "No se pudo conectar a MT5. Revisa .env y que el terminal esté abierto."
        )
        return 1

    total = 0
    ok_syms: list[str] = []
    fail_syms: list[str] = []
    try:
        for name, cfg in targets.items():
            tf = args.timeframe or cfg.timeframe
            n = fetch_one(client, name, cfg.broker_symbol, tf, from_date)
            total += n
            (ok_syms if n > 0 else fail_syms).append(name)
    finally:
        client.shutdown()

    logger.info("─" * 60)
    logger.info(f"Listo. Velas nuevas descargadas: {total}. Carpeta: {HISTORY_DIR}")
    if ok_syms:
        logger.info(f"✅ OK: {ok_syms}")
    if fail_syms:
        logger.warning(
            f"❌ Sin datos: {fail_syms}\n"
            f"   Dos causas posibles (ver detalle arriba por activo):\n"
            f"   1) broker_symbol incorrecto → corregir en symbols.yaml\n"
            f"   2) histórico no bajado en el terminal → abrir el gráfico, hacer\n"
            f"      scroll atrás, y RE-CORRER este script (es incremental)."
        )
    return 0 if not fail_syms else 2


if __name__ == "__main__":
    raise SystemExit(main())
