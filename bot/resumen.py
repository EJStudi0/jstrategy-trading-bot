"""Ganancia por día, semana y mes, contada en la hora del que mira el panel.

Sale de la curva de patrimonio (una foto por hora) más el valor de ahora mismo.
El día de cada foto se decide en la zona horaria del navegador: la medianoche es
la suya, no la del servidor.

La ganancia de un día es el patrimonio con el que acaba menos el patrimonio con
el que acabó el anterior; el primer día arranca en el capital inicial, así que
las comisiones de montar la cartera cuentan (son un gasto de verdad). Con los
acumulados de financiación y comisiones de cada foto, esa ganancia se reparte en
tres partes que suman exacto:

    ganancia = mercado + financiación − comisiones

«Mercado» es lo que movió el precio en la parte expuesta, más el deslizamiento al
operar. Si a una foto antigua le faltan los acumulados, el reparto de ese tramo
queda vacío (None) en vez de inventarse.
"""

from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional
from zoneinfo import ZoneInfo

# Por debajo de medio céntimo, un día no cuenta ni como positivo ni como negativo.
PLANO = 0.005
_NOMBRE_ZONA = re.compile(r"^[A-Za-z0-9_+\-]+(/[A-Za-z0-9_+\-]+){0,2}$")
UTC = timezone.utc


@dataclass(frozen=True)
class Punto:
    t: datetime                       # con zona (UTC)
    patrimonio: float
    financiacion: Optional[float]     # acumulada desde el inicio de la cartera
    comisiones: Optional[float]       # acumuladas desde el inicio de la cartera


def zona(nombre: Optional[str]):
    """La zona horaria pedida, o UTC si no existe o no es un nombre válido."""
    if not nombre or len(nombre) > 64 or not _NOMBRE_ZONA.match(nombre):
        return UTC
    try:
        return ZoneInfo(nombre)
    except Exception:            # nombre desconocido, carpeta en vez de zona, etc.
        return UTC


def _float(x) -> Optional[float]:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def instante(texto: str) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(str(texto))
    except (TypeError, ValueError):
        return None
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


_cache: dict = {}


def leer_curva(ruta: str) -> list:
    """Las fotos de la curva de patrimonio, en orden. Se vuelve a leer solo si el fichero cambió."""
    try:
        st = os.stat(ruta)
    except FileNotFoundError:
        return []
    firma = (ruta, st.st_mtime_ns, st.st_size)
    if _cache.get("firma") == firma:
        return _cache["puntos"]
    with open(ruta, newline="", encoding="utf-8") as fh:
        texto = fh.read()
    # El bot añade una línea por hora desde otro hilo: una última línea a medio escribir se ignora.
    texto = texto[: texto.rfind("\n") + 1]
    puntos = []
    for f in csv.DictReader(io.StringIO(texto, newline="")):
        t = instante(f.get("utc"))
        p = _float(f.get("patrimonio"))
        if t is None or p is None:
            continue
        puntos.append(Punto(t, p, _float(f.get("financiacion")), _float(f.get("comisiones"))))
    puntos.sort(key=lambda x: x.t)
    _cache.update(firma=firma, puntos=puntos)
    return puntos


def _resta(b: Optional[float], a: Optional[float]) -> Optional[float]:
    return None if a is None or b is None else b - a


def tramo(a: Punto, b: Punto) -> dict:
    """De la foto `a` a la `b`: ganancia y su reparto."""
    ganancia = b.patrimonio - a.patrimonio
    fin = _resta(b.financiacion, a.financiacion)
    com = _resta(b.comisiones, a.comisiones)
    mercado = None if fin is None or com is None else ganancia - fin + com
    return {
        "inicio": a.patrimonio, "fin": b.patrimonio, "ganancia": ganancia,
        "pct": ganancia / a.patrimonio * 100 if a.patrimonio else 0.0,
        "financiacion": fin, "comisiones": com, "mercado": mercado,
        "desde_utc": a.t.isoformat(timespec="seconds"), "hasta_utc": b.t.isoformat(timespec="seconds"),
    }


def dias(puntos: Iterable[Punto], inicio: Punto, tz) -> list:
    """Un registro por cada día (en la zona `tz`) que tenga alguna foto, del más antiguo al de hoy."""
    ultimo = {}
    for p in puntos:
        if p.t >= inicio.t:
            ultimo[p.t.astimezone(tz).date()] = p
    out, previo = [], inicio
    for fecha in sorted(ultimo):
        fin = ultimo[fecha]
        out.append({"fecha": fecha.isoformat(), **tramo(previo, fin)})
        previo = fin
    return out


def _suma(valores: list) -> Optional[float]:
    return None if any(v is None for v in valores) else sum(valores)


def _signo(g: float) -> int:
    return 1 if g > PLANO else -1 if g < -PLANO else 0


def agrupar(ds: list, clave: str) -> dict:
    """Junta días seguidos: la ganancia es la del primer al último (los días encadenan)."""
    inicio, fin = ds[0]["inicio"], ds[-1]["fin"]
    signos = [_signo(d["ganancia"]) for d in ds]
    mejor = max(ds, key=lambda d: d["ganancia"])
    peor = min(ds, key=lambda d: d["ganancia"])
    return {
        "clave": clave, "inicio": inicio, "fin": fin, "ganancia": fin - inicio,
        "pct": (fin - inicio) / inicio * 100 if inicio else 0.0,
        "financiacion": _suma([d["financiacion"] for d in ds]),
        "comisiones": _suma([d["comisiones"] for d in ds]),
        "mercado": _suma([d["mercado"] for d in ds]),
        "dias": len(ds), "dias_positivos": signos.count(1), "dias_negativos": signos.count(-1),
        "mejor": {"fecha": mejor["fecha"], "ganancia": mejor["ganancia"]},
        "peor": {"fecha": peor["fecha"], "ganancia": peor["ganancia"]},
    }


def _racha(completos: list) -> dict:
    """Días seguidos con el mismo signo al final de la serie (sin contar hoy)."""
    n, signo = 0, 0
    for d in reversed(completos):
        s = _signo(d["ganancia"])
        if n == 0:
            signo = s
        if s != signo:
            break
        n += 1
    return {"dias": n, "signo": signo}


def calcular(puntos: Iterable[Punto], inicio: Punto, ahora: Punto, nombre_zona: Optional[str]) -> dict:
    """Todo lo que enseña la vista de ganancias. `ahora` es el valor en vivo (se añade como última foto)."""
    tz = zona(nombre_zona)
    serie = [p for p in puntos if p.t < ahora.t] + [ahora]
    ds = dias(serie, inicio, tz)
    hoy = ahora.t.astimezone(tz).date()
    hoy_s = hoy.isoformat()

    por_mes = {}
    for d in ds:
        por_mes.setdefault(d["fecha"][:7], []).append(d)
    meses = [agrupar(v, k) for k, v in sorted(por_mes.items())]

    lunes = (hoy - timedelta(days=hoy.weekday())).isoformat()
    semana = [d for d in ds if d["fecha"] >= lunes]
    del_mes = por_mes.get(hoy_s[:7], [])
    de_hoy = [d for d in ds if d["fecha"] == hoy_s]
    completos = [d for d in ds if d["fecha"] < hoy_s]
    signos = [_signo(d["ganancia"]) for d in completos]

    return {
        "zona": getattr(tz, "key", "UTC"),
        "hoy_fecha": hoy_s,
        "inicio_utc": inicio.t.isoformat(timespec="seconds"),
        "dias": ds,
        "meses": meses,
        "resumen": {
            "hoy": agrupar(de_hoy, hoy_s) if de_hoy else None,
            "semana": agrupar(semana, lunes) if semana else None,
            "mes": agrupar(del_mes, hoy_s[:7]) if del_mes else None,
            "total": tramo(inicio, ahora),
            "dias_completos": len(completos),
            "media_dia": sum(d["ganancia"] for d in completos) / len(completos) if completos else None,
            "dias_positivos": signos.count(1),
            "dias_negativos": signos.count(-1),
            "mejor_dia": max(completos, key=lambda d: d["ganancia"], default=None),
            "peor_dia": min(completos, key=lambda d: d["ganancia"], default=None),
            "racha": _racha(completos),
        },
    }
