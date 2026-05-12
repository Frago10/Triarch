"""
Test rápido de conexión a MT5.

Uso:
    python -m scripts.connect_mt5
"""
from __future__ import annotations

import sys

from loguru import logger
from rich.console import Console
from rich.table import Table

from config.settings import get_settings, get_symbols
from data_layer.mt5_client import MT5Client


def main() -> int:
    console = Console()
    settings = get_settings()

    console.print(f"[bold cyan]Triarch — test de conexión MT5[/bold cyan]")
    console.print(f"Login: {settings.mt5_login} @ {settings.mt5_server}")
    console.print(f"Path: {settings.mt5_path or '(default)'}")
    console.print(f"Env: {settings.triarch_env.value}")
    console.print()

    client = MT5Client()
    if not client.initialize():
        console.print("[red]Conexión fallida. Revisa .env y que MT5 terminal esté instalado.[/red]")
        return 1

    info = client.account_info()
    if info:
        console.print(f"[green]✓ Conectado[/green] — {info.name} ({info.login})")
        console.print(f"  Server: {info.server}")
        console.print(f"  Balance: {info.balance:.2f} {info.currency}")
        console.print(f"  Equity: {info.equity:.2f} {info.currency}")
        console.print(f"  Free margin: {info.free_margin:.2f}")
        console.print(f"  Leverage: 1:{info.leverage}")
    console.print()

    # Test cada símbolo
    table = Table(title="Símbolos configurados")
    table.add_column("Activo")
    table.add_column("Broker symbol")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Min lot", justify="right")
    table.add_column("Velas M15 (n)", justify="right")

    for name, cfg in get_symbols().items():
        sym_info = client.symbol_info(cfg.broker_symbol)
        if sym_info is None:
            table.add_row(name, cfg.broker_symbol, "—", "—", "—", "—", "[red]NO[/red]")
            continue
        df = client.get_rates(cfg.broker_symbol, cfg.timeframe, n_bars=10)
        n_bars = len(df)
        table.add_row(
            name,
            cfg.broker_symbol,
            f"{sym_info.bid:.5f}",
            f"{sym_info.ask:.5f}",
            str(sym_info.spread),
            f"{sym_info.volume_min}",
            str(n_bars),
        )

    console.print(table)
    client.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
