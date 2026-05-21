"""
Triarch — Strategy ABC.

Contrato: cada estrategia recibe un DataFrame de velas con indicadores y una
config de símbolo, y devuelve un Signal o None.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from config.settings import SymbolConfig
from signals.schema import Eval, Signal


@dataclass
class StrategyContext:
    symbol_cfg: SymbolConfig
    df: pd.DataFrame  # velas con indicadores ya añadidos


class Strategy(ABC):
    """ABC para todas las estrategias atómicas del bot."""

    name: str = "BASE"
    family: str = "base"  # opening | trend | mean | levels | structural

    @abstractmethod
    def evaluate(self, ctx: StrategyContext) -> tuple[Eval, Signal | None]:
        """
        Evalúa la última vela del DataFrame.
        Devuelve siempre un Eval (para audit trail) y opcionalmente un Signal si
        detecta setup válido.
        """
        ...

    # ─────────────────────────────────────────────────────
    # Helpers
    # ─────────────────────────────────────────────────────
    def _make_eval(
        self,
        ctx: StrategyContext,
        detected: bool,
        **kwargs,
    ) -> Eval:
        return Eval(
            symbol=ctx.symbol_cfg.name,
            timeframe=ctx.symbol_cfg.timeframe,
            strategy=self.name,
            family=self.family,
            detected_setup=detected,
            **kwargs,
        )
