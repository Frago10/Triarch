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


def _do_publish(full: bool, include_mt5: bool, years_full: int = 1) -> None:
    """Exporta el snapshot del dashboard y lo pushea a GitHub. Nunca tumba el loop."""
    try:
        from scripts.publish import publish_full, publish_light

        if full:
            publish_full(years=years_full, include_mt5=include_mt5)
        else:
            publish_light(include_mt5=include_mt5)
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Publicación a GitHub falló (continúo operando): {e}")


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
    parser.add_argument(
        "--publish-every-min",
        type=int,
        default=0,
        help="Cada N min, exporta state.json y lo pushea a GitHub (dashboard live). 0=off.",
    )
    parser.add_argument(
        "--publish-full-every-min",
        type=int,
        default=0,
        help="Cada N min, refresh completo (histórico+OHLC+backtest) y push. 0=off. Sugerido 1440.",
    )
    parser.add_argument(
        "--publish-no-mt5",
        action="store_true",
        help="No incluir la cuenta MT5 en el snapshot publicado (privacidad).",
    )
    parser.add_argument(
        "--control-port",
        type=int,
        default=8772,
        help="Puerto del servidor de control local (switch web). 0 = desactivado.",
    )
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
    # Aviso de arranque por Telegram (confirma que el bot está vivo y vigilando).
    try:
        orch.send_startup_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"No se pudo enviar el aviso de arranque: {e}")

    # Servidor de control local — hace funcional el switch "Trades reales" de la
    # web cuando se abre en esta máquina (escribe runtime.yaml vía HTTP local).
    if args.control_port:
        try:
            from scripts.control_server import start_control_server

            start_control_server(args.control_port)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Control server no arrancó: {e}")

    if args.once:
        logger.info("Modo --once: ejecutando UN tick…")
        orch.tick()
        logger.info("Tick único completado. Revisa arriba qué velas/setups se evaluaron.")
        client.shutdown()
        return 0

    logger.info(f"Triarch live loop iniciado — tick cada {args.tick}s. Ctrl+C para parar.")

    # ─── Publicación del dashboard (GitHub Pages) ───
    publish_mt5 = not args.publish_no_mt5
    last_light = last_full = 0.0
    if args.publish_every_min > 0 or args.publish_full_every_min > 0:
        # Publicación inicial LIGERA (rápida) para que el dashboard refleje el
        # arranque de inmediato sin demorar el primer tick. El refresh completo
        # (histórico+OHLC, pesado) queda para el timer diario.
        _do_publish(full=False, include_mt5=publish_mt5, years_full=1)
        last_light = last_full = time.monotonic()
        logger.info(
            f"Publicación a GitHub activa — light cada {args.publish_every_min}min, "
            f"full cada {args.publish_full_every_min}min."
        )

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

            # ─── Snapshot al dashboard según intervalos ───
            now = time.monotonic()
            if args.publish_full_every_min > 0 and now - last_full >= args.publish_full_every_min * 60:
                _do_publish(full=True, include_mt5=publish_mt5, years_full=1)
                last_full = last_light = now
            elif args.publish_every_min > 0 and now - last_light >= args.publish_every_min * 60:
                _do_publish(full=False, include_mt5=publish_mt5, years_full=1)
                last_light = now

            time.sleep(args.tick)
    except KeyboardInterrupt:
        logger.info("Detenido por usuario.")
    finally:
        client.shutdown()

    return 0


if __name__ == "__main__":
    sys.exit(main())
