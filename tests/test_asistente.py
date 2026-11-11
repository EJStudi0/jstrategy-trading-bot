"""El asistente: cuenta manual con costes, stop y objetivo, vetos por moneda, mando que caduca y avisos."""
import time

import numpy as np
import pytest

from bot import asistente as asis
from bot import datos, patrones
from tests.test_ejecutor import SIMBOLOS, avanzar, bot  # noqa: F401  (fixture)


@pytest.fixture
def a(tmp_path):
    return asis.Asistente(feed=None, simbolos=("BTCUSDT", "ETHUSDT"), carpeta=str(tmp_path))


def test_abrir_y_cerrar_cobra_comision_y_deslizamiento(a):
    p = a.abrir("BTCUSDT", 1, 500, {"BTCUSDT": 100.0})
    assert p["entrada"] == pytest.approx(100.02) and a.manual["saldo"] == pytest.approx(1000 - 0.30)
    f = a.cerrar(p["id"], {"BTCUSDT": 100.0})
    assert f["neto"] < 0                       # ida y vuelta al mismo precio: se pierde lo que cuesta
    assert a.patrimonio({}) == pytest.approx(1000 + f["neto"])
    assert a.manual["posiciones"] == [] and len(a.manual["cerradas"]) == 1


def test_un_corto_gana_si_baja(a):
    p = a.abrir("ETHUSDT", -1, 400, {"ETHUSDT": 50.0})
    assert a.cerrar(p["id"], {"ETHUSDT": 45.0})["neto"] > 35


def test_el_stop_y_el_objetivo_cierran_solos(a):
    px = {"BTCUSDT": 100.0, "ETHUSDT": 50.0}
    a.abrir("BTCUSDT", 1, 200, px, stop=98, objetivo=105)
    a.abrir("ETHUSDT", -1, 200, px, stop=52, objetivo=45)
    assert a.vigilar(px) == []
    hechas = a.vigilar({"BTCUSDT": 97.0, "ETHUSDT": 44.0})
    assert {h["motivo"] for h in hechas} == {"stop", "objetivo"}
    stop = next(h for h in hechas if h["motivo"] == "stop")
    assert stop["salida"] < 97.0               # el stop sale al precio de ahora, con deslizamiento
    assert next(h for h in hechas if h["motivo"] == "objetivo")["salida"] == 45


def test_rechaza_lo_que_no_tiene_sentido(a):
    px = {"BTCUSDT": 100.0}
    for kw in ({"usdt": 1}, {"usdt": 6000}, {"usdt": 100, "stop": 101}, {"usdt": 100, "objetivo": 99}):
        with pytest.raises(ValueError):
            a.abrir("BTCUSDT", 1, precios=px, **kw)
    with pytest.raises(ValueError):
        a.abrir("DOGEUSDT", 1, 100, px)
    with pytest.raises(ValueError):
        a.abrir("ETHUSDT", 1, 100, px)          # sin precio


def test_la_financiacion_se_paga_y_se_guarda(a, tmp_path):
    p = a.abrir("BTCUSDT", 1, 1000, {"BTCUSDT": 100.0})
    antes = a.manual["saldo"]
    a.vigilar({"BTCUSDT": 100.0}, [(p["id"], p["ultimo_funding_ms"] + 1, 0.001)])
    assert a.manual["saldo"] == pytest.approx(antes - 1000 / 100.02 * 100 * 0.001)
    a.guardar()
    otro = asis.Asistente(None, ("BTCUSDT", "ETHUSDT"), str(tmp_path))
    assert otro.manual["posiciones"][0]["financiacion"] < 0


def test_cierre_parcial(a):
    p = a.abrir("BTCUSDT", 1, 400, {"BTCUSDT": 100.0})
    a.cerrar(p["id"], {"BTCUSDT": 110.0}, parte=0.5)
    assert a.manual["posiciones"][0]["cantidad"] == pytest.approx(p["entrada"] and 400 / 100.02 / 2)


def test_vetos_y_su_caducidad(a):
    base, neto = {"BTCUSDT": 0.3, "ETHUSDT": 0.2}, {"BTCUSDT": 0.2, "ETHUSDT": 0.1}
    assert a.aplicar_vetos(base, neto) == (base, neto)
    a.poner_veto("BTCUSDT", "cubrir", 2)
    a.poner_veto("ETHUSDT", "congelar")
    b, n = a.aplicar_vetos(base, neto)
    assert b == {"BTCUSDT": 0.3} and n == {"BTCUSDT": 0.0}
    a.poner_veto("ETHUSDT", "cerrar")
    assert a.aplicar_vetos(base, neto)[0]["ETHUSDT"] == 0.0
    a.vetos["BTCUSDT"]["hasta_ms"] = 1
    assert "BTCUSDT" not in a.vetos_activos()
    a.poner_veto("ETHUSDT", None)
    assert a.vetos_activos() == {}
    with pytest.raises(ValueError):
        a.poner_veto("ETHUSDT", "borrar")


def test_el_bot_obedece_un_veto_de_cerrar_y_no_toca_las_demas(bot):  # noqa: F811
    bot.ciclo()
    s = SIMBOLOS[0]
    assert bot.cartera.contado.get(s, 0) > 0
    otras = {x: bot.cartera.contado.get(x, 0) for x in SIMBOLOS[1:]}
    bot.poner_veto(s, "cerrar")
    assert bot.cartera.contado.get(s, 0) == pytest.approx(0, abs=1e-9)
    assert {x: bot.cartera.contado.get(x, 0) for x in SIMBOLOS[1:]} == otras
    assert bot.instantanea()["vetos"][s]["modo"] == "cerrar"
    bot.poner_veto(s, None)
    assert bot.cartera.contado.get(s, 0) > 0


def test_el_mando_temporal_vuelve_solo_a_automatico(bot):  # noqa: F811
    bot.ciclo()
    bot.poner_mando("neutral", horas=1)
    assert bot.mando == "neutral" and bot.asistente.mando_hasta_ms
    bot.ciclo()
    assert bot.mando == "neutral"
    bot.asistente.mando_hasta_ms = 1
    bot.ciclo()
    assert bot.mando == "auto" and bot.asistente.mando_hasta_ms is None


def test_avisa_de_una_ruptura_y_lleva_el_marcador(tmp_path):
    n = 1500
    rng = np.random.default_rng(4)
    t = (int(time.time() * 1000) // patrones.M30 - n) * patrones.M30 + np.arange(n) * patrones.M30
    c = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.002, n)))
    c[-1] = c[:-1].max() * 1.02                      # la última vela rompe el máximo...
    o = np.r_[100.0, c[:-1]]
    h, l = np.maximum(o, c) * 1.0005, np.minimum(o, c) * 0.9995
    v = np.ones(n)
    v[-1] = 10.0                                     # ...con mucho volumen
    a = asis.Asistente(None, ("BTCUSDT",), str(tmp_path))
    a.velas["BTCUSDT"] = datos.Velas("BTCUSDT", "30m", t, o, h, l, c, v)
    tc4, o4, h4, l4, c4, v4 = patrones.agrupar(t, o, h, l, c, v, 240)
    t4 = np.r_[tc4[0] - 240 * 60_000 * np.arange(300, 0, -1), tc4] - 240 * 60_000
    sube = np.r_[np.linspace(50, 99, 300), c4]       # historia larga de 4 h, alcista: fondo a favor
    v4h = datos.Velas("BTCUSDT", "4h", t4, sube, sube * 1.001, sube * 0.999, sube, np.ones(len(sube)))
    nuevas = a.analizar({"BTCUSDT": v4h})
    rup = [x for x in nuevas if x["patron"] in ("ruptura", "ruptura_floja")]
    assert rup and rup[0]["lado"] == 1 and rup[0]["stop"] < rup[0]["precio"]
    assert a.analizar({"BTCUSDT": v4h}) == []        # la misma vela no avisa dos veces
    al = rup[0]
    al["t"] -= 25 * 3600_000                         # como si hubieran pasado 25 h
    a.seguir({"BTCUSDT": al["precio"] * 1.03})
    assert al["a_24h"] == pytest.approx(3.0) and a.marcador[al["patron"]]["a_favor"] == 1
    i = a.instantanea({"BTCUSDT": 100.0})
    assert i["alertas"][0]["id"] >= 1 and i["manual"]["patrimonio"] == 1000 and i["sin_ver"] >= 1
