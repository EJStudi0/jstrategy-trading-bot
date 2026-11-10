"""Configuración del bot: rutas, entorno y ajustes que el panel puede cambiar."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import replace
from typing import Optional

from bot import datos
from bot.estrategia import Parametros

RAIZ = datos.RAIZ
RUTA_ESTADO = os.path.join(RAIZ, "estado_cartera.json")
RUTA_BOT = os.path.join(RAIZ, "estado_bot.json")
RUTA_DIARIO = os.path.join(RAIZ, "diario_operaciones.csv")
RUTA_PATRIMONIO = os.path.join(RAIZ, "patrimonio_historico.csv")
RUTA_ESTADO_ANTIGUO = os.path.join(RAIZ, "jorge_bot_state.json")

# Lo que el panel puede tocar, con sus límites. Fuera de aquí no se cambia nada
# en caliente: el resto de la estrategia está validado tal como está.
AJUSTABLES = {
    "vol_cartera":    {"min": 0.05, "max": 0.60, "paso": 0.01, "formato": "pct",
                       "etiqueta": "Riesgo objetivo de la cartera (volatilidad anual)"},
    "apalancamiento": {"min": 1.00, "max": 2.00, "paso": 0.25, "formato": "x",
                       "etiqueta": "Apalancamiento de la tendencia (×1 = sin deuda)"},
    "tope_base":      {"min": 0.10, "max": 0.80, "paso": 0.05, "formato": "pct",
                       "etiqueta": "Parte del capital en la base"},
    "cobertura_max":  {"min": 1.00, "max": 1.50, "paso": 0.05, "formato": "pct",
                       "etiqueta": "Cobertura máxima (100 % = neutral)"},
}

# Perfiles medidos en investigacion/perfiles.py. Validación 2024-01 → 2026-11:
#   prudente  (vol_cartera 0,15)                      +9 %/año, caída máxima −13 %
#   moderado  (por defecto)                          +12 %/año, caída máxima −18 %
#   decidido  (vol_cartera 0,40, apalancamiento 1,5) +16 %/año, caída máxima −27 %
#   agresivo  (vol_cartera 0,60, apalancamiento 2)   +23 %/año, caída máxima −37 %
# Por encima de ×2 la rentabilidad deja de subir y la caída no: no se ofrece.

MANDOS = ("auto", "pausa", "neutral", "fuera")


def _bool(nombre: str, defecto: bool) -> bool:
    v = os.getenv(nombre)
    return defecto if v is None else v.strip().lower() in {"1", "true", "yes", "on", "si", "sí"}


def simulacion() -> bool:
    return _bool("JORGE_BOT_PAPER", True)


def capital_inicial() -> float:
    """Capital de la simulación: el del entorno o, si no, donde quedó la simulación anterior."""
    v = os.getenv("JORGE_BOT_CAPITAL_USDT")
    if v:
        return float(v)
    try:
        with open(RUTA_ESTADO_ANTIGUO, encoding="utf-8") as fh:
            saldo = float(json.load(fh).get("balance"))
        if saldo > 0:
            return saldo
    except Exception:
        pass
    return 5000.0


def mercados() -> tuple:
    v = os.getenv("JORGE_BOT_MERCADOS")
    return tuple(m.strip() for m in v.split(",") if m.strip()) if v else datos.MERCADOS_POR_DEFECTO


def panel() -> dict:
    return {
        "activo": os.getenv("JORGE_BOT_PANEL", "1") not in ("0", "false", "no"),
        "host": os.getenv("JORGE_BOT_PANEL_HOST", "127.0.0.1"),
        "puerto": int(os.getenv("JORGE_BOT_PANEL_PORT", "8787")),
        "token": os.getenv("JORGE_BOT_PANEL_TOKEN", ""),
    }


def escribir_json(ruta: str, datos_: dict) -> None:
    carpeta = os.path.dirname(os.path.abspath(ruta))
    fd, tmp = tempfile.mkstemp(dir=carpeta, prefix=".tmp_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(datos_, fh, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def leer_json(ruta: str) -> dict:
    try:
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return {}


def validar_ajustes(cambios: dict) -> dict:
    """Devuelve solo los ajustes válidos, convertidos a número. Lanza ValueError si alguno no vale."""
    limpio = {}
    for clave, valor in cambios.items():
        if clave not in AJUSTABLES:
            raise ValueError(f"'{clave}' no se puede ajustar")
        try:
            x = float(valor)
        except (TypeError, ValueError):
            raise ValueError(f"'{clave}' debe ser un número")
        lim = AJUSTABLES[clave]
        if not (lim["min"] <= x <= lim["max"]):
            raise ValueError(f"'{clave}' debe estar entre {lim['min']} y {lim['max']}")
        limpio[clave] = x
    return limpio


def parametros(ajustes: Optional[dict] = None) -> Parametros:
    p = Parametros()
    if ajustes:
        p = replace(p, **validar_ajustes(ajustes))
    return p
