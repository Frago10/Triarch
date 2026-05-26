"""
Triarch — registry de estrategias.

Mapping nombre → clase. Permite que symbols.yaml liste estrategias por nombre.
"""

from __future__ import annotations

from strategies.base import Strategy
from strategies.bb_mr import BBMeanReversionStrategy
from strategies.donchian_break import DonchianBreakStrategy
from strategies.ema_momentum import EMAMomentumStrategy
from strategies.keltner_break import KeltnerBreakStrategy
from strategies.macd_cross import MACDCrossStrategy
from strategies.orb import ORBStrategy
from strategies.pullback_trend import PullbackTrendStrategy
from strategies.rsi_reversal import RSIReversalStrategy
from strategies.scalper import ScalperStrategy
from strategies.vwap_mr import VWAPMeanReversionStrategy

REGISTRY: dict[str, type[Strategy]] = {
    # Originales (v0.3)
    "ORB": ORBStrategy,
    "VWAP_MR": VWAPMeanReversionStrategy,
    "EMA_MOMENTUM": EMAMomentumStrategy,
    "SCALPER": ScalperStrategy,
    "BB_MR": BBMeanReversionStrategy,
    # Nuevas (v0.5 — pool ampliado, 10 strats totales, 6 por activo)
    "PULLBACK_TREND": PullbackTrendStrategy,
    "DONCHIAN_BREAK": DonchianBreakStrategy,
    "KELTNER_BREAK": KeltnerBreakStrategy,
    "MACD_CROSS": MACDCrossStrategy,
    "RSI_REVERSAL": RSIReversalStrategy,
}


def build_strategies(names: list[str]) -> list[Strategy]:
    """Instancia las estrategias por nombre."""
    out: list[Strategy] = []
    for n in names:
        cls = REGISTRY.get(n)
        if cls is None:
            raise KeyError(
                f"Estrategia no registrada: {n}. Disponibles: {list(REGISTRY)}"
            )
        out.append(cls())
    return out
