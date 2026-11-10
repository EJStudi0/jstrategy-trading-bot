"""Periodos de diseño y de validación, y utilidades de los estudios."""
from __future__ import annotations

import numpy as np
import pandas as pd

from bot import datos
from investigacion import laboratorio as lab

# Todo se DISEÑA con 2020-2023 y se VALIDA una sola vez con 2024 en adelante.
# Si se ajusta mirando la validación, deja de ser validación.
FIN_DISEÑO = "2024-01-01"


def tramo(g: lab.Cuadricula, W: np.ndarray, desde=None, hasta=None):
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    return g.recorte(desde, hasta), W[m]


def diseño(g, W, **kw):
    gg, ww = tramo(g, W, hasta=FIN_DISEÑO)
    return lab.simular(gg, ww, **kw)


def validacion(g, W, **kw):
    gg, ww = tramo(g, W, desde=FIN_DISEÑO)
    return lab.simular(gg, ww, **kw)


COLS_CONSTANCIA = ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "calmar", "meses_positivos_pct",
                   "peor_mes_pct", "peor_12m_pct", "dias_bajo_maximo", "coste_anual_pct",
                   "financiacion_anual_pct", "neto_medio"]


def mascara(g: lab.Cuadricula, desde=None, hasta=None) -> np.ndarray:
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    return m


def con_anios(res: dict, columnas=None) -> pd.DataFrame:
    """La tabla de métricas con el rendimiento de cada año al lado."""
    anios = pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T
    return pd.concat([lab.tabla(res, columnas or COLS_CONSTANCIA), anios], axis=1)


def configurar_pandas():
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 200)
