"""Jorge en futuros, intradía: tres jugadas sacadas de su material, medidas con costes.

Contexto en diario y 4 h, zona en 1 h, gatillo en 30 min, ejecución vela a vela de 15 min.
Solo velas cerradas. Nada gratis: comisión de Bitget (0,02 % limitada, 0,06 % a mercado),
deslizamiento en lo que va a mercado y financiación. El plan y lo que se fijó antes de mirar
resultados está en `intradia_plan.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

CACHE = Path(__file__).resolve().parent.parent / "datos_cache"
MONEDAS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT", "DOGEUSDT",
           "AVAXUSDT", "LINKUSDT", "LTCUSDT"]

M15 = 15 * 60_000
COM_LIMITADA = 0.0002   # Bitget futuros, orden que espera en el libro
COM_MERCADO = 0.0006    # Bitget futuros, orden que cruza
DESLIZ = 0.0002         # lo que se pierde al cruzar (mercado y stop)


# ---------------------------------------------------------------- velas e indicadores

@dataclass
class Velas:
    tc: np.ndarray  # instante de cierre (ms)
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray


def agrupar(t, o, h, l, c, v, minutos: int) -> Velas:
    """Junta velas de 15 min en velas mayores, alineadas al reloj UTC."""
    paso = minutos * 60_000
    clave = t // paso
    ini = np.flatnonzero(np.r_[True, clave[1:] != clave[:-1]])
    fin = np.r_[ini[1:], len(t)] - 1
    return Velas((clave[ini] + 1) * paso, o[ini], np.maximum.reduceat(h, ini),
                 np.minimum.reduceat(l, ini), c[fin], np.add.reduceat(v, ini))


def ema(x, n):
    return pd.Series(x).ewm(span=n, adjust=False).mean().to_numpy()


def _wilder(x, n):
    return pd.Series(x).ewm(alpha=1 / n, adjust=False).mean().to_numpy()


def atr(k: Velas, n=14):
    cp = np.r_[k.c[0], k.c[:-1]]
    return _wilder(np.maximum(k.h - k.l, np.maximum(abs(k.h - cp), abs(k.l - cp))), n)


def adx(k: Velas, n=14):
    sube = np.r_[0, np.diff(k.h)]
    baja = np.r_[0, -np.diff(k.l)]
    mas = np.where((sube > baja) & (sube > 0), sube, 0.0)
    menos = np.where((baja > sube) & (baja > 0), baja, 0.0)
    a = atr(k, n)
    dmas, dmenos = 100 * _wilder(mas, n) / a, 100 * _wilder(menos, n) / a
    return _wilder(100 * abs(dmas - dmenos) / np.maximum(dmas + dmenos, 1e-12), n)


def al_reloj(tc_mayor, valores, instantes):
    """El último valor de una vela mayor YA CERRADA en cada instante."""
    i = np.searchsorted(tc_mayor, instantes, side="right") - 1
    out = np.asarray(valores, dtype=float)[np.maximum(i, 0)]
    return np.where(i >= 0, out, np.nan)


# ---------------------------------------------------------------- una moneda preparada

@dataclass
class Moneda:
    nombre: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    ft: np.ndarray       # instantes de financiación
    fr: np.ndarray       # financiación acumulada
    k30: Velas = field(repr=False, default=None)
    k60: Velas = field(repr=False, default=None)
    i15_30: np.ndarray = field(repr=False, default=None)  # 1.ª vela de 15 min tras cerrar cada vela de 30
    ctx30: np.ndarray = field(repr=False, default=None)   # +1 alcista, -1 bajista, 0 nada (en cada cierre de 30)
    adx30: np.ndarray = field(repr=False, default=None)   # ADX de 1 h visto desde cada cierre de 30
    mov30: np.ndarray = field(repr=False, default=None)   # movimiento de 1 h frente a su media de 30 días


def cargar(nombre: str, desde=None, hasta=None) -> Moneda:
    d = np.load(CACHE / f"{nombre}_15m.npz")
    t = d["t"]
    m = np.ones(len(t), bool)
    if desde:
        m &= t >= pd.Timestamp(desde, tz="UTC").value // 10**6
    if hasta:
        m &= t < pd.Timestamp(hasta, tz="UTC").value // 10**6
    t, o, h, l, c, v = (d[x][m] for x in "tohlcv")
    f = np.load(CACHE / f"{nombre}_funding.npz")
    mon = Moneda(nombre, t, o, h, l, c, v, f["t"], np.cumsum(f["tasa"]))
    k30, k60 = agrupar(t, o, h, l, c, v, 30), agrupar(t, o, h, l, c, v, 60)
    k4, k1d = agrupar(t, o, h, l, c, v, 240), agrupar(t, o, h, l, c, v, 1440)
    mon.k30, mon.k60 = k30, k60
    mon.i15_30 = np.searchsorted(t, k30.tc, side="left")
    mon.ctx30 = contexto(k4, k1d, k30.tc)
    mon.adx30 = al_reloj(k60.tc, adx(k60), k30.tc)
    a60 = atr(k60) / k60.c
    mon.mov30 = al_reloj(k60.tc, a60 / pd.Series(a60).rolling(720, min_periods=240).mean().to_numpy(), k30.tc)
    mon._k4, mon._k1d = k4, k1d
    return mon


def contexto(k4: Velas, k1d: Velas, instantes) -> np.ndarray:
    """Tendencia de fondo: cierre diario respecto a su media de 10 y cierre de 4 h respecto a la de 55."""
    d = al_reloj(k1d.tc, np.sign(k1d.c - ema(k1d.c, 10)), instantes)
    c4 = al_reloj(k4.tc, np.sign(k4.c - ema(k4.c, 55)), instantes)
    arranque = (np.searchsorted(k1d.tc, instantes, side="right") >= 20) & \
               (np.searchsorted(k4.tc, instantes, side="right") >= 110)
    return np.where(arranque & (d == c4), np.nan_to_num(d), 0.0)


# ---------------------------------------------------------------- las tres jugadas

@dataclass
class Señales:
    i: np.ndarray        # vela de 15 min desde la que vale la orden
    d: np.ndarray        # +1 largo, -1 corto
    nivel: np.ndarray    # precio de la orden limitada (nan = a mercado en la apertura)
    stop: np.ndarray
    vida: np.ndarray     # velas de 15 min que la orden espera
    adx: np.ndarray      # ADX de 1 h al dar la señal (para filtrar después)
    mov: np.ndarray = None  # movimiento relativo al dar la señal

    def donde(self, m):
        return Señales(*[None if x is None else x[m] for x in (self.i, self.d, self.nivel, self.stop, self.vida, self.adx, self.mov)])


def _señales(mon, j30, d, nivel, stop, vida):
    j30 = np.asarray(j30, int)
    i = mon.i15_30[j30]
    ok = i < len(mon.t)
    return Señales(i[ok], np.asarray(d, float)[ok], np.asarray(nivel, float)[ok],
                   np.asarray(stop, float)[ok], np.full(ok.sum(), vida), mon.adx30[j30][ok], mon.mov30[j30][ok])


def jugada_ruptura(mon: Moneda, ventana=16, estrechez=3.0, volumen=1.5, espera=8, margen=1.0) -> Señales:
    """A · Rango estrecho de `ventana` velas de 30 min, cierre fuera con volumen, a favor del fondo.
    Orden limitada en el borde roto (el retroceso), viva `espera` velas. Stop a `margen` ATR."""
    k = mon.k30
    a = atr(k)
    H = pd.Series(k.h).rolling(ventana).max().shift(1).to_numpy()
    L = pd.Series(k.l).rolling(ventana).min().shift(1).to_numpy()
    vm = pd.Series(k.v).rolling(ventana).mean().shift(1).to_numpy()
    ap = np.r_[np.nan, a[:-1]]
    estrecho = (H - L) <= estrechez * ap
    fuerte = k.v > volumen * vm
    js, ds, niv, st = [], [], [], []
    for d, borde, fuera in ((1, H, k.c > H), (-1, L, k.c < L)):
        j = np.flatnonzero(estrecho & fuerte & fuera & (mon.ctx30 == d))
        js.append(j); ds.append(np.full(len(j), d)); niv.append(borde[j]); st.append(borde[j] - d * margen * a[j])
    orden = np.argsort(np.concatenate(js), kind="stable")
    return _señales(mon, np.concatenate(js)[orden], np.concatenate(ds)[orden],
                    np.concatenate(niv)[orden], np.concatenate(st)[orden], espera * 2)


def jugada_inercia(mon: Moneda, ventana=48, volumen=2.5, margen=1.0, fondo=True) -> Señales:
    """D · Inercia: la vela de 30 min cierra por fuera del máximo/mínimo de `ventana` velas con volumen
    `volumen` veces el normal. Entrada a mercado en la apertura siguiente; stop a `margen` ATR del cierre."""
    k = mon.k30
    a = atr(k)
    H = pd.Series(k.h).rolling(ventana).max().shift(1).to_numpy()
    L = pd.Series(k.l).rolling(ventana).min().shift(1).to_numpy()
    fuerte = k.v > volumen * pd.Series(k.v).rolling(ventana).mean().shift(1).to_numpy()
    d = np.where(k.c > H, 1.0, np.where(k.c < L, -1.0, 0.0))
    j = np.flatnonzero(fuerte & (d != 0) & ((mon.ctx30 == d) | (not fondo)))
    return _señales(mon, j, d[j], np.full(len(j), np.nan), k.c[j] - d[j] * margen * a[j], 1)


def jugada_rebote(mon: Moneda, colchon=0.25, minimo=0.5) -> Señales:
    """B · Con el fondo a favor y la media de 10 por encima de la de 55 en 30 min, la vela toca la
    media de 10 y cierra de vuelta a favor. Entrada a mercado en la apertura siguiente."""
    k = mon.k30
    a, e10, e55 = atr(k), ema(k.c, 10), ema(k.c, 55)
    js, ds, st = [], [], []
    for d in (1, -1):
        toca = (k.l <= e10) if d == 1 else (k.h >= e10)
        previa = np.r_[False, d * (k.c[:-1] - e10[:-1]) > 0]
        j = np.flatnonzero((mon.ctx30 == d) & (d * (e10 - e55) > 0) & previa & toca
                           & (d * (k.c - e10) > 0) & (d * (k.c - k.o) > 0))
        j = j[j >= 1]
        extremo = np.minimum(k.l[j], k.l[j - 1]) if d == 1 else np.maximum(k.h[j], k.h[j - 1])
        s = extremo - d * colchon * a[j]
        s = np.where(d * (k.c[j] - s) < minimo * a[j], k.c[j] - d * minimo * a[j], s)
        js.append(j); ds.append(np.full(len(j), d)); st.append(s)
    orden = np.argsort(np.concatenate(js), kind="stable")
    j = np.concatenate(js)[orden]
    return _señales(mon, j, np.concatenate(ds)[orden], np.full(len(j), np.nan), np.concatenate(st)[orden], 1)


def jugada_zona(mon: Moneda, estructura=20, impulso=1.5, atras=5, caduca=72, colchon=0.25) -> Señales:
    """C · Zona virgen: en 1 h, una vela de cuerpo grande rompe el máximo de `estructura` velas; la zona
    es la última vela contraria anterior. Orden limitada en el borde de la zona, solo en el PRIMER regreso
    y con el fondo todavía a favor. Stop al otro lado de la zona."""
    k = mon.k60
    a = atr(k)
    ap = np.r_[np.nan, a[:-1]]
    H = pd.Series(k.h).rolling(estructura).max().shift(1).to_numpy()
    L = pd.Series(k.l).rolling(estructura).min().shift(1).to_numpy()
    out = []
    for d in (1, -1):
        rompe = (k.c > H) if d == 1 else (k.c < L)
        for q in np.flatnonzero(rompe & (d * (k.c - k.o) > impulso * ap)):
            contrarias = [p for p in range(q - 1, max(q - 1 - atras, -1), -1) if d * (k.c[p] - k.o[p]) < 0]
            if not contrarias:
                continue
            p = contrarias[0]
            borde, fondo = (k.h[p], k.l[p]) if d == 1 else (k.l[p], k.h[p])
            if d * (k.c[q] - borde) <= 0:
                continue
            i0 = np.searchsorted(mon.t, k.tc[q], side="left")
            i1 = min(i0 + caduca * 4, len(mon.t))
            toca = (mon.l[i0:i1] < borde) if d == 1 else (mon.h[i0:i1] > borde)
            if not toca.any():
                continue
            i = i0 + int(np.argmax(toca))
            j30 = np.searchsorted(mon.k30.tc, mon.t[i], side="right") - 1  # última de 30 cerrada antes
            if j30 < 0 or mon.ctx30[j30] != d:
                continue
            out.append((i, d, borde, fondo - d * colchon * a[q], mon.adx30[j30]))
    out.sort()
    z = np.array(out, float).reshape(-1, 5)
    return Señales(z[:, 0].astype(int), z[:, 1], z[:, 2], z[:, 3], np.ones(len(z), int), z[:, 4])


# ---------------------------------------------------------------- simulación de las operaciones

def simular(mon: Moneda, s: Señales, objetivo=1.5, aguante=24, adx_min=0.0, horas=None,
            laborables=False, lados=(1, -1), stop_max=0.03, seguir=None) -> pd.DataFrame:
    """Una posición a la vez por moneda. `aguante` en velas de 15 min. Si en una misma vela caben el
    stop y el objetivo, cuenta el stop. La orden limitada solo se da por hecha si el precio la atraviesa.
    `seguir`: el stop sube detrás del mejor precio YA cerrado, a esa distancia en veces el riesgo inicial."""
    t, o, h, l, c = mon.t, mon.o, mon.h, mon.l, mon.c
    n = len(t)
    libre = 0
    filas = []
    for i0, d, nivel, stop, vida, ax in zip(s.i, s.d, s.nivel, s.stop, s.vida, s.adx):
        if i0 < libre or d not in lados or not ax >= adx_min:
            continue
        momento = pd.Timestamp(t[i0], unit="ms")
        if horas and not (horas[0] <= momento.hour < horas[1]):
            continue
        if laborables and momento.dayofweek >= 5:
            continue
        mercado = np.isnan(nivel)
        ie = -1
        if mercado:
            ie, entrada = i0, o[i0] * (1 + d * DESLIZ)
        else:
            for i in range(i0, min(i0 + int(vida), n)):
                if (d == 1 and l[i] < nivel) or (d == -1 and h[i] > nivel):
                    ie, entrada = i, (min(nivel, o[i]) if d == 1 else max(nivel, o[i]))
                    break
        riesgo = d * (entrada - stop) / entrada if ie >= 0 else 0
        if ie < 0 or riesgo <= 0.0005 or riesgo > stop_max:
            continue
        meta = entrada + d * objetivo * abs(entrada - stop)
        salida, motivo, com = None, "tiempo", COM_MERCADO
        dist, mejor = abs(entrada - stop), entrada
        ult = min(ie + aguante, n) - 1
        for i in range(ie, ult + 1):
            if (d == 1 and l[i] <= stop) or (d == -1 and h[i] >= stop):
                px = stop if i == ie else (min(stop, o[i]) if d == 1 else max(stop, o[i]))
                salida, motivo, isal = px * (1 - d * DESLIZ), "stop", i
                break
            if (i > ie or mercado) and ((d == 1 and h[i] > meta) or (d == -1 and l[i] < meta)):
                salida, motivo, com, isal = meta, "objetivo", COM_LIMITADA, i
                break
            if seguir:
                mejor = max(mejor, h[i]) if d == 1 else min(mejor, l[i])
                stop = max(stop, mejor - seguir * dist) if d == 1 else min(stop, mejor + seguir * dist)
        if salida is None:
            isal, salida = ult, c[ult] * (1 - d * DESLIZ)
        a, b = np.searchsorted(mon.ft, [t[ie], t[isal] + M15], side="right")
        fin = (mon.fr[b - 1] - mon.fr[a - 1]) if b > a and a > 0 else 0.0
        neto = d * (salida / entrada - 1) - (COM_MERCADO if mercado else COM_LIMITADA) - com - d * fin
        filas.append((mon.nombre, t[ie], t[isal] + M15, d, entrada, stop, salida, motivo, riesgo, neto, neto / riesgo))
        libre = isal + 1
    df = pd.DataFrame(filas, columns=["moneda", "entra", "sale", "lado", "entrada", "stop", "salida",
                                      "motivo", "riesgo", "neto", "R"])
    df["entra"] = pd.to_datetime(df["entra"], unit="ms")
    df["sale"] = pd.to_datetime(df["sale"], unit="ms")
    return df


def resumen(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0}
    g, p = df.R[df.R > 0].sum(), -df.R[df.R <= 0].sum()
    return {"n": len(df), "acierto_pct": round(100 * (df.neto > 0).mean(), 1),
            "neto_medio_pct": round(100 * df.neto.mean(), 3), "R_medio": round(df.R.mean(), 3),
            "factor": round(g / p, 2) if p else np.nan, "R_total": round(df.R.sum(), 1),
            "stop_pct": round(100 * (df.motivo == "stop").mean(), 1),
            "riesgo_medio_pct": round(100 * df.riesgo.mean(), 2)}


def cartera(df: pd.DataFrame, riesgo=0.005, palanca_max=3.0, simultaneas=3) -> pd.Series:
    """Cuenta única que compone: cada operación arriesga `riesgo` de la cuenta en ese momento."""
    df = df.sort_values("entra")
    capital, abiertas, curva = 1.0, [], {}
    for r in df.itertuples():
        for x in [x for x in abiertas if x[0] <= r.entra]:
            capital += x[1]; curva[x[0]] = capital; abiertas.remove(x)
        if len(abiertas) >= simultaneas:
            continue
        nocional = capital * min(riesgo / r.riesgo, palanca_max)
        abiertas.append((r.sale, nocional * r.neto))
        abiertas.sort()
    for x in abiertas:
        capital += x[1]; curva[x[0]] = capital
    return pd.Series(curva).sort_index()


def medir(df: pd.DataFrame, riesgo=0.005, palanca_max=3.0, simultaneas=4) -> dict:
    """La cuenta compuesta en cuatro números: crecimiento anual, caída máxima, meses en positivo y peor mes."""
    dia = cartera(df, riesgo, palanca_max, simultaneas).resample("1D").last().ffill()
    mes = dia.resample("ME").last().pct_change().dropna()
    anios = (dia.index[-1] - dia.index[0]).days / 365.25
    return {"cagr": round(100 * (dia.iloc[-1] ** (1 / anios) - 1), 1),
            "caida": round(100 * (dia / dia.cummax() - 1).min(), 1),
            "meses+": round(100 * (mes > 0).mean()), "peor_mes": round(100 * mes.min(), 1)}
