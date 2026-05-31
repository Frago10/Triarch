"""
Modo AUTO — coloca órdenes de mercado en MT5 y verifica que se ejecuten.

Reglas duras:
  - Magic number único por estrategia (para auditar trades).
  - SL siempre puesto en la orden (no se confía en cierre manual).
  - TP1 puesto. TP2 lo gestiona el orchestrator (se mueve a BE tras TP1).
  - Slippage / deviation controlado.

Robustez (v0.8 — fixes para que el broker REALMENTE ejecute):
  - FILLING MODE ADAPTIVO: cada símbolo/broker soporta distintos modos de
    relleno (FOK / IOC / RETURN). MetaQuotes-Demo y muchos otros RECHAZAN la
    orden con retcode 10030 "Unsupported filling mode" si mandas el modo
    equivocado. Aquí se lee el bitmask `symbol_info.filling_mode` y se elige
    el correcto; si aún falla, se reintenta con los otros modos.
  - NORMALIZACIÓN: price/SL/TP se redondean a los `digits` del símbolo y se
    respeta la distancia mínima `trade_stops_level` (si el SL/TP está más
    cerca que el mínimo del broker → retcode 10016 "Invalid stops").
  - VERIFICACIÓN: tras order_send se confirma con la posición/deal real para
    distinguir "orden aceptada" de "posición efectivamente abierta".
"""

from __future__ import annotations

from loguru import logger

from config.settings import ExecutionMode, SymbolConfig
from data_layer.mt5_client import MT5_AVAILABLE, MT5Client
from executor.base import Executor, ExecutionResult
from signals.schema import Direction, Signal, SignalStatus

# Magic numbers — uno por estrategia. Permiten filtrar trades del bot vs manuales.
# IMPORTANTE: el TradeMonitor usa estos mismos valores para detectar cierres,
# así que TODA estrategia que pueda ejecutar AUTO debe estar aquí.
MAGIC_NUMBERS = {
    "ORB": 100100,
    "VWAP_MR": 100200,
    "EMA_MOMENTUM": 100300,
    "SCALPER": 100400,
    "BB_MR": 100500,
    "PULLBACK_TREND": 100600,
    "DONCHIAN_BREAK": 100700,
    "KELTNER_BREAK": 100800,
    "MACD_CROSS": 100900,
    "RSI_REVERSAL": 101000,
}
MAGIC_FALLBACK = 100000


class AutoExecutor(Executor):
    mode = ExecutionMode.AUTO

    def __init__(self, mt5_client: MT5Client, symbol_cfg: SymbolConfig) -> None:
        self.mt5_client = mt5_client
        self.symbol_cfg = symbol_cfg

    # ─────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────
    @staticmethod
    def _supported_fillings(mt5, sym_info) -> list[int]:
        """
        Devuelve la lista de ORDER_FILLING_* a probar, ordenada por preferencia
        según el bitmask del símbolo. SYMBOL_FILLING_FOK=1, SYMBOL_FILLING_IOC=2.
        RETURN no está en el bitmask pero suele aceptarse para DEAL en muchos brokers.
        """
        mask = int(getattr(sym_info, "filling_mode", 0) or 0)
        modes: list[int] = []
        # bit 1 → FOK, bit 2 → IOC
        if mask & 1:
            modes.append(mt5.ORDER_FILLING_FOK)
        if mask & 2:
            modes.append(mt5.ORDER_FILLING_IOC)
        # Si el bitmask no informa nada útil, probamos el orden más compatible.
        if not modes:
            modes = [mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC]
        # RETURN como último recurso (algunos brokers solo aceptan este).
        modes.append(mt5.ORDER_FILLING_RETURN)
        # dedupe preservando orden
        seen: set[int] = set()
        out: list[int] = []
        for m in modes:
            if m not in seen:
                seen.add(m)
                out.append(m)
        return out

    @staticmethod
    def _normalize_levels(sym_info, direction, price, sl, tp):
        """
        Redondea price/SL/TP a los digits del símbolo y respeta la distancia
        mínima de stops (trade_stops_level * point). Si SL/TP están más cerca
        que el mínimo, los aleja para evitar retcode 10016 "Invalid stops".
        """
        digits = int(getattr(sym_info, "digits", 5) or 5)
        point = float(getattr(sym_info, "point", 0.0) or 0.0)
        stops_level = int(getattr(sym_info, "trade_stops_level", 0) or 0)
        min_dist = stops_level * point if point > 0 else 0.0

        def r(x):
            return round(float(x), digits)

        price = r(price)
        sl = r(sl)
        tp = r(tp)

        if min_dist > 0:
            if direction == Direction.LONG:
                if (price - sl) < min_dist:
                    sl = r(price - min_dist)
                if (tp - price) < min_dist:
                    tp = r(price + min_dist)
            else:  # SHORT
                if (sl - price) < min_dist:
                    sl = r(price + min_dist)
                if (price - tp) < min_dist:
                    tp = r(price - min_dist)
        return price, sl, tp

    # ─────────────────────────────────────────────────────
    # Place
    # ─────────────────────────────────────────────────────
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

        # ─── Verificar que el símbolo permite trading ───
        # SYMBOL_TRADE_MODE_FULL = 4. Cualquier valor < 4 limita o desactiva.
        if getattr(sym_info, "trade_mode", 4) == 0:
            return ExecutionResult(
                success=False,
                new_status=SignalStatus.FAILED,
                message=f"Trading deshabilitado para {broker_symbol} (trade_mode=0)",
            )

        # Lot size — calculado por el sizer (orchestrator lo mete en features['lot']).
        lot = signal.features.get("lot")
        if lot is None:
            lot = self.symbol_cfg.position_sizing.min_lot
            logger.warning(
                f"Signal sin 'lot' calculado — usando min_lot={lot}. "
                "Esto debería venir del position sizer."
            )
        lot = float(lot)

        order_type = (
            mt5.ORDER_TYPE_BUY
            if signal.direction == Direction.LONG
            else mt5.ORDER_TYPE_SELL
        )
        # Precio fresco del tick (ask para compra, bid para venta).
        raw_price = sym_info.ask if signal.direction == Direction.LONG else sym_info.bid

        price, sl, tp = self._normalize_levels(
            sym_info, signal.direction, raw_price, signal.stop_loss, signal.take_profit_1
        )

        magic = MAGIC_NUMBERS.get(signal.strategy, MAGIC_FALLBACK)
        deviation = 30  # puntos máx. de slippage al rellenar (índices necesitan más)

        fillings = self._supported_fillings(mt5, sym_info)

        last_err = ""
        for filling in fillings:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": broker_symbol,
                "volume": lot,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": deviation,
                "magic": magic,
                "comment": f"triarch:{signal.strategy}:{signal.signal_id}"[:31],
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }

            # ─── Pre-check: order_check valida sin enviar ───
            check = mt5.order_check(request)
            if check is not None and check.retcode not in (
                0,
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_PLACED,
            ):
                # 10030 = unsupported filling → probar el siguiente modo.
                if check.retcode == 10030:
                    last_err = f"filling {filling} no soportado (10030)"
                    continue
                # Otros errores de check: refrescar precio una vez por si fue stale.
                last_err = f"order_check retcode={check.retcode} {check.comment}"
                # Para 10016 (invalid stops) o 10018 (market closed) no insistimos
                # con otros fillings: el problema no es el filling.
                if check.retcode in (10016, 10018, 10019, 10027):
                    return ExecutionResult(
                        success=False,
                        new_status=SignalStatus.FAILED,
                        message=(
                            f"order_check rechazó: retcode={check.retcode} "
                            f"{check.comment} (price={price} sl={sl} tp={tp} lot={lot})"
                        ),
                    )
                # otros → seguir probando fillings

            result = mt5.order_send(request)
            if result is None:
                last_err = f"order_send None: {mt5.last_error()}"
                continue

            if result.retcode == 10030:  # unsupported filling
                last_err = f"order_send filling {filling} no soportado (10030)"
                continue

            if result.retcode not in (
                mt5.TRADE_RETCODE_DONE,
                mt5.TRADE_RETCODE_PLACED,
            ):
                last_err = f"order_send retcode={result.retcode} {result.comment}"
                # market closed / stops → no insistir con otros fillings
                if result.retcode in (10016, 10018, 10019, 10027):
                    return ExecutionResult(
                        success=False,
                        new_status=SignalStatus.FAILED,
                        message=last_err
                        + f" (price={price} sl={sl} tp={tp} lot={lot})",
                    )
                continue

            # ─── Éxito ───
            ticket = result.order
            # Verificar que la posición existe (deal ejecutado, no solo aceptado).
            filled = self._verify_filled(mt5, broker_symbol, magic, ticket)
            status = SignalStatus.FILLED if filled else SignalStatus.PLACED
            logger.success(
                f"[AUTO] Orden {'EJECUTADA' if filled else 'colocada'}: "
                f"ticket={ticket} filling={filling} {signal.short_repr()} "
                f"(price={price} sl={sl} tp={tp} lot={lot})"
            )
            return ExecutionResult(
                success=True,
                new_status=status,
                mt5_ticket=ticket,
                message=(
                    f"Orden {'ejecutada (posición abierta)' if filled else 'colocada'} "
                    f"ticket={ticket}"
                ),
            )

        # Si llegamos aquí, todos los fillings fallaron.
        return ExecutionResult(
            success=False,
            new_status=SignalStatus.FAILED,
            message=f"No se pudo colocar la orden tras probar {len(fillings)} fillings. "
            f"Último error: {last_err}",
        )

    @staticmethod
    def _verify_filled(mt5, broker_symbol: str, magic: int, ticket: int) -> bool:
        """
        Confirma que la orden generó una posición abierta real.
        order_send con retcode DONE normalmente ya implica ejecución para
        TRADE_ACTION_DEAL, pero verificamos contra positions_get por seguridad.
        """
        try:
            positions = mt5.positions_get(symbol=broker_symbol) or ()
            for p in positions:
                # match por ticket de orden o por position id, según broker
                if getattr(p, "ticket", None) == ticket or getattr(p, "magic", None) == magic:
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False
