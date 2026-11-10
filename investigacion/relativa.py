"""Tendencia relativa: cada alt medida en Bitcoin. Diseño y validación.

Hipótesis fijada ANTES de mirar la validación (2026-11-10):
  - mismos relojes que la estrategia principal, aplicados al precio de la alt en BTC;
  - largo la alt y corto BTC si la alt gana terreno, al revés si lo pierde;
  - volatilidad objetivo 30 % por par, repartida entre las alts; neutral en dólares;
  - todo en perpetuos, banda del 20 %;
  - se suma a la principal a media talla (0,5).

Uso: python -m investigacion.relativa [diseño|validacion|todo]
"""
import sys

import numpy as np
import pandas as pd

from bot import datos, estrategia as est, indicadores as ind
from investigacion import comun, laboratorio as lab

VOL_PAR = 0.30
TALLA = 0.5
COLS = ["cagr_pct", "vol_pct", "sharpe", "sortino", "max_dd_pct", "calmar", "peor_mes_pct",
        "rotacion_anual", "coste_anual_pct", "financiacion_anual_pct", "bruto_medio", "neto_medio"]


def pesos_relativa(g: lab.Cuadricula, p: est.Parametros, vol_par: float = VOL_PAR) -> np.ndarray:
    N = g.C.shape[1]
    vd = est.VELAS_DIA[p.intervalo]
    W = np.zeros((g.n, N))
    for j in range(1, N):
        ok = ~np.isnan(g.C[:, j]) & ~np.isnan(g.C[:, 0])
        if ok.sum() < 5:
            continue
        ratio = g.C[ok, j] / g.C[ok, 0]
        s = est.puntuacion(ratio, ratio, ratio, vd, p)
        v = np.maximum(ind.volatilidad_ewma(ratio, p.dias_vol * vd, vd * 365.0), 0.10)
        W[ok, j] = s * (vol_par / v) / (N - 1)
    W[:, 0] = -W[:, 1:].sum(axis=1)
    return W


def correr(desde, hasta) -> dict:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    o = est.calcular(g.H, g.L, g.C, p)
    Wr = pesos_relativa(g, p)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    gg = g.recorte(desde, hasta)
    res = {
        "principal (lo que corre hoy)": lab.simular_cubierta(gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura),
        "relativa sola, talla entera": lab.simular(gg, Wr[m], banda_rel=p.banda_sin_base),
        f"PRINCIPAL + RELATIVA a {TALLA} (candidata)": lab.simular_cubierta(
            gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura, extra_perp=TALLA * Wr[m]),
        "principal + relativa a 1,0": lab.simular_cubierta(
            gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura, extra_perp=Wr[m]),
    }
    return res


def informe(titulo, desde, hasta) -> str:
    res = correr(desde, hasta)
    a = res["relativa sola, talla entera"].diario()
    b = res["principal (lo que corre hoy)"].diario()
    ix = a.index.intersection(b.index)
    return "\n".join([f"=== {titulo} ===", lab.tabla(res, COLS).to_string(), "",
                      pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string(),
                      f"correlación diaria relativa ↔ principal: {np.corrcoef(a[ix], b[ix])[0, 1]:+.2f}", ""])


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    if que in ("diseño", "todo"):
        t = informe("DISEÑO 2020-2023", None, comun.FIN_DISEÑO); print(t); lab.guardar("relativa_diseño.txt", t)
    if que in ("validacion", "todo"):
        t = informe("VALIDACIÓN 2024-01 → 2026-11", comun.FIN_DISEÑO, None); print(t); lab.guardar("relativa_validacion.txt", t)
