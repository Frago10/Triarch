"""
Triarch — escritura automática de notas en el Obsidian vault.

Genera 2 tipos de notas:
  - sessions/YYYY-MM-DD.md  — resumen del día por activo (señales, taken, P&L)
  - postmortems/YYYY-WW.md  — resumen semanal con propuestas (lo gestiona learning/postmortem)

Las notas usan frontmatter compatible con el resto del vault.
"""

from __future__ import annotations

from datetime import date as ddate
from pathlib import Path

from loguru import logger


class ObsidianWriter:
    """Escribe notas markdown directamente en el vault."""

    def __init__(self, vault_path: str) -> None:
        self.vault_path = Path(vault_path)
        if not self.vault_path.exists():
            logger.warning(f"Vault path no existe: {self.vault_path}")
        # Estructura: <vault>/wiki/triarch/sessions/ y wiki/triarch/postmortems/
        self.sessions_dir = self.vault_path / "wiki" / "triarch" / "sessions"
        self.postmortems_dir = self.vault_path / "wiki" / "triarch" / "postmortems"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.postmortems_dir.mkdir(parents=True, exist_ok=True)

    def write_session_note(
        self,
        day: ddate,
        per_symbol: dict[str, dict],
    ) -> Path:
        """
        Genera/actualiza la nota de sesión del día.
        per_symbol: {"NAS100": {"signals": 3, "taken": 1, "pnl": 12.5, ...}, ...}
        """
        path = self.sessions_dir / f"{day.isoformat()}.md"

        # Frontmatter
        lines = [
            "---",
            "tipo: session",
            "area: trading",
            "subtema: triarch",
            f"fecha: {day.isoformat()}",
            "tags:",
            "  - session",
            "  - area/trading",
            "  - tipo/bot-real",
            "---",
            "",
            f"# Triarch — sesión {day.isoformat()}",
            "",
            "> Generado automáticamente por el bot. Lee, edita si quieres añadir contexto manual.",
            "",
            "## Resumen por activo",
            "",
            "| Activo | Señales | Tomadas | Skip | P&L | DD del día | Lock-out |",
            "|---|---|---|---|---|---|---|",
        ]
        for sym, d in per_symbol.items():
            lines.append(
                f"| {sym} | {d.get('signals', 0)} | {d.get('taken', 0)} | "
                f"{d.get('skipped', 0)} | {d.get('pnl', 0):+.2f} | "
                f"{d.get('drawdown', 0):.2f}% | {d.get('lock_reason', '—')} |"
            )

        lines += [
            "",
            "## Notas relacionadas",
            "- [[../../../01 - Projects/Proyecto - Triarch Bot (MT5 Multi-Asset)|Proyecto Triarch]]",
            "- [[../../../03 - Resources/Trading/Roybot/MOC - Roybot]]",
            "",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        logger.info(f"Session note escrita: {path}")
        return path

    def write_postmortem_note(self, year: int, week: int, body_md: str) -> Path:
        """Escribe la nota de postmortem semanal generada por el LLM."""
        path = self.postmortems_dir / f"{year}-W{week:02d}.md"
        frontmatter = (
            "---\n"
            "tipo: postmortem\n"
            "area: trading\n"
            "subtema: triarch\n"
            f"semana: {year}-W{week:02d}\n"
            "tags:\n"
            "  - postmortem\n"
            "  - area/trading\n"
            "  - tipo/bot-real\n"
            "---\n\n"
        )
        path.write_text(frontmatter + body_md, encoding="utf-8")
        logger.info(f"Postmortem note escrita: {path}")
        return path
