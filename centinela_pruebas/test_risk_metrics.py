"""Gestor de riesgo, regla de rebalanceo y métricas."""

import math

import numpy as np
import pandas as pd
import pytest

from centinela.backtest.metrics import bootstrap_sharpe, compute_metrics, max_drawdown, yearly_table
from centinela.data.store import to_index
from centinela.risk import RiskConfig, RiskManager, RiskState, is_full_exit, should_rebalance

HOUR = 3_600_000


def test_rebalance_rule():
    assert not should_rebalance(0.50, 0.45, band=0.15)
    assert should_rebalance(0.50, 0.30, band=0.15)
    assert should_rebalance(0.0, 0.05, band=0.15)  # salida total aunque esté dentro de la banda
    assert not should_rebalance(0.0, 0.0, band=0.15)
    assert not should_rebalance(0.004, 0.0, band=0.15)
    assert is_full_exit(0.0, 0.2) and not is_full_exit(0.1, 0.2)


def test_drawdown_governor_halts_cools_down_and_resumes():
    rm = RiskManager(RiskConfig(dd_halt=0.30, dd_cooldown_h=48))
    t = 0
    assert rm.on_close(t, 100.0, 0.5, 0.8, 1.0, 0) == 0.8
    assert rm.on_close(t + HOUR, 80.0, 0.5, 0.8, 1.0, 1) == 0.8  # -20 %: aún no
    assert rm.on_close(t + 2 * HOUR, 69.0, 0.5, 0.8, 1.0, 2) == 0.0  # -31 %: fuera
    assert rm.state.halts == 1
    assert rm.on_close(t + 20 * HOUR, 69.0, 0.0, 0.8, 1.0, 20) == 0.0  # enfriando
    assert rm.state.halts == 1  # no se cuenta dos veces
    # terminado el enfriamiento vuelve a operar y mide la caída desde el capital actual
    assert rm.on_close(t + 50 * HOUR, 69.0, 0.0, 0.8, 1.0, 50) == 0.8
    assert rm.state.peak_equity == 69.0
    assert rm.on_close(t + 51 * HOUR, 60.0, 0.5, 0.8, 1.0, 51) == 0.8  # -13 % desde el nuevo máximo


def test_drawdown_governor_reduces_before_halting():
    rm = RiskManager(RiskConfig(dd_reduce=0.10, dd_halt=0.30, dd_reduce_factor=0.5))
    rm.on_close(0, 100.0, 0.5, 1.0, 1.0, 0)
    assert rm.on_close(HOUR, 88.0, 0.5, 1.0, 1.0, 1) == 0.5


def test_risk_layers_never_increase_exposure():
    rng = np.random.default_rng(0)
    rm = RiskManager(RiskConfig(dd_reduce=0.1, dd_halt=0.2, dd_cooldown_h=5))
    eq = 100.0
    for i in range(500):
        eq *= math.exp(rng.normal(0, 0.03))
        raw = float(rng.uniform(0, 1))
        assert rm.on_close(i * HOUR, eq, 0.5, raw, 1.0, i) <= raw + 1e-12


def test_crash_stop_level_and_cooldown():
    sigma = np.full(10, 0.03)
    high = np.full(10, 100.0)
    rm = RiskManager(RiskConfig(crash_sigmas=3.0, crash_cooldown_h=5), sigma, high)
    assert math.isnan(rm.stop_level())
    rm.on_close(0, 100.0, 1.0, 1.0, 100.0, 0)
    assert rm.stop_level() == pytest.approx(100 * math.exp(-0.09))
    rm.on_stop(HOUR, 91.0)
    assert math.isnan(rm.stop_level()) and rm.state.stops == 1
    assert rm.on_close(2 * HOUR, 91.0, 0.0, 1.0, 91.0, 2) == 0.0  # enfriando
    assert rm.on_close(7 * HOUR, 91.0, 0.0, 1.0, 91.0, 7) == 1.0  # de vuelta


def test_crash_stop_is_off_by_default():
    rm = RiskManager(RiskConfig(), np.full(3, 0.03), np.full(3, 100.0))
    rm.on_close(0, 100.0, 1.0, 1.0, 100.0, 0)
    assert math.isnan(rm.stop_level())


def test_risk_state_survives_serialization():
    st = RiskState(peak_equity=123.4, halted_until_ms=99, stops=2)
    back = RiskState.from_dict(st.to_dict())
    assert back.peak_equity == 123.4 and back.halted_until_ms == 99 and back.stops == 2
    assert math.isnan(back.stop_level)
    assert RiskState.from_dict(None).peak_equity == 0.0
    assert RiskState.from_dict({"peak_equity": 5.0, "campo_viejo": 1}).peak_equity == 5.0


def test_invalid_risk_config_is_rejected():
    with pytest.raises(ValueError):
        RiskConfig(dd_reduce=0.4, dd_halt=0.3)
    with pytest.raises(ValueError):
        RiskConfig(crash_sigmas=-1)


# ------------------------------------------------------------------ métricas
def daily(values, start="2021-01-01"):
    idx = pd.date_range(start, periods=len(values), freq="D", tz="UTC")
    return pd.Series(np.asarray(values, dtype="float64"), index=idx)


def test_cagr_of_a_doubling_year():
    eq = daily(np.linspace(100, 200, 366))  # 365 días exactos
    m = compute_metrics(eq)
    assert m["cagr"] == pytest.approx(1.0, rel=1e-6)
    assert m["total_return"] == pytest.approx(1.0)
    assert m["max_drawdown"] == 0.0


def test_max_drawdown_finds_peak_and_trough():
    eq = daily([100, 120, 90, 60, 80, 130, 125])
    dd, peak, trough, _ = max_drawdown(eq)
    assert dd == pytest.approx(-0.5)
    assert peak == eq.index[1] and trough == eq.index[3]


def test_sharpe_matches_definition():
    rng = np.random.default_rng(5)
    r = rng.normal(0.001, 0.02, 800)
    eq = daily(100 * np.cumprod(1 + r))
    m = compute_metrics(eq)
    rr = eq.pct_change().dropna()
    assert m["sharpe"] == pytest.approx(rr.mean() / rr.std(ddof=1) * np.sqrt(365))


def test_yearly_table_compounds_to_total():
    rng = np.random.default_rng(6)
    eq = daily(100 * np.cumprod(1 + rng.normal(0.001, 0.02, 900)), "2020-03-01")
    yt = yearly_table(eq, eq)
    assert np.prod(1 + yt["estrategia"].to_numpy()) == pytest.approx(eq.iloc[-1] / eq.iloc[0])


def test_bootstrap_interval_brackets_the_point_estimate():
    rng = np.random.default_rng(7)
    eq = daily(100 * np.cumprod(1 + rng.normal(0.002, 0.02, 1500)))
    b = bootstrap_sharpe(eq, n_boot=400)
    s = compute_metrics(eq)["sharpe"]
    assert b["sharpe_p05"] < s < b["sharpe_p95"]


def test_exposure_metrics_use_weights():
    idx = to_index(np.arange(48) * HOUR)
    eq = pd.Series(np.linspace(100, 110, 48), index=idx)
    w = pd.Series([0.0] * 24 + [0.5] * 24, index=idx)
    m = compute_metrics(eq, w, pd.DataFrame({"w_before": [0.0], "w_after": [0.5], "kind": ["rebalance"], "fee": [0.1]}))
    assert m["avg_exposure"] == pytest.approx(0.25) and m["time_in_market"] == pytest.approx(0.5)
    assert m["episodes"] == 1 and m["executions"] == 1
