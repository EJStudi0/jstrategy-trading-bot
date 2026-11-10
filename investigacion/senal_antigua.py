"""Recalcula la señal del bot antiguo sobre todo el histórico, vela a vela.

Usa las funciones del propio `04_SCRIPT_BOT_PYTHON.py` (no una copia), pero
dándoles SOLO velas cerradas: su backtest original filtraba las velas de 4 h y
diarias por hora de apertura, con lo que la vela en curso entraba con su cierre
definitivo — es decir, con información del futuro.

Uso: python -m investigacion.senal_antigua BTCUSDT [max_velas]
Salida: investigacion/salidas/senal_antigua_<SIMBOLO>.npz
"""
import importlib.util
import os
import sys
import tempfile
import time

import numpy as np
import pandas as pd

from bot import datos

RAIZ = datos.RAIZ
SALIDAS = os.path.join(RAIZ, "investigacion", "salidas")


def cargar_modulo_antiguo():
    # Al importarse abre `jorge_bot.log` en el directorio actual: que sea uno desechable.
    aqui = os.getcwd()
    os.chdir(tempfile.mkdtemp(prefix="jorge_antiguo_"))
    try:
        spec = importlib.util.spec_from_file_location(
            "bot_antiguo", os.path.join(RAIZ, "04_SCRIPT_BOT_PYTHON.py"))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    finally:
        os.chdir(aqui)
    import logging
    logging.getLogger().setLevel(logging.ERROR)
    return mod


def a_frame(v: datos.Velas) -> pd.DataFrame:
    df = pd.DataFrame({"open": v.o, "high": v.h, "low": v.l, "close": v.c, "volume": v.v},
                      index=pd.to_datetime(v.t, unit="ms"))
    df.index.name = "timestamp"
    return df


def main(simbolo: str, max_velas: int = 0) -> None:
    os.makedirs(SALIDAS, exist_ok=True)
    viejo = cargar_modulo_antiguo()
    cfg = dict(viejo.CONFIG)
    cfg["structural_break_enabled"] = False

    base = datos.cargar_velas(simbolo, "15m")
    v1h, v4h, v1d = (datos.reagrupar(base, tf) for tf in ("1h", "4h", "1d"))
    t0 = time.time()
    d1h, d4h, d1d = (viejo._add_all_indicators(a_frame(v)) for v in (v1h, v4h, v1d))
    print(f"indicadores listos en {time.time() - t0:.0f}s", flush=True)

    cierre_4h = v4h.t + v4h.ms
    cierre_1d = v1d.t + v1d.ms
    n = len(v1h)
    ini = 60 * 24  # 60 días de rodaje
    fin = n if not max_velas else min(n, ini + max_velas)
    VENT = 400

    campos = ["score", "score_adj", "can_long", "tipo", "can_short_sa", "score_short_adj",
              "can_short", "regimen", "adx_trend", "sqz_on", "distrib", "stop_long", "stop_short"]
    out = {k: [] for k in campos}
    idx = []
    tipos = {"none": 0, "A": 1, "B": 2, "C": 3}
    regs = {"warmup": 0, "expansion": 1, "trending": 2, "ranging": 3, "exhaustion": 4, "quiet": 5}
    t0 = time.time()
    for i in range(ini, fin):
        T = v1h.t[i] + v1h.ms
        j4 = int(np.searchsorted(cierre_4h, T, side="right"))
        jd = int(np.searchsorted(cierre_1d, T, side="right"))
        if j4 < 60 or jd < 60:
            continue
        de = d1h.iloc[max(0, i + 1 - VENT):i + 1]
        dmi = d4h.iloc[max(0, j4 - VENT):j4]
        dm = d1d.iloc[max(0, jd - VENT):jd]
        try:
            s = viejo.evaluate_signal(dm, dmi, de, cfg)
        except Exception:
            continue
        idx.append(i)
        out["score"].append(s["score"])
        out["score_adj"].append(s["score_adjusted"])
        out["can_long"].append(bool(s["can_long"]))
        out["tipo"].append(tipos.get(s["entry_type"], 0))
        out["can_short_sa"].append(bool(s["can_short_standalone"]))
        out["score_short_adj"].append(s["score_short_adjusted"])
        out["can_short"].append(bool(s["can_short"]))
        out["regimen"].append(regs.get(s["regime"], 0))
        out["adx_trend"].append(bool(s["adx"]["trend"]))
        out["sqz_on"].append(bool(s["squeeze_on"]))
        out["distrib"].append(bool(s["distribution_warning"]))
        out["stop_long"].append(s["dynamic_stop_long"] or np.nan)
        out["stop_short"].append(s["dynamic_stop_short"] or np.nan)
        if len(idx) % 5000 == 0:
            hecho = len(idx)
            print(f"  {hecho}/{fin - ini}  {time.time() - t0:.0f}s", flush=True)

    idx = np.asarray(idx)
    np.savez_compressed(os.path.join(SALIDAS, f"senal_antigua_{simbolo}.npz"),
                        i=idx, t=v1h.t[idx], c=v1h.c[idx],
                        **{k: np.asarray(v) for k, v in out.items()})
    print(f"{simbolo}: {len(idx)} velas evaluadas en {time.time() - t0:.0f}s | "
          f"can_long={int(np.sum(out['can_long']))} can_short_sa={int(np.sum(out['can_short_sa']))}")


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
