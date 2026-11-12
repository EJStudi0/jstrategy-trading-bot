"""El asistente: vigila el mercado en velas de 30 min, avisa de patrones y lleva la cuenta de lo que
el dueño opera a mano. Todo en SIMULACIÓN y aparte de la cartera del bot: aquí no se toca su dinero.

- Avisos: `patrones.detectar` sobre la última vela cerrada de cada moneda. Cada aviso lleva lo que pasó
  las otras veces que salió ese patrón (en el último mes) y, con el tiempo, cómo le fue a él: el marcador
  de cada patrón se rellena solo, a las 24 h de cada aviso.
- Cuenta manual: largos y cortos en futuros con stop y objetivo, vigilados en cada ciclo. Nada gratis:
  comisión, deslizamiento y financiación.
- Vetos por moneda con caducidad (los aplica el bot al decidir) y mando temporal.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from bot import config, datos, patrones, telegram

log = logging.getLogger("asistente")

COMISION = 0.0006          # futuros de Bitget, orden a mercado
DESLIZAMIENTO = 0.0002
PALANCA_MAX = 5.0          # nocional total de la cuenta manual frente a su patrimonio
CAPITAL_MANUAL = 1000.0
VELAS_30 = 1500            # un mes largo de velas de 30 min
MAX_ALERTAS = 300
MAX_CERRADAS = 300
VETOS = ("congelar", "cubrir", "cerrar")
FUERZA = {"ruptura": "alta", "barrido": "media", "sacudida": "media", "ruptura_floja": "baja",
          "zona_virgen": "media", "rebote_media": "baja", "volumen": "baja", "compresion": "baja", "fondo": "baja"}
H4, H24 = 4 * 3600_000, 24 * 3600_000


def _utc(ms: Optional[float] = None) -> str:
    t = datetime.now(timezone.utc) if ms is None else datetime.fromtimestamp(ms / 1000, timezone.utc)
    return t.isoformat(timespec="seconds")


class Asistente:
    def __init__(self, feed, simbolos, carpeta: Optional[str] = None):
        self.feed = feed
        self.simbolos = tuple(simbolos)
        self.ruta = os.path.join(carpeta or config.RAIZ, "estado_asistente.json")
        g = config.leer_json(self.ruta)
        capital = float(os.getenv("JORGE_ASISTENTE_CAPITAL", CAPITAL_MANUAL))
        self.manual = g.get("manual") or {"capital_inicial": capital, "saldo": capital, "posiciones": [],
                                          "cerradas": [], "creada_utc": _utc()}
        self.alertas: list = g.get("alertas", [])
        self.marcador: dict = g.get("marcador", {})      # patrón -> {n, a_favor, suma}
        self.vetos: dict = g.get("vetos", {})            # símbolo -> {modo, hasta_ms}
        self.mando_hasta_ms: Optional[int] = g.get("mando_hasta_ms")
        self.n_id: int = g.get("n_id", 0)
        self.niveles: list = g.get("niveles", [])        # «avísame si X cruza tal precio»
        self.prefs: dict = {"patrones_callados": [], "monedas_calladas": [], **g.get("prefs", {})}
        self.prefs["telegram"] = {**telegram.PREFS, **self.prefs.get("telegram", {})}
        self.velas: dict = {}                            # símbolo -> Velas de 30 min
        self._analizada: dict = {}                       # símbolo -> apertura de la última vela analizada
        self.previo: dict = {}                           # patrón -> {n, a_favor_pct, media_pct} (último mes)
        self._despues: dict = {}                         # símbolo -> {patrón: movimientos a favor}
        self.lectura: dict = {}                          # símbolo -> {fondo, movimiento}
        self._ultimo_funding = 0.0
        self.notificar = None                            # función(alerta) para sacar el aviso fuera; apagado

    # ── estado ────────────────────────────────────────────────────────────────

    def guardar(self) -> None:
        config.escribir_json(self.ruta, {"manual": self.manual, "alertas": self.alertas[-MAX_ALERTAS:],
                                         "marcador": self.marcador, "vetos": self.vetos,
                                         "mando_hasta_ms": self.mando_hasta_ms, "n_id": self.n_id,
                                         "niveles": self.niveles, "prefs": self.prefs})

    def _id(self) -> int:
        self.n_id += 1
        return self.n_id

    # ── velas de 30 min (red: fuera del candado del bot) ──────────────────────

    def actualizar_velas(self) -> None:
        ultima_cerrada = (int(time.time() * 1000) // patrones.M30 - 1) * patrones.M30
        for s in self.simbolos:
            v = self.velas.get(s)
            if v is not None and len(v) and v.t[-1] >= ultima_cerrada:
                continue
            try:
                if v is None or len(v) == 0 or (ultima_cerrada - v.t[-1]) // patrones.M30 > 250:
                    nuevas = self.feed.historia(datos.a_ccxt(s), "30m", VELAS_30)
                else:
                    faltan = int((ultima_cerrada - v.t[-1]) // patrones.M30) + 2
                    nuevas = self.feed.velas(datos.a_ccxt(s), "30m", max(faltan, 5))
            except datos.SinDatos as e:
                log.warning("%s: sin velas de 30 min (%s)", s, str(e)[:120])
                continue
            nuevas = datos.Velas(s, "30m", nuevas.t, nuevas.o, nuevas.h, nuevas.l, nuevas.c, nuevas.v)
            v = datos.unir(v, nuevas) if v is not None else nuevas
            if len(v) > VELAS_30 + 100:
                v = datos.Velas(s, "30m", *(getattr(v, k)[-VELAS_30:] for k in ("t", "o", "h", "l", "c", "v")))
            self.velas[s] = v

    def financiacion_pendiente(self) -> list:
        """Eventos de financiación de las posiciones manuales abiertas. Red: fuera del candado."""
        if time.time() - self._ultimo_funding < 1800 or not self.manual["posiciones"]:
            return []
        self._ultimo_funding = time.time()
        out = []
        for p in list(self.manual["posiciones"]):
            try:
                for t, tasa in self.feed.financiacion(datos.a_ccxt(p["simbolo"]), p["ultimo_funding_ms"]):
                    out.append((p["id"], t, tasa))
            except Exception as e:  # la red no debe parar nada
                log.warning("financiación manual %s: %s", p["simbolo"], str(e)[:120])
        return out

    # ── patrones y avisos ─────────────────────────────────────────────────────

    def analizar(self, velas4h: dict) -> list:
        """Mira la última vela cerrada de 30 min de cada moneda. Devuelve los avisos nuevos."""
        nuevas = []
        ahora = time.time() * 1000
        for s in self.simbolos:
            v, v4 = self.velas.get(s), velas4h.get(s)
            if v is None or len(v) < 200 or v4 is None or len(v4) < 120 or self._analizada.get(s) == int(v.t[-1]):
                continue
            self._analizada[s] = int(v.t[-1])
            ctx = patrones.fondo(v4.t, v4.o, v4.h, v4.l, v4.c, v4.v, v.t + patrones.M30)
            det = patrones.detectar(v.t, v.o, v.h, v.l, v.c, v.v, ctx)
            extra = det.pop("_")
            self._despues[s] = {k: patrones.despues(d, v.c) for k, d in det.items()}
            mov = extra["mov"][-1]
            self.lectura[s] = {"fondo": int(ctx[-1]), "movimiento": None if np.isnan(mov) else round(float(mov), 2)}
            if ahora - (v.t[-1] + patrones.M30) > 45 * 60_000:
                continue   # vela vieja (arranque o mercado caído): se lee, no se avisa
            for k, d in det.items():
                lado = float(d[-1])
                if lado == 0 or any(a["simbolo"] == s and a["patron"] == k and a["t"] == int(v.t[-1]) for a in self.alertas[-60:]):
                    continue
                lado = 0 if lado == 2 else int(lado)
                precio, a = float(v.c[-1]), float(extra["atr"][-1])
                nuevas.append({"id": self._id(), "utc": _utc(), "t": int(v.t[-1]), "simbolo": s, "patron": k,
                               "lado": lado, "precio": precio, "fuerza": FUERZA.get(k, "baja"),
                               "stop": round(precio - lado * 2 * a, 8) if lado else None,
                               "atr_pct": round(100 * a / precio, 2), "fondo": int(ctx[-1]),
                               "a_4h": None, "a_24h": None, "vista": False,
                               "callada": k in self.prefs["patrones_callados"] or s in self.prefs["monedas_calladas"]})
        self._recalcular_previo()
        for al in nuevas:
            al["previo"] = self.previo.get(al["patron"])
            self.alertas.append(al)
            log.info("Aviso: %s %s %s", al["simbolo"], al["patron"], {1: "arriba", -1: "abajo", 0: ""}[al["lado"]])
            if self.notificar:   # quien recibe decide, según el nivel que eligió el dueño
                try:
                    self.notificar(al)
                except Exception as e:
                    log.warning("no se pudo sacar el aviso: %s", str(e)[:120])
        self.alertas = self.alertas[-MAX_ALERTAS:]
        return nuevas

    def _recalcular_previo(self) -> None:
        juntos: dict = {}
        for por_patron in self._despues.values():
            for k, x in por_patron.items():
                juntos.setdefault(k, []).append(x)
        self.previo = {}
        for k, trozos in juntos.items():
            x = np.concatenate(trozos) if trozos else np.array([])
            if len(x):
                self.previo[k] = {"n": int(len(x)), "a_favor_pct": round(100 * float((x > 0).mean())),
                                  "media_pct": round(100 * float(x.mean()), 2)}

    def seguir(self, precios: dict) -> None:
        """Apunta cómo le fue a cada aviso con dirección a las 4 h y a las 24 h; a las 24 h cuenta en el marcador."""
        ahora = time.time() * 1000
        for al in self.alertas:
            px = precios.get(al["simbolo"])
            if not al["lado"] or not px or al["a_24h"] is not None:
                continue
            cierre = al["t"] + patrones.M30
            mov = round(100 * al["lado"] * (px / al["precio"] - 1), 2)
            if al["a_4h"] is None and ahora >= cierre + H4:
                al["a_4h"] = mov
            if ahora >= cierre + H24:
                al["a_24h"] = mov
                m = self.marcador.setdefault(al["patron"], {"n": 0, "a_favor": 0, "suma": 0.0})
                m["n"] += 1
                m["a_favor"] += mov > 0
                m["suma"] = round(m["suma"] + mov, 2)

    def marcar_vistas(self) -> None:
        for al in self.alertas:
            al["vista"] = True
        self.guardar()

    # ── cuenta manual ─────────────────────────────────────────────────────────

    def _no_realizado(self, p: dict, precios: dict) -> float:
        px = precios.get(p["simbolo"], p["entrada"])
        return p["lado"] * p["cantidad"] * (px - p["entrada"])

    def patrimonio(self, precios: dict) -> float:
        return self.manual["saldo"] + sum(self._no_realizado(p, precios) for p in self.manual["posiciones"])

    def abrir(self, simbolo: str, lado: int, usdt: float, precios: dict, stop: Optional[float] = None,
              objetivo: Optional[float] = None, nota: str = "", alerta: Optional[int] = None) -> dict:
        if simbolo not in self.simbolos:
            raise ValueError("moneda desconocida")
        if lado not in (1, -1):
            raise ValueError("el lado es 1 (largo) o -1 (corto)")
        px = precios.get(simbolo)
        if not px:
            raise ValueError("no hay precio de esa moneda ahora mismo")
        try:
            usdt = float(usdt)
            stop = None if stop in (None, "") else float(stop)
            objetivo = None if objetivo in (None, "") else float(objetivo)
        except (TypeError, ValueError):
            raise ValueError("importe, stop y objetivo deben ser números")
        if not usdt >= 5:
            raise ValueError("el importe mínimo es 5 USDT")
        abierto = sum(p["cantidad"] * precios.get(p["simbolo"], p["entrada"]) for p in self.manual["posiciones"])
        if abierto + usdt > PALANCA_MAX * max(self.patrimonio(precios), 0):
            raise ValueError(f"demasiado para la cuenta manual: el tope es {PALANCA_MAX:g} veces su patrimonio")
        entrada = px * (1 + lado * DESLIZAMIENTO)
        if stop is not None and not lado * (entrada - stop) > 0:
            raise ValueError("el stop tiene que quedar al otro lado del precio")
        if objetivo is not None and not lado * (objetivo - entrada) > 0:
            raise ValueError("el objetivo tiene que quedar a favor del precio")
        comision = usdt * COMISION
        self.manual["saldo"] -= comision
        p = {"id": self._id(), "simbolo": simbolo, "lado": lado, "cantidad": usdt / entrada, "entrada": entrada,
             "stop": stop, "objetivo": objetivo, "abierta_utc": _utc(), "nota": str(nota)[:200], "alerta": alerta,
             "comisiones": comision, "financiacion": 0.0, "ultimo_funding_ms": int(time.time() * 1000)}
        self.manual["posiciones"].append(p)
        log.info("Manual: %s %s %.2f USDT a %.6f", "LARGO" if lado == 1 else "CORTO", simbolo, usdt, entrada)
        self.guardar()
        return p

    def _posicion(self, id_: int) -> dict:
        for p in self.manual["posiciones"]:
            if p["id"] == id_:
                return p
        raise ValueError("esa operación ya no está abierta")

    def cerrar(self, id_: int, precios: dict, parte: float = 1.0, motivo: str = "manual",
               precio: Optional[float] = None) -> dict:
        p = self._posicion(int(id_))
        parte = float(parte)
        if not 0 < parte <= 1:
            raise ValueError("la parte a cerrar va de 0 a 1")
        px = precio or precios.get(p["simbolo"])
        if not px:
            raise ValueError("no hay precio de esa moneda ahora mismo")
        salida = px if motivo == "objetivo" else px * (1 - p["lado"] * DESLIZAMIENTO)   # el objetivo es orden limitada
        q = p["cantidad"] * parte
        comision = q * salida * COMISION
        bruto = p["lado"] * q * (salida - p["entrada"])
        self.manual["saldo"] += bruto - comision
        fila = {"id": p["id"], "simbolo": p["simbolo"], "lado": p["lado"], "entrada": p["entrada"], "salida": salida,
                "usdt": q * p["entrada"], "abierta_utc": p["abierta_utc"], "cerrada_utc": _utc(), "motivo": motivo,
                "neto": bruto - comision - p["comisiones"] * parte + p["financiacion"] * parte, "nota": p["nota"]}
        p["cantidad"] -= q
        p["comisiones"] *= 1 - parte
        p["financiacion"] *= 1 - parte
        if parte >= 1 or p["cantidad"] * p["entrada"] < 1:
            self.manual["posiciones"].remove(p)
        self.manual["cerradas"] = (self.manual["cerradas"] + [fila])[-MAX_CERRADAS:]
        log.info("Manual: cierre %s (%s) neto %+.2f USDT", p["simbolo"], motivo, fila["neto"])
        self.guardar()
        return fila

    def mover(self, id_: int, precios: dict, stop=None, objetivo=None) -> dict:
        p = self._posicion(int(id_))
        px = precios.get(p["simbolo"], p["entrada"])
        try:
            stop = None if stop in (None, "") else float(stop)
            objetivo = None if objetivo in (None, "") else float(objetivo)
        except (TypeError, ValueError):
            raise ValueError("stop y objetivo deben ser números")
        if stop is not None and not p["lado"] * (px - stop) > 0:
            raise ValueError("el stop tiene que quedar al otro lado del precio")
        if objetivo is not None and not p["lado"] * (objetivo - px) > 0:
            raise ValueError("el objetivo tiene que quedar a favor del precio")
        p["stop"], p["objetivo"] = stop, objetivo
        self.guardar()
        return p

    def vigilar(self, precios: dict, financiaciones: list = ()) -> list:
        """Cobra o paga la financiación y cierra lo que haya tocado su stop o su objetivo."""
        for id_, t, tasa in financiaciones:
            for p in self.manual["posiciones"]:
                if p["id"] == id_ and t > p["ultimo_funding_ms"]:
                    cobro = -p["lado"] * p["cantidad"] * precios.get(p["simbolo"], p["entrada"]) * tasa
                    p["financiacion"] += cobro
                    p["ultimo_funding_ms"] = int(t)
                    self.manual["saldo"] += cobro
        hechas = []
        for p in list(self.manual["posiciones"]):
            px = precios.get(p["simbolo"])
            if not px:
                continue
            if p["stop"] is not None and p["lado"] * (px - p["stop"]) <= 0:
                hechas.append(self.cerrar(p["id"], precios, motivo="stop"))      # al precio de ahora, que es peor o igual
            elif p["objetivo"] is not None and p["lado"] * (px - p["objetivo"]) >= 0:
                hechas.append(self.cerrar(p["id"], precios, motivo="objetivo", precio=p["objetivo"]))
        if self.manual["posiciones"] and self.patrimonio(precios) <= 0:
            for p in list(self.manual["posiciones"]):
                hechas.append(self.cerrar(p["id"], precios, motivo="liquidada"))
        return hechas

    def cerrar_todas(self, precios: dict) -> list:
        return [self.cerrar(p["id"], precios, motivo="manual") for p in list(self.manual["posiciones"])
                if precios.get(p["simbolo"])]

    def reiniciar_cuenta(self, capital: float) -> dict:
        """Empieza la cuenta manual de cero con otro capital ficticio. Solo sin operaciones abiertas."""
        capital = float(capital)
        if self.manual["posiciones"]:
            raise ValueError("cierra antes las operaciones abiertas")
        if not 100 <= capital <= 1_000_000:
            raise ValueError("el capital ficticio va de 100 a 1 000 000 USDT")
        self.manual = {"capital_inicial": capital, "saldo": capital, "posiciones": [], "cerradas": [], "creada_utc": _utc()}
        self.guardar()
        return self.manual

    # ── niveles de precio y preferencias de avisos ────────────────────────────

    def poner_nivel(self, simbolo: str, precio, precios: dict, nota: str = "") -> dict:
        if simbolo not in self.simbolos:
            raise ValueError("moneda desconocida")
        px = precios.get(simbolo)
        try:
            precio = float(precio)
        except (TypeError, ValueError):
            raise ValueError("el precio debe ser un número")
        if not px or not precio > 0 or precio == px:
            raise ValueError("pon un precio distinto del actual")
        if len(self.niveles) >= 40:
            raise ValueError("ya hay 40 niveles: borra alguno")
        n = {"id": self._id(), "simbolo": simbolo, "precio": precio, "sentido": 1 if precio > px else -1,
             "nota": str(nota)[:120], "creado_utc": _utc()}
        self.niveles.append(n)
        self.guardar()
        return n

    def quitar_nivel(self, id_: int) -> list:
        self.niveles = [n for n in self.niveles if n["id"] != int(id_)]
        self.guardar()
        return self.niveles

    def vigilar_niveles(self, precios: dict) -> list:
        """Avisa (una vez) cuando el precio cruza un nivel que el dueño pidió vigilar."""
        nuevas = []
        for n in list(self.niveles):
            px = precios.get(n["simbolo"])
            if px and n["sentido"] * (px - n["precio"]) >= 0:
                self.niveles.remove(n)
                al = {"id": self._id(), "utc": _utc(), "t": int(time.time() * 1000) - patrones.M30, "simbolo": n["simbolo"],
                      "patron": "nivel", "lado": n["sentido"], "precio": float(px), "fuerza": "alta", "stop": None,
                      "atr_pct": None, "fondo": self.lectura.get(n["simbolo"], {}).get("fondo", 0), "a_4h": None,
                      "a_24h": None, "vista": False, "callada": False, "nivel": n["precio"], "nota": n["nota"], "previo": None}
                self.alertas.append(al)
                nuevas.append(al)
                log.info("Aviso: %s cruza %s", n["simbolo"], n["precio"])
                if self.notificar:
                    try:
                        self.notificar(al)
                    except Exception as e:
                        log.warning("no se pudo sacar el aviso: %s", str(e)[:120])
        return nuevas

    def cambiar_prefs(self, cambios: dict) -> dict:
        for clave, validos in (("patrones_callados", set(patrones.CATALOGO)), ("monedas_calladas", set(self.simbolos))):
            if clave in cambios:
                lista = cambios[clave]
                if not isinstance(lista, list) or not set(lista) <= validos:
                    raise ValueError("preferencias no válidas")
                self.prefs[clave] = sorted(set(lista))
        if "telegram" in cambios:
            self.prefs["telegram"] = {**self.prefs["telegram"], **telegram.validar_prefs(cambios["telegram"])}
        self.guardar()
        return self.prefs

    # ── vetos y mando temporal ────────────────────────────────────────────────

    def vetos_activos(self) -> dict:
        ahora = time.time() * 1000
        caducados = [s for s, v in self.vetos.items() if v.get("hasta_ms") and v["hasta_ms"] <= ahora]
        for s in caducados:
            del self.vetos[s]
        return dict(self.vetos)

    def poner_veto(self, simbolo: str, modo: Optional[str], horas: float = 0) -> dict:
        if simbolo not in self.simbolos:
            raise ValueError("moneda desconocida")
        if modo in (None, "", "ninguno"):
            self.vetos.pop(simbolo, None)
        else:
            if modo not in VETOS:
                raise ValueError("el veto es congelar, cubrir o cerrar")
            horas = float(horas or 0)
            if not 0 <= horas <= 24 * 30:
                raise ValueError("la duración va de 0 (sin caducidad) a 720 horas")
            self.vetos[simbolo] = {"modo": modo, "desde_utc": _utc(),
                                   "hasta_ms": int(time.time() * 1000 + horas * 3600_000) if horas else None}
        self.guardar()
        return self.vetos_activos()

    def aplicar_vetos(self, base: dict, neto: dict) -> tuple:
        """Lo que el dueño ha mandado sobre monedas sueltas, encima de lo que decide la estrategia."""
        base, neto = dict(base), dict(neto)
        for s, v in self.vetos_activos().items():
            if s not in base:
                continue
            if v["modo"] == "congelar":       # el bot no la toca: se queda como esté
                base.pop(s), neto.pop(s, None)
            elif v["modo"] == "cubrir":       # conserva la base, sin apuesta de dirección
                neto[s] = 0.0
            elif v["modo"] == "cerrar":       # fuera de esa moneda
                base[s], neto[s] = 0.0, 0.0
        return base, neto

    def mando_caducado(self) -> bool:
        if self.mando_hasta_ms and time.time() * 1000 >= self.mando_hasta_ms:
            self.mando_hasta_ms = None
            return True
        return False

    # ── para el panel ─────────────────────────────────────────────────────────

    def instantanea(self, precios: dict) -> dict:
        pos = []
        for p in self.manual["posiciones"]:
            px = precios.get(p["simbolo"])
            nr = self._no_realizado(p, precios)
            pos.append({**p, "precio": px, "usdt": p["cantidad"] * p["entrada"], "no_realizado": nr,
                        "pct": 100 * p["lado"] * (px / p["entrada"] - 1) if px else None})
        cerradas = self.manual["cerradas"]
        pat = self.patrimonio(precios)
        ci = self.manual["capital_inicial"]
        marcador = {k: {**m, "a_favor_pct": round(100 * m["a_favor"] / m["n"]) if m["n"] else None,
                        "media_pct": round(m["suma"] / m["n"], 2) if m["n"] else None}
                    for k, m in self.marcador.items()}
        return {
            "utc": _utc(), "simulacion": True,
            "alertas": list(reversed(self.alertas[-100:])),
            "sin_ver": sum(1 for a in self.alertas if not a.get("vista") and a["fuerza"] != "baja" and not a.get("callada")),
            "niveles": self.niveles, "prefs": self.prefs,
            "catalogo": patrones.CATALOGO, "previo": self.previo, "marcador": marcador,
            "lectura": self.lectura,
            "manual": {"capital_inicial": ci, "patrimonio": pat, "ganancia": pat - ci,
                       "ganancia_pct": 100 * (pat / ci - 1) if ci else 0.0, "saldo": self.manual["saldo"],
                       "posiciones": pos, "cerradas": list(reversed(cerradas[-50:])),
                       "operaciones": len(cerradas),
                       "acierto_pct": round(100 * sum(c["neto"] > 0 for c in cerradas) / len(cerradas)) if cerradas else None,
                       "palanca_max": PALANCA_MAX, "comision_pct": COMISION * 100,
                       "creada_utc": self.manual.get("creada_utc")},
            "vetos": self.vetos_activos(), "mando_hasta_ms": self.mando_hasta_ms,
            "velas_al_dia": sum(1 for s in self.simbolos if s in self.velas), "monedas": list(self.simbolos),
        }
