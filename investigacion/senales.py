"""Señales candidatas, como matrices tiempo × moneda en [-1, 1]."""
from __future__ import annotations

import numpy as np

from bot import indicadores as ind
from investigacion.laboratorio import Cuadricula, por_columnas


def velas_por_dia(g: Cuadricula) -> float:
    return g.velas_anio / 365.0


def tsmom(g: Cuadricula, dias: float) -> np.ndarray:
    """Signo del rendimiento de los últimos `dias`."""
    L = int(round(dias * velas_por_dia(g)))

    def f(c):
        out = np.zeros(len(c))
        out[L:] = np.sign(c[L:] / c[:-L] - 1.0)
        return out
    return por_columnas(f, g.C)


def cruce(g: Cuadricula, dias_rapida: float, dias_lenta: float) -> np.ndarray:
    """Signo de EMA rápida − EMA lenta."""
    vpd = velas_por_dia(g)

    def f(c):
        return np.sign(ind.ema(c, dias_rapida * vpd) - ind.ema(c, dias_lenta * vpd))
    return por_columnas(f, g.C)


def cruce_suave(g: Cuadricula, dias_rapida: float, dias_lenta: float, k: float = 1.0) -> np.ndarray:
    """(EMA rápida − EMA lenta) medida en desviaciones del precio, pasada por tanh.

    A diferencia del cruce a secas no salta de -1 a +1 en el cruce: crece con la
    fuerza de la tendencia, así que cerca del cruce la posición es pequeña.
    """
    vpd = velas_por_dia(g)

    def f(c):
        r = ind.rendimientos(c)
        sigma = np.sqrt(ind.ema(r * r, 30 * vpd)) * c
        dif = ind.ema(c, dias_rapida * vpd) - ind.ema(c, dias_lenta * vpd)
        escala = sigma * np.sqrt(dias_lenta * vpd)
        with np.errstate(divide="ignore", invalid="ignore"):
            z = np.where(escala > 0, dif / escala, 0.0)
        return np.tanh(k * z)
    return por_columnas(f, g.C)


def ruptura(g: Cuadricula, dias: float) -> np.ndarray:
    """Canal de Donchian: +1 desde que cierra sobre el máximo de `dias`, -1 bajo el mínimo."""
    L = int(round(dias * velas_por_dia(g)))

    def f(h, l, c):
        arriba = ind.maximo(h, L)
        abajo = ind.minimo(l, L)
        arriba = np.concatenate(([np.nan], arriba[:-1]))   # canal de las velas ANTERIORES
        abajo = np.concatenate(([np.nan], abajo[:-1]))
        estado = np.zeros(len(c))
        s = 0.0
        for i in range(len(c)):
            if c[i] > arriba[i]:
                s = 1.0
            elif c[i] < abajo[i]:
                s = -1.0
            estado[i] = s
        return estado
    return por_columnas(f, g.H, g.L, g.C)


def conjunto(mats: list) -> np.ndarray:
    """Media de varias señales."""
    return np.nanmean(np.stack(mats), axis=0)


def volatilidad(g: Cuadricula, dias: float = 30.0) -> np.ndarray:
    vpd = velas_por_dia(g)
    return por_columnas(lambda c: ind.volatilidad_ewma(c, dias * vpd, g.velas_anio), g.C)


def pesos(g: Cuadricula, señal: np.ndarray, vol_objetivo: float = 0.5, dias_vol: float = 30.0,
          solo_largo: bool = False, factor_corto: float = 1.0, tope_moneda: float = 1.0,
          tope_bruto: float = 2.0, vol_minima: float = 0.15) -> np.ndarray:
    """Convierte señal en pesos: riesgo igual por moneda, con topes."""
    N = señal.shape[1]
    vol = np.maximum(volatilidad(g, dias_vol), vol_minima)
    s = np.where(señal < 0, señal * (0.0 if solo_largo else factor_corto), señal)
    W = s * (vol_objetivo / vol) / N
    W = np.clip(np.nan_to_num(W, nan=0.0), -tope_moneda, tope_moneda)
    bruto = np.abs(W).sum(axis=1, keepdims=True)
    escala = np.minimum(1.0, tope_bruto / np.maximum(bruto, 1e-12))
    return W * escala
