import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def serie_sintetica(n: int, semilla: int = 7, deriva: float = 0.0002, vol: float = 0.01,
                    inicio: float = 100.0):
    """Paseo aleatorio con máximo/mínimo coherentes. Devuelve (o, h, l, c)."""
    rng = np.random.default_rng(semilla)
    r = rng.normal(deriva, vol, n)
    c = inicio * np.exp(np.cumsum(r))
    o = np.concatenate(([inicio], c[:-1]))
    ancho = np.abs(rng.normal(0, vol / 2, n)) * c
    h = np.maximum(o, c) + ancho
    l = np.minimum(o, c) - ancho
    return o, h, l, c


@pytest.fixture
def mercado_sintetico():
    """Tres monedas correlacionadas, 1 600 velas de 4 h. Matrices (H, L, C)."""
    n = 1600
    rng = np.random.default_rng(3)
    comun = rng.normal(0.0003, 0.012, n)
    cols = []
    for j in range(3):
        r = comun + rng.normal(0, 0.008, n)
        c = (100.0 * (j + 1)) * np.exp(np.cumsum(r))
        o = np.concatenate(([c[0]], c[:-1]))
        ancho = np.abs(rng.normal(0, 0.004, n)) * c
        cols.append((np.maximum(o, c) + ancho, np.minimum(o, c) - ancho, c))
    H = np.column_stack([x[0] for x in cols])
    L = np.column_stack([x[1] for x in cols])
    C = np.column_stack([x[2] for x in cols])
    return H, L, C
