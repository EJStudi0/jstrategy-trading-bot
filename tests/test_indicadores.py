"""Los indicadores no pueden mirar al futuro: es lo que hace creíble al simulador."""
import numpy as np
import pytest

from bot import indicadores as ind
from tests.conftest import serie_sintetica

O, H, L, C = serie_sintetica(600)
CORTE = 400

CASOS = {
    "ema": lambda h, l, c: ind.ema(c, 20),
    "sma": lambda h, l, c: ind.sma(c, 20),
    "maximo": lambda h, l, c: ind.maximo(h, 30),
    "minimo": lambda h, l, c: ind.minimo(l, 30),
    "desviacion": lambda h, l, c: ind.desviacion(c, 20),
    "volatilidad": lambda h, l, c: ind.volatilidad_ewma(c, 30, 2190),
    "atr": lambda h, l, c: ind.atr(h, l, c, 14),
    "adx": lambda h, l, c: ind.adx(h, l, c, 14)[0],
    "rsi": lambda h, l, c: ind.rsi(c, 14),
}


@pytest.mark.parametrize("nombre", sorted(CASOS))
def test_es_causal(nombre):
    """El valor en `i` no cambia por lo que venga después de `i`."""
    f = CASOS[nombre]
    entero = f(H, L, C)
    cortado = f(H[:CORTE], L[:CORTE], C[:CORTE])
    np.testing.assert_allclose(entero[:CORTE], cortado, rtol=1e-12, atol=1e-12, equal_nan=True)


def test_ema_coincide_con_la_definicion():
    x = np.array([1.0, 2.0, 3.0, 4.0])
    a = 2 / (3 + 1)
    esperado = [1.0]
    for v in x[1:]:
        esperado.append(a * v + (1 - a) * esperado[-1])
    np.testing.assert_allclose(ind.ema(x, 3), esperado)


def test_rendimientos():
    np.testing.assert_allclose(ind.rendimientos(np.array([100.0, 110.0, 99.0])), [0.0, 0.10, -0.10])


def test_desde_ultimo():
    out = ind.desde_ultimo(np.array([False, True, False, False, True, False]))
    assert out[0] == np.inf
    assert list(out[1:]) == [0, 1, 2, 0, 1]


def test_rsi_extremos():
    assert ind.rsi(np.arange(1.0, 60.0))[-1] > 99          # solo sube
    assert ind.rsi(np.arange(60.0, 1.0, -1.0))[-1] < 1     # solo baja
