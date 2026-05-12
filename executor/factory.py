"""
Triarch — factory de executor según modo del activo.
"""
from __future__ import annotations

from config.settings import ExecutionMode, SymbolConfig
from data_layer.mt5_client import MT5Client
from executor.approval import ApprovalExecutor
from executor.auto import AutoExecutor
from executor.base import Executor
from executor.signal_only import SignalOnlyExecutor


def build_executor(symbol_cfg: SymbolConfig, mt5_client: MT5Client) -> Executor:
    if symbol_cfg.mode == ExecutionMode.SIGNAL_ONLY:
        return SignalOnlyExecutor()
    if symbol_cfg.mode == ExecutionMode.APPROVAL:
        return ApprovalExecutor()
    if symbol_cfg.mode == ExecutionMode.AUTO:
        return AutoExecutor(mt5_client=mt5_client, symbol_cfg=symbol_cfg)
    raise ValueError(f"Modo desconocido: {symbol_cfg.mode}")
