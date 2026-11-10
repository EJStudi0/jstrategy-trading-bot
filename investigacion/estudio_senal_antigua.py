"""¿Predecía algo la señal del bot antiguo? Rendimiento medio tras cada señal frente a un momento cualquiera.

Uso: python -m investigacion.estudio_senal_antigua
"""
import os

import numpy as np
import pandas as pd

from bot import datos
from investigacion import laboratorio as lab

SALIDAS = os.path.join(datos.RAIZ, "investigacion", "salidas")
HORIZONTES = (4, 12, 24, 72, 168)      # horas
COSTE = 2 * lab.COSTE_POR_LADO         # entrar y salir


def episodios(mascara: np.ndarray, separacion: int) -> np.ndarray:
    """Primera vela de cada racha de señal (separadas al menos `separacion` velas)."""
    idx = np.nonzero(mascara)[0]
    out, ultimo = [], -10**9
    for i in idx:
        if i - ultimo >= separacion:
            out.append(i)
        ultimo = i
    return np.asarray(out, dtype=int)


def estudiar(simbolo: str) -> str:
    ruta = os.path.join(SALIDAS, f"senal_antigua_{simbolo}.npz")
    if not os.path.exists(ruta):
        return f"{simbolo}: sin calcular"
    z = np.load(ruta)
    v = datos.reagrupar(datos.cargar_velas(simbolo, "15m"), "1h")
    c = v.c
    i = z["i"]
    fechas = pd.to_datetime(v.t[i], unit="ms", utc=True)
    # Los mismos filtros que ponía el bucle en vivo encima de la señal.
    hora, dia = fechas.hour.to_numpy(), fechas.dayofweek.to_numpy()
    en_sesion = ((hora >= 22) | (hora < 4) | ((hora >= 7) & (hora < 10)) | ((hora >= 13) & (hora < 16))
                 | ((hora >= 17) & (hora < 21)))
    tipo = z["tipo"]
    largo = z["can_long"] & (dia < 5) & z["adx_trend"] & ~z["distrib"] & (z["regimen"] != 5) \
        & ~((tipo == 3) & z["sqz_on"]) & en_sesion
    corto = z["can_short_sa"] & (dia < 5) & en_sesion
    lineas = [f"── {simbolo}: {len(i)} velas de 1 h evaluadas ({fechas[0]:%Y-%m} → {fechas[-1]:%Y-%m})"]
    for nombre, masc, signo in (("LARGO, señal en bruto", z["can_long"], 1), ("LARGO, con los filtros del bot", largo, 1),
                                ("CORTO, señal en bruto", z["can_short_sa"], -1), ("CORTO, con los filtros del bot", corto, -1)):
        ep = episodios(masc, 24)
        lineas.append(f"  {nombre}: {int(masc.sum())} velas con señal, {len(ep)} entradas distintas "
                      f"({len(ep) / (len(i) / 8760):.1f} al año)")
        if len(ep) < 5:
            lineas.append("     demasiado pocas para medir nada")
            continue
        fila = []
        for h in HORIZONTES:
            j = i[ep]
            ok = j + h < len(c)
            r = signo * (c[j[ok] + h] / c[j[ok]] - 1) - COSTE
            # contra entrar en un momento cualquiera en la misma dirección
            todo = signo * (c[h:] / c[:-h] - 1) - COSTE
            t = r.mean() / (r.std(ddof=1) / np.sqrt(len(r))) if len(r) > 2 and r.std() > 0 else 0.0
            fila.append(f"{h:>3}h: {r.mean() * 100:+.2f}% (azar {todo.mean() * 100:+.2f}%, acierta {np.mean(r > 0) * 100:.0f}%, t={t:+.1f})")
        lineas.append("     " + " | ".join(fila))
    return "\n".join(lineas)


if __name__ == "__main__":
    texto = "\n".join(estudiar(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT"))
    texto += ("\n\nCómo leerlo: rendimiento medio tras la señal, ya descontadas comisiones de entrar y salir, frente a\n"
              "entrar en un momento cualquiera. |t| < 2 quiere decir que no se distingue del azar.")
    print(texto)
    lab.guardar("senal_antigua.txt", texto)
