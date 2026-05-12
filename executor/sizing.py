"""
Position sizing.

Default: risk_pct (riesgo X% del equity por trade).
  lot = (equity * risk_pct/100) / (risk_pts * pip_value_per_lot)
"""
from __future__ import annotations

from loguru import logger

from config.settings import SymbolConfig
from data_layer.mt5_client import MT5Client
from signals.schema import Signal


def calc_lot_risk_pct(
    signal: Signal,
    symbol_cfg: SymbolConfig,
    mt5_client: MT5Client,
) -> float:
    """
    Calcula el lot size en función de:
      - riesgo % del equity
      - distancia entry-SL (risk_pts)
      - tick value del símbolo (lo da MT5)
    """
    info = mt5_client.account_info()
    sym = mt5_client.symbol_info(symbol_cfg.broker_symbol)
    if info is None or sym is None:
        logger.warning("No info de cuenta/símbolo — usando min_lot")
        return symbol_cfg.position_sizing.min_lot

    equity = info.equity
    risk_money = equity * symbol_cfg.position_sizing.risk_per_trade_pct / 100.0

    # Para CFDs/FX, la fórmula simplificada:
    #   lot = risk_money / (risk_pts * trade_contract_size)
    # Esto NO es 100% preciso (no contabiliza el tick value en moneda de la cuenta),
    # pero es lo bastante bueno como punto de partida. Lo refinamos en v2.
    risk_per_lot = signal.risk_pts * sym.trade_contract_size
    if risk_per_lot <= 0:
        return symbol_cfg.position_sizing.min_lot

    raw_lot = risk_money / risk_per_lot

    # Snap a step y bounds
    step = sym.volume_step or 0.01
    snapped = round(raw_lot / step) * step
    bounded = max(
        symbol_cfg.position_sizing.min_lot,
        min(symbol_cfg.position_sizing.max_lot, snapped),
    )
    return float(round(bounded, 2))
