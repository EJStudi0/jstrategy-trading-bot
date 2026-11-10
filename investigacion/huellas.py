"""Huellas de los grandes: posicionamiento y flujo como predictores.

Datos públicos de Binance (ver `bot.datos.descargar_metricas` y `descargar_flujo`):
interés abierto, largo/corto de los traders grandes y de la multitud, quién compra
a mercado, y la financiación.

Cada huella se convierte en una serie por moneda, CAUSAL, y se mira si predice el
rendimiento de los días siguientes. Dos relojes:

  "instantaneo"  el dato se conoce al cerrar la hora. Exige leer la API de Binance
                 en vivo, que desde este servidor responde 451.
  "archivo"      el dato llega por el volcado diario, que Binance publica hacia las
                 07:30 UTC del día siguiente. Es lo que el bot puede usar hoy.

Una huella solo sirve si aguanta con el reloj "archivo".
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from bot import datos
from investigacion import laboratorio as lab

HORA = datos.MS["1h"]
DIA = datos.MS["1d"]
RETRASO_ARCHIVO_H = 8          # el volcado del día D está disponible desde D+1 08:00 UTC


def _zscore(x: pd.Series, horas: int) -> pd.Series:
    m = x.rolling(horas, min_periods=horas // 3).mean()
    s = x.rolling(horas, min_periods=horas // 3).std()
    return (x - m) / s.replace(0, np.nan)


def _cuota(ratio: pd.Series) -> pd.Series:
    """Ratio largo/corto → fracción en largo, entre 0 y 1."""
    return ratio / (1.0 + ratio)


def series_horarias(simbolo: str) -> pd.DataFrame:
    """Huellas de una moneda en rejilla de 1 h. Índice = apertura de la hora (ms)."""
    v = datos.reagrupar(datos.cargar_velas(simbolo, "15m"), "1h")
    df = pd.DataFrame({"c": v.c}, index=v.t)
    f = datos.descargar_flujo(simbolo)
    df = df.join(pd.DataFrame({"v": f["v"], "v_compra": f["v_compra"]}, index=f["t"]))
    try:
        m = datos.descargar_metricas(simbolo)
        df = df.join(pd.DataFrame({k: m[k] for k in m if k != "t"}, index=m["t"]))
    except Exception:
        for k in ("oi", "oi_valor", "top_cuentas", "top_posiciones", "global_cuentas", "taker"):
            df[k] = np.nan
    ft, fr = datos.descargar_funding(simbolo)
    fund = pd.Series(fr, index=(ft // HORA) * HORA)
    fund = fund[~fund.index.duplicated()]
    df["fund"] = fund.reindex(df.index).fillna(0.0)

    r24 = np.log(df["c"] / df["c"].shift(24))
    r72 = np.log(df["c"] / df["c"].shift(72))
    vol = np.log(df["c"]).diff().rolling(24 * 30, min_periods=240).std() * np.sqrt(24)
    out = pd.DataFrame(index=df.index)

    # Financiación: media de los últimos 3 y 7 días, anualizada.
    out["fund_3d"] = df["fund"].rolling(72).sum() / 3.0 * 365.0
    out["fund_7d"] = df["fund"].rolling(168).sum() / 7.0 * 365.0
    out["fund_z"] = _zscore(out["fund_3d"], 24 * 90)

    # Posicionamiento: la multitud y los grandes.
    multitud = _cuota(df["global_cuentas"])
    grandes = _cuota(df["top_posiciones"])
    grandes_ctas = _cuota(df["top_cuentas"])
    out["multitud"] = multitud
    out["multitud_z"] = _zscore(multitud, 24 * 30)
    out["grandes_z"] = _zscore(grandes, 24 * 30)
    out["grandes_ctas_z"] = _zscore(grandes_ctas, 24 * 30)
    out["grandes_menos_multitud"] = grandes - multitud
    out["gmm_z"] = _zscore(grandes - multitud, 24 * 30)
    out["multitud_cambio_3d"] = multitud - multitud.shift(72)

    # Interés abierto: cuánta posición apalancada entra o sale.
    loi = np.log(df["oi"].where(df["oi"] > 0))
    out["oi_1d"] = loi - loi.shift(24)
    out["oi_3d"] = loi - loi.shift(72)
    out["oi_1d_z"] = _zscore(out["oi_1d"], 24 * 30)
    out["oi_3d_z"] = _zscore(out["oi_3d"], 24 * 30)
    # Purga: sale mucha posición mientras el precio cae (liquidaciones).
    out["purga"] = (-out["oi_1d_z"]).clip(lower=0) * (-(r24 / vol)).clip(lower=0)
    # Persecución: entra mucha posición mientras el precio sube.
    out["persecucion"] = out["oi_3d_z"].clip(lower=0) * (r72 / (vol * np.sqrt(3))).clip(lower=0)

    # Flujo: quién toma la iniciativa.
    compra_24 = df["v_compra"].rolling(24).sum() / df["v"].rolling(24).sum()
    compra_72 = df["v_compra"].rolling(72).sum() / df["v"].rolling(72).sum()
    out["flujo_1d_z"] = _zscore(compra_24, 24 * 30)
    out["flujo_3d_z"] = _zscore(compra_72, 24 * 30)
    # Absorción: compran con prisa y el precio no avanza (alguien grande vende enfrente), o al revés.
    out["absorcion"] = out["flujo_1d_z"] - _zscore(r24, 24 * 30)

    out["ret_1d"] = r24
    out["ret_3d"] = r72
    out["vol"] = vol
    return out


def panel(g: lab.Cuadricula, reloj: str = "archivo", columnas: Optional[list] = None) -> dict:
    """Huellas muestreadas en la cuadrícula de la estrategia: {nombre: matriz tiempo × moneda}."""
    cierres = g.t + datos.MS[g.intervalo]
    if reloj == "archivo":
        # Último día completo cuyo volcado ya está publicado.
        corte = ((cierres - RETRASO_ARCHIVO_H * HORA) // DIA) * DIA
    elif reloj == "instantaneo":
        corte = cierres
    else:
        raise ValueError(reloj)
    out: dict = {}
    for j, s in enumerate(g.simbolos):
        h = series_horarias(s)
        fin_hora = h.index.to_numpy(np.int64) + HORA
        idx = np.searchsorted(fin_hora, corte, side="right") - 1
        ok = idx >= 0
        for col in (columnas or h.columns):
            m = out.setdefault(col, np.full((g.n, len(g.simbolos)), np.nan))
            vals = h[col].to_numpy()
            m[ok, j] = vals[idx[ok]]
    return out


def rendimiento_futuro(g: lab.Cuadricula, velas: int) -> np.ndarray:
    """Rendimiento de las `velas` siguientes a cada cierre."""
    F = np.full_like(g.C, np.nan)
    F[:-velas] = g.C[velas:] / g.C[:-velas] - 1.0
    return F


def _spearman(a: np.ndarray, b: np.ndarray) -> float:
    ok = np.isfinite(a) & np.isfinite(b)
    if ok.sum() < 30:
        return np.nan
    ra = pd.Series(a[ok]).rank().to_numpy()
    rb = pd.Series(b[ok]).rank().to_numpy()
    return float(np.corrcoef(ra, rb)[0, 1])


def poder_predictivo(g: lab.Cuadricula, X: np.ndarray, velas: int, desde=None, hasta=None) -> dict:
    """Correlación de rangos entre la huella y el rendimiento siguiente, sin solapar.

    'tiempo':   ¿la huella de una moneda predice SU rendimiento? (media de las correlaciones
                moneda a moneda, cada una sobre muestras separadas `velas`)
    'corte':    ¿la moneda con más huella rinde más que las demás EN ESE MOMENTO?
    't_*':      estadístico t aproximado de cada una.
    """
    F = rendimiento_futuro(g, velas)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    filas = np.nonzero(m)[0][::velas]            # sin solapes
    Xs, Fs = X[filas], F[filas]
    por_moneda = [_spearman(Xs[:, j], Fs[:, j]) for j in range(X.shape[1])]
    por_moneda = np.array([c for c in por_moneda if np.isfinite(c)])
    cortes = []
    for i in range(len(filas)):
        ok = np.isfinite(Xs[i]) & np.isfinite(Fs[i])
        if ok.sum() >= 5:
            cortes.append(_spearman_corto(Xs[i][ok], Fs[i][ok]))
    cortes = np.array(cortes)
    n_t = int(np.isfinite(Xs).all(axis=1).sum()) if X.shape[1] == 1 else int(np.isfinite(Xs).any(axis=1).sum())
    ic_t = float(np.mean(por_moneda)) if len(por_moneda) else np.nan
    # Las monedas se mueven juntas: la incertidumbre de 'tiempo' es la de UNA serie, no la de diez.
    t_t = ic_t * np.sqrt(max(n_t - 2, 1)) if np.isfinite(ic_t) else np.nan
    ic_c = float(np.mean(cortes)) if len(cortes) else np.nan
    t_c = ic_c / (np.std(cortes, ddof=1) / np.sqrt(len(cortes))) if len(cortes) > 5 and np.std(cortes) > 0 else np.nan
    return {"tiempo": ic_t, "t_tiempo": t_t, "corte": ic_c, "t_corte": t_c, "muestras": n_t}


def _spearman_corto(a: np.ndarray, b: np.ndarray) -> float:
    ra = np.argsort(np.argsort(a)).astype(float)
    rb = np.argsort(np.argsort(b)).astype(float)
    if ra.std() == 0 or rb.std() == 0:
        return 0.0
    return float(np.corrcoef(ra, rb)[0, 1])


def por_quintiles(g: lab.Cuadricula, X: np.ndarray, velas: int, desde=None, hasta=None) -> pd.DataFrame:
    """Rendimiento medio siguiente según el quintil de la huella (cada moneda contra su propia historia)."""
    F = rendimiento_futuro(g, velas)
    m = np.ones(g.n, dtype=bool)
    if desde:
        m &= g.t >= datos._a_ms(desde)
    if hasta:
        m &= g.t < datos._a_ms(hasta)
    filas = np.nonzero(m)[0][::velas]
    acum = {q: [] for q in range(5)}
    for j in range(X.shape[1]):
        x, f = X[filas, j], F[filas, j]
        ok = np.isfinite(x) & np.isfinite(f)
        if ok.sum() < 50:
            continue
        q = pd.qcut(pd.Series(x[ok]).rank(method="first"), 5, labels=False).to_numpy()
        for k in range(5):
            acum[k].extend(f[ok][q == k])
    filas_out = []
    for k in range(5):
        a = np.array(acum[k])
        filas_out.append({"quintil": k + 1, "rend_medio_pct": round(float(a.mean()) * 100, 2) if len(a) else np.nan,
                          "acierta_pct": round(float((a > 0).mean()) * 100, 0) if len(a) else np.nan, "n": len(a)})
    return pd.DataFrame(filas_out).set_index("quintil")


def prima_coinbase(g: lab.Cuadricula, producto: str = "BTC-USD", contado: str = "BTCUSDT") -> dict:
    """Prima de Coinbase sobre el contado de Binance, muestreada en la cuadrícula (vector por vela).

    Coinbase cotiza en dólares y su clientela es de EE. UU. (fondos, ETF, empresas);
    Binance cotiza en USDT y es el resto del mundo. Cuando en Coinbase se paga más,
    es que la presión compradora viene de allí. Dato en vivo: no depende de Binance.
    """
    cb = datos.descargar_coinbase(producto)
    sp = datos.descargar_contado_binance(contado)
    a = pd.Series(cb.c, index=cb.t)
    b = pd.Series(sp.c, index=sp.t)
    prima = (np.log(a) - np.log(b)).dropna() * 1e4           # puntos básicos
    h = pd.DataFrame({"prima": prima})
    h["prima_1d"] = h["prima"].rolling(24, min_periods=12).mean()
    h["prima_3d"] = h["prima"].rolling(72, min_periods=36).mean()
    h["prima_7d"] = h["prima"].rolling(168, min_periods=84).mean()
    h["prima_1d_z"] = _zscore(h["prima_1d"], 24 * 30)
    h["prima_3d_z"] = _zscore(h["prima_3d"], 24 * 90)
    h["prima_giro"] = h["prima_1d"] - h["prima_7d"]
    cierres = g.t + datos.MS[g.intervalo]
    fin_hora = h.index.to_numpy(np.int64) + HORA
    idx = np.searchsorted(fin_hora, cierres, side="right") - 1
    viejo = (cierres - fin_hora[np.maximum(idx, 0)]) > 6 * HORA      # dato rancio (hueco): no vale
    out = {}
    for col in h.columns:
        x = np.where((idx >= 0) & ~viejo, h[col].to_numpy()[np.maximum(idx, 0)], np.nan)
        out[col] = x
    return out
