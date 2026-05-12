"""
Triarch — Executor ABC.

Tres modos:
  - SIGNAL_ONLY: solo notifica, no toca MT5.
  - APPROVAL: notifica y espera confirmación humana (vía Telegram en v2).
  - AUTO: coloca orden directamente con SL siempre puesto.

Cada modo es una clase concreta que implementa `place(signal)`.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from config.settings import ExecutionMode
from signals.schema import Signal, SignalStatus


@dataclass
class ExecutionResult:
    success: bool
    new_status: SignalStatus
    message: str = ""
    mt5_ticket: int | None = None


class Executor(ABC):
    mode: ExecutionMode

    @abstractmethod
    def place(self, signal: Signal) -> ExecutionResult:
        ...
