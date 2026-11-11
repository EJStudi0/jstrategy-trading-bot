"""Datos públicos de Binance para BTCUSDT (la referencia de precio del bot).

Se usa exclusivamente el espejo de *solo datos de mercado* ``data-api.binance.vision``
y el repositorio histórico ``data.binance.vision``. Ninguno requiere cuenta ni clave,
y ambos son accesibles incluso desde ubicaciones donde ``api.binance.com`` no lo es.

Binance spot es el mercado de BTC con mayor profundidad y donde se forma el precio,
por eso es la serie con la que el bot aprende y decide, opere donde opere después.
"""

from __future__ import annotations

import io
import logging
import zipfile
from typing import Callable

import numpy as np
import pandas as pd

from . import http

log = logging.getLogger(__name__)

SPOT_API = "https://data-api.binance.vision"
BULK = "https://data.binance.vision"

INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}

KLINE_COLUMNS = [
    "ts",  # apertura de la vela, ms epoch UTC
    "open",
    "high",
    "low",
    "close",
    "volume",  # BTC negociados
    "quote_volume",  # USDT negociados
    "trades",  # número de operaciones
    "taker_base",  # BTC comprados de forma agresiva (taker buy)
]

_RAW = [
    "ts", "open", "high", "low", "close", "volume", "close_ts",
    "quote_volume", "trades", "taker_base", "taker_quote", "_ignore",
]  # fmt: skip

# Primera vela horaria de BTCUSDT en Binance spot: 2017-08-17 04:00 UTC
FIRST_KLINE_MS = 1_502_942_400_000


def server_time_ms() -> int:
    return int(http.get(f"{SPOT_API}/api/v3/time").json()["serverTime"])


def _parse_klines(rows: list[list]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=KLINE_COLUMNS)
    raw = pd.DataFrame(rows, columns=_RAW)
    out = pd.DataFrame(
        {
            "ts": raw["ts"].astype("int64"),
            "open": raw["open"].astype("float64"),
            "high": raw["high"].astype("float64"),
            "low": raw["low"].astype("float64"),
            "close": raw["close"].astype("float64"),
            "volume": raw["volume"].astype("float64"),
            "quote_volume": raw["quote_volume"].astype("float64"),
            "trades": raw["trades"].astype("int64"),
            "taker_base": raw["taker_base"].astype("float64"),
        }
    )
    return out


def fetch_klines(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    start_ms: int | None = None,
    end_ms: int | None = None,
    limit: int = 1000,
) -> pd.DataFrame:
    """Una página de velas (incluye la vela en curso si cae dentro del rango)."""
    params: dict[str, object] = {"symbol": symbol, "interval": interval, "limit": limit}
    if start_ms is not None:
        params["startTime"] = int(start_ms)
    if end_ms is not None:
        params["endTime"] = int(end_ms)
    rows = http.get(f"{SPOT_API}/api/v3/klines", params).json()
    return _parse_klines(rows)


def fetch_klines_range(
    symbol: str = "BTCUSDT",
    interval: str = "1h",
    start_ms: int = FIRST_KLINE_MS,
    end_ms: int | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Descarga paginada de velas **cerradas** en ``[start_ms, end_ms]``.

    Una vela solo se considera cerrada si ``ts + intervalo <= hora del servidor``:
    así nunca entra en el histórico una vela a medio formar.
    """
    step = INTERVAL_MS[interval]
    now = server_time_ms()
    last_closed_open = (now // step) * step - step
    stop = last_closed_open if end_ms is None else min(int(end_ms), last_closed_open)
    cursor = int(start_ms)
    chunks: list[pd.DataFrame] = []
    while cursor <= stop:
        page = fetch_klines(symbol, interval, start_ms=cursor, end_ms=stop, limit=1000)
        if page.empty:
            break
        chunks.append(page)
        last_ts = int(page["ts"].iloc[-1])
        if on_progress:
            on_progress(last_ts, stop)
        if len(page) < 1000:
            break
        cursor = last_ts + step
    if not chunks:
        return pd.DataFrame(columns=KLINE_COLUMNS)
    df = pd.concat(chunks, ignore_index=True)
    df = df[df["ts"] <= stop].drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    return df


def book_ticker(symbol: str = "BTCUSDT") -> dict[str, float]:
    """Mejor bid/ask actual del libro de órdenes."""
    j = http.get(f"{SPOT_API}/api/v3/ticker/bookTicker", {"symbol": symbol}, retries=2).json()
    return {
        "bid": float(j["bidPrice"]),
        "ask": float(j["askPrice"]),
        "bid_qty": float(j["bidQty"]),
        "ask_qty": float(j["askQty"]),
    }


def fetch_funding_month(symbol: str, year: int, month: int) -> pd.DataFrame | None:
    """Histórico mensual de funding del perpetuo USDT-M (repositorio público).

    Devuelve ``None`` si el mes todavía no está publicado.
    Columnas: ``ts`` (ms, redondeado a la hora de liquidación) y ``rate`` (por periodo de 8 h).
    """
    name = f"{symbol}-fundingRate-{year:04d}-{month:02d}"
    url = f"{BULK}/data/futures/um/monthly/fundingRate/{symbol}/{name}.zip"
    r = http.get(url, ok_404=True, timeout=30)
    if r is None:
        return None
    with zipfile.ZipFile(io.BytesIO(r.content)) as zf:
        raw = zf.read(zf.namelist()[0]).decode("utf-8")
    first = raw.split("\n", 1)[0].split(",")[0]
    header = 0 if not first.strip().lstrip("-").isdigit() else None
    df = pd.read_csv(io.StringIO(raw), header=header)
    df.columns = ["calc_time", "interval_h", "rate"][: len(df.columns)]
    ts = df["calc_time"].astype("int64").to_numpy()
    if ts.max() > 10**14:  # por si el repositorio pasara a microsegundos, como hizo en spot
        ts = ts // 1000
    hour = 3_600_000
    ts = ((ts + hour // 2) // hour) * hour
    interval_h = df["interval_h"].astype("float64").to_numpy() if "interval_h" in df else np.full(len(df), 8.0)
    rate = df["rate"].astype("float64").to_numpy() * (8.0 / interval_h)  # normalizado a 8 h
    return pd.DataFrame({"ts": ts, "rate": rate})
