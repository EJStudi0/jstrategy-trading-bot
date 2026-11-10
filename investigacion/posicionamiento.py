"""Posicionamiento como un reloj más: los traders grandes frente a la multitud.

Hipótesis fijada ANTES de mirar la validación (2026-11-10):
  huella   = «grandes menos multitud»: fracción en largo de los traders grandes (por tamaño de
             posición) menos la de todas las cuentas, normalizada contra sus últimos 30 días;
  reloj    = «archivo» (el volcado diario de Binance, publicado hacia las 07:30 UTC), que es lo
             único que el bot puede leer hoy;
  uso      = se suma a la nota de tendencia con peso 0,15 por desviación típica (como un reloj y
             medio de los diez), acotada a ±2; el filtro de Bitcoin sigue usando la tendencia sola;
  sentido  = con los grandes más largos que la multitud, menos cobertura; al revés, más.

Uso: python -m investigacion.posicionamiento [diseño|validacion|todo]
"""
import sys

import numpy as np
import pandas as pd

from bot import datos, estrategia as est
from investigacion import comun, huellas as hu, laboratorio as lab

PESO = 0.15
TOPE_Z = 2.0
INICIO_DATOS = "2022-01-15"
COLS = ["cagr_pct", "vol_pct", "sharpe", "sortino", "max_dd_pct", "calmar", "peor_mes_pct",
        "rotacion_anual", "coste_anual_pct", "financiacion_anual_pct", "bruto_medio", "neto_medio"]


def objetivos_con_huella(g: lab.Cuadricula, p: est.Parametros, Z: np.ndarray, peso: float) -> est.Objetivos:
    """Igual que `estrategia.calcular`, con la huella sumada a la nota. Solo para investigar."""
    extra = peso * np.clip(np.nan_to_num(Z, nan=0.0), -TOPE_Z, TOPE_Z)
    return est.calcular(g.H, g.L, g.C, p, ajuste_nota=extra)


def correr(desde, hasta, reloj: str = "archivo") -> dict:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    Z = hu.panel(g, reloj, ["gmm_z"])["gmm_z"]
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    gg = g.recorte(desde, hasta)
    res = {}
    for nombre, peso, signo in (("principal (lo que corre hoy)", 0.0, 1), (f"CON POSICIONAMIENTO, peso {PESO} (candidata)", PESO, 1),
                                ("peso doble (0,30)", 2 * PESO, 1), ("control: la huella AL REVÉS", PESO, -1)):
        o = objetivos_con_huella(g, p, signo * Z, peso)
        res[nombre] = lab.simular_cubierta(gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura)
    return res


def informe(titulo, desde, hasta, reloj="archivo") -> str:
    res = correr(desde, hasta, reloj)
    return "\n".join([f"=== {titulo} · reloj «{reloj}» ===", lab.tabla(res, COLS).to_string(), "",
                      pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string(), ""])


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    if que in ("diseño", "todo"):
        t = informe("DISEÑO con datos de posicionamiento: ene-2022 → dic-2023", INICIO_DATOS, comun.FIN_DISEÑO)
        t += "\n" + informe("DISEÑO, mismo tramo", INICIO_DATOS, comun.FIN_DISEÑO, reloj="instantaneo")
        print(t); lab.guardar("posicionamiento_diseño.txt", t)
    if que in ("validacion", "todo"):
        t = informe("VALIDACIÓN 2024-01 → 2026-11", comun.FIN_DISEÑO, None)
        print(t); lab.guardar("posicionamiento_validacion.txt", t)
