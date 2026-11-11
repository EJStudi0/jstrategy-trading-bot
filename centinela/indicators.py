"""Indicadores causales (sin mirar al futuro) sobre series horarias.

Todas las funciones cumplen la misma garantía: el valor en la fila ``t`` depende
solo de las filas ``<= t``. Esta propiedad se comprueba en ``tests/test_causal.py``
recalculando sobre históricos truncados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

HOURS_PER_DAY = 24
HOURS_PER_YEAR = 24 * 365


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close).diff()


def ema(x: pd.Series, span: float) -> pd.Series:
    """Media exponencial con ``span`` en velas (``adjust=False`` => recursiva y causal)."""
    return x.ewm(span=span, adjust=False, min_periods=1).mean()


def ewm_vol(returns: pd.Series, halflife: float, min_periods: int = 48) -> pd.Series:
    """Volatilidad horaria EWMA (raíz de la media exponencial de r²; media asumida cero)."""
    var = (returns**2).ewm(halflife=halflife, adjust=True, min_periods=min_periods).mean()
    return np.sqrt(var)


def garman_klass_var(o: pd.Series, h: pd.Series, l: pd.Series, c: pd.Series) -> pd.Series:
    """Varianza por vela de Garman-Klass: usa el rango, ~7x más eficiente que cierre-cierre."""
    hl = np.log(h / l)
    co = np.log(c / o)
    return (0.5 * hl**2 - (2.0 * np.log(2.0) - 1.0) * co**2).clip(lower=0.0)


def blended_vol(
    close: pd.Series,
    o: pd.Series | None = None,
    h: pd.Series | None = None,
    l: pd.Series | None = None,
    fast_hl: float = 24.0,
    slow_hl: float = 24.0 * 14,
    w_fast: float = 0.5,
    floor_frac: float = 0.5,
    use_range: bool = True,
) -> pd.Series:
    """Previsión de volatilidad **anualizada** combinando horizonte rápido y lento.

    La mezcla de varianzas reacciona rápido a los choques (componente rápida) sin
    olvidar el nivel de fondo (componente lenta). El suelo evita que una calma
    excepcional infle el tamaño de la posición justo antes de una expansión de
    volatilidad, algo característico de BTC.
    """
    r = log_returns(close)
    if use_range and o is not None and h is not None and l is not None:
        # mitad rango (eficiente) + mitad cierre-cierre (capta saltos entre velas)
        v = 0.5 * garman_klass_var(o, h, l, close) + 0.5 * r**2
    else:
        v = r**2
    v = v.fillna(0.0)
    fast = v.ewm(halflife=fast_hl, adjust=True, min_periods=48).mean()
    slow = v.ewm(halflife=slow_hl, adjust=True, min_periods=48).mean()
    var = w_fast * fast + (1.0 - w_fast) * slow
    # suelo: una fracción de la volatilidad de muy largo plazo (1 año de semivida ~ 90 días)
    long_run = v.ewm(halflife=24.0 * 90, adjust=True, min_periods=48).mean()
    var = np.maximum(var, (floor_frac**2) * long_run)
    return np.sqrt(var * HOURS_PER_YEAR)


def ewmac(close: pd.Series, fast_days: float, slow_days: float, vol_ann: pd.Series) -> pd.Series:
    """Cruce de medias exponenciales normalizado por volatilidad (en unidades de sigma diaria)."""
    f = ema(close, fast_days * HOURS_PER_DAY)
    s = ema(close, slow_days * HOURS_PER_DAY)
    daily_sigma_price = close * vol_ann / np.sqrt(365.0)
    return (f - s) / daily_sigma_price


def tsmom(close: pd.Series, days: float, vol_ann: pd.Series) -> pd.Series:
    """Momentum de serie temporal: retorno a ``days`` en unidades de su sigma esperada."""
    n = int(round(days * HOURS_PER_DAY))
    ret = np.log(close / close.shift(n))
    return ret / (vol_ann * np.sqrt(days / 365.0))


def donchian_position(close: pd.Series, h: pd.Series, l: pd.Series, days: float) -> pd.Series:
    """Posición del cierre dentro del canal de máximos/mínimos de ``days``: -1 (suelo) a +1 (techo)."""
    n = int(round(days * HOURS_PER_DAY))
    hi = h.rolling(n, min_periods=n // 2).max()
    lo = l.rolling(n, min_periods=n // 2).min()
    width = (hi - lo).replace(0.0, np.nan)
    return (2.0 * (close - lo) / width - 1.0).clip(-1.0, 1.0)


def sma_distance(close: pd.Series, days: float, vol_ann: pd.Series) -> pd.Series:
    """Distancia a la media simple de ``days`` en sigmas del horizonte correspondiente."""
    n = int(round(days * HOURS_PER_DAY))
    sma = close.rolling(n, min_periods=n // 2).mean()
    return np.log(close / sma) / (vol_ann * np.sqrt(days / 2.0 / 365.0))


def rsi(close: pd.Series, period: int) -> pd.Series:
    """RSI de Wilder, reescalado a [-1, 1] (0 = neutral)."""
    d = close.diff()
    up = d.clip(lower=0.0).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    dn = (-d.clip(upper=0.0)).ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = up / dn.replace(0.0, np.nan)
    out = 100.0 - 100.0 / (1.0 + rs)
    return ((out.fillna(100.0).where(up.notna())) - 50.0) / 50.0


def zscore_return(close: pd.Series, hours: int, vol_ann: pd.Series) -> pd.Series:
    """Retorno a ``hours`` horas en sigmas (lo que la volatilidad actual haría esperar)."""
    ret = np.log(close / close.shift(hours))
    return ret / (vol_ann * np.sqrt(hours / HOURS_PER_YEAR))


def rolling_rank(x: pd.Series, window: int, min_periods: int | None = None) -> pd.Series:
    """Percentil del valor actual dentro de su ventana móvil pasada, en [0, 1]."""
    mp = min_periods if min_periods is not None else max(window // 4, 2)
    return x.rolling(window, min_periods=mp).rank(pct=True)


def efficiency_ratio(close: pd.Series, hours: int) -> pd.Series:
    """Ratio de eficiencia de Kaufman: 1 = tendencia limpia, 0 = ruido puro."""
    net = (close - close.shift(hours)).abs()
    path = close.diff().abs().rolling(hours, min_periods=hours).sum()
    return (net / path.replace(0.0, np.nan)).clip(0.0, 1.0)


def drawdown_from_high(close: pd.Series, days: float | None = None) -> pd.Series:
    """Caída logarítmica desde el máximo (histórico si ``days`` es None; si no, de la ventana)."""
    if days is None:
        peak = close.cummax()
    else:
        n = int(round(days * HOURS_PER_DAY))
        peak = close.rolling(n, min_periods=1).max()
    return np.log(close / peak)


def squash(x: pd.Series | np.ndarray, scale: float = 1.0):
    """Compresión suave a (-1, 1): lineal cerca de cero, saturada en los extremos."""
    return np.tanh(np.asarray(x, dtype="float64") / scale) if not isinstance(x, pd.Series) else np.tanh(x / scale)
