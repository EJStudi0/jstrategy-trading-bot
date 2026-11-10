"""Jugar el rango y la reversión de corto plazo. Solo diseño.

Jorge juega los rangos: compra en el soporte, vende en la resistencia, con recompras. Aquí va la
versión que se puede escribir sin mirar un gráfico, como manga aparte en perpetuos:

  - Rango: cuando la nota de tendencia está cerca de cero, largo cerca del mínimo de los últimos N
    días y corto cerca del máximo, en proporción a lo cerca que esté de cada extremo.
  - Reversión: contra el movimiento de las últimas n velas, medido en desviaciones.

Uso: python -m investigacion.reversion
"""
import itertools

import numpy as np

from bot import estrategia as est, indicadores as ind
from investigacion import comun, laboratorio as lab
from investigacion.tamano import nota_filtrada

COLS = ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "rotacion_anual", "coste_anual_pct"]


def pesos_rango(g, p, dias: int, umbral: float, largo_y_corto: bool = True) -> np.ndarray:
    S, _, o = nota_filtrada(g, p)
    vd = int(est.VELAS_DIA[p.intervalo])
    techo = lab.por_columnas(lambda h: ind.maximo(h, dias * vd), g.H)
    suelo = lab.por_columnas(lambda l: ind.minimo(l, dias * vd), g.L)
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.clip((g.C - suelo) / np.maximum(techo - suelo, 1e-12), 0.0, 1.0)
    pos = 1.0 - 2.0 * u                                      # +1 en el suelo del rango, −1 en el techo
    if not largo_y_corto:
        pos = np.maximum(pos, 0.0)
    return np.where((np.abs(S) <= umbral) & ~np.isnan(u), o.base * pos, 0.0)


def pesos_reversion(g, p, velas: int, solo_sin_tendencia=None) -> np.ndarray:
    S, _, o = nota_filtrada(g, p)
    vd = est.VELAS_DIA[p.intervalo]
    r = np.full(g.C.shape, np.nan)
    r[velas:] = g.C[velas:] / g.C[:-velas] - 1.0
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.clip(r / (o.vol / np.sqrt(vd * 365.0) * np.sqrt(velas)), -2.0, 2.0) / 2.0
    W = np.where(np.isfinite(z), -o.base * z, 0.0)
    return W if solo_sin_tendencia is None else np.where(np.abs(S) <= solo_sin_tendencia, W, 0.0)


def correr() -> str:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    m = comun.mascara(g, hasta=comun.FIN_DISEÑO)
    gd = g.recorte(None, comun.FIN_DISEÑO)
    mangas = {}
    for dias, umbral, lc in itertools.product((3, 5, 10, 20), (0.2, 0.4), (True, False)):
        mangas[f"rango de {dias} d, |nota| <= {umbral}, {'largo y corto' if lc else 'solo largo'}"] = \
            pesos_rango(g, p, dias, umbral, lc)
    for velas in (1, 3, 6, 18, 42):
        mangas[f"reversión de las últimas {velas} velas"] = pesos_reversion(g, p, velas)
    for velas in (6, 18):
        mangas[f"reversión de {velas} velas, solo sin tendencia"] = pesos_reversion(g, p, velas, 0.2)
    res = {k: lab.simular(gd, W[m], banda_rel=0.2) for k, W in mangas.items()}
    t = comun.con_anios(res, COLS)
    # Sin comisiones, para separar «no hay nada» de «lo que hay se lo comen los costes».
    t.insert(3, "sharpe_sin_costes",
             [lab.simular(gd, W[m], banda_rel=0.2, coste=0.0).metricas()["sharpe"] for W in mangas.values()])
    return "=== DISEÑO 2020-2023 · mangas de reversión, solas, en perpetuos ===\n" + t.to_string()


if __name__ == "__main__":
    comun.configurar_pandas()
    texto = correr()
    print(texto)
    lab.guardar("reversion_diseño.txt", texto)
