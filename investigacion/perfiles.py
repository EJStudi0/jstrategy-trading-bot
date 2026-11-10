"""Niveles de riesgo: la misma estrategia con más o menos exposición.

Uso: python -m investigacion.perfiles
"""
from dataclasses import replace

import pandas as pd

from bot import estrategia as est
from investigacion import comun, laboratorio as lab
from investigacion.validacion import simular

PERFILES = {
    "prudente": dict(vol_cartera=0.15),
    "moderado (por defecto)": dict(),
    "decidido": dict(vol_cartera=0.40, apalancamiento=1.5),
    "agresivo": dict(vol_cartera=0.60, apalancamiento=2.0),
    "muy agresivo": dict(vol_cartera=0.90, apalancamiento=3.0),
}
COLS = ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "peor_mes_pct", "coste_anual_pct",
        "financiacion_anual_pct", "neto_medio"]

if __name__ == "__main__":
    comun.configurar_pandas()
    lineas = []
    for titulo, desde, hasta in (("DISEÑO 2020-2023", None, comun.FIN_DISEÑO),
                                 ("VALIDACIÓN 2024-01 → 2026-11", comun.FIN_DISEÑO, None)):
        res = {k: simular(replace(est.Parametros(), **v), desde, hasta) for k, v in PERFILES.items()}
        lineas += [f"=== {titulo} ===", lab.tabla(res, COLS).to_string(),
                   pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string(), ""]
    texto = "\n".join(lineas)
    print(texto)
    lab.guardar("perfiles_de_riesgo.txt", texto)
