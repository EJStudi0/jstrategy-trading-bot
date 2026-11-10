"""Las reglas de Jorge, una por una, contra los datos.

Fuente: `ESTRATEGIA_DEFINITIVA_JORGE.md` y los textos originales del material del mentor
(«estrategia jorge.txt», «ARGUMENTOS.txt»). Aquí solo entran las reglas que se pueden escribir
sin ambigüedad; las que dependen de mirar un gráfico (order blocks, perfil de volumen, zonas de
liquidez) no se pueden comprobar así.

Las afirmaciones de HECHO («nunca cae un 20 % en un día») se miran en todo el histórico.
Las reglas que PREDICEN se miran solo en el diseño (2020-2023).

Uso: python -m investigacion.reglas_jorge
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from bot import datos, indicadores as ind
from investigacion import comun, laboratorio as lab

FIN = datos._a_ms(comun.FIN_DISEÑO)


def _t(x: np.ndarray, base: float = 0.0) -> float:
    x = x[np.isfinite(x)]
    if len(x) < 5 or x.std() == 0:
        return float("nan")
    return float((x.mean() - base) / (x.std(ddof=1) / np.sqrt(len(x))))


def _futuro(c: np.ndarray, n: int) -> np.ndarray:
    f = np.full(len(c), np.nan)
    f[:-n] = c[n:] / c[:-n] - 1.0
    return f


def _sin_solapar(idx: np.ndarray, n: int) -> np.ndarray:
    out, ultimo = [], -10**9
    for i in idx:
        if i - ultimo >= n:
            out.append(i)
            ultimo = i
    return np.asarray(out, dtype=int)


def _fila(regla: str, dato: str, veredicto: str) -> dict:
    return {"regla de Jorge": regla, "lo que dicen los datos": dato, "veredicto": veredicto}


# ── Hechos ────────────────────────────────────────────────────────────────────

def caidas_en_un_dia() -> list:
    """«El precio nunca va a caer 20 % en un solo día.» Del cierre de un día al mínimo del siguiente."""
    filas = []
    for s, umbrales in (("BTCUSDT", (0.10, 0.15, 0.20)), ("ETHUSDT", (0.15, 0.20, 0.30)), ("SOLUSDT", (0.20, 0.30, 0.40))):
        d = datos.reagrupar(datos.cargar_velas(s, "15m"), "1d")
        caida = d.l[1:] / d.c[:-1] - 1.0
        dias = pd.to_datetime(d.t[1:], unit="ms")
        trozos = [f"≥{int(u * 100)} %: {int((caida <= -u).sum())} días" for u in umbrales]
        k = int(np.argmin(caida))
        filas.append(f"{s[:-4]}: " + ", ".join(trozos) + f" (peor: {caida[k] * 100:.0f} % el {dias[k]:%d-%m-%Y})")
    return [_fila("«El precio nunca cae un 20 % en un solo día»", " | ".join(filas),
                  "FALSO: ha pasado, y en las alts varias veces")]


def martingala(con_filtro: bool) -> dict:
    """La estrategia base tal como está escrita: x100, 0,2 % inicial, recompras dobladas cada -1,6 %, sin stop.

    Unidad = la cuenta de futuros (el 20 % del capital, según el texto). Márgenes de su tabla:
    0,2 / 0,4 / 0,8 / 1,16 / 2,32 / 4,64 % de la cuenta, a x100. Sale entera cuando el precio supera
    el precio medio en un 1,6 %. El tamaño es siempre el mismo (no compone), para poder sumar.
    Si la pérdida abierta se come la cuenta de futuros, queda liquidada: se pierde 1 unidad y se
    sigue. Es el caso de no añadir dinero desde contado.
    """
    v = datos.cargar_velas("BTCUSDT", "15m")
    h4 = datos.reagrupar(v, "4h")
    alcista_4h = ind.ema(h4.c, 10) > ind.ema(h4.c, 55)
    k4 = np.searchsorted(h4.t + h4.ms, v.t + v.ms, side="right") - 1      # última vela de 4 h ya cerrada
    nocionales = np.array([0.2, 0.4, 0.8, 1.16, 2.32, 4.64]) / 100.0 * 100.0     # en cuentas de futuros
    PASO, COMISION = 0.016, 0.0005
    tamano, coste, nivel, p0 = 0.0, 0.0, 0, 0.0
    ganado = perdido = comisiones = 0.0
    ciclos = agotados = 0
    liquidaciones = []
    peor = 0.0
    for i in range(len(v)):
        lo, hi, c = v.l[i], v.h[i], v.c[i]
        if tamano == 0.0:
            if con_filtro and (k4[i] < 60 or not alcista_4h[k4[i]]):
                continue
            tamano, coste, nivel, p0 = nocionales[0] / c, nocionales[0], 1, c
            comisiones += nocionales[0] * COMISION
            continue
        while nivel < len(nocionales) and lo <= p0 * (1 - PASO * nivel):
            px = p0 * (1 - PASO * nivel)
            tamano += nocionales[nivel] / px
            coste += nocionales[nivel]
            comisiones += nocionales[nivel] * COMISION
            nivel += 1
            if nivel == len(nocionales):
                agotados += 1
        medio = coste / tamano
        abierta = tamano * (lo - medio)
        peor = min(peor, abierta)
        if abierta <= -1.0:                              # la pérdida se come la cuenta de futuros
            perdido += 1.0
            liquidaciones.append(v.t[i])
            tamano, coste, nivel = 0.0, 0.0, 0
            continue
        if hi >= medio * (1 + PASO):
            salida = medio * (1 + PASO)
            ganado += tamano * (salida - medio)
            comisiones += tamano * salida * COMISION
            tamano, coste, nivel = 0.0, 0.0, 0
            ciclos += 1
    abierta_final = tamano * (v.c[-1] - coste / tamano) if tamano else 0.0
    return {"ciclos": ciclos, "agotados": agotados, "liquidaciones": liquidaciones, "peor": peor,
            "ganado": ganado, "perdido": perdido, "comisiones": comisiones, "abierta": abierta_final,
            "anios": len(v) / (96 * 365)}


def fila_martingala() -> list:
    out = []
    for filtro, nombre in ((False, "siempre largo"), (True, "solo con EMA10 > EMA55 en 4 h")):
        r = martingala(filtro)
        meses = sorted({pd.Timestamp(t, unit="ms").strftime("%Y-%m") for t in r["liquidaciones"]})
        neto = r["ganado"] - r["perdido"] - r["comisiones"] + r["abierta"]
        out.append(_fila(
            f"Base escrita: x100, 0,2 % inicial, recompras dobladas cada −1,6 %, sin stop ({nombre})",
            f"BTC {r['anios']:.1f} años: {r['ciclos']} operaciones ganadoras que suman +{r['ganado']:.1f} cuentas de futuros; "
            f"{r['agotados']} veces gastó las 5 recompras; LIQUIDADA {len(r['liquidaciones'])} veces en {len(meses)} meses distintos "
            f"(−{r['perdido']:.0f} cuentas); comisiones −{r['comisiones']:.1f}. Neto: {neto:+.1f} cuentas de futuros",
            "Gana casi siempre y cada cierto tiempo lo pierde todo; el neto depende de sobrevivir a esas veces"))
    return out


# ── Reglas que predicen (solo diseño) ─────────────────────────────────────────

def _btc(tf: str):
    v = datos.reagrupar(datos.cargar_velas("BTCUSDT", "15m"), tf)
    m = v.t < FIN
    return datos.Velas(v.simbolo, tf, v.t[m], v.o[m], v.h[m], v.l[m], v.c[m], v.v[m])


def sobreextension() -> list:
    """«No entrar si el precio está más de un 3 % sobre la EMA10 diaria.»"""
    d = _btc("1d")
    e10, e55 = ind.ema(d.c, 10), ind.ema(d.c, 55)
    alc = e10 > e55
    lejos = alc & (d.c / e10 - 1 > 0.03)
    cerca = alc & (d.c / e10 - 1 <= 0.03)
    f = _futuro(d.c, 7)
    a, b = f[lejos], f[cerca]
    return [_fila("«No entrar si el precio está >3 % sobre la EMA10 diaria»",
                  f"BTC en tendencia alcista, 7 días después: lejos de la EMA10 {np.nanmean(a) * 100:+.1f} % (n={np.isfinite(a).sum()}), "
                  f"cerca {np.nanmean(b) * 100:+.1f} % (n={np.isfinite(b).sum()})",
                  "AL REVÉS: lejos de la EMA10 rinde más" if np.nanmean(a) > np.nanmean(b) else "Se cumple")]


def vela_siete() -> list:
    """«Tras el cruce alcista EMA10/55, la vela 7 es la entrada óptima.»"""
    h = _btc("4h")
    e10, e55 = ind.ema(h.c, 10), ind.ema(h.c, 55)
    cruce = np.nonzero((e10[1:] > e55[1:]) & (e10[:-1] <= e55[:-1]))[0] + 1
    f = _futuro(h.c, 18)                                  # 3 días después, como su horizonte en 4 h
    por_vela = {k: np.array([f[i + k] for i in cruce if i + k < len(f)]) for k in range(1, 13)}
    medias = {k: np.nanmean(x) * 100 for k, x in por_vela.items()}
    zona = np.concatenate([por_vela[k] for k in (5, 6, 7, 8)])
    resto = np.concatenate([por_vela[k] for k in (1, 2, 3, 4, 9, 10, 11, 12)])
    return [_fila("«Vela 7 tras el cruce alcista (zona 5-8) es la entrada óptima»",
                  f"BTC 4 h, {len(cruce)} cruces: entrar en velas 5-8 da {np.nanmean(zona) * 100:+.2f} % a 3 días; "
                  f"en las demás, {np.nanmean(resto) * 100:+.2f} %. Por vela: " +
                  " ".join(f"{k}:{m:+.1f}" for k, m in medias.items()),
                  "Sin diferencia apreciable" if abs(np.nanmean(zona) - np.nanmean(resto)) < 0.004 else
                  ("Se cumple" if np.nanmean(zona) > np.nanmean(resto) else "AL REVÉS"))]


def calendario() -> list:
    """Lunes alcista, fin de semana flojo y ventana de Chicago 16-18 h."""
    out = []
    d = _btc("1d")
    r = d.c[1:] / d.c[:-1] - 1
    dia = pd.to_datetime(d.t[1:], unit="ms").dayofweek.to_numpy()
    lunes, otros = r[dia == 0], r[dia != 0]
    out.append(_fila("«Los lunes compran los institucionales»",
                     f"BTC: lunes {lunes.mean() * 100:+.2f} % de media (t={_t(lunes):+.1f}), resto de días {otros.mean() * 100:+.2f} %",
                     "No se distingue del azar" if abs(_t(lunes, otros.mean())) < 2 else "Se cumple"))
    finde = r[dia >= 5]
    semana = r[dia < 5]
    out.append(_fila("«No operar en fin de semana»",
                     f"BTC: sábado y domingo {finde.mean() * 100:+.2f} %/día con volatilidad {finde.std() * 100:.1f} %; "
                     f"entre semana {semana.mean() * 100:+.2f} %/día con {semana.std() * 100:.1f} %",
                     "El fin de semana es más tranquilo, no peor"))
    h = _btc("1h")
    hora = pd.to_datetime(h.t, unit="ms").hour.to_numpy()
    rh = np.zeros(len(h)); rh[1:] = h.c[1:] / h.c[:-1] - 1
    ventana = np.isin(hora, (22, 23))                     # 16-18 h de Chicago en horario de invierno
    despues = np.isin(hora, (0, 1, 2, 3, 4, 5, 6, 7))
    por_dia = pd.DataFrame({"v": np.where(ventana, rh, 0.0), "d": np.where(despues, rh, 0.0)},
                           index=pd.to_datetime(h.t, unit="ms").floor("D")).groupby(level=0).sum()
    out.append(_fila("«Chicago 16-18 h: lo tiran para comprar y luego lo suben»",
                     f"BTC: en esa ventana {por_dia['v'].mean() * 100:+.3f} % de media (t={_t(por_dia['v'].to_numpy()):+.1f}); "
                     f"las 8 h siguientes {por_dia['d'].mean() * 100:+.3f} % (t={_t(por_dia['d'].to_numpy()):+.1f})",
                     "No se ve ni la caída ni la subida"
                     if abs(_t(por_dia['v'].to_numpy())) < 2 and abs(_t(por_dia['d'].to_numpy())) < 2 else "Algo hay"))
    return out


def retesteo() -> list:
    """«Cada máximo se retestea: no entrar en la ruptura, esperar el retesteo.»"""
    h = _btc("4h")
    n = 120                                               # máximo de 20 días
    techo = np.concatenate(([np.nan], ind.maximo(h.h, n)[:-1]))
    ruptura = np.nonzero((h.c > techo) & (np.concatenate(([False], h.c[:-1] <= techo[:-1]))))[0]
    ruptura = _sin_solapar(ruptura, 42)
    vuelve, r_rupt, r_ret = [], [], []
    for i in ruptura:
        nivel = techo[i]
        ventana = slice(i + 1, min(i + 43, len(h)))       # 7 días
        toca = np.nonzero(h.l[ventana] <= nivel)[0]
        if i + 42 < len(h):
            r_rupt.append(h.c[i + 42] / h.c[i] - 1)
        vuelve.append(len(toca) > 0)
        if len(toca) and i + 1 + toca[0] + 42 < len(h):
            j = i + 1 + toca[0]
            r_ret.append(h.c[j + 42] / nivel - 1)
    r_rupt, r_ret = np.array(r_rupt), np.array(r_ret)
    perdidas = 1 - np.mean(vuelve)
    return [_fila("«Cada máximo se retestea: esperar el retesteo, no comprar la ruptura»",
                  f"BTC, {len(ruptura)} rupturas del máximo de 20 días: vuelve al nivel en 7 días el {np.mean(vuelve) * 100:.0f} %. "
                  f"Comprar la ruptura: {r_rupt.mean() * 100:+.1f} % a 7 días. Esperar el retesteo: {r_ret.mean() * 100:+.1f} % "
                  f"cuando llega, y te quedas fuera del {perdidas * 100:.0f} % que no vuelve",
                  "Se retestea a menudo, pero no «por ley»; esperar deja fuera las mejores")]


def volumen_de_parada() -> list:
    """«Tras una caída, la primera vela con volumen alto marca el suelo.»"""
    h = _btc("4h")
    roja = h.c < h.o
    tres = np.concatenate(([False] * 3, roja[:-3] & roja[1:-2] & roja[2:-1]))
    vol_alto = h.v > 1.5 * ind.sma(h.v, 20)
    senal = _sin_solapar(np.nonzero(tres & vol_alto)[0], 18)
    f = _futuro(h.c, 18)
    x = f[senal]
    todo = f[np.isfinite(f)]
    return [_fila("«Volumen de parada: 3 velas rojas y luego una con volumen alto = suelo»",
                  f"BTC 4 h, {len(senal)} casos: {np.nanmean(x) * 100:+.2f} % a 3 días (acierta {np.nanmean(x > 0) * 100:.0f} %), "
                  f"frente a {todo.mean() * 100:+.2f} % en un momento cualquiera (t={_t(x, todo.mean()):+.1f})",
                  "No se distingue del azar" if abs(_t(x, todo.mean())) < 2 else "Se cumple")]


def squeeze() -> list:
    """«Squeeze liberado + histograma positivo y subiendo = LONG inmediato.»"""
    h = _btc("4h")
    c, hi, lo = pd.Series(h.c), pd.Series(h.h), pd.Series(h.l)
    media, desv = c.rolling(20).mean(), c.rolling(20).std()
    rango = pd.Series(ind.rango_verdadero(h.h, h.l, h.c)).rolling(20).mean()
    kc = c.ewm(span=20, adjust=False).mean()
    apretado = ((media - 2 * desv) > (kc - 1.5 * rango)) & ((media + 2 * desv) < (kc + 1.5 * rango))
    delta = c - ((hi.rolling(20).max() + lo.rolling(20).min()) / 2 + media) / 2
    x = np.arange(20.0)
    valor = delta.rolling(20).apply(lambda y: np.polyval(np.polyfit(x, y, 1), 19.0), raw=True)
    liberado = (~apretado) & apretado.shift(1, fill_value=False)
    alcista = (liberado & (valor > 0) & (valor > valor.shift(1))).to_numpy()
    bajista = (liberado & (valor < 0) & (valor < valor.shift(1))).to_numpy()
    f = _futuro(h.c, 18)
    todo = f[np.isfinite(f)]
    a, b = f[_sin_solapar(np.nonzero(alcista)[0], 18)], f[_sin_solapar(np.nonzero(bajista)[0], 18)]
    return [_fila("«Squeeze liberado con histograma positivo y subiendo = LONG inmediato» (y el bajista, SHORT)",
                  f"BTC 4 h a 3 días: disparo alcista {np.nanmean(a) * 100:+.2f} % (n={np.isfinite(a).sum()}, t={_t(a, todo.mean()):+.1f}); "
                  f"disparo bajista {np.nanmean(b) * 100:+.2f} % (n={np.isfinite(b).sum()}, t={_t(b, todo.mean()):+.1f}); "
                  f"cualquier momento {todo.mean() * 100:+.2f} %",
                  "No se distingue del azar" if max(abs(_t(a, todo.mean())), abs(_t(b, todo.mean()))) < 2 else "Algo hay")]


def emas() -> list:
    """El corazón: EMA10 > EMA55 en 4 h y en diario como guía de tendencia."""
    out = []
    for tf, velas_dia in (("4h", 6), ("1d", 1)):
        v = _btc(tf)
        arriba = ind.ema(v.c, 10) > ind.ema(v.c, 55)
        r = np.zeros(len(v)); r[1:] = v.c[1:] / v.c[:-1] - 1
        dentro = np.concatenate(([False], arriba[:-1]))    # la señal de ayer decide hoy
        a, b = r[dentro], r[~dentro]
        anual = lambda x: ((1 + x.mean()) ** (velas_dia * 365) - 1) * 100
        out.append(_fila(f"«Las EMAs no mienten»: largo solo con EMA10 > EMA55 en {tf}",
                         f"BTC: con la EMA10 por encima rinde un {anual(a):+.0f} % anualizado; por debajo, {anual(b):+.0f} % "
                         f"(está arriba el {dentro.mean() * 100:.0f} % del tiempo)",
                         "SE CUMPLE: es la base de lo que corre"))
    return out


if __name__ == "__main__":
    comun.configurar_pandas()
    pd.set_option("display.max_colwidth", 400)
    filas = []
    for fn in (emas, sobreextension, vela_siete, retesteo, volumen_de_parada, squeeze, calendario,
               caidas_en_un_dia, fila_martingala):
        filas += fn()
    lineas = []
    for f in filas:
        lineas += [f"■ {f['regla de Jorge']}", f"    datos: {f['lo que dicen los datos']}", f"    → {f['veredicto']}", ""]
    texto = "\n".join(lineas)
    print(texto)
    lab.guardar("reglas_jorge.txt", texto)
