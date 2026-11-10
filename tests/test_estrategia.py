import numpy as np
import pytest
from dataclasses import replace

from bot import estrategia as est
from tests.conftest import serie_sintetica

P = est.Parametros(simbolos=("AAAUSDT", "BBBUSDT", "CCCUSDT"))


def test_no_mira_al_futuro(mercado_sintetico):
    """Los objetivos de la vela k salen iguales si se calculan sin las velas posteriores."""
    H, L, C = mercado_sintetico
    entero = est.calcular(H, L, C, P)
    for k in (900, 1200, 1599):
        cortado = est.calcular(H[:k + 1], L[:k + 1], C[:k + 1], P)
        for campo in ("puntuacion", "base", "neto", "cobertura"):
            np.testing.assert_allclose(getattr(cortado, campo)[-1], getattr(entero, campo)[k],
                                       rtol=1e-10, atol=1e-12, err_msg=f"{campo} en {k}")


def test_ventana_reciente_da_lo_mismo_que_todo_el_historico(mercado_sintetico):
    """En vivo se calcula sobre las últimas 1 500 velas: debe coincidir con el histórico entero."""
    H, L, C = mercado_sintetico
    largo = np.vstack([H, H * 1.0]), np.vstack([L, L]), np.vstack([C, C])   # 3 200 velas
    # Para que la serie doble sea continua, la segunda mitad arranca donde acaba la primera.
    f = C[-1] / C[0]
    largo = (np.vstack([H, H * f]), np.vstack([L, L * f]), np.vstack([C, C * f]))
    entero = est.calcular(*largo, P)
    ventana = est.calcular(*(m[-1500:] for m in largo), P)
    np.testing.assert_allclose(ventana.neto[-1], entero.neto[-1], atol=5e-3)
    np.testing.assert_allclose(ventana.base[-1], entero.base[-1], rtol=2e-2)
    np.testing.assert_allclose(ventana.puntuacion[-1], entero.puntuacion[-1], atol=0.11)


def test_invariantes_de_los_pesos(mercado_sintetico):
    H, L, C = mercado_sintetico
    o = est.calcular(H, L, C, P)
    assert np.all(o.base >= 0)
    assert np.all(o.neto >= -1e-12), "sin sobrecobertura nunca queda neto corto"
    assert np.all(o.neto <= o.base + 1e-12), "la exposición nunca supera la base"
    assert np.all(o.cobertura >= -1e-12)
    np.testing.assert_allclose(o.cobertura, o.base - o.neto)
    assert o.base.sum(axis=1).max() <= P.tope_base + 1e-9
    np.testing.assert_allclose(o.perp(), -o.cobertura)
    assert np.all(np.abs(o.puntuacion) <= 1.0)


def test_rodaje_sin_opinion(mercado_sintetico):
    H, L, C = mercado_sintetico
    o = est.calcular(H, L, C, P)
    velas_rodaje = int(P.rodaje_dias * 6)
    assert np.all(o.puntuacion[:velas_rodaje] == 0)
    assert np.all(o.neto[:velas_rodaje] == 0)


def test_filtro_del_ancla(mercado_sintetico):
    """Con el ancla (la primera moneda) sin tendencia positiva, las demás no se exponen."""
    H, L, C = mercado_sintetico
    o = est.calcular(H, L, C, P)
    ancla_mal = o.puntuacion[:, 0] <= 0
    assert ancla_mal.sum() > 50, "la serie de prueba debe tener tramos bajistas del ancla"
    assert np.all(o.neto[ancla_mal, 1:] == 0)
    sin = est.calcular(H, L, C, replace(P, filtro_ancla=False))
    assert (sin.neto[ancla_mal, 1:] > 0).any(), "sin el filtro sí habría exposición en esos tramos"


def test_tendencia_clara_da_puntuacion_extrema():
    n = 1200
    sube = 100 * np.exp(np.linspace(0, 3, n))
    baja = 100 * np.exp(np.linspace(0, -3, n))
    for c, esperado in ((sube, 1.0), (baja, -1.0)):
        s = est.puntuacion(c * 1.001, c * 0.999, c, 6.0, P)
        assert s[-1] == pytest.approx(esperado)


def test_bajista_queda_cubierto_del_todo():
    n = 1200
    baja = 100 * np.exp(np.linspace(0, -3, n))
    C = np.column_stack([baja, baja * 2])
    o = est.calcular(C * 1.001, C * 0.999, C, replace(P, simbolos=("A", "B")))
    assert np.all(o.base[-1] > 0)
    np.testing.assert_allclose(o.neto[-1], 0.0)
    np.testing.assert_allclose(o.cobertura[-1], o.base[-1])


def test_sobrecobertura_deja_neto_corto():
    n = 1200
    baja = 100 * np.exp(np.linspace(0, -3, n))
    C = np.column_stack([baja, baja * 2])
    o = est.calcular(C * 1.001, C * 0.999, C, replace(P, simbolos=("A", "B"), cobertura_max=1.5))
    np.testing.assert_allclose(o.neto[-1], -0.5 * o.base[-1])


def test_control_de_cartera_recorta_cuando_hay_mucho_riesgo():
    """Con el mismo mercado, pedir menos riesgo de cartera nunca da más exposición."""
    n = 1400
    rng = np.random.default_rng(11)
    r = rng.normal(0.004, 0.03, n)             # sube con mucha volatilidad
    c = 100 * np.exp(np.cumsum(r))
    C = np.column_stack([c, c * 3])
    args = (C * 1.002, C * 0.998, C)
    p2 = replace(P, simbolos=("A", "B"))
    prudente = est.calcular(*args, replace(p2, vol_cartera=0.05))
    normal = est.calcular(*args, replace(p2, vol_cartera=0.60))
    assert np.all(prudente.neto <= normal.neto + 1e-12)
    assert prudente.neto.sum() < normal.neto.sum() * 0.8
    assert prudente.vol_prevista[prudente.neto.sum(axis=1) > 0].max() <= 0.05 + 1e-9


def test_modo_perpetuos_no_tiene_base(mercado_sintetico):
    H, L, C = mercado_sintetico
    o = est.calcular(H, L, C, replace(P, modo="perpetuos"))
    assert np.all(o.base == 0) and np.all(o.cobertura == 0)
    np.testing.assert_allclose(o.perp(), o.neto)


def test_moneda_que_empieza_a_cotizar_mas_tarde(mercado_sintetico):
    H, L, C = (m.copy() for m in mercado_sintetico)
    for m in (H, L, C):
        m[:500, 2] = np.nan
    o = est.calcular(H, L, C, P)
    assert np.all(o.base[:500, 2] == 0) and np.all(o.neto[:500, 2] == 0)
    assert np.all(np.isfinite(o.neto)) and np.all(np.isfinite(o.base))
    assert o.base[-1, 2] > 0


def test_canal():
    h = np.array([10, 11, 12, 11, 10, 9, 8, 9, 12, 13], dtype=float)
    l = h - 1
    c = h - 0.5
    # Canal de las 3 velas ANTERIORES: sin opinión hasta tener 3; rompe por abajo en la
    # vela 4 (9,5 < mínimo 10), aguanta, y rompe por arriba en la 8 (11,5 > máximo 9).
    np.testing.assert_array_equal(est._canal(h, l, c, 3), [0, 0, 0, 0, -1, -1, -1, -1, 1, 1])


def test_hay_que_mover():
    f = lambda a, o, banda=0.2: bool(est.hay_que_mover([a], [o], banda)[0])
    assert not f(0.10, 0.11)            # dentro de la banda
    assert f(0.10, 0.13)                # fuera
    assert f(0.05, 0.0)                 # cerrar se ejecuta siempre
    assert f(0.02, -0.02)               # cambio de signo, siempre
    assert not f(0.0, 0.0)
    assert f(0.0, 0.01)                 # abrir desde cero, siempre (signo distinto)
    # Con banda absoluta, un resto pequeño quedaría dentro de la banda: cerrar manda igualmente.
    g = lambda a, o: bool(est.hay_que_mover([a], [o], 0.2, banda_abs=0.05)[0])
    assert g(0.01, 0.0)                 # cerrar, aunque el resto sea menor que la banda
    assert not g(0.10, 0.13)            # dentro de la banda absoluta
    assert g(0.10, 0.16)


def test_apalancamiento_permite_pasar_de_la_base_y_por_defecto_no():
    n = 1200
    sube = 100 * np.exp(np.linspace(0, 3, n))
    C = np.column_stack([sube, sube * 2])
    args = (C * 1.001, C * 0.999, C)
    p2 = replace(P, simbolos=("A", "B"), vol_cartera=9.0, escala_max=1.0)
    sin = est.calcular(*args, p2)
    np.testing.assert_allclose(sin.neto[-1], sin.base[-1])               # tendencia plena: toda la base expuesta
    con = est.calcular(*args, replace(p2, apalancamiento=2.0))
    np.testing.assert_allclose(con.neto[-1], 2.0 * con.base[-1])         # y el doble si se pide
    np.testing.assert_allclose(con.perp()[-1], con.base[-1])             # el exceso va en perpetuo, en largo
    np.testing.assert_allclose(con.base, sin.base)                       # la base no cambia
