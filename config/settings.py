"""
Triarch — global settings.

Carga `.env` y `config/symbols.yaml`. Punto único de verdad de configuración.
"""
from __future__ import annotations

from datetime import time as dtime
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent
SYMBOLS_YAML = REPO_ROOT / "config" / "symbols.yaml"


class ExecutionMode(str, Enum):
    SIGNAL_ONLY = "SIGNAL_ONLY"
    APPROVAL = "APPROVAL"
    AUTO = "AUTO"


class Environment(str, Enum):
    DEMO = "demo"
    LIVE = "live"


# ─────────────────────────────────────────────────────────
# .env — variables globales
# ─────────────────────────────────────────────────────────
class TriarchSettings(BaseSettings):
    """Cargado desde .env. Override con env vars."""

    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # MT5
    mt5_login: int = 0
    mt5_password: str = ""
    mt5_server: str = ""
    mt5_path: str | None = None

    # Modo y entorno
    triarch_default_mode: ExecutionMode = ExecutionMode.SIGNAL_ONLY
    triarch_kill: int = 0
    triarch_env: Environment = Environment.DEMO

    # Risk defaults
    risk_max_daily_loss_pct: float = 2.0
    risk_max_consec_losses: int = 3
    risk_max_trades_per_day: int = 5
    risk_min_rr_ratio: float = 1.5
    risk_max_slippage_atr: float = 1.5

    # Confluence (activa por defecto; usa min=1 para debug o si solo corre 1 estrategia)
    triarch_confluence_min_signals: int = 2
    triarch_confluence_min_families: int = 2
    triarch_confluence_min_score: float = 1.0

    # Notificaciones
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_webhook_url: str = ""

    # Obsidian
    obsidian_vault_path: str = str(REPO_ROOT.parent.parent.parent.parent)

    # Logging
    log_level: str = "INFO"
    log_file: str = "logs/triarch.log"


# ─────────────────────────────────────────────────────────
# symbols.yaml — config por activo
# ─────────────────────────────────────────────────────────
class SessionWindow(BaseModel):
    start: str  # "HH:MM" UTC
    end: str

    def to_times(self) -> tuple[dtime, dtime]:
        sh, sm = map(int, self.start.split(":"))
        eh, em = map(int, self.end.split(":"))
        return dtime(sh, sm), dtime(eh, em)


class RiskOverride(BaseModel):
    max_daily_loss_pct: float = 2.0
    max_consec_losses: int = 3
    max_trades_per_day: int = 5
    min_rr_ratio: float = 1.5


class PositionSizing(BaseModel):
    method: str = "risk_pct"  # risk_pct | fixed_lots | atr
    risk_per_trade_pct: float = 0.5
    min_lot: float = 0.01
    max_lot: float = 5.0
    fixed_lots: float | None = None


class ConfluenceOverride(BaseModel):
    """
    Confluencia por activo. Si un símbolo no la define, se usan los defaults
    globales del .env.
      • Perfil quality  → exigente: 2 señales / 2 familias.
      • Perfil scalper  → permisivo: 1 señal basta (un scalper no puede
        esperar a que 2 estrategias coincidan en la misma vela).
    """
    min_signals: int = 2
    min_families: int = 2
    min_combined_score: float = 1.0


class SymbolConfig(BaseModel):
    name: str  # clave canónica (NAS100, XAUUSD, EURUSD)
    broker_symbol: str
    description: str = ""
    family: str  # index | commodity | fx
    timeframe: str = "M15"
    mode: ExecutionMode = ExecutionMode.SIGNAL_ONLY
    take_trades: bool = False            # switch live: si False → fuerza SIGNAL_ONLY
    profile: str = "balanced"            # quality | scalper | balanced
    target_trades_wk: int = 0            # objetivo trades/semana (referencia)
    session_utc: SessionWindow
    risk: RiskOverride = Field(default_factory=RiskOverride)
    position_sizing: PositionSizing = Field(default_factory=PositionSizing)
    confluence: ConfluenceOverride | None = None   # None → usa defaults del .env
    strategies: list[str] = Field(default_factory=list)


def load_symbols(yaml_path: Path = SYMBOLS_YAML) -> dict[str, SymbolConfig]:
    """Lee symbols.yaml y devuelve dict {NAME: SymbolConfig}."""
    raw: dict[str, Any] = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    out: dict[str, SymbolConfig] = {}
    for name, body in raw.items():
        out[name] = SymbolConfig(name=name, **body)
    return out


# ─────────────────────────────────────────────────────────
# Singleton-style accessors
# ─────────────────────────────────────────────────────────
_settings: TriarchSettings | None = None
_symbols: dict[str, SymbolConfig] | None = None


def get_settings() -> TriarchSettings:
    global _settings
    if _settings is None:
        _settings = TriarchSettings()
    return _settings


def get_symbols() -> dict[str, SymbolConfig]:
    global _symbols
    if _symbols is None:
        _symbols = load_symbols()
    return _symbols


def get_symbol(name: str) -> SymbolConfig:
    return get_symbols()[name]
