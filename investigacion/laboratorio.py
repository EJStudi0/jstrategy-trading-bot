"""Laboratorio: cuadrícula común de precios, simulador de cartera y métricas.

El simulador trabaja con PESOS: fracción del patrimonio puesta en cada moneda
(negativa = corto). Un peso decidido al cierre de la vela `k` se mantiene hasta
el cierre de la `k+1`; paga comisión por lo que se mueve y financiación por lo
que se mantiene. Es deliberadamente simple para que no haya dónde esconder un
vistazo al futuro: lo único que entra en la decisión de `k` es lo que ya había
cerrado en `k`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import pandas as pd

from bot import datos
from bot.estrategia import hay_que_mover

UNIVERSO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
            "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]

VELAS_ANIO = {"15m": 4 * 24 * 365, "1h": 24 * 365, "2h": 12 * 365, "4h": 6 * 365,
              "8h": 3 * 365, "12h": 2 * 365, "1d": 365}

# Coste por lado de cada operación, sobre el nocional movido:
# 0,05 % de comisión de tomador en Binance USDT-M + 0,02 % de deslizamiento.
COSTE_POR_LADO = 0.0007


@dataclass
class Cuadricula:
    """Matrices tiempo × moneda. NaN donde la moneda aún no cotizaba."""

    intervalo: str
    simbolos: list
    t: np.ndarray            # apertura de cada vela, ms UTC
    O: np.ndarray
    H: np.ndarray
    L: np.ndarray
    C: np.ndarray
    V: np.ndarray
    F: np.ndarray            # financiación que paga un largo de peso 1 al mantener tras el cierre de k

    @property
    def n(self) -> int:
        return len(self.t)

    @property
    def velas_anio(self) -> float:
        return VELAS_ANIO[self.intervalo]

    def fechas(self) -> pd.DatetimeIndex:
        # Apertura de cada vela: el rendimiento de la vela k se gana DENTRO de ella.
        return pd.to_datetime(self.t, unit="ms", utc=True)

    def recorte(self, desde: Optional[str] = None, hasta: Optional[str] = None) -> "Cuadricula":
        m = np.ones(self.n, dtype=bool)
        if desde:
            m &= self.t >= datos._a_ms(desde)
        if hasta:
            m &= self.t < datos._a_ms(hasta)
        return Cuadricula(self.intervalo, self.simbolos, self.t[m], self.O[m], self.H[m],
                          self.L[m], self.C[m], self.V[m], self.F[m])

    def columnas(self, simbolos: list) -> "Cuadricula":
        j = [self.simbolos.index(s) for s in simbolos]
        return Cuadricula(self.intervalo, list(simbolos), self.t, self.O[:, j], self.H[:, j],
                          self.L[:, j], self.C[:, j], self.V[:, j], self.F[:, j])


_CACHE: dict = {}


def cuadricula(intervalo: str = "4h", simbolos: Optional[list] = None) -> Cuadricula:
    simbolos = list(simbolos or UNIVERSO)
    clave = (intervalo, tuple(simbolos))
    if clave in _CACHE:
        return _CACHE[clave]
    series = [datos.reagrupar(datos.cargar_velas(s, "15m"), intervalo) for s in simbolos]
    t = np.unique(np.concatenate([v.t for v in series]))
    T, N = len(t), len(simbolos)
    mats = {k: np.full((T, N), np.nan) for k in "OHLCV"}
    F = np.zeros((T, N))
    ms = datos.MS[intervalo]
    cierres = t + ms
    for j, v in enumerate(series):
        pos = np.searchsorted(t, v.t)
        for k, col in zip("OHLCV", (v.o, v.h, v.l, v.c, v.v)):
            mats[k][pos, j] = col
        ft, fr = datos.descargar_funding(simbolos[j])
        # El evento en τ lo paga la posición decidida en la última vela cerrada ANTES de τ.
        k = np.searchsorted(cierres, ft, side="left") - 1
        ok = (k >= 0) & (k < T)
        np.add.at(F[:, j], k[ok], fr[ok])
    g = Cuadricula(intervalo, simbolos, t, mats["O"], mats["H"], mats["L"], mats["C"], mats["V"], F)
    _CACHE[clave] = g
    return g


@dataclass
class Resultado:
    fechas: pd.DatetimeIndex
    rend: np.ndarray                 # rendimiento neto por vela
    patrimonio: np.ndarray
    rotacion: np.ndarray             # nocional movido por vela (fracción del patrimonio)
    bruto: np.ndarray                # apalancamiento bruto mantenido
    neto: np.ndarray                 # exposición neta mantenida
    coste: np.ndarray
    financiacion: np.ndarray
    por_moneda: np.ndarray           # PnL por vela y moneda (antes de costes)
    velas_anio: float
    extra: dict = field(default_factory=dict)

    def diario(self) -> pd.Series:
        s = pd.Series(np.log1p(self.rend), index=self.fechas)
        return np.expm1(s.groupby(s.index.floor("D")).sum())

    def metricas(self) -> dict:
        d = self.diario()
        anios = len(self.rend) / self.velas_anio
        total = float(self.patrimonio[-1] / self.patrimonio[0])
        cagr = total ** (1 / anios) - 1 if anios > 0 and total > 0 else -1.0
        vol = float(d.std() * np.sqrt(365))
        sharpe = float(d.mean() / d.std() * np.sqrt(365)) if d.std() > 0 else 0.0
        negativos = d[d < 0]
        sortino = float(d.mean() / np.sqrt((negativos ** 2).mean()) * np.sqrt(365)) if len(negativos) else 0.0
        pico = np.maximum.accumulate(self.patrimonio)
        dd = self.patrimonio / pico - 1
        mensual = np.expm1(np.log1p(d).groupby([d.index.year, d.index.month]).sum())
        return {
            "anios": round(anios, 2),
            "total_pct": round((total - 1) * 100, 1),
            "cagr_pct": round(cagr * 100, 1),
            "vol_pct": round(vol * 100, 1),
            "sharpe": round(sharpe, 2),
            "sortino": round(sortino, 2),
            "max_dd_pct": round(float(dd.min()) * 100, 1),
            "calmar": round(cagr / abs(float(dd.min())), 2) if dd.min() < 0 else 0.0,
            "meses_positivos_pct": round(float((mensual > 0).mean()) * 100, 0),
            "peor_mes_pct": round(float(mensual.min()) * 100, 1),
            "rotacion_anual": round(float(self.rotacion.sum() / anios), 1),
            "coste_anual_pct": round(float(self.coste.sum() / anios) * 100, 2),
            "financiacion_anual_pct": round(float(self.financiacion.sum() / anios) * 100, 2),
            "bruto_medio": round(float(self.bruto.mean()), 2),
            "neto_medio": round(float(self.neto.mean()), 2),
        }

    def por_anio(self) -> pd.DataFrame:
        d = self.diario()
        filas = []
        for a, g in d.groupby(d.index.year):
            eq = (1 + g).cumprod()
            dd = float((eq / eq.cummax() - 1).min())
            filas.append({"año": a, "rend_pct": round(float(eq.iloc[-1] - 1) * 100, 1),
                          "max_dd_pct": round(dd * 100, 1),
                          "sharpe": round(float(g.mean() / g.std() * np.sqrt(365)), 2) if g.std() > 0 else 0.0})
        return pd.DataFrame(filas).set_index("año")


def simular(g: Cuadricula, W: np.ndarray, coste=COSTE_POR_LADO,
            banda_abs: float = 0.0, banda_rel: float = 0.0,
            con_financiacion: bool = True, retraso: int = 0) -> Resultado:
    """Simula mantener los pesos `W` (tiempo × moneda).

    `W[k]` se decide con lo cerrado en `k`. Con `retraso=1` se ejecuta una vela
    más tarde: sirve para comprobar que el resultado no depende de clavar el
    precio de cierre.

    La banda evita operar por migajas: solo se reajusta una moneda cuando el
    peso real se aleja del objetivo más que `max(banda_abs, banda_rel·|objetivo|)`.

    `coste`, `banda_abs` y `banda_rel` admiten un valor por columna, para simular
    a la vez patas con costes distintos (contado y perpetuo).
    """
    T, N = W.shape
    W = np.nan_to_num(W, nan=0.0)
    if retraso:
        W = np.vstack([np.zeros((retraso, N)), W[:-retraso]])
    C = g.C
    R = np.zeros((T, N))
    R[1:] = C[1:] / C[:-1] - 1.0
    R = np.nan_to_num(R, nan=0.0, posinf=0.0, neginf=0.0)
    cotiza = ~np.isnan(C)
    F = g.F if con_financiacion else np.zeros_like(g.F)

    rend = np.zeros(T)
    rot = np.zeros(T)
    bruto = np.zeros(T)
    neto = np.zeros(T)
    costes = np.zeros(T)
    fin = np.zeros(T)
    por_moneda = np.zeros((T, N))
    pos = np.zeros(N)
    for k in range(T - 1):
        objetivo = np.where(cotiza[k], W[k], 0.0)
        mover = hay_que_mover(pos, objetivo, banda_rel, banda_abs)
        op = np.where(mover, objetivo - pos, 0.0)
        pos = pos + op
        c = float((coste * np.abs(op)).sum())
        r = R[k + 1]
        bruto_pnl = pos * r
        f = (pos * F[k]).sum()
        pnl = bruto_pnl.sum() - f - c
        rend[k + 1] = pnl
        rot[k + 1] = np.abs(op).sum()
        bruto[k + 1] = np.abs(pos).sum()
        neto[k + 1] = pos.sum()
        costes[k + 1] = c
        fin[k + 1] = f
        por_moneda[k + 1] = bruto_pnl
        pos = pos * (1.0 + r) / (1.0 + pnl) if pnl > -1 else np.zeros(N)
    patrimonio = np.cumprod(1.0 + rend)
    return Resultado(g.fechas(), rend, patrimonio, rot, bruto, neto, costes, fin, por_moneda,
                     g.velas_anio)


def tabla(resultados: dict, columnas: Optional[list] = None) -> pd.DataFrame:
    """Una fila por variante con sus métricas."""
    df = pd.DataFrame({k: r.metricas() for k, r in resultados.items()}).T
    cols = columnas or ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "calmar",
                        "meses_positivos_pct", "rotacion_anual", "coste_anual_pct",
                        "financiacion_anual_pct", "bruto_medio", "neto_medio"]
    return df[cols]


def por_columnas(fn, *mats, **kw) -> np.ndarray:
    """Aplica `fn` columna a columna saltándose el tramo NaN inicial de cada moneda."""
    T, N = mats[0].shape
    out = np.full((T, N), np.nan)
    for j in range(N):
        ok = ~np.isnan(mats[0][:, j])
        if ok.sum() < 5:
            continue
        out[ok, j] = fn(*(m[ok, j] for m in mats), **kw)
    return out


def guardar(nombre: str, texto: str) -> str:
    ruta = os.path.join(datos.RAIZ, "investigacion", "salidas", nombre)
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as fh:
        fh.write(texto)
    return ruta


# Contado: 0,10 % de comisión + 0,02 % de deslizamiento por lado, sin financiación.
COSTE_CONTADO = 0.0012


def doble_pata(g: Cuadricula, W_contado: np.ndarray, W_perp: np.ndarray):
    """Cuadrícula con cada moneda duplicada: primero la pata de contado, luego el perpetuo.

    Devuelve (cuadrícula, pesos, costes por columna). La pata de contado no paga
    financiación; la del perpetuo sí.
    """
    dup = lambda M: np.hstack([M, M])
    F2 = np.hstack([np.zeros_like(g.F), g.F])
    g2 = Cuadricula(g.intervalo, [s + ":contado" for s in g.simbolos] + [s + ":perp" for s in g.simbolos],
                    g.t, dup(g.O), dup(g.H), dup(g.L), dup(g.C), dup(g.V), F2)
    N = len(g.simbolos)
    costes = np.concatenate([np.full(N, COSTE_CONTADO), np.full(N, COSTE_POR_LADO)])
    return g2, np.hstack([W_contado, W_perp]), costes


def simular_cubierta(g: Cuadricula, base: np.ndarray, neto: np.ndarray,
                     banda_base: float, banda_cobertura: float,
                     coste_contado: float = COSTE_CONTADO, coste_perp: float = COSTE_POR_LADO,
                     con_financiacion: bool = True, extra_perp: Optional[np.ndarray] = None) -> Resultado:
    """Simula «base en contado + cobertura en perpetuo» con las MISMAS reglas que el bot.

    La regla que importa es la de `bot.cartera.ordenes`: la cobertura se pide como
    fracción del contado que realmente hay, no de su objetivo. `doble_pata` trataba
    las dos patas como libros independientes y dejaba que la exposición neta se
    desviara con la deriva de la base; el bot no hace eso, así que medir con
    aquella habría sido medir otra cosa.
    """
    T, N = base.shape
    base = np.nan_to_num(base, nan=0.0)
    neto = np.nan_to_num(neto, nan=0.0)
    C = g.C
    R = np.zeros((T, N))
    R[1:] = C[1:] / C[:-1] - 1.0
    R = np.nan_to_num(R, nan=0.0, posinf=0.0, neginf=0.0)
    cotiza = ~np.isnan(C)
    F = g.F if con_financiacion else np.zeros_like(g.F)

    rend, rot, bruto, net = (np.zeros(T) for _ in range(4))
    costes, fin = np.zeros(T), np.zeros(T)
    por_moneda = np.zeros((T, N))
    pc = np.zeros(N)       # peso del contado
    pp = np.zeros(N)       # peso del perpetuo (negativo = corto)
    for k in range(T - 1):
        b = np.where(cotiza[k], base[k], 0.0)
        n = np.where(cotiza[k], neto[k], 0.0)
        op_c = np.where(hay_que_mover(pc, b, banda_base), b - pc, 0.0)
        pc = pc + op_c
        with np.errstate(divide="ignore", invalid="ignore"):
            expuesto = np.where(b > 0, n / np.where(b > 0, b, 1.0), 0.0)
        obj_p = np.where(b > 0, -(1.0 - expuesto) * pc, n)
        if extra_perp is not None:
            # Posiciones en perpetuo que se suman a la cobertura (la manga de tendencia relativa).
            obj_p = obj_p + np.where(cotiza[k], np.nan_to_num(extra_perp[k]), 0.0)
        op_p = np.where(hay_que_mover(pp, obj_p, banda_cobertura), obj_p - pp, 0.0)
        pp = pp + op_p
        c = coste_contado * np.abs(op_c).sum() + coste_perp * np.abs(op_p).sum()
        r = R[k + 1]
        bruto_pnl = (pc + pp) * r
        f = float((pp * F[k]).sum())
        pnl = float(bruto_pnl.sum()) - f - c
        rend[k + 1] = pnl
        rot[k + 1] = np.abs(op_c).sum() + np.abs(op_p).sum()
        bruto[k + 1] = np.abs(pc).sum() + np.abs(pp).sum()
        net[k + 1] = (pc + pp).sum()
        costes[k + 1] = c
        fin[k + 1] = f
        por_moneda[k + 1] = bruto_pnl
        if pnl > -1:
            pc = pc * (1.0 + r) / (1.0 + pnl)
            pp = pp * (1.0 + r) / (1.0 + pnl)
        else:
            pc, pp = np.zeros(N), np.zeros(N)
    return Resultado(g.fechas(), rend, np.cumprod(1.0 + rend), rot, bruto, net, costes, fin,
                     por_moneda, g.velas_anio)
