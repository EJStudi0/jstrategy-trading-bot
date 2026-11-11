"""Diseño (solo 2020-2023) de las tres jugadas intradía. Uso: python -m investigacion.intradia_diseno"""
import pickle
import pandas as pd
from investigacion import intradia as it
from investigacion.comun import FIN_DISEÑO

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
JUG = {"A ruptura": it.jugada_ruptura, "B rebote": it.jugada_rebote, "C zona": it.jugada_zona}
ops = {k: [] for k in JUG}
for nombre in it.MONEDAS:
    mon = it.cargar(nombre, hasta=FIN_DISEÑO)
    for k, f in JUG.items():
        df = it.simular(mon, f(mon)); df["adx"] = 0.0
        ops[k].append(df)
    print(nombre, "hecho", flush=True)
ops = {k: pd.concat(v, ignore_index=True) for k, v in ops.items()}
pickle.dump(ops, open("investigacion/salidas/intradia_diseno_base.pkl", "wb"))
for k, df in ops.items():
    print("\n==", k, it.resumen(df))
    print(pd.DataFrame({"largos": it.resumen(df[df.lado == 1]), "cortos": it.resumen(df[df.lado == -1])}).T)
    print(df.groupby(df.entra.dt.year).R.agg(["count", "mean", "sum"]).round(3).T)
    print(df.groupby("moneda").R.agg(["count", "mean"]).round(3).T)
    print(df.groupby(df.entra.dt.hour // 4 * 4).R.agg(["count", "mean"]).round(3).T)
    print(df.groupby(df.entra.dt.dayofweek).R.agg(["count", "mean"]).round(3).T)
    print(df.groupby("motivo").neto.agg(["count", "mean"]).round(4).T)
