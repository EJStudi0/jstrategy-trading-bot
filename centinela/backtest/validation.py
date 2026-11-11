"""Pruebas de robustez: lo que separa una estrategia validada de una ajustada al pasado.

Protocolo seguido al diseñar Centinela (y reproducible con ``centinela validar``):

* **Periodo de diseño**: hasta el 31-12-2024. Todas las decisiones de diseño se
  tomaron mirando únicamente estos datos.
* **Periodo fuera de muestra**: desde el 01-01-2025. Se evaluó una sola vez, con el
  diseño ya congelado. Es la estimación más honesta de qué esperar en adelante.
"""

from __future__ import annotations

from dataclasses import replace

import pandas as pd

from .. import pipeline
from ..config import Config
from .engine import BacktestResult, run_backtest
from .metrics import compute_metrics

HOLDOUT_START = "2025-01-01"
DEFAULT_START = "2014-01-01"


def summarize(res: BacktestResult) -> dict:
    m = compute_metrics(res.equity, res.weight, res.trades)
    b = compute_metrics(res.benchmark)
    return {"strategy": m, "benchmark": b}


def fee_sensitivity(cfg: Config, bars: pd.DataFrame, fees: tuple[float, ...], start=None, end=None) -> list[dict]:
    """Resultados con distintas comisiones por lado (cada exchange y nivel cobra distinto)."""
    out = []
    for fee in fees:
        res = pipeline.backtest(cfg, bars, start=start, end=end, fee=fee)
        m = compute_metrics(res.equity, res.weight, res.trades)
        out.append({"fee": fee, "cagr": m["cagr"], "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"]})
    return out


def delay_sensitivity(cfg: Config, bars: pd.DataFrame, delays_h: tuple[int, ...], start=None, end=None) -> list[dict]:
    """Resultados si cada decisión se ejecutara con N horas de retraso (bot caído, red lenta...)."""
    feats, target = pipeline.build_targets(cfg, bars)
    out = []
    for d in delays_h:
        risk = pipeline.make_risk(cfg, bars, feats)
        res = run_backtest(bars, target.shift(d), cfg.backtest_config(), risk=risk, start=start, end=end)
        m = compute_metrics(res.equity, res.weight, res.trades)
        out.append({"delay_h": d, "cagr": m["cagr"], "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"]})
    return out


def parameter_sensitivity(cfg: Config, bars: pd.DataFrame, start=None, end=None) -> list[dict]:
    """Resultados al mover cada parámetro alrededor de su valor: debe haber meseta, no pico."""
    s = cfg.strategy
    variants: list[tuple[str, Config]] = [("configuración actual", cfg)]
    for tv in (0.7, 1.4):
        variants.append((f"volatilidad objetivo x{tv:g}", replace(cfg, strategy=replace(s, target_vol=round(s.target_vol * tv, 4)))))
    for ff in (0.75, 1.25):
        variants.append((f"previsión plena x{ff:g}", replace(cfg, strategy=replace(s, full_forecast=min(1.0, round(s.full_forecast * ff, 4))))))
    for band in (0.10, 0.25):
        variants.append((f"banda {band:.2f}", replace(cfg, band=band)))
    speeds = s.trend_speeds_days
    if len(speeds) > 3:
        variants.append(("sin la tendencia más rápida", replace(cfg, strategy=replace(s, trend_speeds_days=speeds[1:]))))
        variants.append(("sin la tendencia más lenta", replace(cfg, strategy=replace(s, trend_speeds_days=speeds[:-1]))))
    variants.append(("tendencias x1,5 más lentas", replace(cfg, strategy=replace(s, trend_speeds_days=tuple(x * 1.5 for x in speeds)))))
    for hl in (0.5, 2.0):
        variants.append(
            (
                f"memoria de volatilidad x{hl:g}",
                replace(cfg, strategy=replace(s, vol_fast_halflife_h=s.vol_fast_halflife_h * hl, vol_slow_halflife_h=s.vol_slow_halflife_h * hl)),
            )
        )
    out = []
    for name, c in variants:
        res = pipeline.backtest(c, bars, start=start, end=end)
        m = compute_metrics(res.equity, res.weight, res.trades)
        out.append({"variant": name, "cagr": m["cagr"], "sharpe": m["sharpe"], "max_drawdown": m["max_drawdown"]})
    return out


def split_design_holdout(res: BacktestResult) -> dict[str, BacktestResult]:
    """Separa un backtest continuo en periodo de diseño y periodo fuera de muestra."""
    cut = pd.Timestamp(HOLDOUT_START, tz="UTC")
    out: dict[str, BacktestResult] = {}
    if res.equity.index[0] < cut - pd.Timedelta(days=30):
        out["diseño"] = res.window(None, cut - pd.Timedelta(hours=1))
    if res.equity.index[-1] > cut + pd.Timedelta(days=30):
        out["fuera de muestra"] = res.window(max(cut, res.equity.index[0]), None)
    return out
