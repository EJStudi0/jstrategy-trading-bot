"""Los patrones del asistente: sin mirar al futuro, y la ruptura igual que la regla medida."""
import numpy as np

from bot import patrones
from investigacion import intradia as it

M15 = 15 * 60_000


def mercado(n=40_000, semilla=11):
    rng = np.random.default_rng(semilla)
    r = rng.standard_t(3, n) * 0.002 + 0.00002
    c = 100 * np.exp(np.cumsum(r))
    o = np.r_[100.0, c[:-1]]
    h = np.maximum(o, c) * (1 + abs(rng.normal(0, 0.001, n)))
    l = np.minimum(o, c) * (1 - abs(rng.normal(0, 0.001, n)))
    v = rng.lognormal(0, 1.0, n)
    t = 1_600_000_000_000 // M15 * M15 + np.arange(n) * M15
    return t, o, h, l, c, v


def en_30(t, o, h, l, c, v):
    tc, o3, h3, l3, c3, v3 = patrones.agrupar(t, o, h, l, c, v, 30)
    return tc - patrones.M30, o3, h3, l3, c3, v3


def fondo_de(t, o, h, l, c, v, t30):
    tc4, o4, h4, l4, c4, v4 = patrones.agrupar(t, o, h, l, c, v, 240)
    return patrones.fondo(tc4 - 240 * 60_000, o4, h4, l4, c4, v4, t30 + patrones.M30)


def test_la_ruptura_es_la_regla_medida():
    t, o, h, l, c, v = mercado()
    mon = it.Moneda("X", t, o, h, l, c, v, np.array([0]), np.array([0.0]))
    k30, k60 = it.agrupar(t, o, h, l, c, v, 30), it.agrupar(t, o, h, l, c, v, 60)
    k4, k1d = it.agrupar(t, o, h, l, c, v, 240), it.agrupar(t, o, h, l, c, v, 1440)
    mon.k30, mon.k60 = k30, k60
    mon.i15_30 = np.searchsorted(t, k30.tc, side="left")
    mon.ctx30 = it.contexto(k4, k1d, k30.tc)
    mon.adx30 = np.zeros(len(k30.tc))
    a60 = it.atr(k60) / k60.c
    import pandas as pd
    mon.mov30 = it.al_reloj(k60.tc, a60 / pd.Series(a60).rolling(720, min_periods=240).mean().to_numpy(), k30.tc)
    s = it.jugada_inercia(mon, ventana=96, volumen=2.5, margen=2.0, fondo=True)
    s = s.donde(np.nan_to_num(s.mov) >= 1.0)

    t30, *resto = en_30(t, o, h, l, c, v)
    det = patrones.detectar(t30, *resto, fondo_de(t, o, h, l, c, v, t30))
    j = np.flatnonzero(det["ruptura"])
    j = j[mon.i15_30[j] < len(t)]
    assert len(j) > 20
    assert np.array_equal(mon.i15_30[j], s.i) and np.array_equal(det["ruptura"][j], s.d)


def test_no_miran_al_futuro():
    t, o, h, l, c, v = mercado(n=12_000)
    t30, *resto = en_30(t, o, h, l, c, v)
    ctx = fondo_de(t, o, h, l, c, v, t30)
    todo = patrones.detectar(t30, *resto, ctx)
    k = len(t30) - 500
    corto = patrones.detectar(t30[:k], *(x[:k] for x in resto), ctx[:k])
    for nombre in corto:
        if nombre == "_":
            continue
        assert np.array_equal(todo[nombre][:k], corto[nombre]), nombre


def test_catalogo_completo_y_despues():
    t, o, h, l, c, v = mercado(n=12_000)
    t30, o3, h3, l3, c3, v3 = en_30(t, o, h, l, c, v)
    det = patrones.detectar(t30, o3, h3, l3, c3, v3, fondo_de(t, o, h, l, c, v, t30))
    det.pop("_")
    assert set(det) | {"nivel"} == set(patrones.CATALOGO)
    x = patrones.despues(det["barrido"], c3)
    assert len(x) <= np.count_nonzero(det["barrido"])
