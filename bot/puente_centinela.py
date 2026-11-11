"""Centinela visto desde el panel: leer su estado y encenderlo o apagarlo.

Centinela (el bot de Bitcoin al contado, paquete `centinela/`) corre en su propio proceso
(`jstrategy-centinela.service`) y guarda todo en una base SQLite. El panel vive en el proceso de
Jorge, así que aquí solo se LEE esa base (abierta en solo lectura) y se pone o se quita el fichero
`STOP`, que es el interruptor que el propio Centinela mira antes de enviar cada orden. Nada de este
módulo importa el paquete `centinela`: si Centinela no está instalado o no ha arrancado nunca, el
panel lo dice y Jorge sigue igual.

Apagado no vende: Centinela conserva la posición que tenga y deja de operar hasta que se encienda.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from typing import Optional

from bot import config

DIR_ESTADO = os.path.join(config.RAIZ, "centinela_vivo", "state")
# La cuenta demo de Bitget (dinero ficticio, órdenes de verdad). La simulación interna (`papel.db`)
# se conserva, pero el panel enseña esta. Con claves, Centinela solo conecta a la demo (candado).
MODO = "real-demo"
# Decide al cierre de cada vela de una hora (más unos segundos): si el último latido es más viejo
# que esto, el proceso no está corriendo o lleva ciclos fallando.
LATIDO_MAXIMO_S = 75 * 60
HORA_S = 3600


def _utc(ms: Optional[float]) -> Optional[str]:
    if not ms:
        return None
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat(timespec="seconds")


def ruta_base(dir_estado: str = DIR_ESTADO) -> str:
    return os.path.join(dir_estado, f"{MODO}.db")


def ruta_stop(dir_estado: str = DIR_ESTADO) -> str:
    """El mismo fichero que `centinela.live.state.stop_file` (lo comprueba una prueba)."""
    return os.path.join(dir_estado, "STOP")


def encendido(dir_estado: str = DIR_ESTADO) -> bool:
    return not os.path.exists(ruta_stop(dir_estado))


def _abrir(dir_estado: str) -> Optional[sqlite3.Connection]:
    ruta = ruta_base(dir_estado)
    if not os.path.isfile(ruta):
        return None
    return sqlite3.connect(f"file:{ruta}?mode=ro", uri=True, timeout=5)


def _valor(db: sqlite3.Connection, clave: str, defecto=None):
    fila = db.execute("SELECT value FROM kv WHERE key=?", (clave,)).fetchone()
    return json.loads(fila[0]) if fila else defecto


def instantanea(dir_estado: str = DIR_ESTADO, ahora: Optional[float] = None) -> dict:
    """Todo lo que la sección «Centinela» enseña, salvo la curva."""
    ahora = time.time() if ahora is None else ahora
    base = {"instalado": False, "encendido": encendido(dir_estado), "en_marcha": False, "modo": MODO}
    try:
        db = _abrir(dir_estado)
    except sqlite3.Error:
        db = None
    if db is None:
        return base
    try:
        latido = _valor(db, "heartbeat")
        saldos = _valor(db, "balances") or {}
        riesgo = _valor(db, "risk") or {}
        # La primera foto con saldo: en la demo, antes de pasarle fondos, la cartera vale 0.
        primera = db.execute("SELECT equity FROM equity WHERE equity > 0 ORDER BY ts LIMIT 1").fetchone()
        ultima = db.execute("SELECT ts, equity, price, weight, target FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
        fila = db.execute("SELECT payload FROM decisions ORDER BY ts DESC LIMIT 1").fetchone()
        decision = json.loads(fila[0]) if fila else {}
        operaciones = [
            {"utc": _utc(ts), "lado": lado, "cantidad": cantidad, "precio": precio, "comision": comision, "motivo": motivo or ""}
            for ts, lado, cantidad, precio, comision, motivo in db.execute(
                "SELECT ts, side, qty, price, fee, reason FROM fills ORDER BY id DESC LIMIT 30")
        ]
        avisos = [
            {"utc": _utc(ts), "nivel": nivel, "texto": texto}
            for ts, nivel, texto in db.execute(
                "SELECT ts, level, message FROM events WHERE level != 'info' ORDER BY id DESC LIMIT 5")
        ]
        n_operaciones = db.execute("SELECT COUNT(*) FROM fills").fetchone()[0]
    except (sqlite3.Error, ValueError):
        return base
    finally:
        db.close()

    capital = float(primera[0]) if primera else None
    patrimonio = float(ultima[1]) if ultima else None
    pico = riesgo.get("peak_equity")
    en_marcha = bool(latido) and (ahora - latido / 1000) < LATIDO_MAXIMO_S
    proxima = (int(ahora // HORA_S) + 1) * HORA_S * 1000 if en_marcha else None
    pausa_hasta = max(riesgo.get("halted_until_ms") or 0, riesgo.get("cooldown_until_ms") or 0)
    return {
        **base,
        "instalado": True,
        "en_marcha": en_marcha,
        "latido_utc": _utc(latido),
        "proxima_decision_utc": _utc(proxima),
        "capital": capital,
        "patrimonio": patrimonio,
        "ganancia": (patrimonio - capital) if capital and patrimonio is not None else None,
        "ganancia_pct": ((patrimonio / capital - 1) * 100) if capital and patrimonio is not None else None,
        "caida_pct": ((patrimonio / pico - 1) * 100) if pico and patrimonio is not None else None,
        "precio": float(ultima[2]) if ultima else None,
        "peso": float(ultima[3]) if ultima else None,
        "objetivo": float(ultima[4]) if ultima and ultima[4] is not None else None,
        "btc": saldos.get("base"),
        "efectivo": saldos.get("quote"),
        "regimen": decision.get("regime") or "",
        "accion": decision.get("action") or "",
        "notas": list(decision.get("notes") or []),
        "explicacion": list(decision.get("explanation") or []),
        "vela": decision.get("bar"),
        "horas_retraso": decision.get("stale_hours"),
        "fuente": decision.get("data_source") or "",
        "cortafuegos_hasta_utc": _utc(pausa_hasta) if pausa_hasta and pausa_hasta / 1000 > ahora else None,
        "n_operaciones": n_operaciones,
        "operaciones": operaciones,
        "avisos": avisos,
    }


def curva(dir_estado: str = DIR_ESTADO, horas: int = 0, maximo: int = 600, ahora: Optional[float] = None) -> list:
    """La curva de patrimonio con el mismo formato que la de Jorge (`neto` = peso en BTC)."""
    ahora = time.time() if ahora is None else ahora
    try:
        db = _abrir(dir_estado)
    except sqlite3.Error:
        return []
    if db is None:
        return []
    try:
        desde = int((ahora - horas * HORA_S) * 1000) if horas else 0
        filas = db.execute("SELECT ts, equity, price, weight FROM equity WHERE ts >= ? AND equity > 0 ORDER BY ts", (desde,)).fetchall()
    except sqlite3.Error:
        return []
    finally:
        db.close()
    puntos = [{"utc": _utc(ts), "patrimonio": float(eq), "neto": float(peso), "btc": float(precio)}
              for ts, eq, precio, peso in filas]
    if len(puntos) > maximo:      # se aclara conservando siempre el último punto
        paso = len(puntos) / maximo
        puntos = [puntos[int(i * paso)] for i in range(maximo - 1)] + [puntos[-1]]
    return puntos


def poner_interruptor(encender: bool, dir_estado: str = DIR_ESTADO) -> dict:
    """Enciende (quita STOP) o apaga (lo pone). Apagado, Centinela no envía órdenes."""
    if not os.path.isdir(dir_estado):
        raise ValueError("Centinela todavía no ha arrancado en este proyecto")
    ruta = ruta_stop(dir_estado)
    if encender:
        try:
            os.unlink(ruta)
        except FileNotFoundError:
            pass
    else:
        with open(ruta, "w", encoding="utf-8") as fh:
            fh.write("apagado desde el panel\n")
    return {"encendido": encendido(dir_estado)}
