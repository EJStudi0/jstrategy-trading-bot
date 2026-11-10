"""Renta: tener la parte cubierta de la base en las monedas cuyo perpetuo paga más. Diseño y prueba.

La base cubierta cobra la financiación del perpetuo. La estrategia la tiene repartida entre las diez
monedas, y cubre más justo las de peor tendencia, que suelen ser las que menos pagan. Idea: dejar
que la tendencia use lo que necesite y poner el resto, cubierto 1:1, en las pocas monedas que más
vienen pagando.

Fijado ANTES de mirar la prueba (2026-11-10), con 2020-2023:
  - se mira la financiación media de los últimos 30 días (lo ya liquidado al cierre de la vela);
  - hasta 3 monedas; entra la que paga más de un 5 % anual; sale si deja de pagar o si baja más de
    2 puestos; se revisa cada 14 días (reloj lento);
  - una moneda con tendencia conserva su base entera hasta la revisión siguiente (reloj rápido: la
    cobertura se ajusta en cada vela, en el perpetuo, que es lo barato);
  - criterio para adoptarla: más rentabilidad y más Sharpe sin más caída.

Resultado: en el diseño pasa con holgura (+43 → +51 % anual, toda la vecindad de parámetros entre
+48 y +53 %). En la prueba no: +11,4 % frente a +11,8 %, con más caída. Desde 2024 la financiación
es baja y parecida entre monedas; lo que se gana eligiendo (+1,1 puntos al año) no paga los cambios
de moneda (+2,4 puntos de comisiones). No entra en el bot.

La prueba se hizo con la regla de cobertura de entonces; `cobertura_antigua=True` la reproduce.

Uso: python -m investigacion.renta [diseño|prueba|todo]
"""
import sys
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd

from bot import estrategia as est
from investigacion import comun, laboratorio as lab

MS_DIA = 86_400_000


@dataclass(frozen=True)
class Renta:
    dias: float = 30.0
    monedas: int = 3
    entrada: float = 0.05
    salida: float = 0.0
    margen: int = 2
    cada_dias: float = 14.0


def financiacion_reciente(F: np.ndarray, cotiza: np.ndarray, velas: int, velas_anio: float) -> np.ndarray:
    """Financiación anual media de las `velas` anteriores a cada vela.

    `F[k]` se liquida DESPUÉS del cierre de `k`: al decidir en `k` solo se conoce hasta `F[k-1]`.
    """
    suma = np.cumsum(np.where(cotiza, F, 0.0), axis=0)
    cuenta = np.cumsum(cotiza.astype(np.float64), axis=0)
    s, c = suma.copy(), cuenta.copy()
    s[velas:] -= suma[:-velas]
    c[velas:] -= cuenta[:-velas]
    media = np.where(c >= 0.9 * velas, s / np.maximum(c, 1.0), np.nan) * velas_anio
    return np.vstack([np.full((1, F.shape[1]), np.nan), media[:-1]])


def periodos(t: np.ndarray, p: est.Parametros, r: Renta) -> np.ndarray:
    """Número de periodo del reloj lento: cambia en la vela cuyo cierre cruza la frontera."""
    ms_vela = MS_DIA / est.VELAS_DIA[p.intervalo]
    return np.floor((t.astype(np.float64) + ms_vela) / (r.cada_dias * MS_DIA)).astype(np.int64)


def elegir(dentro: np.ndarray, f: np.ndarray, r: Renta) -> np.ndarray:
    """Un paso del reloj lento: quién sigue y quién entra."""
    ft = np.where(np.isnan(f), -np.inf, f)
    orden = np.argsort(-ft, kind="stable")
    puesto = np.empty(len(f), dtype=np.int64)
    puesto[orden] = np.arange(len(f))
    nuevo = dentro & (puesto < r.monedas + r.margen) & (ft > r.salida)
    huecos = r.monedas - int(nuevo.sum())
    for j in orden:
        if huecos <= 0:
            break
        if not nuevo[j] and ft[j] > r.entrada:
            nuevo[j] = True
            huecos -= 1
    return nuevo


def elegidas(g: lab.Cuadricula, p: est.Parametros, r: Renta) -> np.ndarray:
    """Las monedas de renta vela a vela (tiempo × moneda), partiendo de ninguna."""
    vd = est.VELAS_DIA[p.intervalo]
    cotiza = ~np.isnan(g.C)
    f = financiacion_reciente(g.F, cotiza, int(round(r.dias * vd)), vd * 365.0)
    per = periodos(g.t, p, r)
    out = np.zeros(g.C.shape, dtype=bool)
    dentro = np.zeros(g.C.shape[1], dtype=bool)
    for k in range(g.n):
        if k == 0 or per[k] != per[k - 1]:
            dentro = elegir(dentro, np.where(cotiza[k], f[k], np.nan), r)
        out[k] = dentro
    return out


def base_con_renta(g: lab.Cuadricula, p: est.Parametros, o: est.Objetivos, r: Renta) -> np.ndarray:
    """La base en contado: entera en las monedas con tendencia; lo que queda libre, en las de renta."""
    cotiza = ~np.isnan(g.C)
    renta = elegidas(g, p, r)
    per = periodos(g.t, p, r)
    con = o.neto > 0.0
    out = np.zeros(g.C.shape)
    retenida = np.zeros(g.C.shape[1], dtype=bool)
    for k in range(g.n):
        retenida = con[k].copy() if (k == 0 or per[k] != per[k - 1]) else (retenida | con[k])
        tendencia = np.where(retenida & cotiza[k], o.base[k], 0.0)
        libre = max(p.tope_base - float(tendencia.sum()), 0.0)
        out[k] = tendencia + np.where(renta[k] & cotiza[k], libre / r.monedas, 0.0)
    return out


def persistencia(g, p, m) -> pd.DataFrame:
    """¿Las que más pagaban siguen pagando más? Correlación de rangos y ventaja de las tres primeras."""
    vd = int(est.VELAS_DIA[p.intervalo])
    cotiza = ~np.isnan(g.C)
    F = np.where(cotiza, g.F, np.nan)[m]
    T = len(F)
    filas = []
    for pasado, futuro in ((7, 14), (30, 14), (30, 30), (60, 30)):
        antes = pd.DataFrame(F).rolling(pasado * vd).mean().to_numpy()
        despues = pd.DataFrame(F).rolling(futuro * vd).mean().shift(-futuro * vd).to_numpy()
        ic, ventaja = [], []
        for k in range(pasado * vd, T - futuro * vd, futuro * vd):       # sin solapar
            a, b = antes[k - 1], despues[k]                               # antes[k-1]: hasta lo cobrado al cierre de k
            ok = ~np.isnan(a) & ~np.isnan(b)
            if ok.sum() >= 6:
                ic.append(np.corrcoef(pd.Series(a[ok]).rank(), pd.Series(b[ok]).rank())[0, 1])
                ventaja.append(b[ok][np.argsort(-a[ok])[:3]].mean() - b[ok].mean())
        ventaja = np.array(ventaja) * vd * 365 * 100
        filas.append({"miro_dias": pasado, "cobro_dias": futuro, "correlacion_rangos": round(float(np.mean(ic)), 2),
                      "tres_primeras_menos_media_%anual": round(float(ventaja.mean()), 1),
                      "t": round(float(ventaja.mean() / (ventaja.std() / np.sqrt(len(ventaja)))), 1)})
    return pd.DataFrame(filas)


def correr(desde, hasta, vecindad: bool) -> dict:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    m = comun.mascara(g, desde, hasta)
    gg = g.recorte(desde, hasta)
    o = est.calcular(g.H, g.L, g.C, p)
    sim = lambda base, neto: lab.simular_cubierta(gg, base[m], neto[m], p.banda_base, p.banda_cobertura,
                                                  cobertura_antigua=True)
    cero = np.zeros_like(o.neto)
    r = Renta()
    res = {"lo que corría (base repartida entre las diez)": sim(o.base, o.neto),
           "CON RENTA (lo fijado)": sim(base_con_renta(g, p, o, r), o.neto),
           "todo cubierto, base repartida": sim(o.base, cero),
           "todo cubierto, con renta": sim(base_con_renta(g, p, o, r), cero)}
    if vecindad:
        for nombre, otro in (("2 monedas", replace(r, monedas=2)), ("5 monedas", replace(r, monedas=5)),
                             ("mira 14 días", replace(r, dias=14.0)), ("mira 60 días", replace(r, dias=60.0)),
                             ("revisa cada 7 días", replace(r, cada_dias=7.0)), ("revisa cada 28 días", replace(r, cada_dias=28.0)),
                             ("entra con cualquier pago positivo", replace(r, entrada=0.0)),
                             ("entra desde el 10 %", replace(r, entrada=0.10)),
                             ("sin margen de puestos", replace(r, margen=0))):
            res["  vecindad: " + nombre] = sim(base_con_renta(g, p, o, otro), o.neto)
    return res


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    cols = comun.COLS_CONSTANCIA + ["rotacion_anual"]
    if que in ("diseño", "todo"):
        p = est.Parametros()
        g = lab.cuadricula(p.intervalo, list(p.simbolos))
        t = "\n".join(["=== DISEÑO 2020-2023 · ¿se mantiene qué moneda paga más? ===",
                       persistencia(g, p, comun.mascara(g, hasta=comun.FIN_DISEÑO)).to_string(index=False), "",
                       "=== DISEÑO 2020-2023 · con renta ===",
                       comun.con_anios(correr(None, comun.FIN_DISEÑO, True), cols).to_string()])
        print(t)
        lab.guardar("renta_diseño.txt", t)
    if que in ("prueba", "todo"):
        t = "=== PRUEBA 2024-01 → 2026-11 · con renta (una sola mirada, solo lo fijado) ===\n" + \
            comun.con_anios(correr(comun.FIN_DISEÑO, None, False), cols).to_string()
        print(t)
        lab.guardar("renta_prueba.txt", t)
