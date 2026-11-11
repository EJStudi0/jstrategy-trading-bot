"""Ruptura a mercado, sin esperar el retroceso (inercia). Solo diseño. Uso: python -m investigacion.intradia_inercia"""
import itertools, dataclasses
import numpy as np, pandas as pd
from investigacion import intradia as it
from investigacion.comun import FIN_DISEÑO

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30)
mons = [it.cargar(n, hasta=FIN_DISEÑO) for n in it.MONEDAS]
filas = []
for ven, est, vol, mar in itertools.product((16, 48), (3.0, 99.0), (1.5, 2.5), (1.0, 2.0)):
    sen = {}
    for m in mons:
        s = it.jugada_ruptura(m, ventana=ven, estrechez=est, volumen=vol, margen=mar)
        sen[m.nombre] = dataclasses.replace(s, nivel=np.full(len(s.i), np.nan), vida=np.ones(len(s.i), int))
    for obj, agu in ((1.5, 24), (3.0, 96), (99.0, 96), (99.0, 192)):
        df = pd.concat([it.simular(m, sen[m.nombre], objetivo=obj, aguante=agu, stop_max=0.06) for m in mons], ignore_index=True)
        r = it.resumen(df)
        filas.append({"ven": ven, "est": est, "vol": vol, "mar": mar, "obj": obj, "agu": agu, "n": r["n"],
                      "acierto": r.get("acierto_pct"), "R": r.get("R_medio"), "neto%": r.get("neto_medio_pct"),
                      **(df.groupby(df.entra.dt.year).R.mean().round(2).to_dict() if len(df) else {})})
t = pd.DataFrame(filas); t.to_csv("investigacion/salidas/intradia_inercia.csv", index=False)
print(t.sort_values("R", ascending=False).head(12).to_string(index=False))
print("mediana R:", t.R.median(), "positivas:", (t.R > 0).sum(), "de", len(t))
