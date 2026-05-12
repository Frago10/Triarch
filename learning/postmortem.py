"""
Triarch — postmortem semanal.

Lee SQLite + escribe nota markdown en `wiki/triarch/postmortems/YYYY-Www.md` del vault.

V1: agregaciones simples (P&L por activo, WR por estrategia, lock-out reasons).
V2: prompt a un LLM para que sugiera ajustes (vía API o stored prompt para Claude).
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Iterable

from loguru import logger

from audit.obsidian_writer import ObsidianWriter
from audit.store import AuditStore


def _week_bounds(year: int, week: int) -> tuple[datetime, datetime]:
    """Calcula los bounds UTC de una semana ISO."""
    monday = datetime.fromisocalendar(year, week, 1).replace(tzinfo=timezone.utc)
    sunday_end = monday + timedelta(days=7)
    return monday, sunday_end


def generate_postmortem(
    year: int,
    week: int,
    store: AuditStore,
    writer: ObsidianWriter,
) -> str:
    start, end = _week_bounds(year, week)
    signals = store.list_signals(since=start, limit=10_000)
    signals_in = [s for s in signals if s["timestamp_utc"] < end.isoformat()]
    evals = store.list_evals(since=start, limit=50_000)
    evals_in = [e for e in evals if e["timestamp_utc"] < end.isoformat()]

    body: list[str] = []
    body.append(f"# Triarch — postmortem semana {year}-W{week:02d}")
    body.append("")
    body.append(f"Periodo: {start.date().isoformat()} → {(end - timedelta(days=1)).date().isoformat()}")
    body.append("")

    # 1. Stats globales
    body.append("## Resumen global")
    body.append("")
    body.append(f"- **Señales emitidas:** {len(signals_in)}")
    body.append(f"- **Evaluaciones totales:** {len(evals_in)}")
    detected = sum(1 for e in evals_in if e["detected_setup"])
    body.append(f"- **Setups detectados:** {detected}")
    body.append(f"- **Hit rate detección → señal:** {(len(signals_in)/detected*100) if detected else 0:.1f}%")
    body.append("")

    # 2. Por activo
    by_symbol: dict[str, list] = {}
    for s in signals_in:
        by_symbol.setdefault(s["symbol"], []).append(s)
    body.append("## Por activo")
    body.append("")
    body.append("| Activo | Señales | PnL total | WR | PF |")
    body.append("|---|---|---|---|---|")
    for sym, ss in by_symbol.items():
        pnls = [s["pnl_money"] for s in ss if s["pnl_money"] is not None]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]
        wr = (len(wins) / len(pnls) * 100) if pnls else 0
        pf = (sum(wins) / abs(sum(losses))) if losses and sum(losses) != 0 else float("inf") if wins else 0
        pf_str = f"{pf:.2f}" if pf != float("inf") else "∞"
        body.append(
            f"| {sym} | {len(ss)} | {sum(pnls):+.2f} | {wr:.1f}% | {pf_str} |"
        )
    body.append("")

    # 3. Lock-out reasons (qué bloqueó al bot)
    blocked = [e["blocked_by"] for e in evals_in if e.get("blocked_by")]
    if blocked:
        c = Counter(blocked)
        body.append("## Top razones de bloqueo")
        body.append("")
        body.append("| Razón | Cantidad |")
        body.append("|---|---|")
        for reason, n in c.most_common(10):
            body.append(f"| `{reason}` | {n} |")
        body.append("")

    # 4. Notas para Claude (template para que lo procese cuando le pases la nota)
    body.append("## Para Claude — análisis")
    body.append("")
    body.append("> Frago: cuando leas esta nota con Claude, pásale este bloque:")
    body.append("")
    body.append("```")
    body.append("Analiza esta semana del bot Triarch. Identifica:")
    body.append("  1. Estrategias que están infraperformando vs el resto.")
    body.append("  2. Activos donde el bot NO emite señales — ¿están mal configurados?")
    body.append("  3. Razones de bloqueo dominantes y si son esperadas o señal de algo roto.")
    body.append("  4. Propón 2-3 ajustes concretos a probar la semana siguiente.")
    body.append("  5. Cualquier patrón que sugiera overfit o regime-shift.")
    body.append("```")
    body.append("")

    body.append("## Acciones siguiente semana")
    body.append("- [ ] (rellenar tras conversación con Claude)")
    body.append("")

    body.append("## Notas relacionadas")
    body.append("- [[../../../../01 - Projects/Proyecto - Triarch Bot (MT5 Multi-Asset)]]")
    body.append("- [[../../../Trading/Roybot/Roybot - Lecciones para nuestro bot]]")
    body.append("")

    md = "\n".join(body)
    path = writer.write_postmortem_note(year, week, md)
    logger.success(f"Postmortem semana {year}-W{week:02d} → {path}")
    return md


# CLI
def main() -> None:
    import argparse
    from datetime import date

    from config.settings import get_settings

    parser = argparse.ArgumentParser()
    parser.add_argument("--week", type=str, help="YYYY-Www (default: semana ISO actual)")
    args = parser.parse_args()

    if args.week:
        year, w = args.week.split("-W")
        year, w = int(year), int(w)
    else:
        today = date.today()
        year, w, _ = today.isocalendar()

    s = get_settings()
    store = AuditStore()
    writer = ObsidianWriter(s.obsidian_vault_path)
    generate_postmortem(year, w, store, writer)


if __name__ == "__main__":
    main()
