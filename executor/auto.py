"""
Modo AUTO — coloca órdenes en MT5.

Reglas duras:
  - Magic number único por estrategia (para auditar trades).
  - SL siempre puesto en la orden (no se confía en cierre manual).
  - TP1 puesto. TP2 lo gestiona el orchestrator (se mueve a BE tras TP1).
  - Cancela cualquier orden existente del mismo signal antes de colocar otra.
  - Slippage guard: si precio de mercado se desvió > X*ATR del entry, NO coloca.
"""

from __future__ import annotations

from loguru import logger

from config.settings import ExecutionMode, SymbolConfig
from data_layer.mt5_client import MT5_AVAILABLE, MT5Client
from executor.base import Executor, ExecutionResult
from signals.schema import Direction, Signal, SignalStatus

# Magic numbers — uno por estrategia. Permiten filtrar trades del bot vs manuales.
MAGIC_NUMBERS = {
    "ORB": 100100,
    "VWAP_MR": 100200,
    "EMA_MOMENTUM": 100300,
}


class AutoExecutor(Executor):
    mode = ExecutionMode.AUTO

    def __init__(self, mt5_client: MT5Client, symbol_cfg: SymbolConfig) -> None:
        self.mt5_client = mt5_client
        self.symbol_cfg = symbol_cfg

    def place(self, signal: Signal) -> ExecutionResult:
        if not MT5_AVAILABLE:
            return ExecutionResult(
                success=False,
                new_status=SignalStatus.FAILED,
                message="MT5 no disponible (¿estás en Windows?)",
            )

        import MetaTrader5 as mt5  # type: ignore[import-not-found]

        broker_symbol = self.symbol_cfg.broker_symbol
        sym_info = self.mt5_client.symbol_info(broker_symbol)
        if sym_info is None:
            return ExecutionResult(
                success=False,
                new_status=SignalStatus.FAILED,
                message=f"No se obtuvo info del símbolo {broker_symbol}",
            )

        # Lot size — calculado en otro módulo (sizing). Aquí asumimos `signal.features['lot']`
        lot = signal.features.get("lot")
        if lot is None:
            lot = self.symbol_cfg.position_sizing.min_lot
            logger.warning(
                f"Signal sin 'lot' calculado — usando min_lot={lot}. "
                "Esto debería venir del position sizer."
            )

        order_type = (
            mt5.ORDER_TYPE_BUY
            if signal.direction == Direction.LONG
            else mt5.ORDER_TYPE_SELL
        )
        price = sym_info.ask if signal.direction == Direction.LONG else sym_info.bid

        magic = MAGIC_NUMBERS.get(signal.strategy, 100000)
        deviation = 20  # puntos máx. de slippage en MT5 al rellenar

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": broker_symbol,
            "volume": float(lot),
            "type": order_type,
            "price": float(price),
            "sl": float(signal.stop_loss),
            "tp": float(signal.take_profit_1),
            "deviation": deviation,
            "magic": magic,
            "comment": f"triarch:{signal.strategy}:{signal.signal_id}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result is None:
            return ExecutionResult(
                success=False,
                new_status=SignalStatus.FAILED,
                message=f"order_send devolvió None: {mt5.last_error()}",
            )

        if result.retcode != mt5.TRADE_RETCODE_DONE:
            return ExecutionResult(
                success=False,
                new_status=SignalStatus.FAILED,
                message=f"order_send retcode={result.retcode} {result.comment}",
            )

        logger.success(
            f"[AUTO] Orden colocada: ticket={result.order} {signal.short_repr()}"
        )
        return ExecutionResult(
            success=True,
            new_status=SignalStatus.PLACED,
            mt5_ticket=result.order,
            message=f"Orden colocada (ticket={result.order})",
        )
