"""Estado persistente en SQLite: sobrevive a reinicios, cortes de luz y caídas del proceso.

Cada modo (papel / real) tiene su propia base de datos para que una simulación
jamás pueda contaminar el estado de la cuenta real ni al revés.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS equity (
    ts INTEGER PRIMARY KEY, equity REAL NOT NULL, price REAL NOT NULL,
    weight REAL NOT NULL, target REAL
);
CREATE TABLE IF NOT EXISTS fills (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, order_id TEXT,
    side TEXT NOT NULL, qty REAL NOT NULL, price REAL NOT NULL, fee REAL NOT NULL, reason TEXT
);
CREATE TABLE IF NOT EXISTS decisions (ts INTEGER PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER NOT NULL, level TEXT NOT NULL, message TEXT NOT NULL
);
"""


class StateStore:
    def __init__(self, state_dir: str | Path, mode: str, durable: bool = True) -> None:
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / f"{mode}.db"
        self.mode = mode
        self.db = sqlite3.connect(self.path, timeout=30)
        self.db.execute("PRAGMA journal_mode=WAL")
        # durabilidad antes que velocidad (``durable=False`` solo para simulaciones y tests)
        self.db.execute(f"PRAGMA synchronous={'FULL' if durable else 'OFF'}")
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ----------------------------------------------------------- clave/valor
    def get(self, key: str, default: Any = None) -> Any:
        row = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def set(self, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT INTO kv(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
        self.db.commit()

    # --------------------------------------------------------------- series
    def record_equity(self, ts_ms: int, equity: float, price: float, weight: float, target: float | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO equity(ts, equity, price, weight, target) VALUES(?,?,?,?,?)",
            (ts_ms, equity, price, weight, target),
        )
        self.db.commit()

    def record_fill(self, ts_ms: int, order_id: str, side: str, qty: float, price: float, fee: float, reason: str) -> None:
        self.db.execute(
            "INSERT INTO fills(ts, order_id, side, qty, price, fee, reason) VALUES(?,?,?,?,?,?,?)",
            (ts_ms, order_id, side, qty, price, fee, reason),
        )
        self.db.commit()

    def record_decision(self, ts_ms: int, payload: dict) -> None:
        self.db.execute("INSERT OR REPLACE INTO decisions(ts, payload) VALUES(?,?)", (ts_ms, json.dumps(payload, default=str)))
        self.db.commit()

    def event(self, level: str, message: str) -> None:
        self.db.execute("INSERT INTO events(ts, level, message) VALUES(?,?,?)", (int(time.time() * 1000), level, message))
        self.db.commit()

    # -------------------------------------------------------------- lectura
    def equity_history(self, limit: int | None = None) -> list[tuple]:
        q = "SELECT ts, equity, price, weight, target FROM equity ORDER BY ts"
        rows = self.db.execute(q).fetchall()
        return rows[-limit:] if limit else rows

    def fills(self, limit: int = 20) -> list[tuple]:
        return self.db.execute(
            "SELECT ts, side, qty, price, fee, reason FROM fills ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()

    def last_decision(self) -> dict | None:
        row = self.db.execute("SELECT payload FROM decisions ORDER BY ts DESC LIMIT 1").fetchone()
        return json.loads(row[0]) if row else None

    def events(self, limit: int = 20) -> list[tuple]:
        return self.db.execute("SELECT ts, level, message FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()

    def close(self) -> None:
        self.db.close()


# ----------------------------------------------------------- interruptor manual
def stop_file(state_dir: str | Path) -> Path:
    return Path(state_dir) / "STOP"


def is_stopped(state_dir: str | Path) -> bool:
    """Interruptor de emergencia: mientras exista el fichero STOP el bot no envía órdenes."""
    return stop_file(state_dir).exists()


def set_stopped(state_dir: str | Path, stopped: bool, note: str = "") -> None:
    p = stop_file(state_dir)
    if stopped:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(note or "detenido manualmente\n", encoding="utf-8")
    elif p.exists():
        p.unlink()
