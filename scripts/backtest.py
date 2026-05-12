"""
Triarch — backtester sobre histórico cacheado.

Carga `data_cache/history/{symbol}_{tf}.parquet` (creado por scripts.fetch_history),
corre las estrategias del activo a lo largo del histórico vela a vela, aplica
confluencia y simula la ejecución asumiendo SL/TP del propio Signal.

Métricas que reporta:
  • # trades, win rate, profit factor, expectancy en R
  • Sharpe-ratio (basado en R por trade)
  • Sortino-ratio (penaliza solo volatilidad negativa)
  • SQN (System Quality Number)
  • Avg win / avg loss / largest win / largest loss (en R)
  • Racha ganadora más larga / racha perdedora más larga
  • Max drawdown (en R) y duración media en velas
  • Equity curve (cum R) — útil para gráficos

Uso:
    python -m scripts.backtest                                    # todos los activos
    python -m scripts.backtest --symbol XAUUSD --from 2024-01-01
    python -m scripts.backtest --symbol USDJPY --to 2025-06-30 --out logs/bt.txt

Usable también desde Python (ej. dashboard):
    from scripts.backtest import backtest_symbol
    res = backtest_symbol(cfg, confluence, from_date=..., to_date=...)
"""
from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from loguru import logger

from config.settings import REPO_ROOT, SymbolConfig, get_settings, get_symbols
from confluence.filter import ConfluenceConfig, ConfluenceFilter
from engine.indicators import add_default_indicators, opening_range
from signals.schema import Direction, Signal
from strategies.base import StrategyContext
from strategies.registry import build_strategies

HISTORY_DIR = REPO_ROOT / "data_cache" / "history"
WARMUP_BARS = 100
MIN_BARS_FOR_EVAL = 60


# ─────────────────────────────────────────────────────────
# Resolución de un trade
# ─────────────────────────────────────────────────────────
def _resolve_trade(sig: Signal, future_bars: pd.DataFrame, max_bars: int = 200) -> dict:
    look = future_bars.iloc[:max_bars]
    risk = abs(sig.entry - sig.stop_loss)
    if risk <= 0:
        return {"outcome": "INVALID", "bars_held": 0, "pnl_r": 0.0}

    for i, (_, bar) in enumerate(look.iterrows()):
        hi, lo = float(bar["high"]), float(bar["low"])
        if sig.direction is Direction.LONG:
            hit_sl = lo <= sig.stop_loss
            hit_tp = hi >= sig.take_profit_1
        else:
            hit_sl = hi >= sig.stop_loss
            hit_tp = lo <= sig.take_profit_1
        if hit_sl and hit_tp:
            return {"outcome": "SL", "bars_held": i + 1, "pnl_r": -1.0}
        if hit_sl:
            return {"outcome": "SL", "bars_held": i + 1, "pnl_r": -1.0}
        if hit_tp:
            reward = abs(sig.take_profit_1 - sig.entry)
            return {"outcome": "TP", "bars_held": i + 1, "pnl_r": reward / risk}

    last_close = float(look.iloc[-1]["close"]) if len(look) else sig.entry
    pnl_pts = (last_close - sig.entry) if sig.direction is Direction.LONG else (sig.entry - last_close)
    return {"outcome": "TIMEOUT", "bars_held": len(look), "pnl_r": pnl_pts / risk}


# ─────────────────────────────────────────────────────────
# Métricas
# ─────────────────────────────────────────────────────────
def _streaks(returns: list[float]) -> tuple[int, int]:
    """Mayor racha ganadora y mayor racha perdedora."""
    longest_win = longest_loss = cur_win = cur_loss = 0
    for r in returns:
        if r > 0:
            cur_win += 1
            cur_loss = 0
            longest_win = max(longest_win, cur_win)
        elif r < 0:
            cur_loss += 1
            cur_win = 0
            longest_loss = max(longest_loss, cur_loss)
        else:
            cur_win = cur_loss = 0
    return longest_win, longest_loss


def _sharpe(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Sharpe-ratio aproximado a partir de R por trade (asume 1 trade ≈ 1 unidad temporal).
    Usamos 252 'trading days' como factor — convención de mercado."""
    if returns.std(ddof=0) == 0 or len(returns) < 2:
        return 0.0
    return float(returns.mean() / returns.std(ddof=0) * math.sqrt(periods_per_year))


def _sortino(returns: pd.Series, periods_per_year: int = 252) -> float:
    """Sortino-ratio: penaliza solo volatilidad negativa."""
    downside = returns[returns < 0]
    if len(downside) < 2 or downside.std(ddof=0) == 0:
        return 0.0
    return float(returns.mean() / downside.std(ddof=0) * math.sqrt(periods_per_year))


def _sqn(returns: pd.Series) -> float:
    """System Quality Number (Van Tharp). >1.7 ≈ aceptable, >2.5 ≈ bueno, >3 ≈ excelente."""
    if returns.std(ddof=0) == 0 or len(returns) < 2:
        return 0.0
    return float(math.sqrt(len(returns)) * returns.mean() / returns.std(ddof=0))


# ─────────────────────────────────────────────────────────
# Backtest de un símbolo
# ─────────────────────────────────────────────────────────
def backtest_symbol(
    cfg: SymbolConfig,
    confluence: ConfluenceFilter,
    from_date: datetime | None = None,
    to_date: datetime | None = None,
    bar_lookback: int = 300,
) -> dict:
    parquet_path = HISTORY_DIR / f"{cfg.name}_{cfg.timeframe}.parquet"
    if not parquet_path.exists():
        return {
            "symbol": cfg.name, "timeframe": cfg.timeframe,
            "error": f"No hay histórico en {parquet_path.name}. Corre scripts.fetch_history primero.",
        }

    df_full = pd.read_parquet(parquet_path).sort_values("time").reset_index(drop=True)
    if from_date is not None:
        df_full = df_full[df_full["time"] >= pd.Timestamp(from_date)].reset_index(drop=True)
    if to_date is not None:
        df_full = df_full[df_full["time"] <= pd.Timestamp(to_date)].reset_index(drop=True)
    if len(df_full) < MIN_BARS_FOR_EVAL + WARMUP_BARS:
        return {
            "symbol": cfg.name, "timeframe": cfg.timeframe,
            "error": f"Histórico insuficiente: {len(df_full)} velas.",
        }

    logger.info(f"▶  Backtest {cfg.name} {cfg.timeframe} — {len(df_full)} velas")

    strategies = build_strategies(cfg.strategies)
    trades: list[dict] = []
    seen_signal_keys: set[str] = set()

    for i in range(WARMUP_BARS, len(df_full) - 1):
        window = df_full.iloc[max(0, i - bar_lookback) : i + 1].copy()
        try:
            window = add_default_indicators(window)
            window = opening_range(window, minutes=15)
        except Exception:
            continue

        ctx = StrategyContext(symbol_cfg=cfg, df=window)
        sigs: list[Signal] = []
        for strat in strategies:
            try:
                _, sig = strat.evaluate(ctx)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"  strat {strat.name} explotó en idx={i}: {exc}")
                continue
            if sig:
                sigs.append(sig)
        if not sigs:
            continue

        decision = confluence.filter(sigs)
        if not decision.accepted or decision.chosen_signal is None:
            continue

        chosen = decision.chosen_signal
        bar_time = window.iloc[-1]["time"]
        dedup_key = f"{chosen.strategy}|{chosen.direction.value}|{bar_time}"
        if dedup_key in seen_signal_keys:
            continue
        seen_signal_keys.add(dedup_key)

        future = df_full.iloc[i + 1 :]
        if future.empty:
            break
        outcome = _resolve_trade(chosen, future)
        trades.append({
            "time": bar_time,
            "symbol": cfg.name,
            "strategy": chosen.strategy,
            "direction": chosen.direction.value,
            "entry": chosen.entry,
            "sl": chosen.stop_loss,
            "tp1": chosen.take_profit_1,
            "rr_planned": chosen.rr_ratio,
            "score": chosen.score,
            "outcome": outcome["outcome"],
            "bars_held": outcome["bars_held"],
            "pnl_r": outcome["pnl_r"],
        })

    if not trades:
        return {
            "symbol": cfg.name, "timeframe": cfg.timeframe, "trades": 0,
            "note": "Sin señales que pasaran confluencia en el rango.",
            "trade_log": [], "equity_curve": [],
        }

    df_t = pd.DataFrame(trades).sort_values("time").reset_index(drop=True)
    returns = df_t["pnl_r"].astype(float)

    wins_mask = returns > 0
    losses_mask = returns < 0
    wins = int(wins_mask.sum())
    losses = int(losses_mask.sum())
    win_rate = wins / len(returns) if len(returns) else 0
    gross_win = returns[wins_mask].sum()
    gross_loss = -returns[losses_mask].sum()
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else math.inf
    expectancy = float(returns.mean())

    avg_win = float(returns[wins_mask].mean()) if wins else 0.0
    avg_loss = float(returns[losses_mask].mean()) if losses else 0.0
    largest_win = float(returns.max()) if len(returns) else 0.0
    largest_loss = float(returns.min()) if len(returns) else 0.0

    df_t["cum_r"] = returns.cumsum()
    peak = df_t["cum_r"].cummax()
    drawdown = peak - df_t["cum_r"]
    max_dd_r = float(drawdown.max())

    longest_win_streak, longest_loss_streak = _streaks(returns.tolist())
    avg_bars_held = float(df_t["bars_held"].mean())

    sharpe = _sharpe(returns)
    sortino = _sortino(returns)
    sqn_val = _sqn(returns)

    df_t["week"] = pd.to_datetime(df_t["time"]).dt.to_period("W")
    trades_per_week = df_t.groupby("week").size().mean() if len(df_t) else 0

    by_strat = (
        df_t.groupby("strategy")["pnl_r"]
        .agg(["count", "mean", "sum"])
        .rename(columns={"count": "trades", "mean": "expectancy_r", "sum": "total_r"})
        .round(4)
        .to_dict(orient="index")
    )

    # Equity curve para gráficos
    equity_points = [
        {"time": str(t), "cum_r": float(c)}
        for t, c in zip(df_t["time"].astype(str), df_t["cum_r"])
    ]

    return {
        "symbol": cfg.name,
        "timeframe": cfg.timeframe,
        "profile": cfg.profile,
        "target_trades_wk": cfg.target_trades_wk,
        "range": {
            "from": str(df_t["time"].min()),
            "to": str(df_t["time"].max()),
        },
        "trades": int(len(df_t)),
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "profit_factor": round(profit_factor, 3) if math.isfinite(profit_factor) else float("inf"),
        "expectancy_r": round(expectancy, 4),
        "avg_win_r": round(avg_win, 4),
        "avg_loss_r": round(avg_loss, 4),
        "largest_win_r": round(largest_win, 4),
        "largest_loss_r": round(largest_loss, 4),
        "max_drawdown_r": round(max_dd_r, 3),
        "longest_win_streak": longest_win_streak,
        "longest_loss_streak": longest_loss_streak,
        "avg_bars_held": round(avg_bars_held, 2),
        "trades_per_week_avg": round(float(trades_per_week), 2),
        "sharpe_ratio": round(sharpe, 3),
        "sortino_ratio": round(sortino, 3),
        "sqn": round(sqn_val, 3),
        "by_strategy": by_strat,
        "trade_log": df_t.assign(time=df_t["time"].astype(str)).drop(columns=["week"]).to_dict(orient="records"),
        "equity_curve": equity_points,
    }


# ─────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────
def _format_summary(results: list[dict], from_date, to_date) -> str:
    lines: list[str] = []
    lines.append("=" * 72)
    lines.append(f"Triarch backtest — {datetime.now(timezone.utc).isoformat(timespec='seconds')}")
    if from_date:
        lines.append(f"Desde: {from_date.date()}")
    if to_date:
        lines.append(f"Hasta: {to_date.date()}")
    lines.append("=" * 72)
    for r in results:
        lines.append("")
        lines.append(f"▶ {r['symbol']}  [{r.get('timeframe','?')}]  perfil={r.get('profile','?')}")
        if "error" in r:
            lines.append(f"   ❌ {r['error']}")
            continue
        if r.get("trades", 0) == 0:
            lines.append(f"   ⚠  {r.get('note','')}")
            continue
        rng = r.get("range", {})
        lines.append(f"   rango: {rng.get('from','?')} → {rng.get('to','?')}")
        lines.append(f"   trades={r['trades']}  wins={r['wins']}  losses={r['losses']}  WR={r['win_rate']:.1%}")
        pf = r['profit_factor']
        pf_str = f"{pf:.2f}" if isinstance(pf, (int, float)) and math.isfinite(pf) else "∞"
        lines.append(f"   PF={pf_str}  E={r['expectancy_r']:+.3f}R  Sharpe={r['sharpe_ratio']}  Sortino={r['sortino_ratio']}  SQN={r['sqn']}")
        lines.append(f"   avg win={r['avg_win_r']:+.3f}R  avg loss={r['avg_loss_r']:+.3f}R  largest +{r['largest_win_r']:+.2f} / {r['largest_loss_r']:+.2f}R")
        lines.append(f"   max DD={r['max_drawdown_r']}R  rachas: +{r['longest_win_streak']} / -{r['longest_loss_streak']}  avg duración={r['avg_bars_held']} velas")
        lines.append(f"   trades/semana ≈ {r['trades_per_week_avg']} (objetivo {r['target_trades_wk']})")
        for sname, s in (r.get("by_strategy") or {}).items():
            lines.append(f"     · {sname}: {int(s['trades'])} trades  E={s['expectancy_r']:+.3f}R  total={s['total_r']:+.2f}R")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Triarch — backtest sobre histórico cacheado")
    parser.add_argument("--symbol", help="Símbolo único (default: todos los de symbols.yaml)")
    parser.add_argument("--timeframe", help="Override del TF (default: el del yaml)")
    parser.add_argument("--from", dest="from_date", help="Fecha ISO YYYY-MM-DD")
    parser.add_argument("--to", dest="to_date", help="Fecha ISO YYYY-MM-DD")
    parser.add_argument("--out", help="Escribir resumen a este archivo (txt/json)")
    args = parser.parse_args()

    settings = get_settings()
    symbols = get_symbols()
    targets: Iterable[SymbolConfig]
    if args.symbol:
        if args.symbol not in symbols:
            logger.error(f"Símbolo {args.symbol} no está en symbols.yaml")
            return 1
        cfg = symbols[args.symbol]
        if args.timeframe:
            cfg = cfg.model_copy(update={"timeframe": args.timeframe})
        targets = [cfg]
    else:
        targets = list(symbols.values())

    confluence = ConfluenceFilter(
        ConfluenceConfig(
            min_signals=settings.triarch_confluence_min_signals,
            min_families=settings.triarch_confluence_min_families,
            min_combined_score=settings.triarch_confluence_min_score,
        )
    )

    from_date = (
        datetime.fromisoformat(args.from_date).replace(tzinfo=timezone.utc)
        if args.from_date else None
    )
    to_date = (
        datetime.fromisoformat(args.to_date).replace(tzinfo=timezone.utc)
        if args.to_date else None
    )

    results = [
        backtest_symbol(cfg, confluence, from_date=from_date, to_date=to_date)
        for cfg in targets
    ]

    summary = _format_summary(results, from_date, to_date)
    print(summary)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        if out_path.suffix.lower() == ".json":
            # Limpiar equity_curve / trade_log opcionalmente para que no sea gigante
            out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
        else:
            out_path.write_text(summary, encoding="utf-8")
        logger.info(f"Resumen guardado en {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
