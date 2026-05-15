"""
Triarch — capa de confluencia.

En v1 sólo corre 1 estrategia por activo, así que la confluencia es no-op
(pasa todas). Pero el contrato ya queda armado para cuando llegue v2.

Reglas estilo Roybot:
  - Mínimo N señales alineadas (misma dirección).
  - Mínimo K familias distintas representadas.
  - Score combinado mínimo.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from signals.schema import Direction, Eval, Signal


@dataclass
class ConfluenceConfig:
    """
    Defaults v2 (confluencia activa):
      - Al menos 2 estrategias deben emitir en la misma dirección.
      - De al menos 2 familias distintas (ej: opening + trend, no 2 trend).
      - Score combinado >= 1.0  (≈ promedio 0.5 con 2 señales).

    Para "pass-through" (debug o solo 1 estrategia activa), poner
    min_signals=1, min_families=1, min_combined_score=0.0.
    """
    min_signals: int = 2
    min_families: int = 2
    min_combined_score: float = 1.0


@dataclass
class ConfluenceDecision:
    accepted: bool
    chosen_signal: Signal | None
    rejected_signals: list[Signal] = field(default_factory=list)
    reason: str = ""


class ConfluenceFilter:
    def __init__(self, cfg: ConfluenceConfig | None = None) -> None:
        self.cfg = cfg or ConfluenceConfig()

    def filter(self, signals: list[Signal]) -> ConfluenceDecision:
        """
        Decide si un conjunto de señales pasa el filtro.
        Si pasa: devuelve la "mejor" señal (mayor score) como `chosen_signal`.
        """
        if not signals:
            return ConfluenceDecision(accepted=False, chosen_signal=None, reason="no_signals")

        # Agrupar por dirección
        by_dir: dict[Direction, list[Signal]] = {}
        for s in signals:
            by_dir.setdefault(s.direction, []).append(s)

        # ¿Empate de dirección? rechazar
        if len(by_dir) > 1:
            counts = {d.value: len(v) for d, v in by_dir.items()}
            return ConfluenceDecision(
                accepted=False,
                chosen_signal=None,
                rejected_signals=signals,
                reason=f"direction_tie:{counts}",
            )

        direction, group = next(iter(by_dir.items()))
        n_signals = len(group)
        families = {s.family for s in group}
        combined_score = sum(s.score for s in group)

        if n_signals < self.cfg.min_signals:
            return ConfluenceDecision(
                accepted=False,
                chosen_signal=None,
                rejected_signals=group,
                reason=f"min_signals:{n_signals}<{self.cfg.min_signals}",
            )
        if len(families) < self.cfg.min_families:
            return ConfluenceDecision(
                accepted=False,
                chosen_signal=None,
                rejected_signals=group,
                reason=f"min_families:{len(families)}<{self.cfg.min_families}",
            )
        if combined_score < self.cfg.min_combined_score:
            return ConfluenceDecision(
                accepted=False,
                chosen_signal=None,
                rejected_signals=group,
                reason=f"score:{combined_score:.2f}<{self.cfg.min_combined_score}",
            )

        chosen = max(group, key=lambda s: s.score)
        return ConfluenceDecision(
            accepted=True,
            chosen_signal=chosen,
            rejected_signals=[s for s in group if s.signal_id != chosen.signal_id],
            reason="ok",
        )


# ─────────────────────────────────────────────────────────
# Builder por símbolo
# ─────────────────────────────────────────────────────────
def build_confluence_for(symbol_cfg, settings) -> "ConfluenceFilter":
    """
    Construye un ConfluenceFilter para un activo.

    Si el símbolo define un bloque `confluence` en symbols.yaml, lo usa.
    Si no, cae a los defaults globales del .env (settings.triarch_confluence_*).

    Esto permite que el perfil scalper tenga confluencia permisiva (1 señal)
    mientras que el perfil quality la tenga exigente (2 señales / 2 familias).
    """
    ov = getattr(symbol_cfg, "confluence", None)
    if ov is not None:
        cfg = ConfluenceConfig(
            min_signals=ov.min_signals,
            min_families=ov.min_families,
            min_combined_score=ov.min_combined_score,
        )
    else:
        cfg = ConfluenceConfig(
            min_signals=settings.triarch_confluence_min_signals,
            min_families=settings.triarch_confluence_min_families,
            min_combined_score=settings.triarch_confluence_min_score,
        )
    return ConfluenceFilter(cfg)
