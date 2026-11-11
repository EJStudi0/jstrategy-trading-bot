"""Detección de patrones para el asistente. Funciones puras sobre velas CERRADAS de 30 min.

Cada patrón devuelve, vela a vela, hacia dónde apunta (+1 arriba, -1 abajo, 0 nada). Así el aviso en
vivo (la última vela) y la estadística de lo que pasó después las otras veces salen del mismo código.

«ruptura» es la regla medida en `investigacion/intradia.py` (jugada_inercia con ventana 96, volumen 2,5,
fondo a favor y movimiento ≥ 1) y `tests/test_patrones.py` comprueba que coinciden. El resto son las
jugadas del material de Jorge o alarmas de movimiento raro: avisan, no tienen ventaja demostrada.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

M30 = 30 * 60_000
HORIZONTE = 48  # velas de 30 min con las que se juzga un aviso: 24 h

CATALOGO = {
    "ruptura": {"nombre": "Ruptura con volumen",
                "que": "Cierra fuera del máximo o mínimo de 48 h con mucho volumen, con la tendencia de fondo a favor.",
                "medido": "Única jugada con algo de ventaja medida, y poca: acierta 1 de cada 5 y gana dejando correr días. "
                          "No pasó la prueba para operarla sola."},
    "ruptura_floja": {"nombre": "Ruptura sin el fondo a favor",
                      "que": "Rompe el máximo o mínimo de 48 h con volumen, pero la tendencia de fondo no acompaña.",
                      "medido": "Sin el fondo a favor, medida, no gana."},
    "barrido": {"nombre": "Barrido de liquidez",
                "que": "Perfora el máximo o mínimo de 48 h y cierra de vuelta dentro, dejando mecha larga.",
                "medido": "Sin ventaja demostrada. Señal de posible giro."},
    "sacudida": {"nombre": "Movimiento brusco",
                 "que": "En una hora se mueve más de tres veces lo normal del último mes.",
                 "medido": "Alarma, no señal: mira qué pasa antes de tocar nada."},
    "volumen": {"nombre": "Volumen anómalo",
                "que": "Entra cuatro veces el volumen normal sin romper nada todavía.",
                "medido": "Alarma, no señal."},
    "compresion": {"nombre": "Rango estrecho",
                   "que": "Ocho horas en un rango muy apretado: suele venir un movimiento, no dice hacia dónde.",
                   "medido": "Aviso de preparación. Entrar en el retroceso tras romper, medido, no gana."},
    "rebote_media": {"nombre": "Rebote en la media de 10",
                     "que": "Con la tendencia a favor, toca la media de 10 en 30 min y cierra de vuelta.",
                     "medido": "Jugada de Jorge. Como regla fija, medida, pierde después de costes."},
    "zona_virgen": {"nombre": "Primer regreso a zona virgen",
                    "que": "El precio vuelve por primera vez a la última vela contraria antes de un impulso que rompió estructura.",
                    "medido": "Jugada de Jorge. Como regla fija, medida, pierde después de costes."},
    "nivel": {"nombre": "Precio que pediste vigilar",
              "que": "El precio ha cruzado un nivel que marcaste tú.",
              "medido": "Es tu nivel: el asistente solo avisa."},
    "fondo": {"nombre": "Cambio de la tendencia de fondo",
              "que": "El diario y las 4 h pasan a estar los dos del mismo lado.",
              "medido": "Contexto, no entrada."},
}


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _wilder(x, n=14):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr(h, l, c, n=14):
    cp = np.r_[c[0], c[:-1]]
    return _wilder(np.maximum(h - l, np.maximum(abs(h - cp), abs(l - cp))), n)


def agrupar(t, o, h, l, c, v, minutos: int):
    """Junta velas en otras mayores alineadas al reloj UTC. `t` es la apertura; devuelve (cierre, o, h, l, c, v)."""
    paso = minutos * 60_000
    clave = t // paso
    ini = np.flatnonzero(np.r_[True, clave[1:] != clave[:-1]])
    fin = np.r_[ini[1:], len(t)] - 1
    return ((clave[ini] + 1) * paso, o[ini], np.maximum.reduceat(h, ini), np.minimum.reduceat(l, ini),
            c[fin], np.add.reduceat(v, ini))


def al_reloj(cierres, valores, instantes):
    """El último valor de una vela mayor YA CERRADA en cada instante."""
    i = np.searchsorted(cierres, instantes, side="right") - 1
    out = np.asarray(valores, dtype=float)[np.maximum(i, 0)]
    return np.where(i >= 0, out, np.nan)


def fondo(t4, o4, h4, l4, c4, v4, instantes) -> np.ndarray:
    """Tendencia de fondo en cada instante: +1 si el diario cierra sobre su media de 10 y las 4 h sobre
    la de 55; -1 si los dos por debajo; 0 si no coinciden o falta historia. `t4` son aperturas de 4 h."""
    tc4 = t4 + 240 * 60_000
    tcd, _, _, _, cd, _ = agrupar(t4, o4, h4, l4, c4, v4, 1440)
    d = al_reloj(tcd, np.sign(cd - ema(cd, 10)), instantes)
    s4 = al_reloj(tc4, np.sign(c4 - ema(c4, 55)), instantes)
    listo = (np.searchsorted(tcd, instantes, side="right") >= 20) & (np.searchsorted(tc4, instantes, side="right") >= 110)
    return np.where(listo & (d == s4), np.nan_to_num(d), 0.0)


def movimiento(t, o, h, l, c, v) -> np.ndarray:
    """Movimiento de 1 h frente a su media de 30 días, visto desde cada cierre de 30 min."""
    tc, _, h1, l1, c1, _ = agrupar(t, o, h, l, c, v, 60)
    a = atr(h1, l1, c1) / c1
    return al_reloj(tc, a / pd.Series(a).rolling(720, min_periods=240).mean().to_numpy(), t + M30)


def detectar(t, o, h, l, c, v, ctx, ventana=96, volumen=2.5) -> dict:
    """Todos los patrones sobre velas de 30 min (`t` = apertura). `ctx` = fondo en cada cierre.
    Devuelve {patrón: dirección por vela} y, en "_", lo que hace falta para sugerir un stop."""
    n = len(t)
    a = atr(h, l, c)
    S = pd.Series
    H = S(h).rolling(ventana).max().shift(1).to_numpy()
    L = S(l).rolling(ventana).min().shift(1).to_numpy()
    vm = S(v).rolling(ventana).mean().shift(1).to_numpy()
    mov = movimiento(t, o, h, l, c, v)
    out = {}

    rompe = np.where(c > H, 1.0, np.where(c < L, -1.0, 0.0))
    fuerte = v > volumen * vm
    buena = fuerte & (rompe != 0) & (ctx == rompe)
    out["ruptura"] = np.where(buena & (np.nan_to_num(mov) >= 1.0), rompe, 0.0)
    out["ruptura_floja"] = np.where(fuerte & (rompe != 0) & (ctx != rompe), rompe, 0.0)

    rango = np.maximum(h - l, 1e-12)
    abajo = (l < L) & (c > L) & ((np.minimum(o, c) - l) >= 0.6 * rango)
    arriba = (h > H) & (c < H) & ((h - np.maximum(o, c)) >= 0.6 * rango)
    out["barrido"] = np.where(abajo, 1.0, np.where(arriba, -1.0, 0.0))

    r2 = S(c).pct_change(2)
    sd = r2.rolling(960, min_periods=480).std().shift(1)
    brusco = (r2.abs() > 3 * sd).to_numpy()
    brusco = brusco & ~np.r_[False, brusco[:-1]]
    out["sacudida"] = np.where(brusco, np.sign(r2.fillna(0).to_numpy()), 0.0)

    mucho = (v > 4 * vm) & (rompe == 0)
    out["volumen"] = np.where(mucho, np.sign(c - o), 0.0)

    H16 = S(h).rolling(16).max().to_numpy()
    L16 = S(l).rolling(16).min().to_numpy()
    prieto = (H16 - L16) <= 3.0 * a
    out["compresion"] = (prieto & ~np.r_[False, prieto[:-1]]).astype(float) * 2.0  # 2 = sin dirección

    e10, e55 = ema(c, 10), ema(c, 55)
    reb = np.zeros(n)
    for d in (1.0, -1.0):
        toca = (l <= e10) if d == 1 else (h >= e10)
        previa = np.r_[False, d * (c[:-1] - e10[:-1]) > 0]
        reb[(ctx == d) & (d * (e10 - e55) > 0) & previa & toca & (d * (c - e10) > 0) & (d * (c - o) > 0)] = d
    out["rebote_media"] = reb

    out["zona_virgen"] = _zonas(t, o, h, l, c, v, ctx)

    cambia = (ctx != 0) & (np.r_[ctx[0], ctx[:-1]] != ctx)
    out["fondo"] = np.where(cambia, ctx, 0.0)
    out["_"] = {"atr": a, "mov": mov, "max": H, "min": L}
    return out


def _zonas(t, o, h, l, c, v, ctx, estructura=20, impulso=1.5, atras=5, caduca=72) -> np.ndarray:
    """Zona virgen como en la jugada C del estudio: marca la vela de 30 min del PRIMER regreso."""
    tc, o1, h1, l1, c1, _ = agrupar(t, o, h, l, c, v, 60)
    a = atr(h1, l1, c1)
    ap = np.r_[np.nan, a[:-1]]
    H = pd.Series(h1).rolling(estructura).max().shift(1).to_numpy()
    L = pd.Series(l1).rolling(estructura).min().shift(1).to_numpy()
    out = np.zeros(len(t))
    for d in (1.0, -1.0):
        rompe = (c1 > H) if d == 1 else (c1 < L)
        for q in np.flatnonzero(rompe & (d * (c1 - o1) > impulso * ap)):
            contrarias = [p for p in range(q - 1, max(q - 1 - atras, -1), -1) if d * (c1[p] - o1[p]) < 0]
            if not contrarias:
                continue
            borde = h1[contrarias[0]] if d == 1 else l1[contrarias[0]]
            if d * (c1[q] - borde) <= 0:
                continue
            i0 = int(np.searchsorted(t, tc[q], side="left"))
            i1 = min(i0 + caduca * 2, len(t))
            toca = (l[i0:i1] < borde) if d == 1 else (h[i0:i1] > borde)
            if toca.any():
                i = i0 + int(np.argmax(toca))
                if i >= 1 and ctx[i - 1] == d:
                    out[i] = d
    return out


def despues(pat: np.ndarray, c: np.ndarray, horizonte=HORIZONTE) -> np.ndarray:
    """Lo que se movió el precio A FAVOR del patrón en las `horizonte` velas siguientes, cada vez que salió."""
    i = np.flatnonzero((pat == 1) | (pat == -1))
    i = i[i + horizonte < len(c)]
    return pat[i] * (c[i + horizonte] / c[i] - 1)
