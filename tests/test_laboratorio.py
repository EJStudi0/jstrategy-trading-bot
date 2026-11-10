"""El simulador de la investigación: si miente, todo lo medido con él miente."""
import numpy as np
import pytest

from investigacion import laboratorio as lab


def cuadricula(C, F=None, intervalo="4h"):
    C = np.asarray(C, dtype=float)
    T, N = C.shape
    t = np.arange(T) * 14_400_000
    return lab.Cuadricula(intervalo, [f"M{j}" for j in range(N)], t, C, C, C, C, np.ones((T, N)),
                          np.zeros((T, N)) if F is None else np.asarray(F, dtype=float))


def test_comprar_y_mantener_reproduce_el_precio():
    c = np.array([[100.0], [110.0], [99.0], [120.0]])
    r = lab.simular(cuadricula(c), np.ones((4, 1)), coste=0.0)
    assert r.patrimonio[-1] == pytest.approx(1.2)
    np.testing.assert_allclose(r.rend[1:], [0.10, -0.10, 120 / 99 - 1])


def test_el_peso_decidido_en_k_solo_cobra_el_movimiento_siguiente():
    c = np.array([[100.0], [200.0], [200.0], [100.0]])
    W = np.array([[0.0], [1.0], [0.0], [0.0]])     # entra tras la subida, sale antes de la caída
    r = lab.simular(cuadricula(c), W, coste=0.0)
    assert r.patrimonio[-1] == pytest.approx(1.0), "no puede haberse llevado el +100 % ya ocurrido"


def test_costes_por_cada_lado():
    c = np.full((4, 1), 100.0)
    W = np.array([[1.0], [1.0], [0.0], [0.0]])
    r = lab.simular(cuadricula(c), W, coste=0.001, banda_rel=0.01)
    # Se compra y se vende el mismo nocional (1,0 del capital inicial): dos comisiones exactas.
    assert r.patrimonio[-1] == pytest.approx(1 - 2 * 0.001, rel=1e-12)
    assert r.coste.sum() == pytest.approx(0.001 + 0.001 / 0.999, rel=1e-9), "la 2ª, sobre el patrimonio ya mermado"


def test_financiacion_la_paga_el_largo_y_la_cobra_el_corto():
    c = np.full((3, 1), 100.0)
    F = np.array([[0.001], [0.001], [0.0]])
    largo = lab.simular(cuadricula(c, F), np.ones((3, 1)), coste=0.0)
    corto = lab.simular(cuadricula(c, F), -np.ones((3, 1)), coste=0.0)
    assert largo.patrimonio[-1] == pytest.approx(0.999 ** 2)
    assert corto.patrimonio[-1] == pytest.approx(1.001 ** 2)
    sin = lab.simular(cuadricula(c, F), np.ones((3, 1)), coste=0.0, con_financiacion=False)
    assert sin.patrimonio[-1] == pytest.approx(1.0)


def test_cubierto_al_cien_no_gana_ni_pierde_con_el_precio():
    c = np.array([[100.0], [150.0], [60.0], [90.0]])
    g = cuadricula(c)
    g2, W2, costes = lab.doble_pata(g, np.full((4, 1), 0.5), np.full((4, 1), -0.5))
    r = lab.simular(g2, W2, coste=0.0, banda_rel=10.0)
    assert r.patrimonio[-1] == pytest.approx(1.0)
    assert list(costes) == [lab.COSTE_CONTADO, lab.COSTE_POR_LADO]
    assert g2.F[:, 0].sum() == 0, "el contado no paga financiación"


def test_base_cubierta_sin_tendencia_queda_neutral():
    """Al perderse la tendencia la cobertura se completa aunque falte poco: el precio deja de mover el patrimonio."""
    c = np.array([[100.0], [100.0], [100.0], [50.0], [50.0]])
    base = np.full((5, 1), 0.5)
    neto = np.array([[0.04], [0.04], [0.0], [0.0], [0.0]])       # un 8 % de la base expuesta, y luego nada
    r = lab.simular_cubierta(cuadricula(c), base, neto, 0.4, 0.1, coste_contado=0.0, coste_perp=0.0)
    assert r.neto[2] == pytest.approx(0.04)
    assert r.neto[3] == pytest.approx(0.0, abs=1e-12), "faltaba menos que la tolerancia, pero sin tendencia se cubre todo"
    assert r.patrimonio[-1] == pytest.approx(1.0), "la caída del 50 % no le toca"


def test_base_cubierta_tolera_desvios_pequeños_de_la_exposicion():
    c = np.full((6, 1), 100.0)
    base = np.full((6, 1), 0.5)
    neto = np.array([[0.45], [0.42], [0.42], [0.38], [0.38], [0.38]])
    r = lab.simular_cubierta(cuadricula(c), base, neto, 0.4, 0.1, coste_contado=0.0, coste_perp=0.0)
    assert r.rotacion[2] == 0.0, "0,03 de desvío es menos que el 10 % de la base (0,05): no se toca"
    assert r.neto[2] == pytest.approx(0.45)
    assert r.rotacion[4] == pytest.approx(0.07), "0,07 ya pasa: se reajusta entera"
    assert r.neto[4] == pytest.approx(0.38)


def test_la_tolerancia_de_la_cobertura_es_sobre_el_contado_que_hay():
    """Si la base se ha desviado dentro de su banda, la tolerancia sale de lo que hay, no del objetivo."""
    c = np.full((4, 1), 100.0)
    base = np.array([[0.5], [0.4], [0.4], [0.4]])                # el contado se queda en 0,5 (banda del 40 %)
    neto = np.array([[0.25], [0.164], [0.164], [0.164]])         # la cobertura pasaría de 0,25 a 0,295
    r = lab.simular_cubierta(cuadricula(c), base, neto, 0.4, 0.1, coste_contado=0.0, coste_perp=0.0)
    assert r.rotacion[2] == 0.0, "0,045 es menos que el 10 % del contado real (0,05), aunque pase del 10 % del objetivo (0,04)"


def test_la_banda_evita_reajustes_pequeños():
    rng = np.random.default_rng(0)
    c = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, (300, 2)), axis=0))
    W = np.full((300, 2), 0.3)
    sin = lab.simular(cuadricula(c), W, banda_rel=0.0)
    con = lab.simular(cuadricula(c), W, banda_rel=0.3)
    assert con.rotacion.sum() < sin.rotacion.sum() * 0.5


def test_retraso_desplaza_la_ejecucion():
    c = np.array([[100.0], [200.0], [400.0], [400.0]])
    W = np.array([[1.0], [1.0], [1.0], [1.0]])
    assert lab.simular(cuadricula(c), W, coste=0.0).patrimonio[-1] == pytest.approx(4.0)
    assert lab.simular(cuadricula(c), W, coste=0.0, retraso=1).patrimonio[-1] == pytest.approx(2.0)


def test_moneda_sin_cotizar_no_cuenta():
    c = np.array([[100.0, np.nan], [110.0, np.nan], [110.0, 50.0], [110.0, 100.0]])
    r = lab.simular(cuadricula(c), np.full((4, 2), 0.5), coste=0.0)
    assert np.all(np.isfinite(r.patrimonio))
    assert r.rend[1] == pytest.approx(0.05)        # solo la primera moneda estaba viva


def test_metricas_basicas():
    c = (100 * np.cumprod(np.full(2191, 1.0001))).reshape(-1, 1)      # un año de velas de 4 h, siempre sube
    m = lab.simular(cuadricula(c), np.ones((2191, 1)), coste=0.0).metricas()
    assert m["max_dd_pct"] == 0.0
    assert m["cagr_pct"] == pytest.approx((1.0001 ** 2190 - 1) * 100, abs=0.2)
    assert m["anios"] == pytest.approx(1.0, abs=0.01)
