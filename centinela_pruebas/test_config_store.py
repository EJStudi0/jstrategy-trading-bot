"""Configuración estricta y almacén de datos."""

import os

import numpy as np
import pandas as pd
import pytest

from centinela import config as C
from centinela.data.store import HOUR_MS, DataStore, assemble, describe_gaps, splice_history, validate_klines


# -------------------------------------------------------------- configuración
def test_defaults_are_safe():
    cfg = C.from_dict({})
    assert cfg.mode == "papel" and cfg.profile == "equilibrado"
    assert cfg.strategy.max_exposure == 1.0  # sin apalancamiento
    assert cfg.risk.dd_halt == 0.30 and cfg.risk.crash_sigmas == 0.0
    assert cfg.execution.symbol == "BTC/USDT"


def test_typos_are_errors_not_silent_defaults():
    with pytest.raises(C.ConfigError, match="desconocidas"):
        C.from_dict({"perfl": "agresivo"})
    with pytest.raises(C.ConfigError, match="desconocidas"):
        C.from_dict({"riesgo": {"parada_caidaa": 0.2}})
    with pytest.raises(C.ConfigError, match="desconocidas"):
        C.from_dict({"ejecucion": {"comission": 0.001}})


def test_only_bitcoin_is_allowed():
    with pytest.raises(C.ConfigError, match="solo opera Bitcoin"):
        C.from_dict({"ejecucion": {"simbolo": "ETH/USDT"}})
    assert C.from_dict({"ejecucion": {"simbolo": "BTC/USD"}}).execution.quote == "USD"


def test_profiles():
    agg = C.from_dict({"perfil": "agresivo"})
    assert agg.strategy.target_vol == 0.80 and agg.allocation == 1.0 and agg.risk.dd_halt == 0.40
    con = C.from_dict({"perfil": "conservador"})
    assert con.allocation == 0.5 and con.effective_band == pytest.approx(0.075) and con.risk.dd_halt == 0.15
    # un cortafuegos fijado a mano manda sobre el del perfil
    assert C.from_dict({"perfil": "agresivo", "riesgo": {"parada_caida": 0.2}}).risk.dd_halt == 0.2
    with pytest.raises(C.ConfigError, match="perfil desconocido"):
        C.from_dict({"perfil": "temerario"})


def test_implausible_values_are_rejected():
    for bad in (
        {"ejecucion": {"comision": 0.5}},  # 50 %: seguro que quiso decir 0.005
        {"estrategia": {"exposicion_maxima": 2.0}},  # apalancamiento
        {"banda": 0.9},
        {"modo": "produccion"},
        {"riesgo": {"reduccion_caida": 0.4, "parada_caida": 0.3}},
        {"capital_papel": -5},
    ):
        with pytest.raises(C.ConfigError):
            C.from_dict(bad)


def test_yaml_roundtrip_and_overrides(tmp_path):
    p = tmp_path / "c.yaml"
    p.write_text(
        "perfil: agresivo\nbanda: 0.2\nestrategia:\n  volatilidad_objetivo: 0.6\n"
        "riesgo:\n  parada_caida: 0.25\n  enfriamiento_dias: 10\nejecucion:\n  exchange: kraken\n  comision: 0.0026\n",
        encoding="utf-8",
    )
    cfg = C.load(p)
    assert cfg.strategy.target_vol == 0.6 and cfg.strategy.full_forecast == 0.30
    assert cfg.risk.dd_halt == 0.25 and cfg.risk.dd_cooldown_h == 240
    assert cfg.execution.exchange == "kraken" and cfg.backtest_config().fee == 0.0026
    assert cfg.backtest_config().band == 0.2
    with pytest.raises(C.ConfigError):
        C.load(tmp_path / "no-existe.yaml")


def test_credentials_come_only_from_the_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("CENTINELA_API_KEY", raising=False)
    monkeypatch.delenv("CENTINELA_API_SECRET", raising=False)
    with pytest.raises(C.ConfigError, match="faltan"):
        C.api_credentials()
    env = tmp_path / ".env"
    env.write_text("# comentario\nCENTINELA_API_KEY = abc\nCENTINELA_API_SECRET='xyz'\n", encoding="utf-8")
    C.load_env(env)
    try:
        assert C.api_credentials() == {"apiKey": "abc", "secret": "xyz"}
        os.environ["CENTINELA_API_KEY"] = "ya-definida"
        C.load_env(env)
        assert os.environ["CENTINELA_API_KEY"] == "ya-definida"  # el entorno manda sobre el fichero
    finally:
        os.environ.pop("CENTINELA_API_KEY", None)
        os.environ.pop("CENTINELA_API_SECRET", None)


# -------------------------------------------------------------------- almacén
def test_missing_hours_become_flat_untradable_bars(klines):
    k = klines.iloc[:100].drop(index=[10, 11, 12, 50]).reset_index(drop=True)
    df = assemble(k)
    assert len(df) == 100 and int(df["gap"].sum()) == 4
    flat = df.iloc[10]
    assert flat["open"] == flat["high"] == flat["low"] == flat["close"] == df["close"].iloc[9]
    assert flat["volume"] == 0.0
    assert [n for _, n in describe_gaps(df)] == [3, 1]


def test_corrupt_candles_are_refused(klines):
    validate_klines(klines)
    bad = klines.copy()
    bad.loc[5, "high"] = bad.loc[5, "low"] * 0.5
    with pytest.raises(ValueError, match="incoherentes"):
        validate_klines(bad)
    bad = klines.copy()
    bad.loc[7, "close"] = np.nan
    with pytest.raises(ValueError, match="no finitos"):
        validate_klines(bad)
    with pytest.raises(ValueError, match="desordenadas"):
        validate_klines(pd.concat([klines.iloc[:5], klines.iloc[:5]], ignore_index=True))
    bad = klines.copy()
    bad.loc[3, "ts"] += 1000
    with pytest.raises(ValueError, match="alineadas"):
        validate_klines(bad)


def test_splice_scales_old_history_to_avoid_a_fake_jump(klines):
    new = klines.iloc[100:200].reset_index(drop=True)
    old = klines.iloc[:101][["ts", "open", "high", "low", "close", "volume"]].copy()
    for col in ("open", "high", "low", "close"):
        old[col] *= 1.02  # el mercado antiguo cotiza un 2 % por encima
    out = splice_history(old, new)
    assert len(out) == 200
    assert out["close"].iloc[99] == pytest.approx(klines["close"].iloc[99])
    assert out["trades"].iloc[:100].isna().all()  # columnas que el mercado antiguo no tiene


def test_store_roundtrip_is_atomic(tmp_path, klines):
    st = DataStore(tmp_path / "d")
    assert st.load("btcusdt_1h") is None
    st.save("btcusdt_1h", klines)
    pd.testing.assert_frame_equal(st.load("btcusdt_1h"), klines)
    assert not list((tmp_path / "d").glob("*.tmp"))
    bars = st.market()
    assert len(bars) == len(klines) and bars.index[1] - bars.index[0] == pd.Timedelta(hours=1)
    with pytest.raises(FileNotFoundError):
        DataStore(tmp_path / "vacio").market()
    assert int(bars.index.as_unit("ms").asi8[0]) % HOUR_MS == 0
