"""La estrategia: tendencia en varias ventanas + base cubierta.

Idea
----
1. Para cada moneda se mide la TENDENCIA con diez relojes a la vez: seis cruces
   de medias exponenciales (de 2/8 a 16/64 días) y cuatro rupturas de canal
   (5, 10, 20 y 40 días). La puntuación es la media, entre -1 y +1. Usar muchas
   ventanas en vez de una "óptima" es lo que evita depender de un ajuste fino.
2. Las alts solo cuentan al alza si BITCOIN también está en tendencia positiva.
3. Se mantiene una BASE de cada moneda, de tamaño inversamente proporcional a
   su volatilidad (todas arriesgan parecido), y se CUBRE con un corto en el
   perpetuo la parte que la tendencia no respalda:

       exposición neta = base × puntuación⁺        cobertura = base − neta

   Tendencia plena → sin cobertura. Tendencia en contra → cubierta al 100 %
   (neutral), cobrando financiación mientras tanto. Es la cobertura del material
   de Jorge, pero graduada por la tendencia y sin pasar del 100 %: medido sobre
   2020-2023, cubrir al 200 % como él indica rinde menos y cae más.
4. Encima, un control de riesgo de CARTERA: si la volatilidad prevista de la
   exposición neta supera el objetivo, se cubre más.

Todo es función pura de velas cerradas, así que el simulador y el bot en vivo
ejecutan exactamente este código.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

import numpy as np

from bot import indicadores as ind

VELAS_DIA = {"1h": 24.0, "2h": 12.0, "4h": 6.0, "8h": 3.0, "12h": 2.0, "1d": 1.0}


@dataclass(frozen=True)
class Parametros:
    # Universo. La primera es el ancla del filtro de mercado.
    simbolos: tuple = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
                       "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT")
    intervalo: str = "4h"

    # Tendencia (en días)
    cruces: tuple = ((2, 8), (4, 16), (5, 20), (8, 32), (10, 40), (16, 64))
    rupturas: tuple = (5, 10, 20, 40)
    rodaje_dias: float = 90.0          # historia mínima antes de opinar sobre una moneda
    filtro_ancla: bool = True          # alts al alza solo si el ancla (BTC) está en positivo

    # Tamaño
    vol_moneda: float = 0.50           # volatilidad anual que aporta cada moneda con señal plena
    dias_vol: float = 30.0
    vol_minima: float = 0.15
    tope_base: float = 0.75            # fracción máxima del patrimonio en la base

    # Riesgo de cartera
    vol_cartera: float = 0.25          # volatilidad anual objetivo de la exposición neta
    dias_cov: float = 45.0
    escala_max: float = 3.0

    # Cobertura
    cobertura_max: float = 1.0         # 1 = como mucho neutral; >1 deja neto corto en tendencia bajista

    # Apalancamiento de la tendencia: 1 = la exposición nunca pasa de la base (sin deuda).
    # Por encima de 1, lo que exceda la base se toma en perpetuos y paga financiación.
    apalancamiento: float = 1.0

    # Ejecución
    modo: str = "base_cubierta"        # "base_cubierta" (contado + corto) o "perpetuos" (solo neto)
    banda_base: float = 0.40           # no se toca la base si se desvía menos del 40 % de su objetivo
    banda_cobertura: float = 0.20
    minimo_orden_usdt: float = 10.0

    def como_dict(self) -> dict:
        return asdict(self)


def puntuacion(h: np.ndarray, l: np.ndarray, c: np.ndarray, velas_dia: float,
               p: Parametros) -> np.ndarray:
    """Tendencia de una moneda en [-1, 1], vela a vela."""
    n = len(c)
    if n == 0:
        return np.zeros(0)
    cruces = np.zeros(n)
    for rapida, lenta in p.cruces:
        cruces += np.sign(ind.ema(c, rapida * velas_dia) - ind.ema(c, lenta * velas_dia))
    cruces /= len(p.cruces)

    rupt = np.zeros(n)
    for dias in p.rupturas:
        rupt += _canal(h, l, c, int(round(dias * velas_dia)))
    rupt /= len(p.rupturas)

    s = 0.5 * (cruces + rupt)
    s[: int(round(p.rodaje_dias * velas_dia))] = 0.0
    return s


def _canal(h: np.ndarray, l: np.ndarray, c: np.ndarray, n: int) -> np.ndarray:
    """+1 desde que el cierre supera el máximo de las `n` velas anteriores; -1 bajo el mínimo."""
    arriba = np.concatenate(([np.nan], ind.maximo(h, n)[:-1]))
    abajo = np.concatenate(([np.nan], ind.minimo(l, n)[:-1]))
    evento = np.where(c > arriba, 1.0, np.where(c < abajo, -1.0, 0.0))
    # Arrastra el último evento no nulo.
    idx = np.where(evento != 0.0, np.arange(len(c)), -1)
    ultimo = np.maximum.accumulate(idx)
    return np.where(ultimo >= 0, evento[np.maximum(ultimo, 0)], 0.0)


@dataclass
class Objetivos:
    """Pesos objetivo (fracción del patrimonio) para cada vela y moneda."""

    puntuacion: np.ndarray       # tendencia bruta [-1, 1]
    vol: np.ndarray              # volatilidad anual estimada de cada moneda
    base: np.ndarray             # peso de la base (contado); 0 en modo perpetuos
    neto: np.ndarray             # exposición neta deseada
    cobertura: np.ndarray        # corto en perpetuo = base − neto (≥ 0); en modo perpetuos, 0
    escala: np.ndarray           # factor del control de riesgo de cartera, por vela
    vol_prevista: np.ndarray     # volatilidad anual prevista de la exposición neta ya escalada

    def perp(self) -> np.ndarray:
        """Peso que debe tener la pata de perpetuos (negativo = corto)."""
        return self.neto - self.base


def calcular(H: np.ndarray, L: np.ndarray, C: np.ndarray, p: Parametros,
             ajuste_nota: Optional[np.ndarray] = None) -> Objetivos:
    """Objetivos para todas las velas. Matrices tiempo × moneda, NaN si aún no cotiza.

    Las columnas van en el orden de `p.simbolos`.

    `ajuste_nota` (tiempo × moneda) se suma a la nota de tendencia antes de decidir cuánto
    exponer; el filtro de mercado sigue mirando la tendencia sin ajustar. Es el enganche para
    información que no sale del precio (posicionamiento). Sin él, la estrategia es solo precio.
    """
    T, N = C.shape
    vd = VELAS_DIA[p.intervalo]
    velas_anio = vd * 365.0
    cotiza = ~np.isnan(C)

    S = np.zeros((T, N))
    V = np.full((T, N), np.nan)
    for j in range(N):
        ok = cotiza[:, j]
        if ok.sum() < 5:
            continue
        S[ok, j] = puntuacion(H[ok, j], L[ok, j], C[ok, j], vd, p)
        V[ok, j] = ind.volatilidad_ewma(C[ok, j], p.dias_vol * vd, velas_anio)

    # Filtro de mercado: sin Bitcoin a favor, las alts no cuentan al alza.
    F = S.copy()
    if p.filtro_ancla and N > 1:
        ancla_ok = S[:, [0]] > 0
        F[:, 1:] = np.where(ancla_ok, S[:, 1:], np.minimum(S[:, 1:], 0.0))

    if ajuste_nota is not None:
        F = np.clip(F + np.where(cotiza, np.nan_to_num(ajuste_nota, nan=0.0), 0.0), -1.0, 1.0)
        if p.filtro_ancla and N > 1:        # el ajuste no puede saltarse el filtro de Bitcoin
            F[:, 1:] = np.where(S[:, [0]] > 0, F[:, 1:], np.minimum(F[:, 1:], 0.0))

    vol = np.maximum(np.nan_to_num(V, nan=np.inf), p.vol_minima)
    base = np.where(cotiza, (p.vol_moneda / vol) / N, 0.0)
    total = base.sum(axis=1, keepdims=True)
    base *= np.minimum(1.0, p.tope_base / np.maximum(total, 1e-12))

    techo = base * p.apalancamiento
    neto = techo * np.clip(F, 0.0, 1.0)

    # Control de riesgo de cartera con covarianza exponencial (causal).
    R = np.zeros((T, N))
    R[1:] = C[1:] / C[:-1] - 1.0
    R = np.nan_to_num(R, nan=0.0, posinf=0.0, neginf=0.0)
    lam = 1.0 - 2.0 / (p.dias_cov * vd + 1.0)
    cov = np.zeros((N, N))
    escala = np.ones(T)
    vol_prev = np.zeros(T)
    for k in range(T):
        cov = lam * cov + (1.0 - lam) * np.outer(R[k], R[k])
        w = neto[k]
        sigma = float(np.sqrt(max(w @ cov @ w, 0.0) * velas_anio))
        if sigma > 1e-9:
            esc = min(p.vol_cartera / sigma, p.escala_max)
            ajustado = np.minimum(w * esc, techo[k])
            neto[k] = ajustado
            escala[k] = esc
            vol_prev[k] = float(np.sqrt(max(ajustado @ cov @ ajustado, 0.0) * velas_anio))

    # Sobrecobertura opcional: en tendencia bajista, corto por encima de la base.
    if p.cobertura_max > 1.0:
        neto = neto - base * (p.cobertura_max - 1.0) * np.clip(-F, 0.0, 1.0)

    if p.modo == "perpetuos":
        return Objetivos(S, V, np.zeros((T, N)), neto, np.zeros((T, N)), escala, vol_prev)
    return Objetivos(S, V, base, neto, base - neto, escala, vol_prev)


def hay_que_mover(actual: np.ndarray, objetivo: np.ndarray, banda_rel, banda_abs=0.0) -> np.ndarray:
    """Qué posiciones se reajustan: las que se alejan del objetivo más que la banda.

    Un cierre a cero y un cambio de signo se ejecutan siempre.
    """
    actual = np.asarray(actual, dtype=np.float64)
    objetivo = np.asarray(objetivo, dtype=np.float64)
    umbral = np.maximum(banda_abs, banda_rel * np.abs(objetivo))
    mover = np.abs(objetivo - actual) > umbral
    mover |= (objetivo == 0.0) & (actual != 0.0)
    mover |= (np.sign(objetivo) != np.sign(actual)) & (objetivo != 0.0)
    return mover

