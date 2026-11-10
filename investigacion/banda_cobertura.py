"""Cuándo se reajusta la cobertura: la regla de antes frente a la de ahora. Diseño y prueba.

Hasta noviembre de 2026 la cobertura de una moneda se reajustaba cuando se apartaba de su objetivo
más de un 20 % DE LA PROPIA COBERTURA. Con casi todo cubierto esa tolerancia es enorme comparada con
la exposición que se busca: con la tendencia en contra podía quedarse sin cubrir hasta un 20 % de
la base. Se vio al bajar el nivel de riesgo: en 2022 perdía lo mismo con riesgo 5 % que con 25 %.

La regla nueva (`estrategia.hay_que_cubrir`) mide la tolerancia sobre la base de la moneda (10 %),
y en los dos extremos no deja ninguna: sin tendencia se cubre todo; con tendencia plena, nada.

Criterio fijado antes de mirar la prueba: en el nivel por defecto, que no empeore ni el Sharpe ni la
caída; en los niveles bajos, menos caída y más Sharpe. Se cumple en los cuatro niveles.

Uso: python -m investigacion.banda_cobertura
"""
from dataclasses import replace

import numpy as np

from bot import estrategia as est
from investigacion import comun, laboratorio as lab


def correr(desde, hasta) -> dict:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    m = comun.mascara(g, desde, hasta)
    gg = g.recorte(desde, hasta)
    res = {}
    for riesgo in (0.05, 0.10, 0.15, 0.25):
        pp = replace(p, vol_cartera=riesgo)
        o = est.calcular(g.H, g.L, g.C, pp)
        for nombre, antigua in (("regla anterior", True), ("REGLA ACTUAL", False)):
            res[f"riesgo {int(riesgo * 100)} % · {nombre}"] = lab.simular_cubierta(
                gg, o.base[m], o.neto[m], pp.banda_base, pp.banda_cobertura, cobertura_antigua=antigua)
    return res


if __name__ == "__main__":
    comun.configurar_pandas()
    cols = comun.COLS_CONSTANCIA + ["rotacion_anual"]
    texto = "\n".join(["=== DISEÑO 2020-2023 ===", comun.con_anios(correr(None, comun.FIN_DISEÑO), cols).to_string(), "",
                       "=== PRUEBA 2024-01 → 2026-11 ===", comun.con_anios(correr(comun.FIN_DISEÑO, None), cols).to_string()])
    print(texto)
    lab.guardar("banda_cobertura.txt", texto)
