import io
import zipfile

import numpy as np
import pytest

from bot import datos


def velas_15m(n, t0=1_600_000_000_000 - 1_600_000_000_000 % 86_400_000, saltar=()):
    t = t0 + np.arange(n) * datos.MS["15m"]
    c = 100 + np.arange(n, dtype=float)
    v = datos.Velas("X", "15m", t, c - 0.5, c + 1, c - 1, c, np.ones(n))
    if saltar:
        m = np.ones(n, dtype=bool)
        m[list(saltar)] = False
        v = datos.Velas("X", "15m", *(getattr(v, k)[m] for k in ("t", "o", "h", "l", "c", "v")))
    return v


def test_reagrupar_a_una_hora():
    v = velas_15m(12)                                  # 3 horas justas
    h = datos.reagrupar(v, "1h")
    assert len(h) == 3
    assert list(h.o) == [v.o[0], v.o[4], v.o[8]]
    assert list(h.c) == [v.c[3], v.c[7], v.c[11]]
    assert list(h.h) == [v.h[:4].max(), v.h[4:8].max(), v.h[8:].max()]
    assert list(h.l) == [v.l[:4].min(), v.l[4:8].min(), v.l[8:].min()]
    assert list(h.v) == [4, 4, 4]
    assert np.all(h.t % datos.MS["1h"] == 0)


def test_reagrupar_descarta_la_vela_en_formacion():
    """Una hora con solo 3 de sus 4 cuartos no está cerrada: usarla sería mirar al futuro al revés."""
    h = datos.reagrupar(velas_15m(11), "1h")
    assert len(h) == 2


def test_reagrupar_con_hueco_en_medio():
    v = velas_15m(12, saltar=(5,))                      # falta un cuarto en la 2ª hora
    h = datos.reagrupar(v, "1h")
    assert len(h) == 3 and h.v[1] == 3
    v2 = velas_15m(12, saltar=(7,))                     # falta el ÚLTIMO cuarto de la 2ª hora
    assert len(datos.reagrupar(v2, "1h")) == 2


def test_reagrupar_exige_multiplo():
    with pytest.raises(ValueError):
        datos.reagrupar(datos.Velas("X", "4h", np.array([0]), *(np.ones(1) for _ in range(5))), "1h")


def test_huecos():
    v = velas_15m(10, saltar=(4, 5))
    assert [n for _, n in datos.huecos(v)] == [2]
    assert datos.huecos(velas_15m(10)) == []


def test_unir_manda_la_serie_nueva():
    a = velas_15m(6)
    b = velas_15m(8)
    b = datos.Velas("X", "15m", b.t[4:], b.o[4:], b.h[4:], b.l[4:], b.c[4:] + 1000, b.v[4:])
    u = datos.unir(a, b)
    assert len(u) == 8 and np.all(np.diff(u.t) > 0)
    assert list(u.c[:4]) == list(a.c[:4])
    assert list(u.c[4:]) == list(b.c)                   # en el solape gana `b`
    assert datos.unir(None, b) is b


def _zip_csv(texto: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("datos.csv", texto)
    return buf.getvalue()


def test_leer_zip_con_y_sin_cabecera():
    fila = "1600000000000,1,2,0.5,1.5,10,1600000899999,15,3,5,7,0\n"
    sin = datos._leer_zip_csv(_zip_csv(fila * 2), datos.COLUMNAS_KLINE)
    con = datos._leer_zip_csv(_zip_csv("open_time,open,high,low,close,volume,close_time,qv,count,tb,tbq,ignore\n" + fila * 2),
                              datos.COLUMNAS_KLINE)
    for df in (sin, con):
        assert len(df) == 2 and float(df["c"].iloc[0]) == 1.5 and int(df["t"].iloc[0]) == 1600000000000


def test_validar_rechaza_velas_incoherentes():
    t = np.array([0, 900_000])
    with pytest.raises(ValueError):                     # máximo por debajo del cierre
        datos._validar(datos.Velas("X", "15m", t, np.array([1.0, 1]), np.array([1.0, 1]), np.array([0.5, 0.5]),
                                   np.array([2.0, 1]), np.ones(2)))
    with pytest.raises(ValueError):                     # tiempos desordenados
        datos._validar(datos.Velas("X", "15m", t[::-1].copy(), *(np.ones(2) for _ in range(5))))


def test_nombres_de_simbolo():
    assert datos.a_ccxt("BTCUSDT") == "BTC/USDT:USDT"
    assert datos.a_binance("BTC/USDT:USDT") == "BTCUSDT"
    assert datos.a_binance(datos.a_ccxt("DOGEUSDT")) == "DOGEUSDT"


class ClienteFalso:
    """Un 'mercado' que falla o contesta según se le diga."""
    def __init__(self, filas=None, error=None):
        self.filas, self.error, self.llamadas = filas, error, 0
        self.has = {"fetchTickers": True, "fetchFundingRateHistory": True}

    def fetch_ohlcv(self, simbolo, intervalo, since=None, limit=None):
        self.llamadas += 1
        if self.error:
            raise self.error
        if since is None:                       # como un mercado real: las más recientes
            return self.filas[-(limit or 10_000):]
        return [f for f in self.filas if f[0] >= since][: (limit or 10_000)]

    def fetch_tickers(self, simbolos):
        if self.error:
            raise self.error
        return {s: {"last": 123.0} for s in simbolos}

    def close(self):
        pass


def feed_con(clientes: dict):
    f = datos.VelasEnVivo(list(clientes))
    f._cliente = lambda nombre: clientes[nombre]
    f._descartar = lambda nombre: None
    return f


def _filas_4h(n, hasta_ms):
    ms = datos.MS["4h"]
    ultimo = (hasta_ms // ms) * ms            # esta vela aún está abierta
    return [[ultimo - (n - 1 - i) * ms, 10.0, 11.0, 9.0, 10.5, 5.0] for i in range(n)]


def test_si_un_mercado_falla_se_usa_el_siguiente():
    import time
    ahora = int(time.time() * 1000)
    roto = ClienteFalso(error=RuntimeError("451 bloqueado"))
    bueno = ClienteFalso(filas=_filas_4h(50, ahora))
    f = feed_con({"a": roto, "b": bueno})
    v = f.velas("BTC/USDT:USDT", "4h", 20)
    assert f.mercado_activo == "b"
    assert "451" in f.errores["a"]
    # La vela en formación no entra: todas las devueltas están cerradas.
    assert np.all(v.t + datos.MS["4h"] <= ahora)
    assert len(v) == 20 and v.t[-1] == bueno.filas[-2][0], "las 20 últimas cerradas"
    # La siguiente vez va directo al que funciona.
    roto.llamadas = 0
    f.velas("BTC/USDT:USDT", "4h", 20)
    assert roto.llamadas == 0
    assert f.precios(["BTC/USDT:USDT"]) == {"BTC/USDT:USDT": 123.0}


def test_sin_ningun_mercado_se_avisa():
    f = feed_con({"a": ClienteFalso(error=RuntimeError("caído")), "b": ClienteFalso(error=RuntimeError("caído"))})
    with pytest.raises(datos.SinDatos):
        f.velas("BTC/USDT:USDT", "4h", 20)
    assert f.ultimo_error and "a:" in f.ultimo_error and "b:" in f.ultimo_error
    assert f.precios(["BTC/USDT:USDT"]) == {}


def test_historia_pagina():
    import time
    ahora = int(time.time() * 1000)
    c = ClienteFalso(filas=_filas_4h(1000, ahora))
    orig = c.fetch_ohlcv
    c.fetch_ohlcv = lambda s, i, since=None, limit=None: orig(s, i, since=since, limit=100)   # mercado tacaño
    v = feed_con({"a": c}).historia("BTC/USDT:USDT", "4h", 800)
    assert 795 <= len(v) <= 802 and np.all(np.diff(v.t) == datos.MS["4h"])
    assert c.llamadas >= 8
