"""
Modo SIGNAL_ONLY — el bot solo notifica, no coloca órdenes.

Es el modo de arranque del MVP. Garantiza que ni en un bug podemos colocar
una orden por error.
"""

from __future__ import annotations

from loguru import logger

from config.settings import ExecutionMode
from executor.base import Executor, ExecutionResult
from signals.schema import Signal, SignalStatus


class SignalOnlyExecutor(Executor):
    mode = ExecutionMode.SIGNAL_ONLY

    def place(self, signal: Signal) -> ExecutionResult:
        logger.info(f"[SIGNAL_ONLY] {signal.short_repr()}")
        return ExecutionResult(
            success=True,
            new_status=SignalStatus.NEW,
            message="Modo SIGNAL_ONLY — no se coloca orden.",
        )
