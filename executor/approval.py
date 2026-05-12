"""
Modo APPROVAL — el bot notifica y espera confirmación humana.

V1: stub que loguea y deja la señal en estado APPROVED si confirmas a mano.
V2: integración Telegram con botones inline (✅ tomar / ❌ saltar / 🟨 modificar SL).
"""
from __future__ import annotations

from loguru import logger

from config.settings import ExecutionMode
from executor.base import Executor, ExecutionResult
from signals.schema import Signal, SignalStatus


class ApprovalExecutor(Executor):
    mode = ExecutionMode.APPROVAL

    def place(self, signal: Signal) -> ExecutionResult:
        logger.info(f"[APPROVAL] {signal.short_repr()} — esperando confirmación humana.")
        # V1: la lógica real de approval queda fuera del executor (vendrá vía Telegram bot).
        # Aquí dejamos NEW; el orchestrator/notifier se encarga de marcar APPROVED.
        return ExecutionResult(
            success=True,
            new_status=SignalStatus.NEW,
            message="Notificación enviada — pendiente de aprobación humana.",
        )
