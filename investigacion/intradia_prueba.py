"""PRUEBA ÚNICA de la versión fijada en intradia_plan.md, con 2024 en adelante. No se repite ni se retoca."""
import numpy as np, pandas as pd
from investigacion import intradia as it
from investigacion.comun import FIN_DISEÑO

if __name__ == "__main__":
    corte = pd.Timestamp(FIN_DISEÑO, tz="UTC").value // 10**6
    ops = []
    for n in it.MONEDAS:
        m = it.cargar(n)  # todo el histórico, para que medias y fondo lleguen calentados
        s = it.jugada_inercia(m, ventana=96, volumen=2.5, margen=2.0, fondo=True)
        s = s.donde((np.nan_to_num(s.mov) >= 1.0) & (m.t[s.i] >= corte))
        ops.append(it.simular(m, s, objetivo=99.0, aguante=384, stop_max=0.06))
    df = pd.concat(ops, ignore_index=True)
    df.to_csv("investigacion/salidas/intradia_prueba.csv", index=False)
    print(it.resumen(df)); print(it.medir(df))
    print(df.groupby(df.entra.dt.year).R.agg(["count", "mean"]).round(2).T.to_string())
    print("largos", round(df.R[df.lado == 1].mean(), 2), "cortos", round(df.R[df.lado == -1].mean(), 2))
    print(df.groupby("moneda").R.mean().round(2).to_dict())
