"""Indicadores sobre columnas numpy.

Todos son CAUSALES: el valor en la posición `i` solo usa datos hasta `i`
incluida. Eso es lo que permite calcularlos una vez sobre todo el histórico en
el simulador y sobre una ventana reciente en vivo, y que den lo mismo
(`tests/test_indicadores.py` lo comprueba cortando la serie por la mitad).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def _s(x: np.ndarray) -> pd.Series:
    return pd.Series(np.asarray(x, dtype=np.float64))


def ema(x: np.ndarray, n: float) -> np.ndarray:
    """Media exponencial con `span = n` (misma convención que TradingView)."""
    return _s(x).ewm(span=n, adjust=False).mean().to_numpy()


def sma(x: np.ndarray, n: int) -> np.ndarray:
    return _s(x).rolling(n).mean().to_numpy()


def maximo(x: np.ndarray, n: int) -> np.ndarray:
    return _s(x).rolling(n).max().to_numpy()


def minimo(x: np.ndarray, n: int) -> np.ndarray:
    return _s(x).rolling(n).min().to_numpy()


def desviacion(x: np.ndarray, n: int) -> np.ndarray:
    return _s(x).rolling(n).std().to_numpy()


def rendimientos(c: np.ndarray) -> np.ndarray:
    """Rendimiento simple vela a vela; el primero es 0."""
    r = np.zeros(len(c))
    r[1:] = c[1:] / c[:-1] - 1.0
    return r


def volatilidad_ewma(c: np.ndarray, n: float, velas_por_anio: float) -> np.ndarray:
    """Volatilidad anualizada: raíz de la media exponencial de r²."""
    r = rendimientos(c)
    var = _s(r * r).ewm(span=n, adjust=False).mean().to_numpy()
    return np.sqrt(var * velas_por_anio)


def rango_verdadero(h: np.ndarray, l: np.ndarray, c: np.ndarray) -> np.ndarray:
    previo = np.concatenate(([c[0]], c[:-1]))
    return np.maximum(h - l, np.maximum(np.abs(h - previo), np.abs(l - previo)))


def atr(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14) -> np.ndarray:
    """ATR de Wilder."""
    return _s(rango_verdadero(h, l, c)).ewm(alpha=1.0 / n, adjust=False).mean().to_numpy()


def adx(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int = 14):
    """ADX de Wilder. Devuelve (adx, +DI, -DI)."""
    sube = np.diff(h, prepend=h[0])
    baja = -np.diff(l, prepend=l[0])
    dm_mas = np.where((sube > baja) & (sube > 0), sube, 0.0)
    dm_menos = np.where((baja > sube) & (baja > 0), baja, 0.0)
    a = _s(rango_verdadero(h, l, c)).ewm(alpha=1.0 / n, adjust=False).mean()
    di_mas = 100.0 * _s(dm_mas).ewm(alpha=1.0 / n, adjust=False).mean() / a
    di_menos = 100.0 * _s(dm_menos).ewm(alpha=1.0 / n, adjust=False).mean() / a
    suma = (di_mas + di_menos).replace(0, np.nan)
    dx = 100.0 * (di_mas - di_menos).abs() / suma
    return (dx.ewm(alpha=1.0 / n, adjust=False).mean().to_numpy(),
            di_mas.to_numpy(), di_menos.to_numpy())


def rsi(c: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(c, prepend=c[0])
    arriba = _s(np.where(d > 0, d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean()
    abajo = _s(np.where(d < 0, -d, 0.0)).ewm(alpha=1.0 / n, adjust=False).mean()
    rs = arriba / abajo.replace(0, np.nan)
    return (100.0 - 100.0 / (1.0 + rs)).fillna(100.0).to_numpy()


def desde_ultimo(cond: np.ndarray) -> np.ndarray:
    """Velas transcurridas desde la última vez que `cond` fue cierta (inf si nunca)."""
    cond = np.asarray(cond, dtype=bool)
    idx = np.where(cond, np.arange(len(cond)), -1)
    ultimo = np.maximum.accumulate(idx)
    out = (np.arange(len(cond)) - ultimo).astype(np.float64)
    out[ultimo < 0] = np.inf
    return out
