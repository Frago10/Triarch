"""
Loop principal del bot Triarch.

Uso:
    python -m scripts.run_live           # default: tick cada 60s
    python -m scripts.run_live --tick 30  # cada 30s

Ctrl+C para detener (cierra MT5 limpio).
"""

from __future__ import annotations

import argparse
import sys
import time

from loguru import logger

from config.settings import get_settings
from data_layer.mt5_client import MT5Client
from engine.orchestrator import Orchestrator


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tick", type=int, default=60, help="Segundos entre ticks")
    args = parser.parse_args()

    settings = get_settings()
    logger.add(settings.log_file, rotation="50 MB", level=settings.log_level)

    client = MT5Client()
    if not client.initialize():
        logger.error("No se pudo conectar a MT5. Revisa .env.")
        return 1

    orch = Orchestrator(client, settings)
    logger.info(f"Triarch live loop iniciado — tick cada {args.tick}s")
    logger.info(
        f"Modo default: {settings.triarch_default_mode.value}  Env: {settings.triarch_env.value}"
    )

    try:
        while True:
            orch.tick()
            time.sleep(args.tick)
    except KeyboardInterrupt:
        logger.info("Detenido por usuario.")
    finally:
        client.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
