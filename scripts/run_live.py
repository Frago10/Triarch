"""
Loop principal del bot Triarch.

Uso:
    python -m scripts.run_live              # tick cada 60s (default)
    python -m scripts.run_live --tick 30    # tick cada 30s (recomendado)
    python -m scripts.run_live --once       # UN solo tick y sale (diagnóstico)

Ctrl+C para detener (cierra MT5 limpio).

IMPORTANTE — el bot SOLO emite/ejecuta mientras este proceso está VIVO.
Si lo cierras (o la máquina se suspende, o cierras el terminal MT5), NO hay
señales. Para una prueba seria, dejá esta ventana abierta y la máquina sin
suspender durante la sesión de mercado.
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from config.runtime import get_take_trades
from config.settings import ExecutionMode, get_settings, get_symbols
from data_layer.mt5_client import MT5Client
from engine.orchestrator import Orchestrator


def _print_startup_summary(settings, symbols) -> None:
    logger.info("─" * 60)
    logger.info("TRIARCH — resumen de arranque")
    logger.info(f"  Entorno: {settings.triarch_env.value}   Kill switch: {bool(settings.triarch_kill)}")
    for name, cfg in symbols.items():
        live = get_take_trades(name, default=cfg.take_trades)
        eff = cfg.mode.value if live else "SIGNAL_ONLY (forzado)"
        flag = "🟢 EJECUTA ÓRDENES" if (live and cfg.mode is ExecutionMode.AUTO) else "· solo señal"
        logger.info(
            f"  {name:7} {cfg.timeframe:4} sesión {cfg.session_utc.start}-{cfg.session_utc.end} UTC "
            f"· modo efectivo: {eff:22} {flag}"
        )
    logger.info("─" * 60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick", type=int, default=60, help="Segundos entre ticks")
    parser.add_argument("--once", action="store_true", help="Un solo tick y salir (diagnóstico)")
    args = parser.parse_args()

    settings = get_settings()
    symbols = get_symbols()
    logger.add(settings.log_file, rotation="50 MB", level=settings.log_level)

    client = MT5Client()
    if not client.initialize():
        logger.error("No se pudo conectar a MT5. Revisa .env y corre: python -m scripts.diagnose_mt5")
        return 1

    orch = Orchestrator(client, settings)
    _print_startup_summary(settings, symbols)

    if args.once:
        logger.info("Modo --once: ejecutando UN tick…")
        orch.tick()
        logger.info("Tick único completado. Revisa arriba qué velas/setups se evaluaron.")
        client.shutdown()
        return 0

    logger.info(f"Triarch live loop iniciado — tick cada {args.tick}s. Ctrl+C para parar.")

    consecutive_disconnects = 0
    try:
        while True:
            # ─── Auto-reconexión si MT5 se cae (suspensión, red, etc.) ───
            if client.account_info() is None:
                consecutive_disconnects += 1
                logger.warning(
                    f"MT5 desconectado (x{consecutive_disconnects}). Reintentando initialize()…"
                )
                try:
                    client.shutdown()
                except Exception:  # noqa: BLE001
                    pass
                if client.initialize():
                    logger.success("Reconectado a MT5.")
                    consecutive_disconnects = 0
                else:
                    # backoff: espera más si sigue cayendo
                    time.sleep(min(args.tick * consecutive_disconnects, 300))
                    continue
            else:
                consecutive_disconnects = 0

            orch.tick()
            time.sleep(args.tick)
    except KeyboardInterrupt:
        logger.info("Detenido por usuario.")
    finally:
        client.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
