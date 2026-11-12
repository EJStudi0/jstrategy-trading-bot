"""Avisos a Telegram: textos, filtro por nivel, conexión con código y que el bot los saque sin red."""
import pytest

from bot import patrones
from bot import telegram as tg
from tests.test_ejecutor import bot  # noqa: F401  (fixture)


class Falsa:
    """Una API de Telegram de mentira: apunta lo que se le pide."""

    def __init__(self, mensajes=()):
        self.llamadas, self.mensajes = [], list(mensajes)

    def __call__(self, token, metodo, datos):
        self.llamadas.append((metodo, datos))
        if metodo == "getMe":
            return {"ok": token.startswith("123456"), "result": {"username": "mi_bot"}}
        if metodo == "getUpdates":
            return {"ok": True, "result": self.mensajes}
        return {"ok": True}

    def enviados(self):
        return [d["text"] for m, d in self.llamadas if m == "sendMessage"]


CLAVE = "123456789:" + "A" * 35
ALERTA = {"simbolo": "BTCUSDT", "patron": "ruptura", "lado": 1, "precio": 103250.0, "fuerza": "alta", "stop": 101900.0,
          "fondo": 1, "callada": False, "previo": {"n": 12, "a_favor_pct": 58, "media_pct": 0.4}}


def conectado(tmp_path, api=None):
    api = api or Falsa()
    t = tg.Telegram(str(tmp_path / "telegram.json"), api=api, hilo=False)
    t.poner_clave(CLAVE)
    api.mensajes.append({"message": {"chat": {"id": 77, "type": "private"}, "text": t.codigo}})
    t.enlazar()
    t.vaciar()
    api.llamadas.clear()
    return t, api


def test_numeros_a_la_espanola():
    assert tg.num(103250.4) == "103.250"
    assert tg.num(8.509) == "8,509"
    assert tg.num(1234.5, 2) == "1.234,50"
    assert tg.con_signo(-3.2) == "−3,20"
    assert tg.moneda("BTCUSDT") == "BTC" and tg.moneda("ETH/USDT:USDT") == "ETH"


def test_texto_de_una_alerta():
    x = tg.texto_alerta(ALERTA, patrones.CATALOGO)
    assert "BTC · Ruptura con volumen" in x and "↑" in x and "103.250" in x and "101.900" in x and "58 %" in x
    n = tg.texto_alerta({"simbolo": "ETHUSDT", "patron": "nivel", "lado": 1, "precio": 3001.0, "nivel": 3000.0,
                         "nota": "a <ver>"}, patrones.CATALOGO)
    assert "ETH cruzó 3.000" in n and "&lt;ver&gt;" in n


def test_nivel_de_avisos():
    baja, media = {**ALERTA, "fuerza": "baja"}, {**ALERTA, "fuerza": "media"}
    assert tg.pasa(ALERTA, "fuertes") and not tg.pasa(media, "fuertes")
    assert tg.pasa(media, "importantes") and not tg.pasa(baja, "importantes")
    assert tg.pasa(baja, "todas")
    assert not tg.pasa({**ALERTA, "callada": True}, "todas")
    assert tg.pasa({"patron": "nivel", "callada": True}, "fuertes")


def test_conectar_pide_el_codigo_y_no_ensena_la_clave(tmp_path):
    api = Falsa()
    t = tg.Telegram(str(tmp_path / "telegram.json"), api=api, hilo=False)
    with pytest.raises(ValueError):
        t.poner_clave("no es una clave")
    with pytest.raises(ValueError):
        t.poner_clave("999999999:" + "A" * 35)          # Telegram no la reconoce
    e = t.poner_clave(CLAVE)
    assert e["bot"] == "mi_bot" and not e["configurado"] and len(e["codigo"]) == 6
    assert CLAVE not in str(e)
    assert not t.enviar("hola")                          # sin chat no sale nada
    api.mensajes.append({"message": {"chat": {"id": 5, "type": "private"}, "text": "otro que pasaba"}})
    with pytest.raises(ValueError):
        t.enlazar()
    api.mensajes.append({"message": {"chat": {"id": 6, "type": "private"}, "text": "mira " + e["codigo"]}})
    with pytest.raises(ValueError):
        t.enlazar()                                      # el código tiene que ir solo, no dentro de otro texto
    api.mensajes.append({"message": {"chat": {"id": 77, "type": "private", "first_name": "Ana"}, "text": "/start " + e["codigo"]}})
    api.mensajes.append({"message": {"chat": {"id": 88, "type": "private"}, "text": e["codigo"]}})
    with pytest.raises(ValueError):
        t.enlazar()                                      # dos cuentas con el código: no se enlaza ninguna
    assert t.chat is None and t.codigo != e["codigo"]
    api.mensajes[:] = [{"message": {"chat": {"id": 77, "type": "private", "first_name": "Ana"}, "text": t.codigo}}]
    r = t.enlazar()
    assert r["configurado"] and t.chat == 77 and r["nombre"] == "Ana"
    t.vaciar()
    assert "conectado" in api.enviados()[0]
    otra = tg.Telegram(str(tmp_path / "telegram.json"), api=api, hilo=False)   # sobrevive a un reinicio
    assert otra.configurado and otra.chat == 77
    assert (tmp_path / "telegram.json").stat().st_mode & 0o077 == 0            # solo la lee el usuario
    assert not otra.quitar()["configurado"]


def test_repetidos_y_espera(tmp_path):
    t, api = conectado(tmp_path)
    assert t.enviar("x", clave="ciclo") and not t.enviar("x", clave="ciclo")
    t.vaciar()
    assert api.enviados() == ["x"]


def test_el_bot_saca_los_avisos_segun_las_preferencias(tmp_path, bot):  # noqa: F811

    t, api = conectado(tmp_path)
    bot.telegram = t
    bot._alerta_fuera(ALERTA)
    bot._alerta_fuera({**ALERTA, "fuerza": "baja"})       # por defecto solo los importantes
    bot._fuera("operó", "operaciones")
    t.vaciar()
    assert len(api.enviados()) == 2 and "Ruptura" in api.enviados()[0]
    bot.asistente.cambiar_prefs({"telegram": {"nivel": "todas", "operaciones": False}})
    bot._alerta_fuera({**ALERTA, "fuerza": "baja"})
    bot._fuera("operó", "operaciones")
    t.vaciar()
    assert len(api.enviados()) == 3
    bot.asistente.cambiar_prefs({"telegram": {"activo": False}})
    bot._alerta_fuera(ALERTA)
    t.vaciar()
    assert len(api.enviados()) == 3
    with pytest.raises(ValueError):
        bot.asistente.cambiar_prefs({"telegram": {"nivel": "ninguno"}})


def test_textos_de_cierre_operaciones_y_resumen():
    c = tg.texto_cierre({"simbolo": "SOLUSDT", "lado": -1, "entrada": 150.0, "salida": 153.0, "motivo": "stop", "neto": -12.3})
    assert "corto de SOL" in c and "saltó el stop" in c and "−12,30" in c
    o = tg.texto_operaciones([{"pata": "contado", "lado": "compra", "simbolo": "BTCUSDT", "nocional": 250.0, "precio": 103000.0}] * 10,
                             "vela", 5123.4)
    assert o.count("Compra BTC") == 8 and "y 2 más" in o and "5.123,40" in o
    r = tg.texto_resumen({"patrimonio": 5100.0, "ganancia_pct": 2.0, "mando": "auto", "exposicion_neta": 0.3},
                         {"patrimonio": 990.0, "ganancia": -10.0, "posiciones": [1]}, 4, 0.5)
    assert "+0,50 %" in r and "1 operación abierta" in r and "Avisos en 24 h: 4" in r
