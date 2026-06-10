"""
Triarch — publicación del snapshot del bot a GitHub (para el dashboard de GH Pages).

El dashboard público es ESTÁTICO: no hay backend que lea MT5/SQLite en vivo.
Para que "se vea live", el bot exporta su estado a `data/state.json` cada pocos
minutos y lo pushea al repo; GitHub Pages re-despliega solo en ~1 min.

Dos niveles:
  · publish_light()  — solo re-exporta state.json (señales + cuenta) y lo pushea.
                       Barato y rápido → se corre cada pocos minutos.
  · publish_full()   — además baja histórico fresco, re-corre el backtest snapshot
                       y re-exporta el OHLC para el backtester interactivo.
                       Pesado (OHLC ~MB) → una vez al día.

Solo toca archivos de DATOS (data/ + docs/data/); nunca commitea código ni .env
(que está en .gitignore). Hace pull --rebase antes de pushear para no chocar con
commits manuales.
"""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone

from loguru import logger

from config.settings import REPO_ROOT

# Archivos de datos que publica el snapshot ligero.
_LIGHT_PATHS = ["data/state.json", "docs/data/state.json"]
# Archivos de datos del refresh completo (incluye OHLC del backtester).
_FULL_PATHS = ["data/state.json", "docs/data/state.json", "data/ohlc", "docs/data/ohlc"]


def _git(*args: str, timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _commit_and_push(paths: list[str], message: str) -> bool:
    """Stagea SOLO `paths`, commitea si hay cambios y pushea (con pull --rebase)."""
    add = _git("add", "--", *paths)
    if add.returncode != 0:
        logger.warning(f"[publish] git add falló: {add.stderr.strip()}")
        return False

    # ¿Hay algo staged? (returncode 1 = sí hay diferencias)
    if _git("diff", "--cached", "--quiet").returncode == 0:
        logger.debug("[publish] sin cambios en el snapshot — nada que pushear.")
        return False

    commit = _git("commit", "-m", message)
    if commit.returncode != 0:
        logger.warning(f"[publish] commit falló: {commit.stderr.strip() or commit.stdout.strip()}")
        return False

    # Mantenerse al día con el remoto antes de pushear (autostash por si quedó algo).
    _git("pull", "--rebase", "--autostash", "origin", "HEAD", timeout=180)

    push = _git("push", "origin", "HEAD", timeout=180)
    if push.returncode != 0:
        logger.warning(f"[publish] push falló: {push.stderr.strip()}")
        return False

    logger.info(f"[publish] ✔ snapshot pusheado — {message}")
    return True


def publish_light(include_mt5: bool = True) -> bool:
    """Re-exporta state.json y lo pushea. Rápido — para correr cada pocos minutos."""
    from scripts.export_web import export_state

    try:
        export_state(include_mt5=include_mt5)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[publish] export_state falló: {exc}")
        return False
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return _commit_and_push(_LIGHT_PATHS, f"chore(web): live snapshot {ts}")


def publish_full(years: int = 1, include_mt5: bool = True) -> bool:
    """Refresh pesado: histórico + backtest snapshot + OHLC + state. Una vez al día."""
    try:
        from scripts.fetch_history import main as fetch_main
        from scripts.export_ohlc import main as ohlc_main
        from scripts.export_web import export_state
        from scripts.backtest import backtest_symbol
        from config.settings import get_settings, get_symbols
    except ImportError as exc:
        logger.warning(f"[publish] imports del refresh completo fallaron: {exc}")
        return False

    import json
    import sys

    # 1. Histórico fresco
    old_argv = sys.argv
    sys.argv = ["fetch_history", "--years", str(years)]
    try:
        fetch_main()
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[publish] fetch_history falló: {exc}")
    finally:
        sys.argv = old_argv

    # 2. Backtest snapshot (data_cache/backtest_last.json — lo lee export_web)
    settings = get_settings()
    symbols = get_symbols()
    results = []
    for name, cfg in symbols.items():
        try:
            results.append(backtest_symbol(cfg, settings))
        except Exception as exc:  # noqa: BLE001
            results.append({"symbol": name, "error": str(exc)})
    (REPO_ROOT / "data_cache").mkdir(parents=True, exist_ok=True)
    (REPO_ROOT / "data_cache" / "backtest_last.json").write_text(
        json.dumps(results, indent=2, default=str, ensure_ascii=False), encoding="utf-8"
    )

    # 3. OHLC para el backtester interactivo del sitio.
    #    Usamos el main() completo (no export_symbol por símbolo) porque es el
    #    único que regenera el manifest.json con los "ranges" — sin eso la web
    #    sigue mostrando el span/timeframe viejo y los presets fallan.
    old_argv = sys.argv
    sys.argv = ["export_ohlc"]
    try:
        ohlc_main()
    except SystemExit:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[publish] export_ohlc falló: {exc}")
    finally:
        sys.argv = old_argv

    # 4. state.json
    try:
        export_state(include_mt5=include_mt5)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[publish] export_state falló: {exc}")

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return _commit_and_push(_FULL_PATHS, f"chore(web): full refresh {ts}")
