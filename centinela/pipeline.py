"""Tubería común a backtest y operativa real: datos -> señales -> objetivo -> riesgo.

Que ambos mundos pasen por estas mismas funciones es lo que garantiza que lo que se
opera en vivo es exactamente lo que se validó en el histórico.
"""

from __future__ import annotations

import pandas as pd

from . import strategy
from .backtest.engine import BacktestResult, run_backtest
from .config import Config
from .risk import RiskManager, RiskState, crash_inputs


def build_targets(cfg: Config, bars: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series]:
    """Características de la estrategia y peso objetivo bruto (ya escalado por la asignación)."""
    feats = strategy.compute(bars, cfg.strategy)
    target = feats["target"] * cfg.allocation
    return feats, target


def make_risk(cfg: Config, bars: pd.DataFrame, feats: pd.DataFrame, state: RiskState | None = None) -> RiskManager:
    sigma_daily, ref_high = crash_inputs(bars["close"], feats["vol"], cfg.risk.crash_lookback_h)
    return RiskManager(cfg.risk, sigma_daily, ref_high, state)


def backtest(cfg: Config, bars: pd.DataFrame, start=None, end=None, **bt_overrides) -> BacktestResult:
    """Backtest completo con la configuración dada (estrategia + riesgo + costes)."""
    feats, target = build_targets(cfg, bars)
    risk = make_risk(cfg, bars, feats)
    res = run_backtest(bars, target, cfg.backtest_config(**bt_overrides), risk=risk, start=start, end=end)
    res.meta.update({"halts": risk.state.halts, "stops": risk.state.stops, "profile": cfg.profile})
    return res
