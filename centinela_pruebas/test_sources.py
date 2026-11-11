"""Fuentes de datos, con respuestas HTTP simuladas (nunca se sale a la red)."""

import io
import zipfile

import pandas as pd
import pytest

from centinela.data import binance, extra, http
from centinela.data.store import FUNDING, HOUR_MS, KLINES, DataStore

T0 = 1_700_000_000_000 // HOUR_MS * HOUR_MS


class Resp:
    def __init__(self, payload=None, content=b"", text=""):
        self._payload, self.content, self.text = payload, content, text

    def json(self):
        return self._payload


def kline_row(ts, px=100.0):
    return [ts, str(px), str(px + 1), str(px - 1), str(px + 0.5), "10.0", ts + HOUR_MS - 1, "1000.0", 42, "6.0", "600.0", "0"]


def install(monkeypatch, handler):
    calls = []

    def fake_get(url, params=None, **kw):
        calls.append((url, dict(params or {})))
        return handler(url, dict(params or {}), kw)

    monkeypatch.setattr(http, "get", fake_get)
    return calls


def test_only_closed_candles_enter_the_history(monkeypatch):
    now = T0 + 5 * HOUR_MS + 17 * 60_000  # son las hh:17: la vela de la hora en curso está a medias

    def handler(url, params, kw):
        if url.endswith("/time"):
            return Resp({"serverTime": now})
        start, end = params["startTime"], params.get("endTime", 10**18)
        rows = [kline_row(t) for t in range(start, T0 + 6 * HOUR_MS, HOUR_MS) if t <= end]
        return Resp(rows)

    install(monkeypatch, handler)
    df = binance.fetch_klines_range("BTCUSDT", "1h", start_ms=T0)
    assert df["ts"].iloc[-1] == T0 + 4 * HOUR_MS  # la última cerrada; la de las hh:00 en curso queda fuera
    assert len(df) == 5 and df["trades"].dtype.kind == "i" and df["close"].iloc[0] == 100.5


def test_pagination_walks_the_whole_range(monkeypatch):
    n = 2500
    now = T0 + (n + 1) * HOUR_MS

    def handler(url, params, kw):
        if url.endswith("/time"):
            return Resp({"serverTime": now})
        start = params["startTime"]
        ts = [t for t in range(start, T0 + n * HOUR_MS, HOUR_MS) if t <= params["endTime"]][: params["limit"]]
        return Resp([kline_row(t) for t in ts])

    calls = install(monkeypatch, handler)
    df = binance.fetch_klines_range("BTCUSDT", "1h", start_ms=T0)
    assert len(df) == n and df["ts"].is_monotonic_increasing and df["ts"].is_unique
    assert sum("klines" in u for u, _ in calls) == 3


def zipped(csv: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("f.csv", csv)
    return buf.getvalue()


def test_funding_month_parsing_handles_headers_jitter_and_microseconds(monkeypatch):
    with_header = "calc_time,funding_interval_hours,last_funding_rate\n" f"{T0 + 3},8,0.0001\n{T0 + 8 * HOUR_MS},8,-0.0002\n"
    install(monkeypatch, lambda u, p, k: Resp(content=zipped(with_header)))
    df = binance.fetch_funding_month("BTCUSDT", 2024, 1)
    assert list(df["ts"]) == [T0, T0 + 8 * HOUR_MS] and list(df["rate"]) == [0.0001, -0.0002]

    no_header_4h = f"{T0},4,0.0001\n"  # intervalo de 4 h: se normaliza a tasa por 8 h
    install(monkeypatch, lambda u, p, k: Resp(content=zipped(no_header_4h)))
    assert binance.fetch_funding_month("BTCUSDT", 2024, 1)["rate"].iloc[0] == pytest.approx(0.0002)

    micros = f"{T0 * 1000},8,0.0003\n"
    install(monkeypatch, lambda u, p, k: Resp(content=zipped(micros)))
    assert binance.fetch_funding_month("BTCUSDT", 2025, 1)["ts"].iloc[0] == T0

    install(monkeypatch, lambda u, p, k: None)  # mes aún no publicado (404)
    assert binance.fetch_funding_month("BTCUSDT", 2030, 1) is None


def test_okx_funding_and_candles(monkeypatch):
    rows = [
        {"fundingTime": str(T0 + 16 * HOUR_MS), "fundingRate": "0.0003", "realizedRate": "0.00031"},
        {"fundingTime": str(T0 + 8 * HOUR_MS), "fundingRate": "0.0002", "realizedRate": ""},
        {"fundingTime": str(T0), "fundingRate": "0.0001", "realizedRate": "0.00011"},
    ]
    pages = iter([Resp({"data": rows}), Resp({"data": []})])
    install(monkeypatch, lambda u, p, k: next(pages))
    df = extra.fetch_okx_funding(since_ms=T0)
    assert list(df["ts"]) == [T0 + 8 * HOUR_MS, T0 + 16 * HOUR_MS]  # ordenado y solo lo posterior a `since`
    assert list(df["rate"]) == [0.0002, 0.00031]  # tasa liquidada si existe; si no, la anunciada

    candles = [
        [str(T0 + 2 * HOUR_MS), "3", "4", "2", "3.5", "9", "0", "0", "0"],  # en curso: confirm = 0
        [str(T0 + HOUR_MS), "2", "3", "1", "2.5", "8", "0", "0", "1"],
        [str(T0), "1", "2", "0.5", "1.5", "7", "0", "0", "1"],
    ]
    install(monkeypatch, lambda u, p, k: Resp({"data": candles}))
    k = extra.fetch_okx_klines()
    assert list(k["ts"]) == [T0, T0 + HOUR_MS] and k["close"].iloc[-1] == 2.5


def test_mvrv_follows_pagination(monkeypatch):
    p1 = Resp({"data": [{"time": "2024-01-01T00:00:00.000000000Z", "CapMVRVCur": "2.1"}], "next_page_url": "https://x/next"})
    p2 = Resp({"data": [{"time": "2024-01-02T00:00:00.000000000Z", "CapMVRVCur": "2.2"}, {"time": "2024-01-03T00:00:00.000000000Z", "CapMVRVCur": None}]})
    pages = iter([p1, p2])
    calls = install(monkeypatch, lambda u, p, k: next(pages))
    df = extra.fetch_mvrv()
    assert list(df["mvrv"]) == [2.1, 2.2] and calls[1][0] == "https://x/next"
    assert df["ts"].iloc[0] == int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)


def test_block_height_failure_is_harmless(monkeypatch):
    def boom(url, params, kw):
        raise http.HttpError("caído")

    install(monkeypatch, boom)
    assert extra.fetch_block_height() is None
    install(monkeypatch, lambda u, p, k: Resp(text="975349\n"))
    assert extra.fetch_block_height() == 975349


def test_incremental_update_appends_and_never_stores_a_forming_candle(monkeypatch, tmp_path):
    state = {"now": T0 + 3 * HOUR_MS + 60_000}

    def handler(url, params, kw):
        if url.endswith("/time"):
            return Resp({"serverTime": state["now"]})
        start, end = params["startTime"], params.get("endTime", 10**18)
        last_open = state["now"] // HOUR_MS * HOUR_MS
        return Resp([kline_row(t, 100 + (t - T0) / HOUR_MS) for t in range(max(start, T0), last_open + 1, HOUR_MS) if t <= end])

    install(monkeypatch, handler)
    monkeypatch.setattr(binance, "FIRST_KLINE_MS", T0)
    st = DataStore(tmp_path)
    assert len(st.update_klines()) == 3
    state["now"] += 2 * HOUR_MS
    k = st.update_klines()
    assert len(k) == 5 and k["ts"].is_unique and k["ts"].iloc[-1] == T0 + 4 * HOUR_MS
    assert len(st.load(KLINES)) == 5


def test_funding_store_splices_okx_after_binance(monkeypatch, tmp_path):
    import centinela.data.store as S

    b_last = int(pd.Timestamp("2024-02-29 16:00", tz="UTC").timestamp() * 1000)
    monkeypatch.setattr(S, "FUNDING_FIRST_MONTH", (2024, 2))

    class FakeNow:
        @staticmethod
        def now(tz=None):
            return pd.Timestamp("2024-03-10 12:00", tz="UTC").to_pydatetime()

        fromtimestamp = staticmethod(S.datetime.fromtimestamp)

    monkeypatch.setattr(S, "datetime", FakeNow)
    monkeypatch.setattr(binance, "fetch_funding_month", lambda sym, y, m: pd.DataFrame({"ts": [b_last - 8 * HOUR_MS, b_last], "rate": [0.0001, 0.0002]}) if (y, m) == (2024, 2) else None)
    okx_rows = pd.DataFrame({"ts": [b_last, b_last + 8 * HOUR_MS, b_last + 16 * HOUR_MS], "rate": [0.9, 0.0003, 0.0004]})
    monkeypatch.setattr(extra, "fetch_okx_funding", lambda since_ms=None: okx_rows[okx_rows["ts"] > (since_ms or 0)])
    st = DataStore(tmp_path)
    f = st.update_funding()
    assert list(f["src"]) == ["binance", "binance", "okx", "okx"]
    assert list(f["rate"]) == [0.0001, 0.0002, 0.0003, 0.0004]  # en el solape manda Binance
    # segunda pasada sin OKX disponible: se conserva lo ya guardado
    def down(since_ms=None):
        raise http.HttpError("okx caído")

    monkeypatch.setattr(extra, "fetch_okx_funding", down)
    f2 = st.update_funding()
    pd.testing.assert_frame_equal(f2.reset_index(drop=True), st.load(FUNDING))
    assert len(f2) == 4
