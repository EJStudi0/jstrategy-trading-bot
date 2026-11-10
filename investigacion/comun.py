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


def configurar_pandas():
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    pd.set_option("display.max_rows", 200)
