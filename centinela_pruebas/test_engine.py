"""Contabilidad y reglas de ejecución del motor de backtest."""

import numpy as np
import pandas as pd
import pytest

from centinela.backtest.engine import BacktestConfig, run_backtest
from centinela.data.store import to_index

HOUR = 3_600_000


def frame(opens, closes=None, lows=None, gaps=None):
    opens = np.asarray(opens, dtype="float64")
    closes = opens if closes is None else np.asarray(closes, dtype="float64")
    lows = np.minimum(opens, closes) if lows is None else np.asarray(lows, dtype="float64")
    idx = to_index(1_600_000_000_000 // HOUR * HOUR + np.arange(len(opens)) * HOUR)
    df = pd.DataFrame({"open": opens, "high": np.maximum(opens, closes), "low": lows, "close": closes}, index=idx)
    df["gap"] = False if gaps is None else np.asarray(gaps, dtype=bool)
    return df


def test_no_signal_means_no_position():
    df = frame([100, 110, 90, 120])
    res = run_backtest(df, pd.Series(np.nan, index=df.index))
    assert (res.equity == 10_000).all() and res.trades.empty


def test_decision_at_close_is_filled_at_next_open_with_costs():
    # la señal aparece al cierre de la vela 0; la vela 1 abre con un salto del +10 %
    df = frame(opens=[100, 110, 110], closes=[100, 110, 121])
    cfg = BacktestConfig(fee=0.001, slippage=0.0005, band=0.1)
    res = run_backtest(df, pd.Series([1.0, 1.0, 1.0], index=df.index), cfg)
    tr = res.trades.iloc[0]
    px = 110 * 1.0005
    assert tr["time"] == df.index[1] and tr["price"] == pytest.approx(px)  # no captura el salto
    qty = 10_000 / (px * 1.001)
    assert tr["qty"] == pytest.approx(qty)
    assert res.equity.iloc[0] == pytest.approx(10_000)
    assert res.equity.iloc[-1] == pytest.approx(qty * 121)
    assert res.fees_paid == pytest.approx(qty * px * 0.001)


def test_band_suppresses_small_rebalances():
    df = frame([100] * 8)
    target = pd.Series([0.5, 0.55, 0.45, 0.6, 0.5, 0.4, 0.62, 0.5], index=df.index)
    res = run_backtest(df, target, BacktestConfig(band=0.15, fee=0, slippage=0))
    assert len(res.trades) == 1  # solo la entrada inicial supera la banda


def test_full_exit_ignores_the_band():
    df = frame([100] * 6)
    target = pd.Series([0.30, 0.12, 0.12, 0.0, 0.0, 0.0], index=df.index)
    res = run_backtest(df, target, BacktestConfig(band=0.15, fee=0, slippage=0))
    assert list(res.trades["side"]) == ["buy", "sell", "sell"]
    assert res.weight.iloc[-1] == 0.0  # 12 % < banda, pero una salida total nunca se retrasa


def test_nothing_executes_while_the_market_is_down():
    df = frame([100, 100, 100, 100, 100], gaps=[False, True, True, False, False])
    res = run_backtest(df, pd.Series(1.0, index=df.index), BacktestConfig(fee=0, slippage=0))
    assert res.trades["time"].iloc[0] == df.index[3]


def test_equity_identity_and_fee_ledger():
    rng = np.random.default_rng(1)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 400)))
    df = frame(px, closes=np.roll(px, -1))
    target = pd.Series(rng.choice([0.0, 0.3, 0.7, 1.0], size=400), index=df.index)
    res = run_backtest(df, target, BacktestConfig(fee=0.002, slippage=0.001, band=0.1))
    assert res.fees_paid == pytest.approx(res.trades["fee"].sum())
    assert (res.weight >= -1e-12).all() and (res.weight <= 1 + 1e-9).all()
    assert (res.equity > 0).all()
    # sin apalancamiento: el peso tras cada operación nunca supera el 100 %
    assert (res.trades["w_after"] <= 1 + 1e-9).all()


def test_costs_only_ever_hurt():
    rng = np.random.default_rng(2)
    px = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, 500)))
    df = frame(px, closes=np.roll(px, -1))
    target = pd.Series(rng.choice([0.0, 1.0], size=500), index=df.index)
    free = run_backtest(df, target, BacktestConfig(fee=0, slippage=0, band=0.1))
    paid = run_backtest(df, target, BacktestConfig(fee=0.004, slippage=0.001, band=0.1))
    assert paid.equity.iloc[-1] < free.equity.iloc[-1]


class StopAt:
    """Capa de riesgo mínima: parada fija a un precio."""

    def __init__(self, level):
        self.level, self.fired = level, []

    def on_close(self, ts_ms, equity, weight, raw_target, close, row):
        return 0.0 if self.fired else raw_target

    def stop_level(self):
        return float("nan") if self.fired else self.level

    def on_stop(self, ts_ms, price):
        self.fired.append(price)


def test_emergency_stop_fills_at_level_or_at_a_gapped_open():
    cfg = BacktestConfig(fee=0, slippage=0, band=0.1, stop_slippage=0.01)
    # caso 1: el mínimo perfora el nivel dentro de la vela -> se vende al nivel
    df = frame(opens=[100, 100, 100, 100], closes=[100, 100, 95, 95], lows=[100, 100, 80, 95])
    hook = StopAt(90.0)
    res = run_backtest(df, pd.Series(1.0, index=df.index), cfg, risk=hook)
    assert hook.fired == [pytest.approx(90 * 0.99)]
    assert res.weight.iloc[-1] == 0.0
    # caso 2: la vela ya abre por debajo -> se vende a la apertura, no al nivel
    df = frame(opens=[100, 100, 85, 85], closes=[100, 100, 85, 85], lows=[100, 100, 84, 85])
    hook = StopAt(90.0)
    run_backtest(df, pd.Series(1.0, index=df.index), cfg, risk=hook)
    assert hook.fired == [pytest.approx(85 * 0.99)]


def test_window_renormalizes_and_filters_trades():
    df = frame(np.linspace(100, 200, 200))
    res = run_backtest(df, pd.Series(1.0, index=df.index), BacktestConfig(fee=0, slippage=0))
    w = res.window(df.index[100], df.index[150])
    assert w.equity.iloc[0] == pytest.approx(10_000) and len(w.equity) == 51
    assert w.trades.empty  # la única compra ocurrió antes de la ventana
