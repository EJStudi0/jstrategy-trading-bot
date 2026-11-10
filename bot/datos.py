"""Datos de mercado: histórico para investigar y velas recientes para operar.

Histórico
---------
Sale de los volcados públicos de Binance (`data.binance.vision`): un zip por
símbolo y mes con las velas del perpetuo USDT-M. Son ficheros estáticos, sin
clave y sin el bloqueo regional de la API, así que se pueden bajar desde
cualquier salida. Se guardan ya limpios en `datos_cache/` como `.npz`.

Los zips se leen en memoria y solo se interpretan como números: de ahí no se
ejecuta ni se extrae nada a disco.

En vivo
-------
`VelasEnVivo` pide velas por ccxt a una lista de mercados en orden y se queda
con el primero que conteste. Existe porque el servidor cambia de salida a
internet y Binance responde 451 según el país: un solo proveedor dejó al bot
ciego 20 días en agosto de 2026.
"""

from __future__ import annotations

import io
import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import numpy as np
import pandas as pd
import requests

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIR_CACHE = os.path.join(RAIZ, "datos_cache")
BASE_VISION = "https://data.binance.vision/data/futures/um"

MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "30m": 1_800_000,
      "1h": 3_600_000, "2h": 7_200_000, "4h": 14_400_000, "8h": 28_800_000,
      "12h": 43_200_000, "1d": 86_400_000}

COLUMNAS_KLINE = ["t", "o", "h", "l", "c", "v", "t_cierre", "vq", "n",
                  "v_compra", "vq_compra", "_"]


@dataclass
class Velas:
    """Velas OHLCV como columnas numpy. `t` es la apertura en ms UTC."""

    simbolo: str
    intervalo: str
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray

    def __len__(self) -> int:
        return len(self.t)

    @property
    def ms(self) -> int:
        return MS[self.intervalo]

    def fechas(self) -> pd.DatetimeIndex:
        return pd.to_datetime(self.t, unit="ms", utc=True)

    def recorte(self, desde: Optional[str] = None, hasta: Optional[str] = None) -> "Velas":
        """Subconjunto por fecha ('2023-01-01'); `hasta` es exclusivo."""
        m = np.ones(len(self.t), dtype=bool)
        if desde:
            m &= self.t >= _a_ms(desde)
        if hasta:
            m &= self.t < _a_ms(hasta)
        return Velas(self.simbolo, self.intervalo, self.t[m], self.o[m], self.h[m],
                     self.l[m], self.c[m], self.v[m])

    def hasta_indice(self, n: int) -> "Velas":
        return Velas(self.simbolo, self.intervalo, self.t[:n], self.o[:n], self.h[:n],
                     self.l[:n], self.c[:n], self.v[:n])


def _a_ms(fecha: str) -> int:
    return int(pd.Timestamp(fecha, tz="UTC").value // 1_000_000)


def _meses(desde: str, hasta: str) -> list[str]:
    ini = pd.Period(desde, freq="M")
    fin = pd.Period(hasta, freq="M")
    return [str(p) for p in pd.period_range(ini, fin, freq="M")]


def _leer_zip_csv(contenido: bytes, columnas: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(io.BytesIO(contenido)) as z:
        nombre = z.namelist()[0]
        with z.open(nombre) as fh:
            crudo = fh.read()
    # Los ficheros antiguos no traen cabecera y los nuevos sí.
    primera = crudo[:64].decode("ascii", "replace")
    tiene_cabecera = not primera.lstrip()[:1].isdigit()
    df = pd.read_csv(io.BytesIO(crudo), header=0 if tiene_cabecera else None)
    df = df.iloc[:, :len(columnas)]
    df.columns = columnas[:df.shape[1]]
    return df


def _bajar(sesion: requests.Session, url: str, intentos: int = 4) -> Optional[bytes]:
    """Devuelve el contenido, o None si el fichero no existe (404)."""
    for i in range(intentos):
        try:
            r = sesion.get(url, timeout=40)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.content
        except requests.RequestException:
            if i == intentos - 1:
                raise
            time.sleep(1.5 * (i + 1))
    return None


def _ruta_cache(simbolo: str, que: str) -> str:
    os.makedirs(DIR_CACHE, exist_ok=True)
    return os.path.join(DIR_CACHE, f"{simbolo}_{que}.npz")


def descargar_velas(simbolo: str, intervalo: str = "15m", desde: str = "2020-01",
                    hasta: Optional[str] = None, hilos: int = 6,
                    refrescar: bool = False) -> Velas:
    """Velas históricas del perpetuo `simbolo` (p. ej. 'BTCUSDT'), con caché en disco."""
    ruta = _ruta_cache(simbolo, intervalo)
    if os.path.exists(ruta) and not refrescar:
        return cargar_velas(simbolo, intervalo)

    ahora = datetime.now(timezone.utc)
    if hasta is None:
        # El mes en curso no está en los volcados mensuales: se completa por días.
        hasta = (ahora.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    meses = _meses(desde, hasta)
    sesion = requests.Session()

    def uno(mes: str) -> Optional[pd.DataFrame]:
        url = f"{BASE_VISION}/monthly/klines/{simbolo}/{intervalo}/{simbolo}-{intervalo}-{mes}.zip"
        cont = _bajar(sesion, url)
        return None if cont is None else _leer_zip_csv(cont, COLUMNAS_KLINE)

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        partes = [p for p in ex.map(uno, meses) if p is not None]

    # Días sueltos del mes en curso (hasta ayer, que es lo último publicado).
    dias = pd.date_range(ahora.replace(day=1).date(), (ahora - timedelta(days=1)).date(), freq="D")
    if pd.Period(hasta, freq="M") == pd.Period((ahora.replace(day=1) - timedelta(days=1)).strftime("%Y-%m"), freq="M"):
        def dia(d) -> Optional[pd.DataFrame]:
            f = d.strftime("%Y-%m-%d")
            url = f"{BASE_VISION}/daily/klines/{simbolo}/{intervalo}/{simbolo}-{intervalo}-{f}.zip"
            cont = _bajar(sesion, url)
            return None if cont is None else _leer_zip_csv(cont, COLUMNAS_KLINE)
        with ThreadPoolExecutor(max_workers=hilos) as ex:
            partes += [p for p in ex.map(dia, dias) if p is not None]

    if not partes:
        raise RuntimeError(f"Sin datos para {simbolo} {intervalo}")

    df = pd.concat(partes, ignore_index=True)
    for col in ("t", "o", "h", "l", "c", "v"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["t", "o", "h", "l", "c", "v"])
    df["t"] = df["t"].astype("int64")
    # Algún volcado reciente viene en microsegundos.
    df.loc[df["t"] > 10**14, "t"] //= 1000
    df = df.drop_duplicates(subset="t").sort_values("t")

    velas = Velas(simbolo, intervalo, df["t"].to_numpy(np.int64),
                  *(df[c].to_numpy(np.float64) for c in ("o", "h", "l", "c", "v")))
    _validar(velas)
    np.savez_compressed(ruta, t=velas.t, o=velas.o, h=velas.h, l=velas.l, c=velas.c, v=velas.v)
    return velas


def cargar_velas(simbolo: str, intervalo: str = "15m") -> Velas:
    z = np.load(_ruta_cache(simbolo, intervalo))
    return Velas(simbolo, intervalo, z["t"], z["o"], z["h"], z["l"], z["c"], z["v"])


def _validar(v: Velas) -> None:
    if len(v) == 0:
        raise ValueError(f"{v.simbolo}: sin velas")
    if not np.all(np.diff(v.t) > 0):
        raise ValueError(f"{v.simbolo}: tiempos no crecientes")
    if np.any(v.h < np.maximum(v.o, v.c) - 1e-9) or np.any(v.l > np.minimum(v.o, v.c) + 1e-9):
        raise ValueError(f"{v.simbolo}: velas con máximo/mínimo incoherente")
    if np.any(v.l <= 0):
        raise ValueError(f"{v.simbolo}: precios no positivos")


def huecos(v: Velas) -> list[tuple[str, int]]:
    """Saltos en la serie: (fecha del hueco, velas que faltan)."""
    d = np.diff(v.t)
    idx = np.nonzero(d > v.ms)[0]
    return [(str(pd.Timestamp(v.t[i], unit="ms")), int(d[i] // v.ms) - 1) for i in idx]


def reagrupar(v: Velas, intervalo: str) -> Velas:
    """Agrupa a un intervalo mayor alineado a UTC. Solo devuelve velas completas.

    Una vela mayor se da por completa si contiene su última subvela; así un
    hueco en mitad no la descarta pero una vela todavía en formación sí.
    """
    destino = MS[intervalo]
    if destino == v.ms:
        return v
    if destino % v.ms != 0:
        raise ValueError(f"{intervalo} no es múltiplo de {v.intervalo}")
    grupo = v.t // destino
    cortes = np.nonzero(np.diff(grupo))[0] + 1
    ini = np.concatenate(([0], cortes))
    fin = np.concatenate((cortes, [len(v.t)]))
    t = grupo[ini] * destino
    o = v.o[ini]
    c = v.c[fin - 1]
    h = np.maximum.reduceat(v.h, ini)
    l = np.minimum.reduceat(v.l, ini)
    vol = np.add.reduceat(v.v, ini)
    completa = v.t[fin - 1] == t + destino - v.ms
    return Velas(v.simbolo, intervalo, t[completa], o[completa], h[completa],
                 l[completa], c[completa], vol[completa])


def descargar_funding(simbolo: str, desde: str = "2020-01", hasta: Optional[str] = None,
                      hilos: int = 6, refrescar: bool = False) -> tuple[np.ndarray, np.ndarray]:
    """Histórico de funding del perpetuo: (t_ms, tasa por periodo)."""
    ruta = _ruta_cache(simbolo, "funding")
    if os.path.exists(ruta) and not refrescar:
        z = np.load(ruta)
        return z["t"], z["tasa"]
    ahora = datetime.now(timezone.utc)
    if hasta is None:
        hasta = (ahora.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    sesion = requests.Session()

    def uno(mes: str) -> Optional[pd.DataFrame]:
        url = f"{BASE_VISION}/monthly/fundingRate/{simbolo}/{simbolo}-fundingRate-{mes}.zip"
        cont = _bajar(sesion, url)
        return None if cont is None else _leer_zip_csv(cont, ["t", "horas", "tasa"])

    with ThreadPoolExecutor(max_workers=hilos) as ex:
        partes = [p for p in ex.map(uno, _meses(desde, hasta)) if p is not None]
    if not partes:
        raise RuntimeError(f"Sin funding para {simbolo}")
    df = pd.concat(partes, ignore_index=True)
    df["t"] = pd.to_numeric(df["t"], errors="coerce")
    df["tasa"] = pd.to_numeric(df["tasa"], errors="coerce")
    df = df.dropna(subset=["t", "tasa"]).drop_duplicates(subset="t").sort_values("t")
    t = df["t"].to_numpy(np.int64)
    tasa = df["tasa"].to_numpy(np.float64)
    np.savez_compressed(ruta, t=t, tasa=tasa)
    return t, tasa


def a_binance(simbolo_ccxt: str) -> str:
    """'BTC/USDT:USDT' -> 'BTCUSDT'."""
    return simbolo_ccxt.split(":")[0].replace("/", "")


# ─── En vivo ──────────────────────────────────────────────────────────────────

# Mercados de los que se pueden leer velas públicas del perpetuo, en orden de
# preferencia. Binance va primero porque es contra el que se midió la
# estrategia; los demás existen para no quedarse ciego cuando Binance no
# contesta desde la salida a internet del momento.
MERCADOS_POR_DEFECTO = ("binanceusdm", "okx", "bitget", "gate", "kucoinfutures", "mexc")


class SinDatos(RuntimeError):
    pass


class VelasEnVivo:
    """Velas públicas recientes con conmutación entre mercados.

    No lleva claves: solo lee. El mercado que contesta se recuerda y se sigue
    usando hasta que falle `fallos_para_cambiar` veces seguidas.
    """

    def __init__(self, mercados: Iterable[str] = MERCADOS_POR_DEFECTO,
                 fallos_para_cambiar: int = 2):
        self.mercados = list(mercados)
        self.fallos_para_cambiar = fallos_para_cambiar
        self._clientes: dict = {}
        self._activo: Optional[str] = None
        self._fallos = 0
        self.ultimo_ok_utc: Optional[float] = None
        self.ultimo_error: Optional[str] = None
        self.errores: dict = {}          # último fallo de cada mercado, para diagnóstico

    @property
    def mercado_activo(self) -> Optional[str]:
        return self._activo

    def _cliente(self, nombre: str):
        import ccxt  # import perezoso: la investigación no necesita ccxt

        if nombre not in self._clientes:
            clase = getattr(ccxt, nombre)
            self._clientes[nombre] = clase({"enableRateLimit": True, "timeout": 15000,
                                            "options": {"defaultType": "swap"}})
        return self._clientes[nombre]

    def _descartar(self, nombre: str) -> None:
        # Un cliente con el pool de conexiones muerto no se recupera solo.
        cli = self._clientes.pop(nombre, None)
        try:
            if cli is not None and hasattr(cli, "close"):
                cli.close()
        except Exception:
            pass

    def _orden(self) -> list[str]:
        if self._activo and self._fallos < self.fallos_para_cambiar:
            return [self._activo] + [m for m in self.mercados if m != self._activo]
        return list(self.mercados)

    def velas(self, simbolo: str, intervalo: str, limite: int = 500) -> Velas:
        """Últimas `limite` velas CERRADAS de `simbolo` ('BTC/USDT:USDT')."""
        errores = []
        for nombre in self._orden():
            try:
                cli = self._cliente(nombre)
                filas = cli.fetch_ohlcv(simbolo, intervalo, limit=limite + 1)
                if not filas:
                    raise SinDatos("respuesta vacía")
                a = np.asarray(filas, dtype=np.float64)
                t = a[:, 0].astype(np.int64)
                # La última vela suele estar en formación: fuera.
                ahora_ms = int(time.time() * 1000)
                cerrada = (t + MS[intervalo] <= ahora_ms) & (t % MS[intervalo] == 0)
                a, t = a[cerrada], t[cerrada]
                if len(t) == 0:
                    raise SinDatos("sin velas cerradas")
                if nombre != self._activo:
                    self._activo = nombre
                self._fallos = 0
                self.ultimo_ok_utc = time.time()
                v = Velas(simbolo, intervalo, t, a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
                _validar(v)
                return v
            except Exception as e:  # red, 451, símbolo inexistente en ese mercado…
                self.errores[nombre] = f"{type(e).__name__}: {str(e)[:160]}"
                errores.append(f"{nombre}: {type(e).__name__}: {str(e)[:120]}")
                if nombre == self._activo:
                    self._fallos += 1
                self._descartar(nombre)
        self.ultimo_error = " | ".join(errores)[:600]
        raise SinDatos(self.ultimo_error)

    def historia(self, simbolo: str, intervalo: str, n: int = 1500) -> Velas:
        """Hasta `n` velas cerradas, paginando. Cada mercado da entre 100 y 1500 por llamada."""
        ms = MS[intervalo]
        errores = []
        for nombre in self._orden():
            try:
                cli = self._cliente(nombre)
                ahora = int(time.time() * 1000)
                desde = (ahora // ms - n - 1) * ms
                filas: dict = {}
                for _ in range(60):
                    lote = cli.fetch_ohlcv(simbolo, intervalo, since=desde, limit=300)
                    if not lote:
                        break
                    for f in lote:
                        filas[int(f[0])] = f
                    ultimo = int(lote[-1][0])
                    if ultimo + ms >= ahora or ultimo < desde:
                        break
                    desde = ultimo + ms
                if not filas:
                    raise SinDatos("respuesta vacía")
                a = np.asarray([filas[k] for k in sorted(filas)], dtype=np.float64)
                t = a[:, 0].astype(np.int64)
                ok = (t + ms <= ahora) & (t % ms == 0)
                a, t = a[ok], t[ok]
                if len(t) == 0:
                    raise SinDatos("sin velas cerradas")
                self._activo = nombre
                self._fallos = 0
                self.ultimo_ok_utc = time.time()
                v = Velas(simbolo, intervalo, t, a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5])
                _validar(v)
                return v
            except Exception as e:
                self.errores[nombre] = f"{type(e).__name__}: {str(e)[:160]}"
                errores.append(f"{nombre}: {type(e).__name__}: {str(e)[:120]}")
                if nombre == self._activo:
                    self._fallos += 1
                self._descartar(nombre)
        self.ultimo_error = " | ".join(errores)[:600]
        raise SinDatos(self.ultimo_error)

    def financiacion(self, simbolo: str, desde_ms: int) -> list:
        """Eventos de financiación ya liquidados desde `desde_ms`: [(t_ms, tasa)]."""
        ahora = int(time.time() * 1000)
        for nombre in self._orden():
            try:
                cli = self._cliente(nombre)
                if not cli.has.get("fetchFundingRateHistory"):
                    continue
                filas = cli.fetch_funding_rate_history(simbolo, since=int(desde_ms), limit=50)
                out = sorted((int(f["timestamp"]), float(f["fundingRate"])) for f in filas
                             if f.get("timestamp") and f.get("fundingRate") is not None)
                return [(t, r) for t, r in out if desde_ms < t <= ahora]
            except Exception:
                self._descartar(nombre)
        return []

    def precios(self, simbolos: list) -> dict:
        """Último precio de varias monedas: una llamada si el mercado lo permite."""
        for nombre in self._orden():
            try:
                cli = self._cliente(nombre)
                if not cli.has.get("fetchTickers"):
                    continue
                tks = cli.fetch_tickers(list(simbolos))
                out = {}
                for s in simbolos:
                    tk = tks.get(s) or {}
                    p = tk.get("last") or tk.get("close")
                    if p and p > 0:
                        out[s] = float(p)
                if out:
                    self._activo = nombre
                    self._fallos = 0
                    self.ultimo_ok_utc = time.time()
                    return out
            except Exception as e:
                self.errores[nombre] = f"{type(e).__name__}: {str(e)[:160]}"
                self._descartar(nombre)
        return {}

    def precio(self, simbolo: str) -> float:
        """Último precio negociado."""
        errores = []
        for nombre in self._orden():
            try:
                tk = self._cliente(nombre).fetch_ticker(simbolo)
                p = tk.get("last") or tk.get("close")
                if not p or p <= 0:
                    raise SinDatos("ticker sin precio")
                self.ultimo_ok_utc = time.time()
                return float(p)
            except Exception as e:
                errores.append(f"{nombre}: {type(e).__name__}")
                self._descartar(nombre)
        self.ultimo_error = " | ".join(errores)[:600]
        raise SinDatos(self.ultimo_error)


def unir(a: Optional[Velas], b: Velas) -> Velas:
    """Une dos series de la misma moneda e intervalo; en los solapes manda `b`."""
    if a is None or len(a) == 0:
        return b
    t = np.concatenate([a.t, b.t])
    cols = [np.concatenate([getattr(a, k), getattr(b, k)]) for k in ("o", "h", "l", "c", "v")]
    # Quedarse con la ÚLTIMA aparición de cada tiempo (la de `b`).
    orden = np.argsort(t, kind="stable")
    t = t[orden]
    cols = [c[orden] for c in cols]
    ultimo = np.concatenate((t[1:] != t[:-1], [True]))
    return Velas(b.simbolo, b.intervalo, t[ultimo], *(c[ultimo] for c in cols))


def a_ccxt(simbolo: str) -> str:
    """'BTCUSDT' -> 'BTC/USDT:USDT'."""
    base = simbolo[:-4] if simbolo.endswith("USDT") else simbolo
    return f"{base}/USDT:USDT"
