"""Centinela en el panel: se lee su estado sin tocarlo y su interruptor no toca a Jorge."""
import os

import pytest
from fastapi.testclient import TestClient

from bot import config, datos, ejecutor, panel, puente_centinela
from bot.estrategia import Parametros
from tests.test_ejecutor import FeedFalso, SIMBOLOS, avanzar

TOKEN = "token-de-prueba-123"
AUT = {"Authorization": f"Bearer {TOKEN}"}
AHORA = 1_794_350_000.0
MS = int(AHORA * 1000)


def sembrar(carpeta, latido_hace_s=600):
    """Un estado de Centinela escrito con su propio almacén, como lo dejaría el bot."""
    pytest.importorskip("yaml")
    from centinela.live.state import StateStore

    s = StateStore(carpeta, "papel", durable=False)
    s.record_equity(MS - 7_200_000, 10_000.0, 70_000.0, 0.0, 0.0)
    s.record_equity(MS - 3_600_000, 10_000.0, 70_500.0, 0.5, 0.5)
    s.record_equity(MS - latido_hace_s * 1000, 10_100.0, 71_900.0, 0.5, 0.5)
    s.record_fill(MS - 3_600_000, "o1", "buy", 0.07, 70_500.0, 4.9, "tendencia alcista")
    s.record_decision(MS - latido_hace_s * 1000, {
        "regime": "tendencia alcista", "action": "mantener", "notes": [], "explanation": ["Peso objetivo en BTC: 50 %."],
        "bar": "2026-11-11 10:00:00+00:00", "stale_hours": 0.0, "data_source": "binance"})
    s.set("heartbeat", MS - latido_hace_s * 1000)
    s.set("balances", {"base": 0.07, "quote": 5_060.0})
    s.set("risk", {"peak_equity": 10_200.0, "halted_until_ms": 0, "cooldown_until_ms": 0})
    s.event("info", "arranque en modo papel")
    s.event("error", "RuntimeError: sin red")
    s.close()
    return str(carpeta)


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(datos, "DIR_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "capital_inicial", lambda: 10_000.0)
    b = ejecutor.Bot(feed=FeedFalso(), carpeta=str(tmp_path))
    b.p = Parametros(simbolos=SIMBOLOS)
    avanzar(b, 0)
    b.decidir()
    c = TestClient(panel.construir_app(b, TOKEN, dir_centinela=sembrar(tmp_path / "centinela")))
    c.bot, c.dir = b, str(tmp_path / "centinela")
    return c


def test_instantanea(tmp_path):
    d = sembrar(tmp_path)
    i = puente_centinela.instantanea(d, ahora=AHORA)
    assert i["instalado"] and i["encendido"] and i["en_marcha"] and i["modo"] == "papel"
    assert i["capital"] == 10_000 and i["patrimonio"] == 10_100
    assert i["ganancia"] == pytest.approx(100) and i["ganancia_pct"] == pytest.approx(1.0)
    assert i["caida_pct"] == pytest.approx(-0.98, abs=0.01)
    assert i["peso"] == 0.5 and i["objetivo"] == 0.5 and i["btc"] == 0.07 and i["precio"] == 71_900
    assert i["regimen"] == "tendencia alcista" and i["explicacion"] == ["Peso objetivo en BTC: 50 %."]
    assert i["n_operaciones"] == 1 and i["operaciones"][0]["lado"] == "buy"
    assert [a["texto"] for a in i["avisos"]] == ["RuntimeError: sin red"]     # los avisos informativos no molestan
    assert i["proxima_decision_utc"] > i["latido_utc"] and i["cortafuegos_hasta_utc"] is None


def test_sin_latido_reciente_no_esta_en_marcha(tmp_path):
    d = sembrar(tmp_path, latido_hace_s=3 * 3600)
    i = puente_centinela.instantanea(d, ahora=AHORA)
    assert i["instalado"] and not i["en_marcha"] and i["proxima_decision_utc"] is None


def test_sin_centinela_el_panel_lo_dice_y_no_falla(tmp_path):
    vacio = str(tmp_path / "no-existe")
    assert puente_centinela.instantanea(vacio) == {"instalado": False, "encendido": True, "en_marcha": False, "modo": "papel"}
    assert puente_centinela.curva(vacio) == []
    with pytest.raises(ValueError):
        puente_centinela.poner_interruptor(False, vacio)
    assert not os.path.exists(vacio), "leer no crea nada"


def test_la_lectura_no_escribe_en_el_estado(tmp_path):
    d = sembrar(tmp_path)
    antes = os.path.getmtime(puente_centinela.ruta_base(d))
    puente_centinela.instantanea(d, ahora=AHORA)
    puente_centinela.curva(d, ahora=AHORA)
    assert os.path.getmtime(puente_centinela.ruta_base(d)) == antes


def test_el_interruptor_es_el_que_mira_centinela(tmp_path):
    d = sembrar(tmp_path)
    from centinela.live.state import is_stopped, stop_file

    assert puente_centinela.ruta_stop(d) == str(stop_file(d))
    assert puente_centinela.poner_interruptor(False, d) == {"encendido": False} and is_stopped(d)
    assert puente_centinela.poner_interruptor(False, d) == {"encendido": False}      # repetir no rompe
    assert puente_centinela.poner_interruptor(True, d) == {"encendido": True} and not is_stopped(d)
    assert puente_centinela.poner_interruptor(True, d) == {"encendido": True}


def test_curva_por_tramo(tmp_path):
    d = sembrar(tmp_path)
    toda = puente_centinela.curva(d, ahora=AHORA)
    assert [p["patrimonio"] for p in toda] == [10_000, 10_000, 10_100] and toda[-1]["neto"] == 0.5
    assert set(toda[0]) == {"utc", "patrimonio", "neto", "btc"}                    # el formato de la curva de Jorge
    assert len(puente_centinela.curva(d, horas=1, ahora=AHORA)) == 2


@pytest.mark.parametrize("ruta", ["/api/centinela", "/api/centinela/patrimonio"])
def test_sin_token_no_se_lee(cliente, ruta):
    assert cliente.get(ruta).status_code == 401
    assert cliente.get(ruta + "?token=" + TOKEN).status_code == 401
    assert cliente.get(ruta, headers=AUT).status_code == 200


def test_sin_token_no_se_apaga(cliente):
    assert cliente.post("/api/centinela/interruptor", json={"encendido": False}).status_code == 401
    cliente.cookies.set("panel_token", TOKEN)
    assert cliente.post("/api/centinela/interruptor", json={"encendido": False}).status_code == 401
    assert puente_centinela.encendido(cliente.dir)


def test_apagar_y_encender_desde_el_panel_no_toca_a_jorge(cliente):
    assert cliente.get("/api/centinela", headers=AUT).json()["encendido"] is True
    r = cliente.post("/api/centinela/interruptor", json={"encendido": False}, headers=AUT)
    assert r.status_code == 200 and r.json() == {"encendido": False}
    assert cliente.get("/api/centinela", headers=AUT).json()["encendido"] is False
    assert cliente.bot.mando == "auto", "el interruptor de Centinela no es el de Jorge"
    assert cliente.post("/api/centinela/interruptor", json={"encendido": True}, headers=AUT).json() == {"encendido": True}
    # y al revés: pausar a Jorge no apaga a Centinela
    cliente.post("/api/mando", json={"mando": "pausa"}, headers=AUT)
    assert cliente.get("/api/centinela", headers=AUT).json()["encendido"] is True


@pytest.mark.parametrize("cuerpo", [{}, {"encendido": "si"}, {"encendido": 1}, {"mando": "fuera"}])
def test_el_interruptor_solo_acepta_verdadero_o_falso(cliente, cuerpo):
    assert cliente.post("/api/centinela/interruptor", json=cuerpo, headers=AUT).status_code == 400
    assert puente_centinela.encendido(cliente.dir)
