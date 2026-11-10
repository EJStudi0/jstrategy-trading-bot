"""Baja los datos de posicionamiento y flujo. Uso: python -m investigacion.descargar_huellas"""
import time

import numpy as np
import pandas as pd

from bot import datos
from investigacion.laboratorio import UNIVERSO

if __name__ == "__main__":
    for s in UNIVERSO:
        t0 = time.time()
        f = datos.descargar_flujo(s)
        m = datos.descargar_metricas(s, desde="2020-09-01" if s in ("BTCUSDT", "ETHUSDT") else "2021-12-01")
        d = pd.to_datetime(m["t"], unit="ms")
        print(f"{s:9s} flujo {len(f['t']):6d} h | métricas {len(m['t']):6d} h  {d[0]:%Y-%m-%d} → {d[-1]:%Y-%m-%d}  "
              f"huecos OI {int(np.isnan(m['oi']).sum())}  {time.time() - t0:.0f}s", flush=True)
