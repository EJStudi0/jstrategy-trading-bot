"""El ejecutor con un mercado de mentira: decide, opera, obedece al mando y no pierde el estado."""
import time

import numpy as np
import pytest

from bot import config, datos, ejecutor
from bot.estrategia import Parametros

SIMBOLOS = ("AAAUSDT", "BBBUSDT", "CCCUSDT")
MS4 = datos.MS["4h"]


class FeedFalso:
    """Sirve velas de 4 h sintéticas hasta un 'ahora' que la prueba mueve a mano."""

    def __init__(self, n=1700, semilla=5, tendencia=0.0006):
        rng = np.random.default_rng(semilla)
        comun = rng.normal(tendencia, 0.012, n)
        self.t0 = (int(time.time() * 1000) // MS4 - n - 5) * MS4
        self.series = {}
        for j, s in enumerate(SIMBOLOS):
            c = 100.0 * (j + 1) * np.exp(np.cumsum(comun + rng.normal(0, 0.006, n)))
            o = np.concatenate(([c[0]], c[:-1]))
            self.series[datos.a_ccxt(s)] = (o, np.maximum(o, c) * 1.002, np.minimum(o, c) * 0.998, c)
        self.visibles = n - 50
        self.mercado_activo = "falso"
        self.ultimo_ok_utc = time.time()
        self.ultimo_error = None
        self.caido = False
        self.financiaciones = []

    def _velas(self, simbolo, n):
        if self.caido:
            raise datos.SinDatos("mercado caído")
        o, h, l, c = self.series[simbolo]
        k = self.visibles
        sl = slice(max(0, k - n), k)
        t = self.t0 + np.arange(len(c))[sl] * MS4
        self.ultimo_ok_utc = time.time()
        return datos.Velas(simbolo, "4h", t, o[sl], h[sl], l[sl], c[sl], np.ones(k - sl.start))

    def historia(self, simbolo, intervalo, n=1500):
        return self._velas(simbolo, n)

    def velas(self, simbolo, intervalo, limite=500):
        return self._velas(simbolo, limite)

    def precios(self, simbolos):
        if self.caido:
            return {}
        return {s: float(self.series[s][3][self.visibles - 1]) for s in simbolos}

    def financiacion(self, simbolo, desde_ms):
        return [(t, r) for (s, t, r) in self.financiaciones if s == simbolo and t > desde_ms]


@pytest.fixture
def bot(tmp_path, monkeypatch):
    monkeypatch.setattr(datos, "DIR_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "capital_inicial", lambda: 10_000.0)
    b = ejecutor.Bot(feed=FeedFalso(), carpeta=str(tmp_path))
    b.p = Parametros(simbolos=SIMBOLOS)
    return b


def avanzar(b, velas=1):
    """Hace que cierren `velas` velas nuevas. `actualizar_velas` mira el reloj: se le fuerza."""
    b.feed.visibles += velas
    for s in SIMBOLOS:
        b.velas[s] = datos.Velas(s, "4h", *(lambda v: (v.t, v.o, v.h, v.l, v.c, v.v))(
            b.feed.historia(datos.a_ccxt(s), "4h", 1500)))
    b.actualizar_precios()


def neto(b):
    return sum(a + c for a, c in b.cartera.pesos(b.precios).values())


def test_primera_decision_monta_la_cartera(bot):
    avanzar(bot, 0)
    hechas = bot.decidir()
    assert hechas, "con capital y datos, la primera decisión opera"
    i = bot.instantanea()
    assert 0.3 < i["exposicion_base"] <= 0.76
    assert -0.01 <= i["exposicion_neta"] <= i["exposicion_base"] + 0.01
    assert i["patrimonio"] == pytest.approx(10_000, rel=0.005), "solo se han pagado costes"
    assert bot.ultima_decision_t == int(bot.velas[SIMBOLOS[0]].t[-1])
    for m in i["monedas"]:
        assert m["cobertura"] <= m["base"] + 1e-6, "nunca más cobertura que base"


def test_no_decide_dos_veces_sobre_la_misma_vela(bot):
    avanzar(bot, 0)
    bot.decidir()
    assert not bot._toca_decidir()
    avanzar(bot, 1)
    assert bot._toca_decidir()


def test_espera_a_las_monedas_rezagadas(bot, monkeypatch):
    avanzar(bot, 0)
    bot.decidir()
    avanzar(bot, 1)
    v = bot.velas[SIMBOLOS[2]]                 # a la tercera moneda le falta la última vela
    bot.velas[SIMBOLOS[2]] = datos.Velas(v.simbolo, "4h", v.t[:-1], v.o[:-1], v.h[:-1], v.l[:-1], v.c[:-1], v.v[:-1])
    cierre = int(bot.velas[SIMBOLOS[0]].t[-1]) + MS4
    monkeypatch.setattr(time, "time", lambda: cierre / 1000 + 30)
    assert not bot._toca_decidir(), "recién cerrada la vela, se espera"
    monkeypatch.setattr(time, "time", lambda: cierre / 1000 + ejecutor.ESPERA_REZAGADAS_S + 5)
    assert bot._toca_decidir(), "pasado el margen, se decide con lo que haya"
    antes = dict(bot.cartera.contado), {s: p.cantidad for s, p in bot.cartera.perp.items()}
    bot.decidir()
    assert bot.cartera.contado.get(SIMBOLOS[2], 0) == antes[0].get(SIMBOLOS[2], 0), "la rezagada no se toca"
    assert bot.cartera.perp.get(SIMBOLOS[2]).cantidad == antes[1].get(SIMBOLOS[2], 0)


def test_pausa_no_opera(bot):
    avanzar(bot, 0)
    bot.decidir()
    bot.poner_mando("pausa")
    foto = bot.cartera.a_dict()
    for _ in range(30):
        avanzar(bot, 1)
        assert bot.decidir() == []
    despues = bot.cartera.a_dict()
    assert despues["contado"] == foto["contado"] and despues["perp"] == foto["perp"]


def test_cubrir_todo_deja_la_exposicion_a_cero_sin_vender(bot):
    avanzar(bot, 0)
    bot.decidir()
    base_antes = dict(bot.cartera.contado)
    bot.poner_mando("neutral")
    assert neto(bot) == pytest.approx(0.0, abs=2e-3)
    assert bot.cartera.contado == base_antes, "cubrir no vende la base"
    pat = bot.cartera.patrimonio(bot.precios)
    movido = {s: p * 1.25 for s, p in bot.precios.items()}
    assert bot.cartera.patrimonio(movido) == pytest.approx(pat, rel=2e-3), "un +25 % ya no mueve el patrimonio"
    avanzar(bot, 3)
    bot.decidir()
    assert neto(bot) == pytest.approx(0.0, abs=0.02), "y sigue cubierto en las siguientes velas"


def test_salir_a_usdt_y_volver(bot):
    avanzar(bot, 0)
    bot.decidir()
    bot.poner_mando("fuera")
    assert bot.cartera.valor_contado(bot.precios) == 0 and bot.cartera.nocional_perp(bot.precios) == 0
    assert bot.cartera.patrimonio(bot.precios) == pytest.approx(bot.cartera.usdt)
    avanzar(bot, 2)
    assert bot.decidir() == [], "fuera se queda fuera"
    bot.poner_mando("auto")
    assert bot.cartera.valor_contado(bot.precios) > 0, "al volver a automático reconstruye la base"


def test_el_estado_sobrevive_a_un_reinicio(bot, tmp_path):
    avanzar(bot, 0)
    bot.decidir()
    bot.poner_mando("neutral")
    bot.cambiar_ajustes({"vol_cartera": 0.15})
    pat = bot.cartera.patrimonio(bot.precios)
    otro = ejecutor.Bot(feed=bot.feed, carpeta=str(tmp_path))
    assert otro.mando == "neutral", "un reinicio no devuelve el bot a automático por su cuenta"
    assert otro.p.vol_cartera == 0.15
    assert otro.ultima_decision_t == bot.ultima_decision_t
    assert otro.cartera.patrimonio(bot.precios) == pytest.approx(pat)


def test_el_panel_sabe_en_que_nivel_de_riesgo_esta(bot):
    assert bot.instantanea()["nivel"] == "moderado"
    assert set(bot.instantanea()["niveles"]) == set(config.NIVELES)
    bot.cambiar_ajustes(config.NIVELES["constante"]["ajustes"])
    assert bot.instantanea()["nivel"] == "constante"
    assert bot.p.vol_cartera == pytest.approx(0.10)
    bot.cambiar_ajustes({"vol_cartera": 0.33})
    assert bot.instantanea()["nivel"] is None, "a medida: no coincide con ningún nivel medido"


def test_ajustes_fuera_de_rango_se_rechazan(bot):
    for malo in ({"vol_cartera": 5}, {"tope_base": 0.99}, {"cobertura_max": 3}, {"modo": "perpetuos"},
                 {"vol_cartera": "mucho"}, {"apalancamiento": 3}, {"apalancamiento": 0.5}):
        with pytest.raises(ValueError):
            bot.cambiar_ajustes(malo)
    assert bot.ajustes == {}
    with pytest.raises(ValueError):
        bot.poner_mando("apalancar_x50")


def test_financiacion_se_liquida_una_sola_vez(bot):
    avanzar(bot, 0)
    bot.poner_mando("neutral")                 # asegura cortos abiertos
    s = next(k for k, p in bot.cartera.perp.items() if p.cantidad < 0)
    t = bot.cartera.ultimo_funding_ms[s] + 1000
    bot.feed.financiaciones = [(datos.a_ccxt(s), t, 0.0005)]
    bot.liquidar_financiacion(bot.consultar_financiacion())
    cobrado = bot.cartera.financiacion
    assert cobrado > 0, "un corto cobra la financiación positiva"
    bot.ultimo_funding_consultado = 0
    bot.liquidar_financiacion(bot.consultar_financiacion())
    assert bot.cartera.financiacion == cobrado


def test_sin_datos_no_decide_y_lo_dice(bot):
    bot.feed.caido = True
    bot.feed.ultimo_ok_utc = None
    bot.arranque = time.time() - 600
    bot.ciclo()
    assert bot.decision == {} and bot.ultima_decision_t is None
    assert bot.salud()["estado"] == "ciego"
    assert bot.cartera.usdt == 10_000


def test_garantia_baja_se_repone_sin_cambiar_la_exposicion(bot):
    avanzar(bot, 0)
    bot.poner_mando("neutral")
    # Subida brutal con todo cubierto: el patrimonio no cambia, pero la garantía se hunde.
    caro = {s: p * 1.6 for s, p in bot.precios.items()}
    assert bot.cartera.colchon_margen(caro) < ejecutor.MARGEN_MINIMO
    pat = bot.cartera.patrimonio(caro)
    neto_antes = sum(a + c for a, c in bot.cartera.pesos(caro).values())
    bot._vigilar_margen(caro)
    assert bot.cartera.colchon_margen(caro) > ejecutor.MARGEN_MINIMO
    assert bot.cartera.patrimonio(caro) == pytest.approx(pat, rel=5e-3)
    assert sum(a + c for a, c in bot.cartera.pesos(caro).values()) == pytest.approx(neto_antes, abs=5e-3)
    assert bot.avisos and "Garantía" in bot.avisos[-1]["texto"]


def test_solo_simulacion(monkeypatch):
    monkeypatch.setenv("JORGE_BOT_PAPER", "false")
    with pytest.raises(SystemExit):
        ejecutor.correr()
