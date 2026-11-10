"""Apalancamiento amontonado: cubrir más las monedas donde la multitud paga más por estar larga.

Lo visto en el diseño (ene-2022 → dic-2023, `estudio_huellas`): la moneda con la financiación
más alta rinde MENOS que las demás los días siguientes (correlación de corte −0,04 a −0,05,
t entre −2,4 y −3,2). Era el signo esperado: financiación alta = largos apalancados amontonados.

Hipótesis fijada ANTES de mirar la validación (2026-11-10):
  huella  = financiación media de los últimos 3 días de cada moneda, comparada con la de las
            demás en ese momento (desviaciones típicas entre monedas, acotada a ±2);
  uso     = se resta de la nota de tendencia con peso 0,15 por desviación: más cobertura en las
            monedas más amontonadas, menos en las que nadie quiere;
  ventaja añadida y mecánica: el corto de una moneda con financiación alta COBRA más.
La financiación se lee en vivo de cualquier mercado: no depende de Binance.

Uso: python -m investigacion.financiacion_relativa [diseño|validacion|todo]
"""
import sys

import numpy as np
import pandas as pd

from bot import datos, estrategia as est
from investigacion import comun, laboratorio as lab

PESO = 0.15
DIAS = 3.0
TOPE = 2.0
COLS = ["cagr_pct", "vol_pct", "sharpe", "sortino", "max_dd_pct", "calmar", "peor_mes_pct",
        "rotacion_anual", "coste_anual_pct", "financiacion_anual_pct", "bruto_medio", "neto_medio"]


def financiacion_media(F: np.ndarray, velas_dia: float, dias: float) -> np.ndarray:
    """Financiación anualizada de los últimos `dias`. En la vela k solo se conoce hasta F[k-1]."""
    n = int(round(dias * velas_dia))
    conocido = np.vstack([np.zeros((1, F.shape[1])), F[:-1]])
    acum = np.cumsum(conocido, axis=0)
    suma = acum.copy()
    suma[n:] = acum[n:] - acum[:-n]
    out = suma * 365.0 / dias
    out[:n] = np.nan
    return out


def amontonamiento(g: lab.Cuadricula, dias: float = DIAS) -> np.ndarray:
    """Financiación de cada moneda frente a las demás, en desviaciones típicas (tiempo × moneda)."""
    f = financiacion_media(g.F, est.VELAS_DIA[g.intervalo], dias)
    f = np.where(np.isnan(g.C), np.nan, f)
    media = np.nanmean(f, axis=1, keepdims=True)
    desv = np.nanstd(f, axis=1, keepdims=True)
    con = np.sum(np.isfinite(f), axis=1, keepdims=True) >= 5
    with np.errstate(invalid="ignore", divide="ignore"):
        z = np.where(con & (desv > 1e-9), (f - media) / desv, 0.0)
    return np.clip(np.nan_to_num(z, nan=0.0), -TOPE, TOPE)


def correr(desde, hasta) -> dict:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    Z = amontonamiento(g)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    gg = g.recorte(desde, hasta)
    res = {}
    for nombre, peso in (("principal (lo que corre hoy)", 0.0), (f"CUBRIR MÁS LO AMONTONADO, peso {PESO} (candidata)", -PESO),
                         ("peso doble (0,30)", -2 * PESO), ("control: AL REVÉS (cubrir menos lo amontonado)", PESO)):
        o = est.calcular(g.H, g.L, g.C, p, ajuste_nota=peso * Z if peso else None)
        res[nombre] = lab.simular_cubierta(gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura)
    return res


def informe(titulo, desde, hasta) -> str:
    res = correr(desde, hasta)
    return "\n".join([f"=== {titulo} ===", lab.tabla(res, COLS).to_string(), "",
                      pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string(), ""])


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    if que in ("diseño", "todo"):
        t = informe("DISEÑO 2020-2023", None, comun.FIN_DISEÑO); print(t); lab.guardar("financiacion_relativa_diseño.txt", t)
    if que in ("validacion", "todo"):
        t = informe("VALIDACIÓN 2024-01 → 2026-11", comun.FIN_DISEÑO, None); print(t); lab.guardar("financiacion_relativa_validacion.txt", t)
