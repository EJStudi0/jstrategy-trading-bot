"""Baja el histórico que usa la investigación. Uso: python -m investigacion.descargar"""
import sys
import time

from bot import datos

UNIVERSO = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT",
            "DOGEUSDT", "ADAUSDT", "AVAXUSDT", "LINKUSDT", "LTCUSDT"]


def main(intervalo: str = "15m") -> None:
    for s in UNIVERSO:
        t0 = time.time()
        v = datos.descargar_velas(s, intervalo)
        ft, fr = datos.descargar_funding(s)
        hs = datos.huecos(v)
        f = v.fechas()
        print(f"{s:9s} {len(v):7d} velas {intervalo}  {f[0]:%Y-%m-%d} → {f[-1]:%Y-%m-%d %H:%M}  "
              f"huecos={len(hs)} (faltan {sum(n for _, n in hs)})  funding={len(ft)}  "
              f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(*sys.argv[1:])
