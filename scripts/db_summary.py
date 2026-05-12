"""
Resumen rápido de la SQLite del bot — útil cuando no tienes sqlite3 CLI.

Uso:
    python -m scripts.db_summary
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def main() -> int:
    db = Path("data_cache/triarch.sqlite")
    if not db.exists():
        console.print(f"[yellow]No existe {db}. Corre run_live primero.[/yellow]")
        return 0

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row

    # Resumen evals
    console.print("[bold cyan]── Evals por activo y estrategia ──[/bold cyan]")
    rows = conn.execute(
        """SELECT symbol, strategy,
                  COUNT(*) AS total,
                  SUM(detected_setup) AS detected,
                  COUNT(emitted_signal_id) AS emitted
           FROM evals
           GROUP BY symbol, strategy
           ORDER BY symbol, strategy"""
    ).fetchall()
    if rows:
        t = Table()
        t.add_column("Activo")
        t.add_column("Estrategia")
        t.add_column("Total evals", justify="right")
        t.add_column("Detected", justify="right")
        t.add_column("Emitted", justify="right")
        for r in rows:
            t.add_row(r["symbol"], r["strategy"], str(r["total"]), str(r["detected"] or 0), str(r["emitted"]))
        console.print(t)
    else:
        console.print("[dim]Sin evals todavía.[/dim]")

    # Top razones de bloqueo
    console.print("\n[bold cyan]── Top razones de bloqueo ──[/bold cyan]")
    rows = conn.execute(
        """SELECT blocked_by, COUNT(*) AS n
           FROM evals
           WHERE blocked_by IS NOT NULL
           GROUP BY blocked_by
           ORDER BY n DESC LIMIT 10"""
    ).fetchall()
    if rows:
        t = Table()
        t.add_column("Razón")
        t.add_column("N", justify="right")
        for r in rows:
            t.add_row(r["blocked_by"], str(r["n"]))
        console.print(t)
    else:
        console.print("[dim]Aún sin bloqueos.[/dim]")

    # Señales recientes
    console.print("\n[bold cyan]── Señales recientes (últimas 10) ──[/bold cyan]")
    rows = conn.execute(
        """SELECT timestamp_utc, symbol, strategy, direction, entry, rr_ratio, score, status
           FROM signals
           ORDER BY timestamp_utc DESC LIMIT 10"""
    ).fetchall()
    if rows:
        t = Table()
        for col in ["Time UTC", "Activo", "Strat", "Dir", "Entry", "R:R", "Score", "Status"]:
            t.add_column(col)
        for r in rows:
            t.add_row(
                r["timestamp_utc"][:19],
                r["symbol"],
                r["strategy"],
                r["direction"],
                f"{r['entry']:.5f}",
                f"{r['rr_ratio']:.2f}",
                f"{r['score']:.2f}",
                r["status"],
            )
        console.print(t)
    else:
        console.print("[dim]Aún sin señales.[/dim]")

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
