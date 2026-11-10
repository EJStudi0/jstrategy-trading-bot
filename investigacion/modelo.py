"""Un modelo que combina todas las huellas a la vez (regresión con contracción fuerte).

Por separado, las huellas son débiles. La pregunta es si juntas dicen algo. Para no engañarse:

  1. Dentro del DISEÑO (ene-2022 → dic-2023) se ajusta con un año y se mide con el otro, en
     los dos sentidos. Si ahí la predicción no se distingue del azar, se acaba: no se mira
     la validación.
  2. Solo si pasa, se ajusta con todo el diseño y se prueba una vez con 2024 en adelante,
     sumada a la nota de tendencia con el mismo peso que las demás candidatas (0,15).

Objetivo: rendimiento de los 3 días siguientes, en desviaciones típicas.
Uso: python -m investigacion.modelo [diseño|validacion]
"""
import sys

import numpy as np
import pandas as pd

from bot import datos, estrategia as est, indicadores as ind
from investigacion import comun, huellas as hu, laboratorio as lab
from investigacion.financiacion_relativa import amontonamiento

HORIZONTE = 18                    # velas de 4 h = 3 días
PESO = 0.15
INICIO = "2022-01-15"
MITAD = "2023-01-01"
HUELLAS = ["fund_z", "multitud_z", "grandes_ctas_z", "gmm_z", "oi_3d_z", "purga", "persecucion",
           "flujo_1d_z", "absorcion"]
LAMBDAS = (1e2, 1e3, 1e4, 1e5)


def caracteristicas(g: lab.Cuadricula, p: est.Parametros):
    """Tensor (tiempo, moneda, característica), todo causal y con el reloj «archivo»."""
    vd = est.VELAS_DIA[p.intervalo]
    S = lab.por_columnas(lambda h, l, c: est.puntuacion(h, l, c, vd, p), g.H, g.L, g.C)
    vol = lab.por_columnas(lambda c: ind.volatilidad_ewma(c, 30 * vd, vd * 365), g.C)

    def tiron(dias):
        n = int(dias * vd)
        r = np.full_like(g.C, np.nan)
        r[n:] = g.C[n:] / g.C[:-n] - 1
        return np.clip(r / (vol * np.sqrt(dias / 365)), -3, 3)

    vol_rel = lab.por_columnas(lambda v: v / pd.Series(v).rolling(int(90 * vd), min_periods=int(30 * vd)).mean().to_numpy() - 1, vol)
    P = hu.panel(g, "archivo", HUELLAS)
    nombres = ["tendencia", "tiron_1d", "tiron_3d", "vol_relativa", "financiacion_vs_resto"] + HUELLAS
    capas = [S, tiron(1), tiron(3), np.clip(vol_rel, -3, 3), amontonamiento(g)] + [np.clip(P[k], -4, 4) for k in HUELLAS]
    X = np.stack(capas, axis=2)
    Y = hu.rendimiento_futuro(g, HORIZONTE) / (vol * np.sqrt(3 / 365))
    return X, np.clip(Y, -5, 5), nombres


def ajustar(X, Y, filas, lam):
    """Regresión con contracción (ridge), todas las monedas juntas. Devuelve (media, desv, coeficientes)."""
    x = X[filas].reshape(-1, X.shape[2])
    y = Y[filas].reshape(-1)
    ok = np.isfinite(x).all(axis=1) & np.isfinite(y)
    x, y = x[ok], y[ok]
    mu, sd = x.mean(axis=0), x.std(axis=0)
    sd[sd == 0] = 1.0
    z = (x - mu) / sd
    beta = np.linalg.solve(z.T @ z + lam * np.eye(z.shape[1]), z.T @ (y - y.mean()))
    return mu, sd, beta, int(ok.sum())


def predecir(X, modelo) -> np.ndarray:
    mu, sd, beta, _ = modelo
    z = (X - mu) / sd
    pred = np.where(np.isfinite(z).all(axis=2), np.nan_to_num(z) @ beta, np.nan)
    return pred


def filas_entre(g, desde, hasta) -> np.ndarray:
    m = (g.t >= datos._a_ms(desde)) & (g.t < datos._a_ms(hasta))
    return np.nonzero(m)[0]


def diseño() -> tuple:
    p = est.Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    X, Y, nombres = caracteristicas(g, p)
    # Entre el tramo de ajuste y el de medida se deja un hueco del horizonte: el objetivo mira 3 días adelante.
    a = filas_entre(g, INICIO, MITAD)[:-HORIZONTE]
    b = filas_entre(g, MITAD, comun.FIN_DISEÑO)[:-HORIZONTE]
    lineas = ["=== Dentro del diseño: se ajusta con un año y se mide con el otro ===",
              "correlación de rangos entre lo predicho y lo ocurrido a 3 días (t entre paréntesis); |t| > 2 = distinto del azar", ""]
    filas = []
    mejor = None
    for lam in LAMBDAS:
        fila = {"contracción": f"{lam:.0e}"}
        notas = []
        for nombre, entreno, prueba, d, h in (("ajusta 2022 → mide 2023", a, b, MITAD, comun.FIN_DISEÑO),
                                              ("ajusta 2023 → mide 2022", b, a, INICIO, MITAD)):
            pred = predecir(X, ajustar(X, Y, entreno, lam))
            r = hu.poder_predictivo(g, pred, HORIZONTE, desde=d, hasta=h)
            fila[nombre + " · tiempo"] = f"{r['tiempo']:+.3f} ({r['t_tiempo']:+.1f})"
            fila[nombre + " · corte"] = f"{r['corte']:+.3f} ({r['t_corte']:+.1f})"
            notas += [r["t_tiempo"], r["t_corte"]]
        filas.append(fila)
        peor = min(max(notas[0], notas[1]), max(notas[2], notas[3]))    # el mejor de cada sentido, y de esos el peor
        if mejor is None or peor > mejor[0]:
            mejor = (peor, lam)
    lineas.append(pd.DataFrame(filas).set_index("contracción").to_string())
    lineas += ["", "(Los ratios de los traders grandes solo existen desde finales de 2022: en 2022 hay dato en el 7 % de",
               " las velas, y por eso al medir sobre 2022 falta 'tiempo' y 'corte' sale de muy pocas muestras.)"]
    pasa = mejor[0] >= 2.0
    lineas += ["", f"Listón: en los DOS sentidos, la predicción debe distinguirse del azar (t ≥ 2). "
                   f"Mejor caso: t = {mejor[0]:+.1f} con contracción {mejor[1]:.0e} → {'PASA' if pasa else 'NO PASA'}."]
    modelo = ajustar(X, Y, np.concatenate([a, b]), mejor[1])
    lineas += ["", "Coeficientes del ajuste con todo el diseño (por desviación típica de cada característica):",
               pd.Series(modelo[2], index=nombres).round(4).sort_values().to_string()]
    return "\n".join(lineas), pasa, (g, p, X, modelo)


def simular_con_modelo(g, p, X, modelo, desde, hasta) -> dict:
    pred = predecir(X, modelo)
    escala = np.nanstd(pred[filas_entre(g, INICIO, comun.FIN_DISEÑO)])
    Z = np.clip(np.nan_to_num(pred / escala), -2, 2)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    gg = g.recorte(desde, hasta)
    res = {}
    for nombre, peso in (("principal (lo que corre hoy)", 0.0), (f"CON EL MODELO, peso {PESO}", PESO), ("control: el modelo AL REVÉS", -PESO)):
        o = est.calcular(g.H, g.L, g.C, p, ajuste_nota=peso * Z if peso else None)
        res[nombre] = lab.simular_cubierta(gg, o.base[m], o.neto[m], p.banda_base, p.banda_cobertura)
    return res


if __name__ == "__main__":
    comun.configurar_pandas()
    que = sys.argv[1] if len(sys.argv) > 1 else "diseño"
    texto, pasa, (g, p, X, modelo) = diseño()
    cols = ["cagr_pct", "vol_pct", "sharpe", "max_dd_pct", "rotacion_anual", "coste_anual_pct", "neto_medio"]
    if que == "validacion":
        if not pasa:
            sys.exit(texto + "\n\nNo pasó el listón del diseño: la validación NO se mira.")
        res = simular_con_modelo(g, p, X, modelo, comun.FIN_DISEÑO, None)
        texto += "\n\n=== VALIDACIÓN 2024-01 → 2026-11 ===\n" + lab.tabla(res, cols).to_string()
        texto += "\n" + pd.DataFrame({k: r.por_anio()["rend_pct"] for k, r in res.items()}).T.to_string()
    print(texto)
    lab.guardar(f"modelo_{que}.txt", texto)
