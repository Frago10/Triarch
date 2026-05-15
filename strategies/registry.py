"""
Triarch — registry de estrategias.

Mapping nombre → clase. Permite que symbols.yaml liste estrategias por nombre.
"""
from __future__ import annotations

from strategies.base import Strategy
from strategies.bb_mr import BBMeanReversionStrategy
from strategies.ema_momentum import EMAMomentumStrategy
from strategies.orb import ORBStrategy
from strategies.scalper import ScalperStrategy
from strategies.vwap_mr import VWAPMeanReversionStrategy

REGISTRY: dict[str, type[Strategy]] = {
    "ORB": ORBStrategy,
    "VWAP_MR": VWAPMeanReversionStrategy,
    "EMA_MOMENTUM": EMAMomentumStrategy,
    "SCALPER": ScalperStrategy,
    "BB_MR": BBMeanReversionStrategy,
}


def build_strategies(names: list[str]) -> list[Strategy]:
    """Instancia las estrategias por nombre."""
    out: list[Strategy] = []
    for n in names:
        cls = REGISTRY.get(n)
        if cls is None:
            raise KeyError(f"Estrategia no registrada: {n}. Disponibles: {list(REGISTRY)}")
        out.append(cls())
    return out
