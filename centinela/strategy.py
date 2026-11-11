"""Estrategia de Centinela: tendencia multi-horizonte con riesgo dirigido por volatilidad.

Idea central, en una frase: *estar en BTC en proporción a la fuerza y la limpieza de
su tendencia, y tanto menos cuanto más violento esté el mercado*.

Por qué esto y no otra cosa. Durante el diseño se contrastaron con datos (2014-2024,
con validación walk-forward) las palancas habituales: funding, MVRV on-chain, flujo
agresor, reversión a corto plazo, estacionalidad horaria y un meta-modelo de
aprendizaje automático. Solo dos efectos resultaron estables en todos los
subperiodos y robustos a costes:

1. **Persistencia de tendencia** de BTC en horizontes de días a meses.
2. **Agrupamiento de la volatilidad**, que la hace predecible (corr. ~0,7 a 24 h).

El resto no superó la validación fuera de muestra y se dejó fuera del motor de
decisión; se muestra solo como contexto (ver ``context``).

Todo el cálculo es vectorizado y causal: el valor en la fila ``t`` usa únicamente
velas ``<= t``. El mismo código corre en backtest y en vivo (en vivo se recalcula
sobre todo el histórico local y se toma la última fila), de modo que no puede haber
divergencia entre lo simulado y lo operado.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from . import btc
from . import indicators as ind


@dataclass(frozen=True)
class StrategyConfig:
    # Velocidades de tendencia: media rápida en días; la lenta es siempre 4x la rápida.
    trend_speeds_days: tuple[float, ...] = (2.0, 4.0, 8.0, 16.0, 32.0, 64.0)
    # Nivel de previsión combinada con el que la exposición por tendencia llega al 100 %.
    full_forecast: float = 0.40
    # Volatilidad anualizada objetivo de la posición en BTC (el dial de riesgo principal).
    target_vol: float = 0.50
    max_exposure: float = 1.0
    # Previsión de volatilidad: mezcla de semividas rápida y lenta (en horas).
    vol_fast_halflife_h: float = 24.0
    vol_slow_halflife_h: float = 336.0
    vol_floor_frac: float = 0.5
    # Histórico mínimo antes de emitir objetivos (la media más lenta debe haber convergido).
    warmup_days: int = 365

    def __post_init__(self) -> None:
        if not self.trend_speeds_days:
            raise ValueError("hace falta al menos una velocidad de tendencia")
        if not 0 < self.full_forecast <= 1:
            raise ValueError("full_forecast debe estar en (0, 1]")
        if not 0 < self.target_vol <= 3:
            raise ValueError("target_vol fuera de rango razonable")
        if not 0 < self.max_exposure <= 1:
            raise ValueError("max_exposure debe estar en (0, 1]: el bot no usa apalancamiento")


def forecast_scalar(fast_days: float) -> float:
    """Escala teórica de un EWMAC (rápida, 4x rápida) para que |previsión| media sea ~0,5.

    Bajo paseo aleatorio la dispersión del cruce crece con la raíz de la velocidad;
    10,6 es el valor de referencia para el par (2, 8) con previsión media 10 y tope 20.
    """
    return 10.6 * np.sqrt(2.0 / fast_days) / 20.0


def sleeve_name(fast_days: float) -> str:
    return f"tend_{fast_days:g}d"


def compute(bars: pd.DataFrame, cfg: StrategyConfig | None = None) -> pd.DataFrame:
    """Calcula previsiones, volatilidad y el peso objetivo en BTC para cada vela.

    Columnas devueltas:
      ``vol``            volatilidad anualizada prevista
      ``tend_<n>d``      previsión de cada velocidad de tendencia, en [-1, 1]
      ``forecast``       media de las previsiones (lo bajista compensa a lo alcista)
      ``trend_exposure`` exposición que pide la tendencia sola, en [0, 1]
      ``vol_scalar``     factor de reducción por volatilidad, en (0, 1]
      ``target``         peso objetivo final en BTC, en [0, max_exposure]
    """
    cfg = cfg or StrategyConfig()
    c, o, h, l = bars["close"], bars["open"], bars["high"], bars["low"]
    out = pd.DataFrame(index=bars.index)
    vol = ind.blended_vol(
        c, o, h, l,
        fast_hl=cfg.vol_fast_halflife_h,
        slow_hl=cfg.vol_slow_halflife_h,
        floor_frac=cfg.vol_floor_frac,
    )  # fmt: skip
    out["vol"] = vol
    names = []
    for fast in cfg.trend_speeds_days:
        name = sleeve_name(fast)
        out[name] = (ind.ewmac(c, fast, 4.0 * fast, vol) * forecast_scalar(fast)).clip(-1.0, 1.0)
        names.append(name)
    out["forecast"] = out[names].mean(axis=1, skipna=False)
    out["trend_exposure"] = (out["forecast"] / cfg.full_forecast).clip(0.0, 1.0)
    out["vol_scalar"] = (cfg.target_vol / vol).clip(upper=1.0)
    target = (out["trend_exposure"] * out["vol_scalar"]).clip(0.0, cfg.max_exposure)
    warm = cfg.warmup_days * 24
    if warm > 0:
        target.iloc[: min(warm, len(target))] = np.nan
    out["target"] = target
    return out


def regime(forecast: float, vol_rank: float) -> str:
    """Etiqueta legible del régimen de mercado (solo descriptiva)."""
    if forecast != forecast:
        return "sin datos suficientes"
    if forecast >= 0.25:
        trend = "tendencia alcista fuerte"
    elif forecast >= 0.08:
        trend = "tendencia alcista"
    elif forecast > -0.08:
        trend = "sin tendencia definida"
    elif forecast > -0.25:
        trend = "tendencia bajista"
    else:
        trend = "tendencia bajista fuerte"
    if vol_rank != vol_rank:
        return trend
    if vol_rank >= 0.85:
        return f"{trend}, volatilidad muy alta"
    if vol_rank >= 0.60:
        return f"{trend}, volatilidad elevada"
    if vol_rank <= 0.20:
        return f"{trend}, mercado en calma"
    return f"{trend}, volatilidad normal"


def context(bars: pd.DataFrame, feats: pd.DataFrame) -> dict:
    """Radiografía de BTC en la última vela: contexto informativo, no señales operadas."""
    last = bars.index[-1]
    c = bars["close"]
    row = feats.iloc[-1]
    vol_rank = float(ind.rolling_rank(feats["vol"], 24 * 365, 24 * 60).iloc[-1])
    f7 = bars["funding"].rolling(24 * 7, min_periods=24).mean()
    fund_rank = float(ind.rolling_rank(f7, 24 * 365, 24 * 60).iloc[-1])
    sma200 = c.rolling(4800, min_periods=2400).mean().iloc[-1]
    ath = float(bars["high"].max())
    fund_age = float(bars["funding_age_h"].iloc[-1]) if "funding_age_h" in bars else np.nan
    mvrv_age = float(bars["mvrv_age_h"].iloc[-1]) if "mvrv_age_h" in bars else np.nan
    cyc = btc.cycle_info(last.to_pydatetime())
    return {
        "time": last,
        "price": float(c.iloc[-1]),
        "regime": regime(float(row["forecast"]), vol_rank),
        "vol": float(row["vol"]),
        "vol_rank_1y": vol_rank,
        "ret_24h": float(c.iloc[-1] / c.iloc[-25] - 1.0) if len(c) > 25 else np.nan,
        "ret_7d": float(c.iloc[-1] / c.iloc[-169] - 1.0) if len(c) > 169 else np.nan,
        "ret_30d": float(c.iloc[-1] / c.iloc[-721] - 1.0) if len(c) > 721 else np.nan,
        "drawdown_from_ath": float(c.iloc[-1] / ath - 1.0),
        "mayer_multiple": float(c.iloc[-1] / sma200) if sma200 == sma200 else np.nan,
        "funding_8h": float(bars["funding"].iloc[-1]),
        "funding_annualized": float(btc.funding_annualized(bars["funding"].iloc[-1])),
        "funding_rank_1y": fund_rank,
        "funding_stale": bool(fund_age != fund_age or fund_age > 30),
        "mvrv": float(bars["mvrv"].iloc[-1]),
        "mvrv_stale": bool(mvrv_age != mvrv_age or mvrv_age > 24 * 5),
        "session": btc.session_of(last.hour),
        "weekend": btc.is_weekend(last),
        "cycle": cyc,
    }


def _dec(x: float, digits: int = 2, signed: bool = False) -> str:
    """Número con coma decimal (formato español)."""
    return (f"{x:+.{digits}f}" if signed else f"{x:.{digits}f}").replace(".", ",")


def _pct(x: float) -> str:
    return f"{x * 100:.0f} %"


def explain(row: pd.Series, cfg: StrategyConfig) -> list[str]:
    """Explica en lenguaje llano por qué el objetivo es el que es."""
    lines: list[str] = []
    if row["target"] != row["target"]:
        return ["Histórico insuficiente todavía para decidir (periodo de calentamiento)."]
    parts = []
    bulls = 0
    for fast in cfg.trend_speeds_days:
        v = float(row[sleeve_name(fast)])
        bulls += v > 0.05
        parts.append(f"{fast:g} d {_dec(v, 2, True)}")
    n = len(cfg.trend_speeds_days)
    lines.append(f"Tendencia por horizonte ({bulls} de {n} alcistas): " + " · ".join(parts))
    f = float(row["forecast"])
    te = float(row["trend_exposure"])
    if f <= 0:
        lines.append(f"Previsión combinada {_dec(f, 2, True)}: negativa, la tendencia no justifica tener BTC.")
    else:
        lines.append(
            f"Previsión combinada {_dec(f, 2, True)} (exposición plena a partir de {_dec(cfg.full_forecast)}): "
            f"la tendencia pide un {_pct(te)} en BTC."
        )
    vs = float(row["vol_scalar"])
    v = float(row["vol"])
    if vs < 0.999:
        lines.append(f"Volatilidad prevista {_pct(v)}, por encima del objetivo ({_pct(cfg.target_vol)}): el tamaño se multiplica por {_dec(vs)}.")
    else:
        lines.append(f"Volatilidad prevista {_pct(v)}, dentro del objetivo ({_pct(cfg.target_vol)}): sin recorte por volatilidad.")
    lines.append(f"Peso objetivo en BTC: {_pct(float(row['target']))}.")
    return lines
