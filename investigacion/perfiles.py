"""Niveles de riesgo: la misma estrategia con más o menos exposición.

Uso: python -m investigacion.perfiles
"""
from dataclasses import replace

import pandas as pd

from bot import estrategia as est
from investigacion import comun, laboratorio as lab
from investigacion.validacion import simular

from bot import config

# Los que ofrece el panel (`config.NIVELES`) y, para ver por qué no se ofrece más, uno por encima.
PERFILES = {**{f"{k} ({v['nombre']})": v["ajustes"] for k, v in config.NIVELES.items()},
            "muy agresivo (no se ofrece)": dict(vol_cartera=0.90, apalancamiento=3.0)}
COLS = ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "meses_positivos_pct", "peor_mes_pct", "peor_12m_pct",
        "dias_bajo_maximo", "coste_anual_pct", "financiacion_anual_pct", "neto_medio"]

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
