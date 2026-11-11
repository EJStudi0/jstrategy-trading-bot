"""Fuentes complementarias específicas de Bitcoin (todas públicas y sin clave).

* OKX        — funding reciente del perpetuo BTC-USDT (empalma con el histórico de Binance).
* CoinMetrics — MVRV on-chain diario (valoración del mercado frente al coste base de la red).
* Bitstamp   — velas horarias BTC/USD anteriores a 2017 para validar en más ciclos.
* mempool.space — altura de bloque actual, para situar el próximo halving.
"""

from __future__ import annotations

import logging
from typing import Callable

import pandas as pd

from . import http

log = logging.getLogger(__name__)

OKX = "https://www.okx.com"
COINMETRICS = "https://community-api.coinmetrics.io"
BITSTAMP = "https://www.bitstamp.net"
MEMPOOL = "https://mempool.space"

HOUR_MS = 3_600_000


# --------------------------------------------------------------------------- OKX
def fetch_okx_funding(inst_id: str = "BTC-USDT-SWAP", since_ms: int | None = None, max_pages: int = 60) -> pd.DataFrame:
    """Funding liquidado del perpetuo en OKX (la API pública conserva ~3 meses).

    Columnas: ``ts`` (ms, hora de liquidación) y ``rate`` (por periodo de 8 h).
    """
    rows: list[dict] = []
    after: int | None = None
    for _ in range(max_pages):
        params: dict[str, object] = {"instId": inst_id, "limit": 100}
        if after is not None:
            params["after"] = after
        j = http.get(f"{OKX}/api/v5/public/funding-rate-history", params).json()
        data = j.get("data") or []
        if not data:
            break
        rows.extend(data)
        after = int(data[-1]["fundingTime"])
        if since_ms is not None and after <= since_ms:
            break
    if not rows:
        return pd.DataFrame(columns=["ts", "rate"])
    df = pd.DataFrame(rows)
    rate = df["realizedRate"].where(df["realizedRate"].astype(str) != "", df["fundingRate"]) if "realizedRate" in df else df["fundingRate"]
    out = pd.DataFrame({"ts": df["fundingTime"].astype("int64"), "rate": rate.astype("float64")})
    out["ts"] = ((out["ts"] + HOUR_MS // 2) // HOUR_MS) * HOUR_MS
    out = out.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    # Normaliza a periodos de 8 h a partir del espaciado real entre liquidaciones.
    gap_h = out["ts"].diff().median() / HOUR_MS if len(out) > 2 else 8.0
    if gap_h and gap_h > 0 and abs(gap_h - 8.0) > 0.5:
        out["rate"] = out["rate"] * (8.0 / gap_h)
    if since_ms is not None:
        out = out[out["ts"] > since_ms].reset_index(drop=True)
    return out


def fetch_okx_klines(inst_id: str = "BTC-USDT", limit: int = 300) -> pd.DataFrame:
    """Últimas velas horarias **cerradas** de OKX spot: fuente de reserva si falla Binance.

    El arbitraje mantiene BTC/USDT de OKX y Binance a pocos puntos básicos, de modo
    que para señales de tendencia de días ambas series son intercambiables.
    """
    j = http.get(f"{OKX}/api/v5/market/candles", {"instId": inst_id, "bar": "1H", "limit": min(limit, 300)}, retries=2).json()
    rows = [r for r in (j.get("data") or []) if len(r) >= 9 and r[8] == "1"]
    cols = ["ts", "open", "high", "low", "close", "volume"]
    if not rows:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame([r[:6] for r in rows], columns=cols).astype("float64")
    df["ts"] = df["ts"].astype("int64")
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


# -------------------------------------------------------------------- CoinMetrics
def fetch_mvrv(start: str = "2012-01-01") -> pd.DataFrame:
    """MVRV diario de BTC (capitalización de mercado / capitalización realizada).

    Columnas: ``ts`` (ms del inicio del día UTC al que corresponde el dato) y ``mvrv``.
    """
    url = f"{COINMETRICS}/v4/timeseries/asset-metrics"
    params: dict[str, object] | None = {
        "assets": "btc",
        "metrics": "CapMVRVCur",
        "frequency": "1d",
        "page_size": 10000,
        "start_time": start,
    }
    rows: list[dict] = []
    for _ in range(20):
        j = http.get(url, params, timeout=40).json()
        rows.extend(j.get("data") or [])
        nxt = j.get("next_page_url")
        if not nxt:
            break
        url, params = nxt, None
    if not rows:
        return pd.DataFrame(columns=["ts", "mvrv"])
    df = pd.DataFrame(rows)
    ts = pd.to_datetime(df["time"], utc=True).dt.as_unit("ms").astype("int64")
    out = pd.DataFrame({"ts": ts.to_numpy(), "mvrv": pd.to_numeric(df["CapMVRVCur"], errors="coerce").to_numpy()})
    return out.dropna().drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


# ----------------------------------------------------------------------- Bitstamp
def fetch_bitstamp_ohlc(
    start_ms: int,
    end_ms: int,
    pair: str = "btcusd",
    step_s: int = 3600,
    on_progress: Callable[[int, int], None] | None = None,
) -> pd.DataFrame:
    """Velas históricas de Bitstamp BTC/USD (el mercado al contado con más historia)."""
    cursor = start_ms // 1000
    stop = end_ms // 1000
    chunks: list[pd.DataFrame] = []
    while cursor <= stop:
        params = {"step": step_s, "limit": 1000, "start": cursor, "exclude_current_candle": "true"}
        j = http.get(f"{BITSTAMP}/api/v2/ohlc/{pair}/", params).json()
        rows = (j.get("data") or {}).get("ohlc") or []
        if not rows:
            break
        df = pd.DataFrame(rows)
        page = pd.DataFrame(
            {
                "ts": df["timestamp"].astype("int64") * 1000,
                "open": df["open"].astype("float64"),
                "high": df["high"].astype("float64"),
                "low": df["low"].astype("float64"),
                "close": df["close"].astype("float64"),
                "volume": df["volume"].astype("float64"),
            }
        )
        chunks.append(page)
        last = int(page["ts"].iloc[-1]) // 1000
        if on_progress:
            on_progress(last * 1000, end_ms)
        if len(rows) < 1000 or last < cursor:
            break
        cursor = last + step_s
    if not chunks:
        return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume"])
    out = pd.concat(chunks, ignore_index=True)
    out = out[(out["ts"] >= start_ms) & (out["ts"] <= end_ms)]
    return out.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


# ------------------------------------------------------------------ mempool.space
def fetch_block_height() -> int | None:
    """Altura actual de la cadena de Bitcoin (``None`` si la fuente no responde)."""
    try:
        r = http.get(f"{MEMPOOL}/api/blocks/tip/height", retries=1, timeout=10)
        return int(r.text.strip()) if r is not None else None
    except Exception as exc:  # dato puramente informativo: nunca debe tumbar al bot
        log.debug("altura de bloque no disponible: %s", exc)
        return None
