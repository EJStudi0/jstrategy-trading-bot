"""Contabilidad de la cartera simulada: aquí un error se convierte en dinero inventado."""
import json
import os

import pytest

from bot import cartera as cart
from bot.cartera import COMISION_CONTADO, COMISION_PERP, DESLIZAMIENTO, Cartera


def nueva(capital=10_000.0, tmp=None):
    return Cartera.nueva(capital, os.path.join(tmp, "diario.csv") if tmp else None)


# ── contado ──────────────────────────────────────────────────────────────────

def test_comprar_contado_paga_comision_y_deslizamiento():
    c = nueva()
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")
    ejec = 50_000.0 * (1 + DESLIZAMIENTO)
    assert c.contado["BTCUSDT"] == pytest.approx(0.1)
    assert c.usdt == pytest.approx(10_000 - 0.1 * ejec * (1 + COMISION_CONTADO))
    # A precio de mercado, el patrimonio baja justo en comisión + deslizamiento.
    assert c.patrimonio({"BTCUSDT": 50_000.0}) == pytest.approx(
        10_000 - 0.1 * ejec * COMISION_CONTADO - 0.1 * 50_000 * DESLIZAMIENTO)


def test_no_se_vende_lo_que_no_hay():
    c = nueva()
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")
    c.operar_contado("BTCUSDT", -5.0, 50_000.0, "t")
    assert c.contado["BTCUSDT"] == 0.0
    assert c.operar_contado("ETHUSDT", -1.0, 3_000.0, "t") == {}
    assert c.usdt > 0


def test_no_se_compra_mas_de_lo_que_hay_en_usdt():
    c = nueva(1_000.0)
    c.operar_contado("BTCUSDT", 1.0, 50_000.0, "t")       # costaría 50 000
    assert c.usdt == pytest.approx(0.0, abs=1e-6)
    assert c.contado["BTCUSDT"] * 50_000 < 1_000
    assert c.patrimonio({"BTCUSDT": 50_000.0}) < 1_000    # ni un céntimo creado


# ── perpetuos ────────────────────────────────────────────────────────────────

def test_corto_gana_cuando_el_precio_baja():
    c = nueva()
    c.operar_perp("BTCUSDT", -0.2, 50_000.0, "t")
    entrada = 50_000.0 * (1 - DESLIZAMIENTO)
    assert c.perp["BTCUSDT"].cantidad == pytest.approx(-0.2)
    assert c.perp["BTCUSDT"].entrada == pytest.approx(entrada)
    assert c.no_realizado({"BTCUSDT": 45_000.0}) == pytest.approx(0.2 * (entrada - 45_000))
    antes = c.usdt
    c.operar_perp("BTCUSDT", 0.2, 45_000.0, "t")            # cierra
    salida = 45_000.0 * (1 + DESLIZAMIENTO)
    realizado = 0.2 * (entrada - salida)
    assert c.pnl_realizado == pytest.approx(realizado)
    assert c.usdt == pytest.approx(antes + realizado - 0.2 * salida * COMISION_PERP)
    assert c.perp["BTCUSDT"].cantidad == 0.0


def test_ampliar_promedia_y_reducir_realiza_proporcional():
    c = nueva()
    c.operar_perp("ETHUSDT", -1.0, 2_000.0, "t")
    c.operar_perp("ETHUSDT", -1.0, 2_200.0, "t")
    e1, e2 = 2_000 * (1 - DESLIZAMIENTO), 2_200 * (1 - DESLIZAMIENTO)
    assert c.perp["ETHUSDT"].entrada == pytest.approx((e1 + e2) / 2)
    c.operar_perp("ETHUSDT", 0.5, 2_100.0, "t")
    assert c.perp["ETHUSDT"].cantidad == pytest.approx(-1.5)
    assert c.perp["ETHUSDT"].entrada == pytest.approx((e1 + e2) / 2), "reducir no cambia el precio medio"
    assert c.pnl_realizado == pytest.approx(0.5 * ((e1 + e2) / 2 - 2_100 * (1 + DESLIZAMIENTO)))


def test_darse_la_vuelta():
    c = nueva()
    c.operar_perp("ETHUSDT", -1.0, 2_000.0, "t")
    c.operar_perp("ETHUSDT", 3.0, 1_900.0, "t")             # cierra 1 y abre 2 largos
    assert c.perp["ETHUSDT"].cantidad == pytest.approx(2.0)
    assert c.perp["ETHUSDT"].entrada == pytest.approx(1_900 * (1 + DESLIZAMIENTO))
    assert c.pnl_realizado == pytest.approx(2_000 * (1 - DESLIZAMIENTO) - 1_900 * (1 + DESLIZAMIENTO))


def test_base_cubierta_al_cien_es_inmune_al_precio():
    """Lo esencial de la cobertura: contado + corto igual → el precio no mueve el patrimonio."""
    c = nueva()
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")
    c.operar_perp("BTCUSDT", -0.1, 50_000.0, "t")
    referencia = c.patrimonio({"BTCUSDT": 50_000.0})
    for precio in (10_000.0, 35_000.0, 50_000.0, 80_000.0, 200_000.0):
        assert c.patrimonio({"BTCUSDT": precio}) == pytest.approx(referencia, abs=1e-6)


def test_cobertura_al_doble_pierde_si_el_precio_sube():
    """La cobertura 2x del material original NO es 'nunca pierdes': queda neto corto."""
    c = nueva()
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")
    c.operar_perp("BTCUSDT", -0.2, 50_000.0, "t")
    antes = c.patrimonio({"BTCUSDT": 50_000.0})
    assert c.patrimonio({"BTCUSDT": 60_000.0}) == pytest.approx(antes - 0.1 * 10_000)
    assert c.patrimonio({"BTCUSDT": 40_000.0}) == pytest.approx(antes + 0.1 * 10_000)


# ── financiación ─────────────────────────────────────────────────────────────

def test_el_corto_cobra_financiacion_positiva_y_el_largo_la_paga():
    c = nueva()
    c.operar_perp("BTCUSDT", -0.1, 50_000.0, "t", t_ms=1_000)
    antes = c.usdt
    cobro = c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 2_000)
    assert cobro == pytest.approx(0.1 * 50_000 * 0.0001) and c.usdt == pytest.approx(antes + cobro)
    c2 = nueva()
    c2.operar_perp("BTCUSDT", 0.1, 50_000.0, "t", t_ms=1_000)
    assert c2.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 2_000) == pytest.approx(-0.5)
    assert c2.financiacion == pytest.approx(-0.5)


def test_un_evento_de_financiacion_no_se_cobra_dos_veces():
    c = nueva()
    c.operar_perp("BTCUSDT", -0.1, 50_000.0, "t", t_ms=1_000)
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 2_000) > 0
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 2_000) == 0.0
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 1_500) == 0.0   # anterior al último


def test_posicion_nueva_no_paga_financiacion_anterior_a_abrirse():
    c = nueva()
    c.operar_perp("BTCUSDT", -0.1, 50_000.0, "t", t_ms=10_000)
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 9_000) == 0.0
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 11_000) > 0


def test_sin_posicion_no_hay_financiacion():
    c = nueva()
    assert c.aplicar_financiacion("BTCUSDT", 0.0001, 50_000.0, 2_000) == 0.0
    assert c.usdt == 10_000


# ── margen ───────────────────────────────────────────────────────────────────

def test_colchon_de_margen():
    c = nueva()
    assert c.colchon_margen({"BTCUSDT": 50_000.0}) == float("inf")
    c.operar_contado("BTCUSDT", 0.15, 50_000.0, "t")          # 7 500 en base
    c.operar_perp("BTCUSDT", -0.15, 50_000.0, "t")            # cubierta entera
    inicial = c.colchon_margen({"BTCUSDT": 50_000.0})
    assert inicial == pytest.approx(c.usdt / 7_500, rel=1e-3)
    # Si el precio sube, el corto pierde y la garantía se estrecha (aunque el patrimonio no cambie).
    assert c.colchon_margen({"BTCUSDT": 60_000.0}) < inicial


# ── persistencia ─────────────────────────────────────────────────────────────

def test_guardar_y_cargar(tmp_path):
    c = nueva(tmp=str(tmp_path))
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")
    c.operar_perp("BTCUSDT", -0.06, 50_000.0, "t", t_ms=5)
    c.aplicar_financiacion("BTCUSDT", 0.0002, 50_000.0, 10)
    ruta = str(tmp_path / "estado.json")
    c.guardar(ruta)
    d = Cartera.cargar(ruta)
    precios = {"BTCUSDT": 47_000.0}
    assert d.patrimonio(precios) == pytest.approx(c.patrimonio(precios))
    assert d.perp["BTCUSDT"].cantidad == pytest.approx(-0.06)
    assert d.ultimo_funding_ms == {"BTCUSDT": 10}
    assert d.capital_inicial == 10_000 and d.financiacion == pytest.approx(c.financiacion)
    assert [f for f in os.listdir(tmp_path) if f.endswith(".tmp")] == [], "no quedan temporales"


def test_guardar_es_atomico(tmp_path, monkeypatch):
    """Si la escritura falla a medias, el estado anterior sigue entero."""
    c = nueva()
    ruta = str(tmp_path / "estado.json")
    c.guardar(ruta)
    c.usdt = 1.0
    monkeypatch.setattr(json, "dump", lambda *a, **k: (_ for _ in ()).throw(OSError("disco lleno")))
    with pytest.raises(OSError):
        c.guardar(ruta)
    monkeypatch.undo()
    assert Cartera.cargar(ruta).usdt == 10_000
    assert sorted(os.listdir(tmp_path)) == ["estado.json"]


def test_el_diario_apunta_cada_operacion(tmp_path):
    c = nueva(tmp=str(tmp_path))
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "vela", {"BTCUSDT": 50_000.0})
    c.operar_perp("BTCUSDT", -0.05, 50_000.0, "vela", {"BTCUSDT": 50_000.0})
    lineas = open(tmp_path / "diario.csv", encoding="utf-8").read().strip().splitlines()
    assert lineas[0].split(",") == cart.CAMPOS_DIARIO
    assert len(lineas) == 3 and ",contado,compra," in lineas[1] and ",perp,venta," in lineas[2]


# ── órdenes ──────────────────────────────────────────────────────────────────

PRECIOS = {"BTCUSDT": 50_000.0, "ETHUSDT": 2_500.0}


def ejecutar(c, pedidos, precios=PRECIOS):
    for pata, s, q in pedidos:
        (c.operar_contado if pata == "contado" else c.operar_perp)(s, q, precios[s], "t", precios)


def pesos(c, precios=PRECIOS):
    return {s: (round(a, 4), round(b, 4)) for s, (a, b) in c.pesos(precios).items()}


def test_ordenes_montan_base_y_cobertura():
    c = nueva()
    base = {"BTCUSDT": 0.40, "ETHUSDT": 0.30}
    neto = {"BTCUSDT": 0.40, "ETHUSDT": 0.00}          # BTC con tendencia plena, ETH bajista
    ejecutar(c, cart.ordenes(c, PRECIOS, base, neto, 0.4, 0.2, 10.0))
    w = pesos(c)
    assert w["BTCUSDT"][0] == pytest.approx(0.40, abs=2e-3) and w["BTCUSDT"][1] == 0.0
    assert w["ETHUSDT"][0] == pytest.approx(0.30, abs=2e-3)
    assert w["ETHUSDT"][1] == pytest.approx(-0.30, abs=2e-3), "ETH cubierto al 100 %"
    assert sum(a + b for a, b in w.values()) == pytest.approx(0.40, abs=3e-3)


def test_la_cobertura_es_fraccion_del_contado_real():
    """Con la base desviada dentro de su banda, 'cubrir la mitad' cubre la mitad de lo que hay."""
    c = nueva()
    c.operar_contado("BTCUSDT", 0.1, 50_000.0, "t")            # 50 % del patrimonio, objetivo 40 %
    pedidos = cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.40}, {"BTCUSDT": 0.20}, 0.4, 0.2, 10.0)
    assert [p[0] for p in pedidos] == ["perp"], "la base no se toca: está dentro de la banda"
    ejecutar(c, pedidos)
    wc, wp = c.pesos(PRECIOS)["BTCUSDT"]
    assert wp == pytest.approx(-0.5 * wc, rel=1e-3)


def test_tendencia_plena_no_deja_micro_coberturas():
    c = nueva()
    c.operar_contado("BTCUSDT", 0.09, 50_000.0, "t")           # 45 %, objetivo 40 %
    assert cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.40}, {"BTCUSDT": 0.40}, 0.4, 0.2, 10.0) == []


def test_las_bandas_evitan_operar_por_migajas():
    c = nueva()
    base, neto = {"BTCUSDT": 0.40}, {"BTCUSDT": 0.20}
    ejecutar(c, cart.ordenes(c, PRECIOS, base, neto, 0.4, 0.2, 10.0))
    assert cart.ordenes(c, PRECIOS, base, neto, 0.4, 0.2, 10.0) == [], "ya está en objetivo"
    poco = {"BTCUSDT": 51_000.0, "ETHUSDT": 2_500.0}           # +2 %: nada que hacer
    assert cart.ordenes(c, poco, base, neto, 0.4, 0.2, 10.0) == []
    assert cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.21}, 0.4, 0.2, 10.0) == []
    cambio = cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.05}, 0.4, 0.2, 10.0)
    assert [p[0] for p in cambio] == ["perp"] and cambio[0][2] < 0, "tendencia peor → más corto"


def test_con_la_tendencia_en_contra_se_cubre_todo_lo_que_hay():
    """Una cobertura casi completa no basta cuando la tendencia es contraria: se completa."""
    c = nueva()
    base = {"BTCUSDT": 0.40}
    ejecutar(c, cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.03}, 0.4, 0.1, 10.0))   # queda expuesto un 7,5 % de la base
    assert cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.02}, 0.4, 0.1, 10.0) == [], "con algo de tendencia es una migaja"
    pedidos = cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.0}, 0.4, 0.1, 10.0)
    assert [p[0] for p in pedidos] == ["perp"] and pedidos[0][2] < 0
    ejecutar(c, pedidos)
    wc, wp = c.pesos(PRECIOS)["BTCUSDT"]
    assert wc + wp == pytest.approx(0.0, abs=1e-4), "sin tendencia, exposición neta cero"
    assert cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.0}, 0.4, 0.1, 10.0) == [], "y ya no hay nada que hacer"


def test_la_tolerancia_de_la_cobertura_se_mide_sobre_la_base():
    c = nueva()
    base = {"BTCUSDT": 0.40}
    ejecutar(c, cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.36}, 0.4, 0.1, 10.0))   # cobertura pequeña: 10 % de la base
    # Del 90 % al 85 % expuesto la cobertura cambia un 50 %, pero la exposición solo un 5 % de la base.
    assert cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.34}, 0.4, 0.1, 10.0) == []
    # Del 90 % al 75 % son 15 puntos de la base: fuera de la tolerancia.
    cambio = cart.ordenes(c, PRECIOS, base, {"BTCUSDT": 0.30}, 0.4, 0.1, 10.0)
    assert [p[0] for p in cambio] == ["perp"] and cambio[0][2] < 0


def test_sin_base_la_banda_es_relativa_al_objetivo():
    c = nueva()
    ejecutar(c, cart.ordenes(c, PRECIOS, {}, {"BTCUSDT": 0.20}, 0.4, 0.1, 10.0, modo="perpetuos"))
    assert cart.ordenes(c, PRECIOS, {}, {"BTCUSDT": 0.23}, 0.4, 0.1, 10.0, modo="perpetuos") == []      # +15 % < 20 %
    assert cart.ordenes(c, PRECIOS, {}, {"BTCUSDT": 0.26}, 0.4, 0.1, 10.0, modo="perpetuos") != []
    assert cart.ordenes(c, PRECIOS, {}, {"BTCUSDT": 0.23}, 0.4, 0.1, 10.0, modo="perpetuos",
                        banda_sin_base=0.05) != []


def test_minimo_de_orden():
    c = nueva(100.0)
    assert cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.05}, {"BTCUSDT": 0.05}, 0.4, 0.2, 10.0) == []


def test_salir_del_todo_y_ventas_antes_que_compras():
    c = nueva()
    ejecutar(c, cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.7}, {"BTCUSDT": 0.2}, 0.4, 0.2, 10.0))
    # Rotar de BTC a ETH: la venta debe ir antes para que haya USDT.
    pedidos = cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.0, "ETHUSDT": 0.7}, {"BTCUSDT": 0.0, "ETHUSDT": 0.7},
                           0.4, 0.2, 10.0)
    patas = [(p[0], p[1], p[2] > 0) for p in pedidos]
    assert patas.index(("contado", "BTCUSDT", False)) < patas.index(("contado", "ETHUSDT", True))
    ejecutar(c, pedidos)
    w = pesos(c)
    assert w["BTCUSDT"] == (0.0, 0.0)
    assert w["ETHUSDT"][0] == pytest.approx(0.7, abs=5e-3)
    # Y fuera del todo:
    ejecutar(c, cart.ordenes(c, PRECIOS, {"ETHUSDT": 0.0}, {"ETHUSDT": 0.0}, 0.4, 0.2, 10.0, forzar=True))
    assert c.valor_contado(PRECIOS) == 0 and c.nocional_perp(PRECIOS) == 0
    assert c.patrimonio(PRECIOS) == pytest.approx(c.usdt)


def test_modo_perpetuos_no_compra_contado():
    c = nueva()
    pedidos = cart.ordenes(c, PRECIOS, {"BTCUSDT": 0.4}, {"BTCUSDT": 0.3}, 0.4, 0.2, 10.0, modo="perpetuos")
    assert [p[0] for p in pedidos] == ["perp"] and pedidos[0][2] > 0
    ejecutar(c, pedidos)
    assert c.pesos(PRECIOS)["BTCUSDT"] == pytest.approx((0.0, 0.3), abs=2e-3)


def test_operar_nunca_crea_dinero():
    """Tras una tanda de operaciones a precio fijo, el patrimonio solo puede bajar (costes)."""
    c = nueva()
    inicial = c.patrimonio(PRECIOS)
    objetivos = [({"BTCUSDT": 0.4, "ETHUSDT": 0.3}, {"BTCUSDT": 0.4, "ETHUSDT": 0.0}),
                 ({"BTCUSDT": 0.2, "ETHUSDT": 0.5}, {"BTCUSDT": 0.0, "ETHUSDT": 0.5}),
                 ({"BTCUSDT": 0.0, "ETHUSDT": 0.0}, {"BTCUSDT": 0.0, "ETHUSDT": 0.0})]
    previo = inicial
    for base, neto in objetivos:
        ejecutar(c, cart.ordenes(c, PRECIOS, base, neto, 0.4, 0.2, 10.0, forzar=True))
        ahora = c.patrimonio(PRECIOS)
        assert ahora <= previo + 1e-9
        previo = ahora
    coste = inicial - previo
    # Lo perdido es comisión más deslizamiento, y nada más: el deslizamiento (0,02 %)
    # es entre un 20 % y un 40 % de la comisión (0,05-0,10 %).
    assert c.comisiones * 1.15 < coste < c.comisiones * 1.45
    assert coste < inicial * 0.01
