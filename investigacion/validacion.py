"""Diseño (2020-2023) frente a validación (2024 en adelante) con el código de producción.

Uso: python -m investigacion.validacion [diseño|validacion|todo]
"""
import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from bot import datos, estrategia as est
from investigacion import comun, laboratorio as lab

COLS = ["cagr_pct", "vol_pct", "sharpe", "sortino", "max_dd_pct", "calmar", "meses_positivos_pct",
        "peor_mes_pct", "rotacion_anual", "coste_anual_pct", "financiacion_anual_pct",
        "bruto_medio", "neto_medio"]


def simular(p: est.Parametros, desde=None, hasta=None, **kw) -> lab.Resultado:
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    o = est.calcular(g.H, g.L, g.C, p)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    gg = g.recorte(desde, hasta)
    if p.modo == "perpetuos":
        return lab.simular(gg, o.neto[m], banda_rel=p.banda_cobertura, **kw)
    mult = kw.pop("coste_mult", 1.0)
    return lab.simular_cubierta(gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura,
                                coste_contado=lab.COSTE_CONTADO * mult,
                                coste_perp=lab.COSTE_POR_LADO * mult, **kw)


def variantes() -> dict:
    p = est.Parametros()
    return {
        "ELEGIDA: base cubierta + control de cartera": p,
        "sin control de cartera": replace(p, vol_cartera=9.9, escala_max=1.0),
        "todo en perpetuos": replace(p, modo="perpetuos"),
        "sin filtro de BTC": replace(p, filtro_ancla=False),
        "cobertura hasta 150%": replace(p, cobertura_max=1.5),
        "cobertura hasta 200% (como Jorge)": replace(p, cobertura_max=2.0),
        "solo BTC y ETH": replace(p, simbolos=("BTCUSDT", "ETHUSDT")),
        "solo BTC": replace(p, simbolos=("BTCUSDT",)),
    }


def referencias(desde, hasta) -> dict:
    g = lab.cuadricula("4h")
    uno = np.zeros_like(g.C); uno[:, 0] = 1.0
    gg, ww = comun.tramo(g, uno, desde, hasta)
    out = {"referencia: BTC comprar y mantener (contado)": lab.simular(gg, ww, coste=0.0012, con_financiacion=False)}
    cesta = np.where(np.isnan(g.C), 0.0, 1.0 / g.C.shape[1])
    gg, ww = comun.tramo(g, cesta, desde, hasta)
    out["referencia: cesta de las 10 a partes iguales (contado)"] = lab.simular(
        gg, ww, coste=0.0012, con_financiacion=False, banda_abs=0.02)
    return out


def informe(titulo, desde, hasta) -> str:
    res = {k: simular(p, desde, hasta) for k, p in variantes().items()}
    res.update(referencias(desde, hasta))
    lineas = [f"=== {titulo} ===", lab.tabla(res, COLS).to_string(), "", "--- rendimiento por año (%) ---",
              pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string(), "",
              "--- peor caída dentro de cada año (%) ---",
              pd.DataFrame({k: r.por_anio()["max_dd_pct"] for k, r in res.items()}).T.to_string()]
    return "\n".join(lineas)


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    if que in ("diseño", "todo"):
        t = informe("DISEÑO 2020-2023", None, comun.FIN_DISEÑO)
        print(t); lab.guardar("validacion_diseño.txt", t)
    if que in ("validacion", "todo"):
        t = informe("VALIDACIÓN 2024-01 → 2026-11 (no usada para ajustar nada)", comun.FIN_DISEÑO, None)
        print(t); lab.guardar("validacion_fuera_de_muestra.txt", t)
