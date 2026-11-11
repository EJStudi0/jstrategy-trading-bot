"""La garantía más importante del bot: ninguna señal usa información del futuro."""

import numpy as np
import pandas as pd
import pytest

from centinela import indicators as ind
from centinela import strategy
from centinela.data.store import HOUR_MS, assemble
from centinela.strategy import StrategyConfig

CFG = StrategyConfig(warmup_days=30)


def test_truncating_history_does_not_change_the_past(bars):
    """Recalcular con el histórico cortado en t debe dar la misma fila t que con todo el histórico."""
    full = strategy.compute(bars, CFG)
    rng = np.random.default_rng(0)
    for cut in rng.integers(24 * 400, len(bars), size=10):
        part = strategy.compute(bars.iloc[:cut], CFG)
        pd.testing.assert_series_equal(part.iloc[-1], full.iloc[cut - 1], check_names=False, rtol=1e-9, atol=1e-12)


def test_changing_the_future_does_not_change_the_past(bars):
    cut = len(bars) - 24 * 50
    tampered = bars.copy()
    for col in ("open", "high", "low", "close"):
        tampered.iloc[cut:, tampered.columns.get_loc(col)] *= 1.7
    a = strategy.compute(bars, CFG).iloc[:cut]
    b = strategy.compute(tampered, CFG).iloc[:cut]
    pd.testing.assert_frame_equal(a, b)


@pytest.mark.parametrize(
    "fn",
    [
        lambda b, v: ind.ewmac(b.close, 4, 16, v),
        lambda b, v: ind.tsmom(b.close, 7, v),
        lambda b, v: ind.donchian_position(b.close, b.high, b.low, 10),
        lambda b, v: ind.sma_distance(b.close, 20, v),
        lambda b, v: ind.rsi(b.close, 14),
        lambda b, v: ind.zscore_return(b.close, 24, v),
        lambda b, v: ind.rolling_rank(b.close, 500),
        lambda b, v: ind.efficiency_ratio(b.close, 240),
        lambda b, v: ind.drawdown_from_high(b.close, 30),
        lambda b, v: ind.drawdown_from_high(b.close),
        lambda b, v: ind.blended_vol(b.close, b.open, b.high, b.low),
        lambda b, v: ind.blended_vol(b.close, use_range=False),
    ],
)
def test_every_indicator_is_causal(bars, fn):
    cut = len(bars) - 24 * 40
    tampered = bars.copy()
    for col in ("open", "high", "low", "close"):
        tampered.iloc[cut:, tampered.columns.get_loc(col)] *= 0.5
    vol = ind.blended_vol(bars.close, bars.open, bars.high, bars.low)
    vol_t = ind.blended_vol(tampered.close, tampered.open, tampered.high, tampered.low)
    a = fn(bars, vol).iloc[:cut]
    b = fn(tampered, vol_t).iloc[:cut]
    pd.testing.assert_series_equal(a, b, check_names=False)


def test_warmup_emits_no_target(bars):
    feats = strategy.compute(bars, StrategyConfig(warmup_days=100))
    assert feats["target"].iloc[: 100 * 24].isna().all()
    assert feats["target"].iloc[100 * 24 :].notna().all()


def test_target_is_long_only_and_bounded(bars):
    feats = strategy.compute(bars, StrategyConfig(warmup_days=30, max_exposure=0.8))
    t = feats["target"].dropna()
    assert (t >= 0).all() and (t <= 0.8 + 1e-12).all()
    # cuando la previsión combinada es negativa, el bot está fuera
    assert (feats.loc[feats["forecast"] <= 0, "target"].dropna() == 0).all()


def test_funding_and_mvrv_are_aligned_without_peeking(klines):
    t0 = int(klines["ts"].iloc[0])
    funding = pd.DataFrame({"ts": [t0 + 8 * HOUR_MS, t0 + 16 * HOUR_MS], "rate": [0.0001, 0.0005]})
    mvrv = pd.DataFrame({"ts": [t0], "mvrv": [2.0]})
    df = assemble(klines.iloc[:200], funding, mvrv)
    f = df["funding"].to_numpy()
    assert np.isnan(f[:8]).all()  # antes de la primera liquidación no se conoce ningún funding
    assert f[8] == 0.0001 and f[15] == 0.0001 and f[16] == 0.0005
    m = df["mvrv"].to_numpy()
    assert np.isnan(m[:48]).all() and m[48] == 2.0  # el dato del día D se usa desde D + 48 h
