"""¿Más tamaño cuanto más confirmada la entrada? ¿Y promediar la caída con poco? Solo diseño.

Viene de dos prácticas de Jorge (2026-11-10): entrar con muy poco («0,1 %») mientras el precio cae y
con un porcentaje mayor cuando la entrada está confirmada. Traducidas a lo que el bot puede medir:

  1. Mapa nota → exposición. Hoy es lineal (media nota, media base). ¿Rinde más uno convexo
     (poco con la nota a medias, todo con la nota plena) o uno con umbral?
  2. Escalera en caídas. Con la tendencia en contra, descubrir un poco de la base por cada tramo
     que el precio cae desde su máximo, y volver a cubrir según recupera.

Uso: python -m investigacion.tamano
"""
import itertools

import numpy as np
import pandas as pd

from bot import estrategia as est, indicadores as ind
from investigacion import comun, laboratorio as lab


def nota_filtrada(g: lab.Cuadricula, p: est.Parametros):
    """(nota bruta, nota tras el filtro de Bitcoin, objetivos de la estrategia tal cual)."""
    o = est.calcular(g.H, g.L, g.C, p)
    S = o.puntuacion
    F = S.copy()
    if p.filtro_ancla and S.shape[1] > 1:
        F[:, 1:] = np.where(S[:, [0]] > 0, S[:, 1:], np.minimum(S[:, 1:], 0.0))
    return S, F, o


def con_mapa(g: lab.Cuadricula, p: est.Parametros, mapa) -> est.Objetivos:
    """La estrategia con otra función nota → fracción de la base expuesta (para notas positivas)."""
    _, F, _ = nota_filtrada(g, p)
    return est.calcular(g.H, g.L, g.C, p, ajuste_nota=np.where(F > 0, mapa(F), F) - F)


def por_tramos(g, p, m) -> pd.DataFrame:
    """Rendimiento de la vela siguiente, en unidades de riesgo, según la nota (tras el filtro)."""
    _, F, o = nota_filtrada(g, p)
    vd = est.VELAS_DIA[p.intervalo]
    C, F, V = g.C[m], F[m], o.vol[m]
    R = np.full(C.shape, np.nan)
    R[:-1] = C[1:] / C[:-1] - 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        Z = R / (V / np.sqrt(vd * 365.0))
    ok = np.isfinite(Z)
    anio = pd.to_datetime(g.t[m], unit="ms").year.to_numpy()
    filas = []
    for a, b in ((-1.01, -0.2), (-0.2, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 0.95), (0.95, 1.01)):
        sel = ok & (F > a) & (F <= b)
        fila = {"nota": f"({a:+.1f}, {b:+.1f}]", "velas_%": round(100 * sel.sum() / ok.sum(), 1),
                "sharpe_anual": round(float(np.mean(Z[sel]) * np.sqrt(vd * 365.0)), 2)}
        for y in sorted(set(anio)):
            sy = sel & (anio == y)[:, None]
            fila[str(y)] = round(float(np.mean(Z[sy]) * np.sqrt(vd * 365.0)), 2) if sy.sum() > 50 else np.nan
        filas.append(fila)
    return pd.DataFrame(filas).set_index("nota")


def mapas(g, p, m) -> dict:
    gd = g.recorte(None, comun.FIN_DISEÑO)
    potencia = lambda e: (lambda F: np.clip(F, 0, 1) ** e)
    rampa = lambda a, b: (lambda F: np.clip((F - a) / (b - a), 0, 1))
    candidatos = {"lineal (lo que corre)": None,
                  "cóncavo: raíz": potencia(0.5), "convexo: cuadrado": potencia(2.0), "convexo: cubo": potencia(3.0),
                  "todo en cuanto la nota es positiva": rampa(0.0, 1e-9),
                  "nada hasta 0,2, todo desde 0,6": rampa(0.2, 0.6), "nada hasta 0,4, todo en 1": rampa(0.4, 1.0),
                  "nada hasta 0,6, todo en 1": rampa(0.6, 1.0)}
    res = {}
    for nombre, mapa in candidatos.items():
        o = est.calcular(g.H, g.L, g.C, p) if mapa is None else con_mapa(g, p, mapa)
        res[nombre] = lab.simular_cubierta(gd, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura)
    return res


def escalera(g, p, dias_max: int, fondo: float, tope: float):
    """Exposición con la escalera: con la nota <= 0 se descubre `tope` × base al llegar la caída a `fondo` (log)."""
    _, F, o = nota_filtrada(g, p)
    vd = int(est.VELAS_DIA[p.intervalo])
    maximo = lab.por_columnas(lambda h: ind.maximo(h, dias_max * vd), g.H)
    with np.errstate(invalid="ignore"):
        hondura = np.log(maximo / g.C)
    tramo = np.clip(hondura / fondo, 0.0, 1.0) * tope
    extra = np.where((F <= 0) & ~np.isnan(g.C) & ~np.isnan(hondura), o.base * tramo, 0.0)
    return o, np.maximum(o.neto, extra), extra


def escaleras(g, p, m) -> dict:
    gd = g.recorte(None, comun.FIN_DISEÑO)
    o = est.calcular(g.H, g.L, g.C, p)
    res = {"sin escalera (lo que corre)": lab.simular_cubierta(gd, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura)}
    for dias_max, fondo, tope in itertools.product((60, 180), (0.5, 1.0), (0.25, 0.5, 1.0)):
        _, neto, _ = escalera(g, p, dias_max, fondo, tope)
        nombre = f"máximo de {dias_max} d, llena al caer {int((1 - np.exp(-fondo)) * 100)} %, hasta {int(tope * 100)} % de la base"
        res[nombre] = lab.simular_cubierta(gd, o.base[m], neto[m], p.banda_base, p.banda_cobertura)
    # Control: la misma exposición media con la nota <= 0, pero fija. Si la escalera no lo supera,
    # lo que aporta es solo estar más largo, no comprar más cuanto más cae.
    _, F, _ = nota_filtrada(g, p)
    _, _, extra = escalera(g, p, 180, 1.0, 0.5)
    sin_nota = (F <= 0) & ~np.isnan(g.C)
    fijo = np.where(sin_nota, np.minimum(o.base, extra[m].sum() / max(sin_nota[m].sum(), 1)), 0.0)
    res["CONTROL: largo fijo del mismo tamaño medio"] = lab.simular_cubierta(
        gd, o.base[m], np.maximum(o.neto, fijo)[m], p.banda_base, p.banda_cobertura)
    return res


def despues_de_caer(g, p, m) -> pd.DataFrame:
    """Con la tendencia en contra: rendimiento a 7 y 30 días según lo hondo de la caída."""
    _, F, _ = nota_filtrada(g, p)
    vd = int(est.VELAS_DIA[p.intervalo])
    maximo = lab.por_columnas(lambda h: ind.maximo(h, 180 * vd), g.H)
    hondura = 1.0 - g.C / maximo
    T = int(m.sum())
    filas = []
    for dias in (7, 30):
        h = dias * vd
        futuro = np.full(g.C.shape, np.nan)
        futuro[:T - h] = g.C[h:T] / g.C[:T - h] - 1.0           # el futuro no cruza la frontera del diseño
        for quien, cols in (("BTC", slice(0, 1)), ("alts", slice(1, None))):
            f = futuro[:, cols]
            cualquiera = np.nanmean(f)
            for a, b in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 1.0)):
                sel = (F[:, cols] <= 0) & (hondura[:, cols] >= a) & (hondura[:, cols] < b) & np.isfinite(f)
                if sel.sum() > 100:
                    x = f[sel]
                    filas.append({"días": dias, "quién": quien, "caída": f"{int(a * 100)}-{int(b * 100)} %",
                                  "medio_%": round(100 * x.mean(), 1), "gana_%": round(100 * (x > 0).mean()),
                                  "peor_%": round(100 * x.min()), "cualquier_momento_%": round(100 * cualquiera, 1)})
    return pd.DataFrame(filas)


if __name__ == "__main__":
    comun.configurar_pandas()
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    m = comun.mascara(g, hasta=comun.FIN_DISEÑO)
    texto = "\n".join([
        "=== DISEÑO 2020-2023 · rendimiento posterior según la nota (Sharpe anualizado de la vela siguiente) ===",
        por_tramos(g, p, m).to_string(), "",
        "=== DISEÑO · mapa nota → exposición ===", comun.con_anios(mapas(g, p, m)).to_string(), "",
        "=== DISEÑO · escalera en caídas (promediar a la baja con la tendencia en contra) ===",
        comun.con_anios(escaleras(g, p, m)).to_string(), "",
        "=== DISEÑO · qué pasa después de caer, con la tendencia en contra ===",
        despues_de_caer(g, p, m).to_string(index=False)])
    print(texto)
    lab.guardar("tamano_diseño.txt", texto)
