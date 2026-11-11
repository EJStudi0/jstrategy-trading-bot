"""Datos sintéticos compartidos por los tests (deterministas, sin red)."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from centinela.data.store import HOUR_MS, assemble

START_MS = 1_577_836_800_000  # 2020-01-01 00:00 UTC


def make_klines(n: int = 24 * 800, seed: int = 3, start_ms: int = START_MS) -> pd.DataFrame:
    """Paseo aleatorio con regímenes de tendencia y volatilidad agrupada, parecido a BTC."""
    rng = np.random.default_rng(seed)
    regime = np.repeat(rng.choice([-1.0, 0.0, 1.0, 1.0], size=n // 500 + 1), 500)[:n]
    vol = 0.006 * np.exp(0.5 * np.sin(np.arange(n) / 700.0) + 0.3 * rng.standard_normal(n).cumsum() / np.sqrt(n))
    r = regime * 0.0004 + vol * rng.standard_normal(n)
    close = 20_000.0 * np.exp(np.cumsum(r))
    open_ = np.concatenate([[20_000.0], close[:-1]])
    spread = np.abs(rng.standard_normal(n)) * vol * close * 0.6
    high = np.maximum(open_, close) + spread
    low = np.minimum(open_, close) - spread
    volume = rng.uniform(100, 2000, n)
    return pd.DataFrame(
        {
            "ts": start_ms + np.arange(n, dtype="int64") * HOUR_MS,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
            "quote_volume": volume * close,
            "trades": rng.integers(1000, 9000, n),
            "taker_base": volume * rng.uniform(0.4, 0.6, n),
        }
    )


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Los tests son herméticos: cualquier intento de salir a la red es un fallo."""
    from centinela.data import http

    def blocked(url, *a, **kw):
        raise AssertionError(f"un test intentó acceder a la red: {url}")

    monkeypatch.setattr(http, "get", blocked)
    try:
        import ccxt
    except ImportError:
        return

    def blocked_exchange(self, url, *a, **kw):
        raise AssertionError(f"un test intentó hablar con un exchange: {url}")

    monkeypatch.setattr(ccxt.Exchange, "fetch", blocked_exchange)


SECRET_VARS = ("CENTINELA_API_KEY", "CENTINELA_API_SECRET", "CENTINELA_API_PASSWORD", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")


@pytest.fixture(autouse=True)
def no_real_credentials(monkeypatch):
    """Los tests jamás ven las claves reales del usuario.

    Ni las que haya en el entorno ni las del ``.env`` del proyecto, que ``cli.main`` cargaría
    al ejecutarse desde la raíz: un fallo de aserción podría acabar imprimiéndolas.
    """
    from centinela import cli

    for var in SECRET_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(cli, "load_env", lambda *a, **kw: None)


@pytest.fixture(scope="session")
def klines() -> pd.DataFrame:
    return make_klines()


@pytest.fixture(scope="session")
def bars(klines) -> pd.DataFrame:
    return assemble(klines)
