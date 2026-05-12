"""
Triarch — Signal schema.

Diseño inspirado en Roybot:
  - Entry, SL, TP1, TP2
  - R:R, score, confidence
  - Audit-friendly (signal_id, timestamp, source strategy + family)
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, computed_field, field_validator


class Direction(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class Confidence(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class SignalStatus(str, Enum):
    NEW = "NEW"             # recién emitida
    APPROVED = "APPROVED"   # aprobada por humano (modo APPROVAL)
    REJECTED_HUMAN = "REJECTED_HUMAN"
    REJECTED_RISK = "REJECTED_RISK"
    REJECTED_CONFLUENCE = "REJECTED_CONFLUENCE"
    PLACED = "PLACED"       # orden colocada en MT5
    FAILED = "FAILED"       # error al colocar
    FILLED = "FILLED"       # orden ejecutada
    CLOSED_TP1 = "CLOSED_TP1"
    CLOSED_TP2 = "CLOSED_TP2"
    CLOSED_SL = "CLOSED_SL"
    CLOSED_MANUAL = "CLOSED_MANUAL"


class Signal(BaseModel):
    """Una idea de trade emitida por una estrategia."""

    # ─── Identidad ───
    signal_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # ─── Origen ───
    symbol: str                  # NAS100 | XAUUSD | USDJPY
    timeframe: str               # M15, H1, etc.
    strategy: str                # ORB | VWAP_MR | ...
    family: str                  # opening | trend | mean | levels | structural

    # ─── Direccional ───
    direction: Direction
    entry: float
    stop_loss: float
    take_profit_1: float
    take_profit_2: float | None = None

    # ─── Quality metrics ───
    score: float = Field(ge=0.0, le=1.0)
    confidence: Confidence = Confidence.MEDIUM

    # ─── Risk ───
    risk_pts: float              # |entry - SL|
    reward_pts_tp1: float        # |entry - TP1|
    rr_ratio: float              # reward / risk
    atr_at_signal: float | None = None
    atr_deviation: float | None = None  # cuánto se desvió entry vs precio actual / ATR

    # ─── Estado y razones ───
    status: SignalStatus = SignalStatus.NEW
    reject_reason: str | None = None

    # ─── Features (para ML futuro) ───
    features: dict[str, Any] = Field(default_factory=dict)

    # ─── Ejecución (rellenado por executor) ───
    mt5_ticket: int | None = None
    placed_at_utc: datetime | None = None
    filled_price: float | None = None
    closed_at_utc: datetime | None = None
    closed_price: float | None = None
    pnl_money: float | None = None     # USD
    pnl_pts: float | None = None

    # ─────────────────────────────────────────────────────
    # Validators
    # ─────────────────────────────────────────────────────
    @field_validator("rr_ratio")
    @classmethod
    def _rr_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("rr_ratio must be > 0")
        return v

    # ─────────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────────
    @computed_field  # type: ignore[misc]
    @property
    def is_open(self) -> bool:
        return self.status in {SignalStatus.PLACED, SignalStatus.FILLED}

    # ─────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────
    def short_repr(self) -> str:
        return (
            f"[{self.symbol} {self.timeframe}] {self.strategy} {self.direction.value} "
            f"@ {self.entry:.5f} SL {self.stop_loss:.5f} TP1 {self.take_profit_1:.5f} "
            f"R:R {self.rr_ratio:.2f} score {self.score:.2f}"
        )


# ─────────────────────────────────────────────────────────
# Eval — registro de evaluación (incluye rechazos)
# ─────────────────────────────────────────────────────────
class Eval(BaseModel):
    """
    Registro de la evaluación de una estrategia en una vela específica.
    Estilo Roybot /evals: cada estrategia × cada vela = 1 fila.
    Incluye rechazos para auditoría.
    """

    eval_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp_utc: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    symbol: str
    timeframe: str
    strategy: str
    family: str

    detected_setup: bool                 # True si la estrategia vio un setup
    direction: Direction | None = None
    score: float | None = None
    proposed_entry: float | None = None

    # Si se emitió señal, su ID. Si no, razón.
    emitted_signal_id: str | None = None
    blocked_by: str | None = None        # "rejected_min_signals", "out_of_window", etc.
    blocked_detail: str | None = None
    families_aligned: list[str] = Field(default_factory=list)
    signals_aligned: int = 0
