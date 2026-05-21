"""
Triarch — audit store sobre SQLite.

Tablas:
  - signals  (todas las señales emitidas o evaluadas con propuesta)
  - evals    (cada evaluación de cada estrategia × cada vela; incluye rechazos)
  - sessions (resumen diario por activo)
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from loguru import logger

from signals.schema import Eval, Signal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    signal_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy TEXT NOT NULL,
    family TEXT NOT NULL,
    direction TEXT NOT NULL,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit_1 REAL NOT NULL,
    take_profit_2 REAL,
    score REAL NOT NULL,
    confidence TEXT NOT NULL,
    risk_pts REAL NOT NULL,
    rr_ratio REAL NOT NULL,
    atr_at_signal REAL,
    status TEXT NOT NULL,
    reject_reason TEXT,
    features TEXT,           -- JSON
    mt5_ticket INTEGER,
    placed_at_utc TEXT,
    filled_price REAL,
    closed_at_utc TEXT,
    closed_price REAL,
    pnl_money REAL,
    pnl_pts REAL
);

CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, timestamp_utc);
CREATE INDEX IF NOT EXISTS idx_signals_status ON signals(status);

CREATE TABLE IF NOT EXISTS evals (
    eval_id TEXT PRIMARY KEY,
    timestamp_utc TEXT NOT NULL,
    symbol TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    strategy TEXT NOT NULL,
    family TEXT NOT NULL,
    detected_setup INTEGER NOT NULL,
    direction TEXT,
    score REAL,
    proposed_entry REAL,
    emitted_signal_id TEXT,
    blocked_by TEXT,
    blocked_detail TEXT,
    families_aligned TEXT,    -- JSON
    signals_aligned INTEGER
);

CREATE INDEX IF NOT EXISTS idx_evals_symbol_ts ON evals(symbol, timestamp_utc);

CREATE TABLE IF NOT EXISTS sessions (
    date TEXT NOT NULL,
    symbol TEXT NOT NULL,
    signals_emitted INTEGER DEFAULT 0,
    signals_taken INTEGER DEFAULT 0,
    pnl_money REAL DEFAULT 0,
    consec_losses_max INTEGER DEFAULT 0,
    locked_at TEXT,
    lock_reason TEXT,
    PRIMARY KEY (date, symbol)
);
"""


class AuditStore:
    def __init__(self, db_path: str = "data_cache/triarch.sqlite") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _init(self) -> None:
        with self._conn() as c:
            c.executescript(SCHEMA)
        logger.debug(f"AuditStore listo en {self.db_path}")

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    # ─────────────────────────────────────────────────────
    # Writes
    # ─────────────────────────────────────────────────────
    def save_signal(self, signal: Signal) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO signals VALUES (
                    :signal_id, :timestamp_utc, :symbol, :timeframe, :strategy, :family,
                    :direction, :entry, :stop_loss, :take_profit_1, :take_profit_2,
                    :score, :confidence, :risk_pts, :rr_ratio, :atr_at_signal,
                    :status, :reject_reason, :features,
                    :mt5_ticket, :placed_at_utc, :filled_price,
                    :closed_at_utc, :closed_price, :pnl_money, :pnl_pts
                )""",
                {
                    "signal_id": signal.signal_id,
                    "timestamp_utc": signal.timestamp_utc.isoformat(),
                    "symbol": signal.symbol,
                    "timeframe": signal.timeframe,
                    "strategy": signal.strategy,
                    "family": signal.family,
                    "direction": signal.direction.value,
                    "entry": signal.entry,
                    "stop_loss": signal.stop_loss,
                    "take_profit_1": signal.take_profit_1,
                    "take_profit_2": signal.take_profit_2,
                    "score": signal.score,
                    "confidence": signal.confidence.value,
                    "risk_pts": signal.risk_pts,
                    "rr_ratio": signal.rr_ratio,
                    "atr_at_signal": signal.atr_at_signal,
                    "status": signal.status.value,
                    "reject_reason": signal.reject_reason,
                    "features": (
                        json.dumps(signal.features) if signal.features else None
                    ),
                    "mt5_ticket": signal.mt5_ticket,
                    "placed_at_utc": (
                        signal.placed_at_utc.isoformat()
                        if signal.placed_at_utc
                        else None
                    ),
                    "filled_price": signal.filled_price,
                    "closed_at_utc": (
                        signal.closed_at_utc.isoformat()
                        if signal.closed_at_utc
                        else None
                    ),
                    "closed_price": signal.closed_price,
                    "pnl_money": signal.pnl_money,
                    "pnl_pts": signal.pnl_pts,
                },
            )

    def save_eval(self, ev: Eval) -> None:
        with self._conn() as c:
            c.execute(
                """INSERT OR REPLACE INTO evals VALUES (
                    :eval_id, :timestamp_utc, :symbol, :timeframe, :strategy, :family,
                    :detected_setup, :direction, :score, :proposed_entry,
                    :emitted_signal_id, :blocked_by, :blocked_detail,
                    :families_aligned, :signals_aligned
                )""",
                {
                    "eval_id": ev.eval_id,
                    "timestamp_utc": ev.timestamp_utc.isoformat(),
                    "symbol": ev.symbol,
                    "timeframe": ev.timeframe,
                    "strategy": ev.strategy,
                    "family": ev.family,
                    "detected_setup": int(ev.detected_setup),
                    "direction": ev.direction.value if ev.direction else None,
                    "score": ev.score,
                    "proposed_entry": ev.proposed_entry,
                    "emitted_signal_id": ev.emitted_signal_id,
                    "blocked_by": ev.blocked_by,
                    "blocked_detail": ev.blocked_detail,
                    "families_aligned": json.dumps(ev.families_aligned),
                    "signals_aligned": ev.signals_aligned,
                },
            )

    # ─────────────────────────────────────────────────────
    # Reads (para dashboard y postmortem)
    # ─────────────────────────────────────────────────────
    def list_signals(
        self,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[dict]:
        sql = "SELECT * FROM signals WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if since:
            sql += " AND timestamp_utc >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def list_evals(
        self,
        symbol: str | None = None,
        since: datetime | None = None,
        limit: int = 500,
    ) -> list[dict]:
        sql = "SELECT * FROM evals WHERE 1=1"
        params: list = []
        if symbol:
            sql += " AND symbol = ?"
            params.append(symbol)
        if since:
            sql += " AND timestamp_utc >= ?"
            params.append(since.isoformat())
        sql += " ORDER BY timestamp_utc DESC LIMIT ?"
        params.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
