"""Inercia, segunda vuelta (solo diseño): stop que sigue, días de movimiento, cartera. python -m investigacion.intradia_inercia2"""
import itertools, pickle
import numpy as np, pandas as pd
from investigacion import intradia as it
from investigacion.comun import FIN_DISEÑO

pd.set_option("display.width", 250); pd.set_option("display.max_columns", 30); pd.set_option("display.max_rows", 200)
mons = [it.cargar(n, hasta=FIN_DISEÑO) for n in it.MONEDAS]


def medir(df):
    cur = it.cartera(df, riesgo=0.005, palanca_max=3.0, simultaneas=4)
    dia = cur.resample("1D").last().ffill()
    mes = dia.resample("ME").last().pct_change().dropna()
    anios = (dia.index[-1] - dia.index[0]).days / 365.25
    return {"cagr": round(100 * (dia.iloc[-1] ** (1 / anios) - 1), 1), "caida": round(100 * (dia / dia.cummax() - 1).min(), 1),
            "meses+": round(100 * (mes > 0).mean()), "peor_mes": round(100 * mes.min(), 1)}


filas, guard = [], {}
for ven, vol, mar, fondo in itertools.product((48, 96), (2.0, 2.5, 3.0), (1.0, 2.0), (True, False)):
    sen = {m.nombre: it.jugada_inercia(m, ventana=ven, volumen=vol, margen=mar, fondo=fondo) for m in mons}
    for seg, agu, mov in itertools.product((None, 2.0, 3.0, 5.0), (192, 384), (0.0, 1.0, 1.3)):
        df = pd.concat([it.simular(m, sen[m.nombre].donde(np.nan_to_num(sen[m.nombre].mov) >= mov), objetivo=99.0,
                                   aguante=agu, stop_max=0.06, seguir=seg) for m in mons], ignore_index=True)
        r = it.resumen(df)
        clave = dict(ven=ven, vol=vol, mar=mar, fondo=fondo, seg=seg or 0, agu=agu, mov=mov)
        filas.append({**clave, "n": r["n"], "acierto": r["acierto_pct"], "R": r["R_medio"], **medir(df),
                      **df.groupby(df.entra.dt.year).R.mean().round(2).to_dict(),
                      "L": round(df.R[df.lado == 1].mean(), 2), "C": round(df.R[df.lado == -1].mean(), 2)})
        guard[tuple(clave.values())] = df
t = pd.DataFrame(filas); t.to_csv("investigacion/salidas/intradia_inercia2.csv", index=False)
pickle.dump(guard, open("investigacion/salidas/intradia_inercia2.pkl", "wb"))
print(t.sort_values("R", ascending=False).head(15).to_string(index=False))
print("positivas:", (t.R > 0).sum(), "de", len(t), " mediana R:", t.R.median())
for c in ("ven", "vol", "mar", "fondo", "seg", "agu", "mov"):
    print(t.groupby(c)[["n", "R", "cagr", "caida", 2022, 2023]].mean().round(3).T.to_string())
