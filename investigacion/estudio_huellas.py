"""¿Predicen algo las huellas de posicionamiento? Las diez monedas, periodo de diseño.

Uso: python -m investigacion.estudio_huellas
"""
import numpy as np
import pandas as pd

from investigacion import comun, huellas as hu, laboratorio as lab

# Lo que se esperaba de cada una ANTES de mirar (signo del rendimiento siguiente).
HIPOTESIS = {
    "fund_3d": "−", "fund_z": "−",
    "multitud_z": "−", "multitud_cambio_3d": "−",
    "grandes_z": "+", "grandes_ctas_z": "+", "gmm_z": "+",
    "oi_1d_z": "?", "oi_3d_z": "?", "purga": "+", "persecucion": "−",
    "flujo_1d_z": "+", "flujo_3d_z": "+", "absorcion": "−",
}
DESDE = "2022-01-15"       # las métricas de las alts empiezan en dic-2021 (más un mes de rodaje)


def tabla(g, reloj: str, desde: str, hasta) -> pd.DataFrame:
    P = hu.panel(g, reloj, list(HIPOTESIS))
    filas = []
    for nombre, signo in HIPOTESIS.items():
        fila = {"huella": nombre, "esperado": signo}
        for dias, velas in ((1, 6), (3, 18), (7, 42)):
            r = hu.poder_predictivo(g, P[nombre], velas, desde=desde, hasta=hasta)
            fila[f"{dias}d tiempo"] = f"{r['tiempo']:+.3f} ({r['t_tiempo']:+.1f})"
            fila[f"{dias}d corte"] = f"{r['corte']:+.3f} ({r['t_corte']:+.1f})"
        filas.append(fila)
    return pd.DataFrame(filas).set_index("huella")


if __name__ == "__main__":
    comun.configurar_pandas()
    g = lab.cuadricula("4h")
    texto = ["Correlación de rangos entre cada huella y el rendimiento de los días siguientes (t entre paréntesis).",
             "'tiempo': la huella de una moneda contra su propio futuro.  'corte': la moneda con más huella contra las demás.",
             "|t| > 2 = se distingue del azar. Diseño: ene-2022 → dic-2023.", ""]
    for reloj in ("instantaneo", "archivo"):
        texto += [f"=== reloj «{reloj}» ===", tabla(g, reloj, DESDE, comun.FIN_DISEÑO).to_string(), ""]
    salida = "\n".join(texto)
    print(salida)
    lab.guardar("huellas_diseño.txt", salida)
