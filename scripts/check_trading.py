"""
Triarch — pre-vuelo de TRADING (verifica que el bot pueda EJECUTAR órdenes).

Distinto de diagnose_mt5 (que verifica la conexión): este script verifica todo
lo necesario para que una orden de mercado se EJECUTE de verdad en la cuenta:

  1. Terminal conectado + Algo Trading habilitado.
  2. Por cada activo: trade_mode (¿permite operar?), filling_mode (FOK/IOC/RETURN),
     trade_stops_level (distancia mínima de SL/TP), point, digits, spread.
  3. Qué modo de relleno usará el bot para ese símbolo.
  4. order_check (simulación SIN enviar) de una orden mínima → confirma que el
     broker la aceptaría (detecta 10030 unsupported filling, 10016 invalid stops,
     10018 market closed, etc.) ANTES de que el mercado abra.
  5. Con --live-test: coloca una orden REAL del lote mínimo y la CIERRA enseguida,
     probando el ciclo completo end-to-end en la cuenta demo.

Uso:
    python -m scripts.check_trading                 # solo diagnóstico (seguro)
    python -m scripts.check_trading --symbol XAUUSD # un solo activo
    python -m scripts.check_trading --live-test     # coloca+cierra orden real (demo)

Recomendado: correrlo el domingo por la noche cuando el mercado abre, con
--live-test sobre 1 activo, para confirmar que el lunes el bot operará.
"""

from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from config.settings import get_settings, get_symbols
from data_layer.mt5_client import MT5_AVAILABLE, MT5Client
from executor.auto import MAGIC_NUMBERS, AutoExecutor

console = Console()


def _filling_name(mt5, mode: int) -> str:
    return {
        mt5.ORDER_FILLING_FOK: "FOK",
        mt5.ORDER_FILLING_IOC: "IOC",
        mt5.ORDER_FILLING_RETURN: "RETURN",
    }.get(mode, str(mode))


def _trade_mode_name(mt5, mode: int) -> str:
    return {
        0: "DISABLED",
        1: "LONGONLY",
        2: "SHORTONLY",
        3: "CLOSEONLY",
        4: "FULL",
    }.get(mode, str(mode))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pre-vuelo de trading Triarch.")
    parser.add_argument("--symbol", help="Solo este activo (default: todos).")
    parser.add_argument(
        "--live-test",
        action="store_true",
        help="Coloca y cierra una orden REAL de lote mínimo (cuenta demo).",
    )
    args = parser.parse_args()

    console.print(Panel.fit("[bold]Triarch — Pre-vuelo de TRADING[/bold]", border_style="cyan"))

    if not MT5_AVAILABLE:
        console.print("[red]✗ Paquete MetaTrader5 no disponible (¿no estás en Windows?).[/red]")
        return 1

    import MetaTrader5 as mt5  # type: ignore

    settings = get_settings()
    client = MT5Client(settings)
    if not client.initialize():
        console.print("[red]✗ No se pudo conectar/loguear a MT5. Corre primero: python -m scripts.diagnose_mt5[/red]")
        return 1

    ti = mt5.terminal_info()
    if ti and not ti.trade_allowed:
        console.print(
            "[red]✗ ALGO TRADING DESHABILITADO en el terminal.[/red]\n"
            "  MT5 → Tools → Options → Expert Advisors → ✓ Allow algorithmic trading\n"
            "  (sin esto, el bot NUNCA podrá ejecutar órdenes)."
        )
        client.shutdown()
        return 1
    console.print("[green]✓[/green] Algo Trading habilitado en el terminal")

    info = client.account_info()
    if info:
        console.print(
            f"[green]✓[/green] Cuenta {info.login} · {info.server} · "
            f"balance {info.balance:.2f} {info.currency} · equity {info.equity:.2f}"
        )
        if settings.triarch_env.value != "demo":
            console.print("[yellow]⚠ TRIARCH_ENV no es 'demo' — cuidado con dinero real.[/yellow]")

    symbols = get_symbols()
    targets = (
        {args.symbol: symbols[args.symbol]}
        if args.symbol and args.symbol in symbols
        else symbols
    )

    # ─── Tabla de capacidades por símbolo ───
    console.print("\n[bold cyan]── Capacidades de ejecución por activo ──[/bold cyan]")
    table = Table()
    for col in ("Activo", "Broker", "Modo yaml", "trade_mode", "Fillings", "Bot usará", "stops_lvl", "spread"):
        table.add_column(col)

    ok_symbols: list[str] = []
    for name, cfg in targets.items():
        si = client.symbol_info(cfg.broker_symbol)
        if si is None:
            table.add_row(name, cfg.broker_symbol, cfg.mode.value, "[red]?[/red]", "—", "—", "—", "—")
            continue
        fillings = AutoExecutor._supported_fillings(mt5, si)
        will_use = _filling_name(mt5, fillings[0]) if fillings else "—"
        tm = _trade_mode_name(mt5, si.trade_mode)
        tm_disp = tm if tm == "FULL" else f"[yellow]{tm}[/yellow]"
        table.add_row(
            name,
            cfg.broker_symbol,
            cfg.mode.value,
            tm_disp,
            "/".join(_filling_name(mt5, f) for f in fillings),
            will_use,
            str(si.trade_stops_level),
            str(si.spread),
        )
        if si.trade_mode == 4:
            ok_symbols.append(name)
    console.print(table)

    # ─── order_check (dry-run) por símbolo ───
    console.print("\n[bold cyan]── order_check (simulación, NO envía) ──[/bold cyan]")
    for name, cfg in targets.items():
        si = client.symbol_info(cfg.broker_symbol)
        if si is None:
            continue
        lot = cfg.position_sizing.min_lot
        price = si.ask
        point = si.point or 0.0001
        # SL/TP a ~50 puntos para pasar el stops_level en el check
        dist = max(si.trade_stops_level, 50) * point
        sl = round(price - dist, si.digits)
        tp = round(price + dist, si.digits)
        fillings = AutoExecutor._supported_fillings(mt5, si)
        accepted = False
        detail = ""
        for filling in fillings:
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": cfg.broker_symbol,
                "volume": float(lot),
                "type": mt5.ORDER_TYPE_BUY,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 30,
                "magic": MAGIC_NUMBERS.get(cfg.strategies[0], 100000),
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            chk = mt5.order_check(req)
            if chk is None:
                detail = f"order_check None: {mt5.last_error()}"
                continue
            if chk.retcode in (0, mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                accepted = True
                detail = f"OK con filling {_filling_name(mt5, filling)} (margin req {chk.margin:.2f})"
                break
            if chk.retcode == 10030:
                detail = "filling no soportado, probando otro…"
                continue
            detail = f"retcode={chk.retcode} {chk.comment}"
            if chk.retcode == 10018:
                detail += " (mercado CERRADO — normal si es fin de semana)"
            break
        mark = "[green]✓[/green]" if accepted else "[yellow]△[/yellow]"
        console.print(f"  {mark} {name}: {detail}")

    # ─── live-test ───
    if args.live_test:
        test_sym = args.symbol or ok_symbols[0] if (args.symbol or ok_symbols) else None
        if not test_sym:
            console.print("[red]No hay símbolo con trade_mode=FULL para live-test.[/red]")
            client.shutdown()
            return 1
        console.print(
            f"\n[bold red]── LIVE TEST: orden REAL en {test_sym} (demo) ──[/bold red]"
        )
        cfg = symbols[test_sym]
        si = client.symbol_info(cfg.broker_symbol)
        lot = cfg.position_sizing.min_lot
        point = si.point or 0.0001
        dist = max(si.trade_stops_level, 100) * point
        price = si.ask
        sl = round(price - dist, si.digits)
        tp = round(price + dist * 2, si.digits)
        fillings = AutoExecutor._supported_fillings(mt5, si)
        placed_ticket = None
        for filling in fillings:
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": cfg.broker_symbol,
                "volume": float(lot),
                "type": mt5.ORDER_TYPE_BUY,
                "price": si.ask,
                "sl": sl,
                "tp": tp,
                "deviation": 30,
                "magic": 999999,  # magic de test
                "comment": "triarch:LIVETEST",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": filling,
            }
            res = mt5.order_send(req)
            if res is None:
                console.print(f"  order_send None ({_filling_name(mt5, filling)}): {mt5.last_error()}")
                continue
            if res.retcode == 10030:
                console.print(f"  filling {_filling_name(mt5, filling)} no soportado, probando otro…")
                continue
            if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                placed_ticket = res.order
                console.print(
                    f"[green]✓ ORDEN EJECUTADA[/green] ticket={res.order} "
                    f"filling={_filling_name(mt5, filling)} price={res.price} vol={res.volume}"
                )
                break
            console.print(f"  retcode={res.retcode} {res.comment}")
            if res.retcode == 10018:
                console.print("  [yellow]Mercado cerrado — reintenta cuando abra.[/yellow]")
                break

        # Cerrar la posición de test enseguida
        if placed_ticket is not None:
            positions = mt5.positions_get(symbol=cfg.broker_symbol) or ()
            pos = next((p for p in positions if p.magic == 999999), None)
            if pos:
                close_req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": cfg.broker_symbol,
                    "volume": pos.volume,
                    "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": pos.ticket,
                    "price": si.bid if pos.type == 0 else si.ask,
                    "deviation": 30,
                    "magic": 999999,
                    "comment": "triarch:LIVETEST-close",
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": AutoExecutor._supported_fillings(mt5, si)[0],
                }
                cres = mt5.order_send(close_req)
                if cres and cres.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                    console.print(f"[green]✓ Posición de test CERRADA[/green] (ticket {pos.ticket})")
                else:
                    console.print(
                        f"[yellow]⚠ No se pudo cerrar la posición de test automáticamente "
                        f"(retcode={getattr(cres,'retcode','?')}). Ciérrala a mano en MT5.[/yellow]"
                    )

    client.shutdown()
    console.print("\n[bold green]✓ Pre-vuelo completo.[/bold green]")
    console.print(
        "[dim]Si los símbolos muestran trade_mode=FULL y order_check OK (o 'mercado cerrado' "
        "en fin de semana), el bot ejecutará órdenes cuando el mercado abra y los activos estén "
        "en modo AUTO con take_trades=ON.[/dim]"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
