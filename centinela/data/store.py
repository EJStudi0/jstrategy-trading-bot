"""Almacén local (Parquet) y ensamblado del conjunto de datos horario de BTC.

Regla de oro de este módulo: **nada del futuro puede colarse en una fila**.
Cada columna de la fila con apertura ``t`` contiene únicamente información que ya
era pública cuando esa vela cerró (``t + 1 h``):

* funding  -> última liquidación con hora <= ``t`` (retardo conservador de 1 h);
* MVRV     -> dato del día ``D`` disponible a partir de ``D + 48 h`` (CoinMetrics lo
  publica durante ``D + 1``; se añade un día de margen).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from . import binance, extra

log = logging.getLogger(__name__)

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
MVRV_DELAY_MS = 2 * DAY_MS

KLINES = "btcusdt_1h"
FUNDING = "funding"
MVRV = "mvrv"
BITSTAMP = "bitstamp_btcusd_1h"

# Bitstamp es líquido desde 2013; antes los huecos hacen la serie poco fiable.
BITSTAMP_START_MS = 1_356_998_400_000  # 2013-01-01 00:00 UTC
FUNDING_FIRST_MONTH = (2019, 9)  # lanzamiento del perpetuo BTCUSDT


def to_index(ts_ms) -> pd.DatetimeIndex:
    """Índice temporal UTC (resolución ms) a partir de marcas en milisegundos."""
    arr = np.asarray(ts_ms, dtype="int64").astype("datetime64[ms]")
    return pd.DatetimeIndex(arr, tz="UTC", name="time")


def index_ms(idx: pd.DatetimeIndex) -> np.ndarray:
    """Marcas en milisegundos epoch de un índice temporal."""
    return idx.as_unit("ms").asi8


def _asof(src_ts: np.ndarray, src_val: np.ndarray, bar_ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Para cada vela, último valor con marca <= apertura de la vela, y su antigüedad en horas."""
    pos = np.searchsorted(src_ts, bar_ts, side="right") - 1
    ok = pos >= 0
    val = np.full(len(bar_ts), np.nan)
    age = np.full(len(bar_ts), np.nan)
    val[ok] = src_val[pos[ok]]
    age[ok] = (bar_ts[ok] - src_ts[pos[ok]]) / HOUR_MS
    return val, age


def assemble(
    klines: pd.DataFrame,
    funding: pd.DataFrame | None = None,
    mvrv: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Construye la rejilla horaria completa con funding y MVRV alineados causalmente.

    Las horas sin vela (paradas del exchange) se rellenan como velas planas al último
    cierre, con volumen cero y ``gap=True``: en ellas no se puede operar.
    """
    if klines is None or klines.empty:
        raise ValueError("no hay velas: ejecuta primero `centinela datos`")
    k = klines.drop_duplicates("ts").sort_values("ts")
    ts = k["ts"].to_numpy("int64")
    grid = np.arange(ts[0], ts[-1] + HOUR_MS, HOUR_MS, dtype="int64")
    df = k.set_index(to_index(ts)).drop(columns="ts").reindex(to_index(grid))
    gap = df["close"].isna().to_numpy()
    df["close"] = df["close"].ffill()
    for col in ("open", "high", "low"):
        df[col] = df[col].fillna(df["close"])
    for col in ("volume", "quote_volume", "trades", "taker_base"):
        if col in df.columns:
            # En el tramo extendido (Bitstamp) estas columnas no existen: allí quedan NaN.
            known = df[col].notna().to_numpy()
            df[col] = df[col].astype("float64")
            df.loc[gap & ~known, col] = 0.0 if known.any() else np.nan
        else:
            df[col] = np.nan
    df["gap"] = gap

    if funding is not None and not funding.empty:
        f = funding.drop_duplicates("ts").sort_values("ts")
        val, age = _asof(f["ts"].to_numpy("int64"), f["rate"].to_numpy("float64"), grid)
    else:
        val = age = np.full(len(grid), np.nan)
    df["funding"] = val
    df["funding_age_h"] = age

    if mvrv is not None and not mvrv.empty:
        m = mvrv.drop_duplicates("ts").sort_values("ts")
        val, age = _asof(m["ts"].to_numpy("int64") + MVRV_DELAY_MS, m["mvrv"].to_numpy("float64"), grid)
    else:
        val = age = np.full(len(grid), np.nan)
    df["mvrv"] = val
    df["mvrv_age_h"] = age
    return df


def splice_history(old: pd.DataFrame, new: pd.DataFrame) -> pd.DataFrame:
    """Antepone ``old`` (p. ej. Bitstamp) a ``new`` (Binance), escalando el empalme.

    El tramo antiguo se multiplica por la razón de precios en la primera vela común
    para que el cambio de mercado no genere un salto artificial.
    """
    first = int(new["ts"].iloc[0])
    head = old[old["ts"] < first].copy()
    if head.empty:
        return new
    both = old[old["ts"] == first]
    ratio = float(new["open"].iloc[0] / both["open"].iloc[0]) if not both.empty else 1.0
    if not 0.9 < ratio < 1.1:
        log.warning("razón de empalme anómala (%.4f); se ignora el escalado", ratio)
        ratio = 1.0
    for col in ("open", "high", "low", "close"):
        head[col] = head[col] * ratio
    for col in new.columns:
        if col not in head.columns:
            head[col] = np.nan
    return pd.concat([head[new.columns], new], ignore_index=True)


class DataStore:
    """Persistencia en disco del histórico, con actualización incremental."""

    def __init__(self, root: str | Path = "data") -> None:
        self.root = Path(root)

    # ------------------------------------------------------------------ E/S
    def path(self, name: str) -> Path:
        return self.root / f"{name}.parquet"

    def load(self, name: str) -> pd.DataFrame | None:
        p = self.path(name)
        return pd.read_parquet(p) if p.exists() else None

    def save(self, name: str, df: pd.DataFrame) -> None:
        """Escritura atómica: nunca queda un fichero a medias si el proceso muere."""
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.path(name).with_suffix(".parquet.tmp")
        df.to_parquet(tmp, index=False)
        os.replace(tmp, self.path(name))

    # -------------------------------------------------------- actualizaciones
    def update_klines(self, on_progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
        """Trae las velas horarias cerradas que falten (re-descarga las 3 últimas por seguridad)."""
        cur = self.load(KLINES)
        if cur is None or cur.empty:
            start = binance.FIRST_KLINE_MS
            cur = None
        else:
            start = int(cur["ts"].iloc[-1]) - 2 * HOUR_MS
        new = binance.fetch_klines_range("BTCUSDT", "1h", start_ms=start, on_progress=on_progress)
        if cur is None:
            out = new
        elif new.empty:
            return cur
        else:
            out = pd.concat([cur[cur["ts"] < int(new["ts"].iloc[0])], new], ignore_index=True)
        out = out.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
        validate_klines(out)
        self.save(KLINES, out)
        return out

    def update_funding(self) -> pd.DataFrame:
        """Histórico mensual de Binance + tramo reciente de OKX hasta el presente."""
        cur = self.load(FUNDING)
        if cur is None:
            cur = pd.DataFrame({"ts": pd.Series(dtype="int64"), "rate": pd.Series(dtype="float64"), "src": pd.Series(dtype="object")})
        cur["src"] = cur["src"].astype("object")
        bulk = cur[cur["src"] == "binance"]
        now = datetime.now(timezone.utc)
        if bulk.empty:
            y, m = FUNDING_FIRST_MONTH
        else:
            last = datetime.fromtimestamp(int(bulk["ts"].iloc[-1]) / 1000, timezone.utc)
            y, m = (last.year, last.month + 1) if last.month < 12 else (last.year + 1, 1)
            # el último mes guardado pudo estar incompleto: si es así se vuelve a pedir
            if last.day < 28:
                y, m = last.year, last.month
        parts = [bulk[["ts", "rate"]]]
        while (y, m) < (now.year, now.month):
            month = binance.fetch_funding_month("BTCUSDT", y, m)
            if month is not None and not month.empty:
                parts.append(month)
            y, m = (y, m + 1) if m < 12 else (y + 1, 1)
        b = pd.concat(parts, ignore_index=True).drop_duplicates("ts").sort_values("ts")
        b["src"] = "binance"
        last_bulk = int(b["ts"].iloc[-1]) if not b.empty else None
        try:
            okx = extra.fetch_okx_funding(since_ms=last_bulk)
        except Exception as exc:  # el tramo reciente es prescindible: se conserva lo que hubiera
            log.warning("funding de OKX no disponible (%s); se mantiene el tramo guardado", exc)
            okx = cur[cur["src"] == "okx"][["ts", "rate"]]
        okx = okx[okx["ts"] > (last_bulk or 0)].copy()
        prev_okx = cur[(cur["src"] == "okx") & (cur["ts"] > (last_bulk or 0))][["ts", "rate"]]
        okx = pd.concat([prev_okx, okx], ignore_index=True).drop_duplicates("ts", keep="last")
        okx["src"] = "okx"
        out = pd.concat([b, okx], ignore_index=True).sort_values("ts").reset_index(drop=True)
        self.save(FUNDING, out)
        return out

    def update_mvrv(self) -> pd.DataFrame:
        cur = self.load(MVRV)
        try:
            new = extra.fetch_mvrv()
        except Exception as exc:
            if cur is not None:
                log.warning("MVRV no disponible (%s); se mantiene el dato guardado", exc)
                return cur
            raise
        if new.empty and cur is not None:
            return cur
        self.save(MVRV, new)
        return new

    def update_bitstamp(self, on_progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
        """Histórico previo a Binance (solo se descarga una vez; es inmutable)."""
        cur = self.load(BITSTAMP)
        if cur is not None and not cur.empty:
            return cur
        end = binance.FIRST_KLINE_MS + 24 * HOUR_MS
        df = extra.fetch_bitstamp_ohlc(BITSTAMP_START_MS, end, on_progress=on_progress)
        self.save(BITSTAMP, df)
        return df

    # ------------------------------------------------------------- lectura
    def market(self, extended: bool = False) -> pd.DataFrame:
        """Conjunto horario ensamblado. ``extended`` antepone Bitstamp (desde 2013)."""
        k = self.load(KLINES)
        if k is None or k.empty:
            raise FileNotFoundError("no hay datos locales: ejecuta `centinela datos` primero")
        if extended:
            old = self.load(BITSTAMP)
            if old is None:
                raise FileNotFoundError("falta el histórico extendido: `centinela datos --extendido`")
            k = splice_history(old, k)
        return assemble(k, self.load(FUNDING), self.load(MVRV))


def validate_klines(df: pd.DataFrame) -> None:
    """Comprobaciones de cordura; un dato corrupto debe detener al bot, no operar con él."""
    if df.empty:
        raise ValueError("histórico de velas vacío")
    ts = df["ts"].to_numpy("int64")
    if (np.diff(ts) <= 0).any():
        raise ValueError("velas desordenadas o duplicadas")
    if (ts % HOUR_MS != 0).any():
        raise ValueError("velas no alineadas a la hora")
    o, h, l, c = (df[x].to_numpy("float64") for x in ("open", "high", "low", "close"))
    if not (np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)).all():
        raise ValueError("precios no finitos en el histórico")
    if (l <= 0).any() or (h < l).any() or (h < np.maximum(o, c) - 1e-9).any() or (l > np.minimum(o, c) + 1e-9).any():
        raise ValueError("velas incoherentes (máximo/mínimo no envuelven apertura/cierre)")


def describe_gaps(df: pd.DataFrame) -> list[tuple[pd.Timestamp, int]]:
    """Lista de paradas del mercado (inicio, horas) presentes en el conjunto ensamblado."""
    gap = df["gap"].to_numpy()
    out: list[tuple[pd.Timestamp, int]] = []
    i, n = 0, len(gap)
    while i < n:
        if gap[i]:
            j = i
            while j < n and gap[j]:
                j += 1
            out.append((df.index[i], j - i))
            i = j
        else:
            i += 1
    return out
