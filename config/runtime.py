"""
Triarch — runtime overrides.

Capa pequeña de configuración que el dashboard puede modificar EN VIVO sin
reiniciar el bot ni editar `symbols.yaml`. Se persiste en `config/runtime.yaml`.

Hoy controla:
  • take_trades por activo (bool): si False → orchestrator fuerza SIGNAL_ONLY.

Diseñado para que cualquier proceso (dashboard Streamlit, CLI, el propio loop)
pueda leer/escribir sin contención: el archivo es chico y el lock no es crítico.
"""
from __future__ import annotations

from pathlib import Path

import yaml
from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_YAML = REPO_ROOT / "config" / "runtime.yaml"


def _read_raw() -> dict:
    if not RUNTIME_YAML.exists():
        return {}
    try:
        data = yaml.safe_load(RUNTIME_YAML.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"runtime.yaml ilegible ({exc}); usando defaults.")
        return {}


def _write_raw(data: dict) -> None:
    RUNTIME_YAML.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_YAML.write_text(
        yaml.safe_dump(data, sort_keys=True, allow_unicode=True),
        encoding="utf-8",
    )


def get_take_trades(symbol: str, default: bool = False) -> bool:
    """Devuelve el override de take_trades para `symbol`, o `default` si no hay."""
    data = _read_raw()
    overrides = data.get("take_trades", {})
    if symbol in overrides:
        return bool(overrides[symbol])
    return default


def set_take_trades(symbol: str, value: bool) -> None:
    """Persiste el toggle de take_trades para `symbol`."""
    data = _read_raw()
    overrides = data.get("take_trades", {})
    overrides[symbol] = bool(value)
    data["take_trades"] = overrides
    _write_raw(data)
    logger.info(f"runtime: take_trades[{symbol}] = {value}")


def all_take_trades(defaults: dict[str, bool] | None = None) -> dict[str, bool]:
    """Devuelve el mapping completo {symbol: take_trades}. Usa defaults si falta."""
    data = _read_raw()
    overrides = data.get("take_trades", {})
    out = dict(defaults or {})
    out.update({k: bool(v) for k, v in overrides.items()})
    return out


__all__ = [
    "RUNTIME_YAML",
    "get_take_trades",
    "set_take_trades",
    "all_take_trades",
]
