"""Variantes de diseño (solo 2020-2023). Uso: python -m investigacion.intradia_variantes"""
import itertools
import pandas as pd
from investigacion import intradia as it
from investigacion.comun import FIN_DISEÑO

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 300)
JUG = {"A": it.jugada_ruptura, "B": it.jugada_rebote, "C": it.jugada_zona}
mons = [it.cargar(n, hasta=FIN_DISEÑO) for n in it.MONEDAS]
sen = {(k, m.nombre): f(m) for k, f in JUG.items() for m in mons}
filas = []
for k in JUG:
    for obj, agu, adx, hor, lab in itertools.product((1.0, 1.5, 2.5), (24, 64), (0, 23, 30),
                                                     (None, (7, 16)), (False, True)):
        df = pd.concat([it.simular(m, sen[(k, m.nombre)], objetivo=obj, aguante=agu, adx_min=adx,
                                   horas=hor, laborables=lab) for m in mons], ignore_index=True)
        r = it.resumen(df)
        bruto = (df.neto + 0.0008).mean() / df.riesgo.mean() if len(df) else 0  # ~sin comisiones
        porA = df.groupby(df.entra.dt.year).R.mean().round(2).to_dict() if len(df) else {}
        filas.append({"j": k, "obj": obj, "agu": agu, "adx": adx, "hor": bool(hor), "lab": lab,
                      "n": r["n"], "acierto": r.get("acierto_pct"), "R": r.get("R_medio"),
                      "R_sin_com": round(bruto, 3), **porA})
t = pd.DataFrame(filas)
t.to_csv("investigacion/salidas/intradia_variantes.csv", index=False)
for k in JUG:
    print(t[t.j == k].sort_values("R", ascending=False).head(8).to_string(index=False))
    print("   mediana R:", t[t.j == k].R.median(), " peor:", t[t.j == k].R.min(), " positivas:", (t[t.j == k].R > 0).sum(), "de", (t.j == k).sum())
