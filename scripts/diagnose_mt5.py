"""
Diagnóstico exhaustivo de la conexión MT5.

Va paso a paso e imprime exactamente qué falla:
  1. ¿Está instalado el paquete MetaTrader5?
  2. ¿Conecta al terminal abierto? (mt5.initialize() sin args)
  3. ¿Información del terminal?
  4. ¿Trade permitido?
  5. ¿Lista de servers disponibles?
  6. ¿Login con credenciales del .env?
  7. ¿Account info?
  8. ¿Símbolos disponibles?

Uso:
    python -m scripts.diagnose_mt5
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


def step(n: int, title: str) -> None:
    console.print(f"\n[bold cyan]── Paso {n}: {title} ──[/bold cyan]")


def main() -> int:
    console.print(
        Panel.fit("[bold]Triarch — Diagnóstico MT5[/bold]", border_style="cyan")
    )

    # ─── Paso 1: paquete ───
    step(1, "Verificar paquete MetaTrader5")
    try:
        import MetaTrader5 as mt5  # type: ignore

        console.print(f"[green]✓[/green] MetaTrader5 v{mt5.__version__} instalado")
    except ImportError as e:
        console.print(f"[red]✗ {e}[/red]")
        console.print("  Solución: pip install MetaTrader5")
        return 1

    # ─── Paso 2: connect terminal ───
    step(2, "Conectar al terminal MT5")
    from config.settings import get_settings

    settings = get_settings()
    init_kwargs = {}
    if settings.mt5_path:
        init_kwargs["path"] = settings.mt5_path
        console.print(f"  Usando path explícito: {settings.mt5_path}")
    else:
        console.print("  Buscando terminal en path default")

    if not mt5.initialize(**init_kwargs):
        err = mt5.last_error()
        console.print(f"[red]✗ initialize() falló: {err}[/red]")
        console.print(
            "  Posibles causas:\n"
            "  - Terminal MT5 no está abierto\n"
            "  - Tienes varios MT5 instalados y Python encuentra uno distinto\n"
            "  - El terminal está iniciando todavía (espera 30s y reintenta)\n\n"
            "  Soluciones:\n"
            "  - Abre MT5 manualmente y espera a ver 'Connected' en esquina inferior derecha\n"
            "  - Si tienes varios MT5 → set MT5_PATH en .env al terminal64.exe correcto"
        )
        return 1
    console.print("[green]✓[/green] initialize() OK")

    # ─── Paso 3: terminal info ───
    step(3, "Info del terminal")
    ti = mt5.terminal_info()
    if ti is None:
        console.print("[red]✗ terminal_info() devolvió None[/red]")
        mt5.shutdown()
        return 1

    table = Table()
    table.add_column("Atributo")
    table.add_column("Valor")
    table.add_row("Nombre", ti.name)
    table.add_row("Build", str(ti.build))
    table.add_row("Path", ti.path)
    table.add_row("Data path", ti.data_path)
    table.add_row("Conectado", "✓" if ti.connected else "[red]✗[/red]")
    table.add_row(
        "Trade permitido",
        "✓" if ti.trade_allowed else "[red]✗ ALGO TRADING DESHABILITADO[/red]",
    )
    table.add_row("Compañía", ti.company)
    console.print(table)

    if not ti.trade_allowed:
        console.print(
            "[yellow]⚠ Trade no permitido.[/yellow] "
            "En MT5: Tools → Options → Expert Advisors → ✓ Allow algorithmic trading"
        )

    # ─── Paso 4: account info actual (sin login) ───
    step(4, "¿Hay cuenta logueada actualmente en el terminal?")
    info = mt5.account_info()
    if info:
        console.print(
            f"[green]✓[/green] Cuenta ya logueada en MT5: "
            f"login={info.login}  server={info.server}  "
            f"balance={info.balance:.2f} {info.currency}"
        )
        console.print(
            f"  [bold]Server EXACTO según MT5: {info.server!r}[/bold] "
            "← copia este valor a MT5_SERVER del .env si no coincide"
        )
        if info.server != settings.mt5_server:
            console.print(
                f"[yellow]⚠ Tu .env dice MT5_SERVER={settings.mt5_server!r} "
                f"pero el terminal está en {info.server!r}[/yellow]"
            )
    else:
        console.print(
            "[yellow]No hay cuenta logueada actualmente en el terminal.[/yellow]\n"
            "  Recomendación: abre MT5, File → Login to Trade Account, "
            "introduce credenciales y selecciona el server del dropdown."
        )

    # ─── Paso 5: login programático ───
    step(
        5,
        f"Login programático (login={settings.mt5_login}, server={settings.mt5_server!r})",
    )
    if not settings.mt5_login or not settings.mt5_password:
        console.print(
            "[yellow]Sin credenciales en .env — saltando login programático.[/yellow]"
        )
    else:
        ok = mt5.login(
            login=int(settings.mt5_login),
            password=settings.mt5_password,
            server=settings.mt5_server or None,
        )
        if not ok:
            err = mt5.last_error()
            console.print(f"[red]✗ login() falló: {err}[/red]")
            console.print(
                "  Causas frecuentes:\n"
                "  1. Server name no exacto. Suele ser:\n"
                "     - 'ICMarkets-Demo'  (clásico)\n"
                "     - 'ICMarketsSC-Demo'\n"
                "     - 'ICMarkets-Demo01' / 'ICMarkets-Demo02' / ...\n"
                "     - Si la demo es del propio MT5 (MetaQuotes) → 'MetaQuotes-Demo'\n"
                "  2. Cuenta de otro broker.\n"
                "  3. Login/password mal copiados (espacios al inicio/final).\n\n"
                "  Para saber el server exacto: en MT5 abre File → Login, mira el dropdown,\n"
                "  copia el nombre EXACTO al .env y vuelve a correr."
            )
            mt5.shutdown()
            return 1
        console.print("[green]✓[/green] login() OK")
        info = mt5.account_info()
        if info:
            console.print(
                f"  Cuenta: {info.name}  login={info.login}  server={info.server}  "
                f"balance={info.balance:.2f} {info.currency}  leverage=1:{info.leverage}"
            )

    # ─── Paso 6: símbolos ───
    step(6, "Test de símbolos (NAS100, XAUUSD, EURUSD)")
    from config.settings import get_symbols

    syms = get_symbols()
    table = Table()
    table.add_column("Activo")
    table.add_column("Broker symbol")
    table.add_column("Bid")
    table.add_column("Ask")
    table.add_column("OK")
    for name, cfg in syms.items():
        if not mt5.symbol_select(cfg.broker_symbol, True):
            table.add_row(name, cfg.broker_symbol, "—", "—", "[red]✗[/red]")
            continue
        tick = mt5.symbol_info_tick(cfg.broker_symbol)
        if tick is None:
            table.add_row(name, cfg.broker_symbol, "—", "—", "[red]no tick[/red]")
        else:
            table.add_row(
                name,
                cfg.broker_symbol,
                f"{tick.bid:.5f}",
                f"{tick.ask:.5f}",
                "[green]✓[/green]",
            )
    console.print(table)
    console.print(
        "[dim]Si algún símbolo falla, prueba en MT5: click derecho en Market Watch → 'Show All' "
        "o busca el nombre exacto y edita config/symbols.yaml.[/dim]"
    )

    mt5.shutdown()
    console.print("\n[bold green]✓ Diagnóstico completo[/bold green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
