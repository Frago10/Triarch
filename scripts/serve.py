"""
Triarch — entrypoint unificado.

Lanza en un mismo proceso:
  • El loop principal de orquestación (tick periódico)  →  background thread
  • El dashboard Streamlit                             →  subproceso en --port

Uso:
    python -m scripts.serve --tick 30 --port 8765

Ctrl+C detiene ambos limpiamente (cierra MT5).
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path

from loguru import logger

from config.settings import get_settings
from data_layer.mt5_client import MT5Client
from engine.orchestrator import Orchestrator


_stop = threading.Event()


def _tick_loop(orch: Orchestrator, tick_s: int) -> None:
    logger.info(f"[serve] Loop iniciado — tick cada {tick_s}s")
    while not _stop.is_set():
        try:
            orch.tick()
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"[serve] Error en tick: {exc}")
        # wait permite interrumpir el sleep cuando se pide stop
        _stop.wait(tick_s)
    logger.info("[serve] Loop detenido.")


def _spawn_dashboard(port: int) -> subprocess.Popen:
    project_root = Path(__file__).resolve().parents[1]
    app_path = project_root / "dashboard" / "app.py"
    if not app_path.exists():
        raise FileNotFoundError(f"No se encontró el dashboard en {app_path}")

    cmd = [
        sys.executable, "-m", "streamlit", "run", str(app_path),
        "--server.port", str(port),
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    logger.info(f"[serve] Dashboard  →  http://localhost:{port}")
    return subprocess.Popen(cmd, cwd=str(project_root))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Triarch — corre el loop live y sirve el dashboard en un puerto."
    )
    parser.add_argument("--tick", type=int, default=60, help="Segundos entre ticks (default 60)")
    parser.add_argument("--port", type=int, default=8501, help="Puerto del dashboard (default 8501)")
    args = parser.parse_args()

    settings = get_settings()
    logger.add(settings.log_file, rotation="50 MB", level=settings.log_level)

    client = MT5Client()
    if not client.initialize():
        logger.error("No se pudo conectar a MT5. Revisa .env.")
        return 1

    orch = Orchestrator(client, settings)
    logger.info(
        f"Triarch serve  ·  env={settings.triarch_env.value}  "
        f"·  default_mode={settings.triarch_default_mode.value}"
    )

    # Dashboard como subproceso
    try:
        dash = _spawn_dashboard(args.port)
    except FileNotFoundError as exc:
        logger.error(str(exc))
        client.shutdown()
        return 1

    # Loop de orquestación en un thread daemon
    t = threading.Thread(target=_tick_loop, args=(orch, args.tick), daemon=True)
    t.start()

    try:
        while True:
            if dash.poll() is not None:
                logger.warning("[serve] Dashboard terminó por su cuenta. Saliendo.")
                break
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("[serve] Ctrl+C recibido, cerrando…")
    finally:
        _stop.set()
        if dash.poll() is None:
            dash.terminate()
            try:
                dash.wait(timeout=5)
            except subprocess.TimeoutExpired:
                dash.kill()
        t.join(timeout=5)
        client.shutdown()
        logger.info("[serve] Bye.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
