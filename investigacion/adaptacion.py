"""¿Sirve que el bot se adapte a lo que le viene funcionando? Solo diseño.

«El mercado cambia»: la estrategia ya se adapta en lo que mide (tendencia, volatilidad y correlación
se recalculan en cada vela). Aquí se prueba el paso siguiente, que cambie ELLA MISMA según sus
resultados recientes:

  A. Dar más peso a los relojes que más aciertan últimamente, en vez de a partes iguales.
  B. Frenar: menos exposición cuando la propia estrategia viene perdiendo o lleva una caída.

Para B se mira la estrategia sin freno (una cartera sombra): con la frenada, parada, no habría
forma de saber cuándo volver.

Uso: python -m investigacion.adaptacion
"""
import itertools

import numpy as np
import pandas as pd

from bot import estrategia as est, indicadores as ind
from investigacion import comun, laboratorio as lab
from investigacion.tamano import nota_filtrada


def relojes(g, p) -> np.ndarray:
    """Los diez relojes por separado: reloj × tiempo × moneda, cada uno en {-1, 0, +1}."""
    vd = est.VELAS_DIA[p.intervalo]
    X = [lab.por_columnas(lambda c, a=a, b=b: np.sign(ind.ema(c, a * vd) - ind.ema(c, b * vd)), g.C)
         for a, b in p.cruces]
    X += [lab.por_columnas(lambda h, l, c, d=d: est._canal(h, l, c, int(round(d * vd))), g.H, g.L, g.C)
          for d in p.rupturas]
    X = np.nan_to_num(np.stack(X, axis=0))
    rodaje = int(round(p.rodaje_dias * vd))
    for j in range(g.C.shape[1]):
        idx = np.nonzero(~np.isnan(g.C[:, j]))[0]
        X[:, idx[:rodaje], j] = 0.0
    return X


def nota_adaptativa(g, p, memoria_dias: float, modo: str) -> np.ndarray:
    """Nota con los relojes pesados por su acierto de los últimos `memoria_dias` (solo lo ya ocurrido)."""
    vd = est.VELAS_DIA[p.intervalo]
    X = relojes(g, p)
    o = est.calcular(g.H, g.L, g.C, p)
    R = np.zeros(g.C.shape)
    R[1:] = g.C[1:] / g.C[:-1] - 1.0
    with np.errstate(divide="ignore", invalid="ignore"):
        Z = np.nan_to_num(R / (o.vol / np.sqrt(vd * 365.0)), posinf=0.0, neginf=0.0)
    # Acierto del reloj en la vela k: su señal de k-1 por lo que pasó en k. Se conoce al cierre de k.
    acierto = np.zeros((len(X), g.n))
    acierto[:, 1:] = (X[:, :-1, :] * Z[None, 1:, :]).sum(axis=2) / np.maximum((~np.isnan(g.C[1:])).sum(axis=1), 1)
    alfa = 2.0 / (memoria_dias * vd + 1.0)
    media = pd.DataFrame(acierto.T).ewm(alpha=alfa, adjust=False).mean().to_numpy().T
    desv = np.sqrt(pd.DataFrame((acierto ** 2).T).ewm(alpha=alfa, adjust=False).mean().to_numpy().T)
    calidad = media / np.maximum(desv, 1e-12)
    if modo == "solo los que ganan":
        w = np.maximum(calidad, 0.0)
    elif modo == "la mejor mitad":
        w = np.zeros_like(calidad)
        np.put_along_axis(w, np.argsort(-calidad, axis=0)[: len(X) // 2], 1.0, axis=0)
    else:
        w = np.exp(calidad * 30.0)
    total = w.sum(axis=0, keepdims=True)
    w = np.where(total > 0, w / np.maximum(total, 1e-12), 1.0 / len(X))
    return (X * w[:, :, None]).sum(axis=0)


def correr() -> str:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    m = comun.mascara(g, hasta=comun.FIN_DISEÑO)
    gd = g.recorte(None, comun.FIN_DISEÑO)
    vd = int(est.VELAS_DIA[p.intervalo])
    S, F, o = nota_filtrada(g, p)
    sim = lambda neto: lab.simular_cubierta(gd, o.base[m], neto[m], p.banda_base, p.banda_cobertura)
    res = {"tal cual (relojes a partes iguales, sin freno)": sim(o.neto)}

    for memoria, modo in itertools.product((60, 180, 365), ("solo los que ganan", "la mejor mitad", "suave")):
        Sn = nota_adaptativa(g, p, memoria, modo)
        Fn = Sn.copy()
        Fn[:, 1:] = np.where(Sn[:, [0]] > 0, Sn[:, 1:], np.minimum(Sn[:, 1:], 0.0))
        oo = est.calcular(g.H, g.L, g.C, p, ajuste_nota=Fn - F)
        res[f"A · relojes pesados: memoria de {memoria} d, {modo}"] = sim(oo.neto)

    sombra = lab.simular_cubierta(g, o.base, o.neto, p.banda_base, p.banda_cobertura).patrimonio
    for dias, piso in itertools.product((30, 90, 180), (0.0, 0.5)):
        n = dias * vd
        atras = np.concatenate([np.zeros(n), sombra[n:] / sombra[:-n] - 1.0])
        conocido = np.concatenate([[0.0], atras[:-1]])                 # lo ganado hasta la vela anterior
        freno = np.where(conocido >= 0, 1.0, piso)
        res[f"B · si pierde en {dias} d, exposición × {piso}"] = sim(o.neto * freno[:, None])
    for a, b in ((0.03, 0.10), (0.05, 0.15)):
        pico = pd.Series(sombra).rolling(365 * vd, min_periods=1).max().to_numpy()
        caida = np.concatenate([[0.0], (1.0 - sombra / pico)[:-1]])
        freno = np.clip(1.0 - (caida - a) / (b - a), 0.0, 1.0)
        res[f"B · freno por caída: empieza en −{int(a * 100)} %, a cero en −{int(b * 100)} %"] = sim(o.neto * freno[:, None])

    d = res["tal cual (relojes a partes iguales, sin freno)"].diario()
    lineas = ["=== DISEÑO 2020-2023 · ¿los resultados de un periodo dicen algo del siguiente? ==="]
    for nombre, regla in (("semana", "W"), ("mes", "ME"), ("trimestre", "QE")):
        x = np.expm1(np.log1p(d).resample(regla).sum())
        lineas.append(f"autocorrelación por {nombre}: {np.corrcoef(x[:-1], x[1:])[0, 1]:+.2f} "
                      f"(n = {len(x)}, error típico ± {1 / np.sqrt(len(x)):.2f})")
    lineas += ["", "=== DISEÑO 2020-2023 · adaptarse a lo que viene funcionando ===", comun.con_anios(res).to_string()]
    return "\n".join(lineas)


if __name__ == "__main__":
    comun.configurar_pandas()
    texto = correr()
    print(texto)
    lab.guardar("adaptacion_diseño.txt", texto)
