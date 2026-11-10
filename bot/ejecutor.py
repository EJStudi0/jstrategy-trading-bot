"""Ejecutor en vivo (simulación): lee velas, decide al cierre de cada vela y opera.

El ciclo es corto (un minuto) pero las decisiones solo ocurren cuando cierra una
vela nueva de la estrategia (4 h). Entre medias solo se valora la cartera, se
liquida la financiación y se vigila que sigan entrando datos.

Las decisiones salen de `estrategia.calcular`, el mismo código que usa el
simulador histórico, y siempre sobre velas CERRADAS.
"""

from __future__ import annotations

import bisect
import csv
import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import numpy as np

from bot import cartera as cart
from bot import config, datos, estrategia, indicadores, resumen

log = logging.getLogger("bot")

VELAS_HISTORIA = 1500          # ~250 días de velas de 4 h: de sobra para la media de 64 días
VELAS_MINIMAS = 700            # con menos, no se opina sobre esa moneda
MARGEN_MINIMO = 0.20           # garantía mínima de los perpetuos sobre su nocional
ESPERA_REZAGADAS_S = 300       # cuánto se espera a que todas las monedas publiquen la vela
VELAS_SEMANA = 42              # siete días de velas de 4 h, para las minigráficas del panel
VELAS_GRAFICA = 360            # sesenta días de velas de 4 h para la gráfica de cada moneda

# Curva de patrimonio: una foto por hora. Los dos acumulados del final permiten repartir la
# ganancia de cada día entre financiación, comisiones y mercado (`bot/resumen.py`).
COLUMNAS_PATRIMONIO = ["utc", "patrimonio", "usdt", "contado", "no_realizado", "neto", "btc",
                       "financiacion", "comisiones"]


class Bot:
    def __init__(self, feed: Optional[datos.VelasEnVivo] = None, carpeta: Optional[str] = None):
        self.lock = threading.RLock()
        self.feed = feed or datos.VelasEnVivo(config.mercados())
        rutas = (config.RUTA_ESTADO, config.RUTA_BOT, config.RUTA_DIARIO, config.RUTA_PATRIMONIO)
        if carpeta:   # para pruebas
            rutas = tuple(os.path.join(carpeta, os.path.basename(r)) for r in rutas)
        self.ruta_estado, self.ruta_bot, self.ruta_diario, self.ruta_patrimonio = rutas

        guardado = config.leer_json(self.ruta_bot)
        self.mando: str = guardado.get("mando", "auto")
        self.ajustes: dict = guardado.get("ajustes", {})
        self.ultima_decision_t: Optional[int] = guardado.get("ultima_decision_t")
        self.p = config.parametros(self.ajustes)

        if os.path.exists(self.ruta_estado):
            self.cartera = cart.Cartera.cargar(self.ruta_estado, self.ruta_diario)
            log.info("Cartera cargada: %.2f USDT líquidos", self.cartera.usdt)
        else:
            self.cartera = cart.Cartera.nueva(config.capital_inicial(), self.ruta_diario)
            log.info("Cartera nueva con %.2f USDT", self.cartera.usdt)

        self.velas: dict = {}                  # simbolo -> Velas del intervalo de la estrategia
        self.precios: dict = {}
        self.decision: dict = {}               # última decisión, para el panel
        self.lectura: dict = {}                # tendencia de la última vela cerrada, decida o no
        self._t_lectura: Optional[int] = None  # vela del ancla con la que se hizo esa lectura
        self.arranque = time.time()
        self.ultimo_ciclo: Optional[float] = None
        self.ultimo_funding_consultado = 0.0
        self.ultima_financiacion = 0.0
        self._poner_al_dia_curva()
        self.hora_foto: Optional[int] = self._hora_de_la_ultima_foto()
        self.avisos: list = []
        self._confirmacion: Optional[tuple] = None

    # ── datos ─────────────────────────────────────────────────────────────────

    def _ruta_velas(self, simbolo: str) -> str:
        return os.path.join(datos.DIR_CACHE, f"vivo_{simbolo}_{self.p.intervalo}.npz")

    def _cargar_cache(self, simbolo: str) -> Optional[datos.Velas]:
        ruta = self._ruta_velas(simbolo)
        if not os.path.exists(ruta):
            return None
        try:
            z = np.load(ruta)
            return datos.Velas(simbolo, self.p.intervalo, z["t"], z["o"], z["h"], z["l"], z["c"], z["v"])
        except Exception:
            return None

    def _guardar_cache(self, v: datos.Velas) -> None:
        os.makedirs(datos.DIR_CACHE, exist_ok=True)
        ruta = self._ruta_velas(v.simbolo)
        tmp = ruta + ".tmp.npz"
        np.savez_compressed(tmp, t=v.t, o=v.o, h=v.h, l=v.l, c=v.c, v=v.v)
        os.replace(tmp, ruta)

    def actualizar_velas(self) -> None:
        """Trae lo que falte de cada moneda. La primera vez pagina la historia entera."""
        ms = datos.MS[self.p.intervalo]
        ahora = int(time.time() * 1000)
        ultima_cerrada = (ahora // ms - 1) * ms
        for s in self.p.simbolos:
            v = self.velas.get(s) or self._cargar_cache(s)
            if v is not None and len(v) and v.t[-1] >= ultima_cerrada:
                self.velas[s] = v
                continue
            faltan = VELAS_HISTORIA if v is None or len(v) == 0 else int((ultima_cerrada - v.t[-1]) // ms) + 2
            try:
                if faltan > 250:
                    nuevas = self.feed.historia(datos.a_ccxt(s), self.p.intervalo, VELAS_HISTORIA)
                else:
                    nuevas = self.feed.velas(datos.a_ccxt(s), self.p.intervalo, max(faltan, 5))
            except datos.SinDatos as e:
                log.warning("%s: sin velas (%s)", s, str(e)[:160])
                if v is not None:
                    self.velas[s] = v
                continue
            nuevas = datos.Velas(s, self.p.intervalo, nuevas.t, nuevas.o, nuevas.h, nuevas.l, nuevas.c, nuevas.v)
            v = datos.unir(v, nuevas)
            if len(v) > VELAS_HISTORIA + 200:
                v = datos.Velas(s, v.intervalo, *(getattr(v, k)[-VELAS_HISTORIA:] for k in ("t", "o", "h", "l", "c", "v")))
            self.velas[s] = v
            self._guardar_cache(v)

    def actualizar_precios(self) -> None:
        nuevos = self.feed.precios([datos.a_ccxt(s) for s in self.p.simbolos])
        for s in self.p.simbolos:
            p = nuevos.get(datos.a_ccxt(s))
            if p:
                self.precios[s] = p
            elif s not in self.precios:
                v = self.velas.get(s)
                if v is not None and len(v):
                    self.precios[s] = float(v.c[-1])

    def salud(self) -> dict:
        ok = self.feed.ultimo_ok_utc
        edad = None if ok is None else time.time() - ok
        if edad is None:
            estado = "arrancando" if time.time() - self.arranque < 180 else "ciego"
        elif edad > 1800:
            estado = "ciego"
        elif edad > 600:
            estado = "viejo"
        else:
            estado = "ok"
        return {"estado": estado, "edad_segundos": None if edad is None else round(edad),
                "mercado": self.feed.mercado_activo, "ultimo_error": self.feed.ultimo_error}

    # ── decisión ──────────────────────────────────────────────────────────────

    def _matrices(self):
        """Cuadrícula común de las monedas con historia suficiente."""
        con_datos = [s for s in self.p.simbolos
                     if s in self.velas and len(self.velas[s]) >= VELAS_MINIMAS]
        if not con_datos or self.p.simbolos[0] not in con_datos:
            return None
        t = np.unique(np.concatenate([self.velas[s].t for s in con_datos]))[-VELAS_HISTORIA:]
        N = len(self.p.simbolos)
        H, L, C = (np.full((len(t), N), np.nan) for _ in range(3))
        for j, s in enumerate(self.p.simbolos):
            if s not in con_datos:
                continue
            v = self.velas[s]
            dentro = v.t >= t[0]
            pos = np.searchsorted(t, v.t[dentro])
            H[pos, j], L[pos, j], C[pos, j] = v.h[dentro], v.l[dentro], v.c[dentro]
        return t, H, L, C

    def objetivos_actuales(self) -> Optional[dict]:
        """Objetivos de la última vela cerrada común, o None si faltan datos."""
        m = self._matrices()
        if m is None:
            return None
        t, H, L, C = m
        o = estrategia.calcular(H, L, C, self.p)
        k = len(t) - 1
        vd = estrategia.VELAS_DIA[self.p.intervalo]
        monedas = {}
        for j, s in enumerate(self.p.simbolos):
            al_dia = not np.isnan(C[k, j])
            ok = ~np.isnan(C[:, j])
            monedas[s] = {
                "al_dia": bool(al_dia),
                "puntuacion": float(o.puntuacion[k, j]),
                "vol": None if np.isnan(o.vol[k, j]) else float(o.vol[k, j]),
                "base": float(o.base[k, j]) if al_dia else None,
                "neto": float(o.neto[k, j]) if al_dia else None,
                # Solo para el panel: lo que vota cada reloj (su media es la puntuación).
                "relojes": estrategia.relojes(H[ok, j], L[ok, j], C[ok, j], vd, self.p) if ok.any() else None,
            }
        return {"t": int(t[k]), "monedas": monedas, "escala": float(o.escala[k]),
                "vol_prevista": float(o.vol_prevista[k])}

    def _aplicar_mando(self, base: dict, neto: dict) -> tuple:
        if self.mando == "neutral":           # todo cubierto
            return base, {s: 0.0 for s in base}
        if self.mando == "fuera":             # todo en USDT
            return {s: 0.0 for s in base}, {s: 0.0 for s in base}
        return base, neto

    def decidir(self, forzar: bool = False, motivo: str = "vela") -> list:
        """Calcula objetivos y opera. Devuelve las operaciones hechas."""
        obj = self.objetivos_actuales()
        if obj is None:
            self._aviso("Sin datos suficientes para decidir")
            return []
        # Solo se opera lo que tiene la vela al día; lo demás se deja como está.
        base = {s: m["base"] for s, m in obj["monedas"].items() if m["al_dia"]}
        neto = {s: m["neto"] for s, m in obj["monedas"].items() if m["al_dia"]}
        base, neto = self._aplicar_mando(base, neto)
        precios = {s: self.precios[s] for s in base if s in self.precios}

        hechas = []
        if self.mando != "pausa":
            pedidos = cart.ordenes(self.cartera, precios, base, neto, self.p.banda_base,
                                   self.p.banda_cobertura, self.p.minimo_orden_usdt,
                                   self.p.modo, forzar=forzar, banda_sin_base=self.p.banda_sin_base)
            for pata, s, cantidad in pedidos:
                fn = self.cartera.operar_contado if pata == "contado" else self.cartera.operar_perp
                fila = fn(s, cantidad, precios[s], motivo, precios)
                if fila:
                    hechas.append(fila)
                    log.info("%s %s %s %.6f a %.4f (%s)", fila["lado"].upper(), pata, s,
                             fila["cantidad"], fila["precio"], motivo)
            self._vigilar_margen(precios)

        self.ultima_decision_t = obj["t"]
        self.lectura = obj
        ancla = self.velas.get(self.p.simbolos[0])
        self._t_lectura = int(ancla.t[-1]) if ancla is not None and len(ancla) else None
        self.decision = {**obj, "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                         "mando": self.mando, "operaciones": len(hechas)}
        self.guardar()
        return hechas

    def _vigilar_margen(self, precios: dict) -> None:
        """Si la garantía de los cortos se queda corta, vende base para reponerla.

        Cuando el precio sube, el corto pierde lo mismo que gana el contado: el
        patrimonio no cambia, pero los USDT sí bajan. Vender algo de contado (y
        recortar el corto en la misma cantidad) devuelve la garantía sin tocar la
        exposición neta.
        """
        if self.cartera.colchon_margen(precios) >= MARGEN_MINIMO:
            return
        pat = self.cartera.patrimonio(precios)
        objetivo_usdt = (1.0 - self.p.tope_base) * pat
        falta = objetivo_usdt - (self.cartera.usdt + self.cartera.no_realizado(precios))
        valor = self.cartera.valor_contado(precios)
        if falta <= 0 or valor <= 0:
            return
        fraccion = min(1.0, falta / valor)
        self._aviso(f"Garantía baja: se vende un {fraccion * 100:.0f} % de la base para reponerla")
        for s, q in list(self.cartera.contado.items()):
            if q <= 0 or s not in precios:
                continue
            vendido = q * fraccion
            self.cartera.operar_contado(s, -vendido, precios[s], "reponer_garantia", precios)
            corto = self.cartera.perp.get(s)
            if corto and corto.cantidad < 0:
                self.cartera.operar_perp(s, min(vendido, -corto.cantidad), precios[s],
                                         "reponer_garantia", precios)

    def consultar_financiacion(self) -> list:
        """Pide a la red los eventos de financiación pendientes. Sin candado: es lento."""
        if time.time() - self.ultimo_funding_consultado < 1800:
            return []
        self.ultimo_funding_consultado = time.time()
        eventos = []
        for s, pos in list(self.cartera.perp.items()):
            ultimo = self.cartera.ultimo_funding_ms.get(s)
            if pos.cantidad == 0 or ultimo is None:
                continue
            for t, tasa in self.feed.financiacion(datos.a_ccxt(s), ultimo):
                eventos.append((s, t, tasa))
        return eventos

    def liquidar_financiacion(self, eventos: list) -> None:
        for s, t, tasa in eventos:
            pos = self.cartera.perp.get(s)
            precio = self.precios.get(s) or (pos.entrada if pos else 0.0)
            cobro = self.cartera.aplicar_financiacion(s, tasa, precio, t)
            if cobro:
                self.ultima_financiacion = time.time()
                log.info("Financiación %s: %+.4f USDT (tasa %.4f %%)", s, cobro, tasa * 100)
        hay_perp = any(p.cantidad for p in self.cartera.perp.values())
        if hay_perp and time.time() - max(self.ultima_financiacion, self.arranque) > 26 * 3600:
            self._aviso("Hace más de un día que no llega ninguna liquidación de financiación")
            self.ultima_financiacion = time.time()

    # ── ciclo ─────────────────────────────────────────────────────────────────

    def ciclo(self) -> None:
        # La red va fuera del candado: el panel no debe quedarse esperando a un mercado lento.
        self.actualizar_velas()
        self.actualizar_precios()
        if not self.precios:
            return
        eventos = self.consultar_financiacion()
        with self.lock:
            self.liquidar_financiacion(eventos)
            if self._toca_decidir():
                self.decidir(motivo="vela")
            elif self._lectura_atrasada():
                # Tras un reinicio, o mientras se espera a las rezagadas, el panel sigue viendo la
                # tendencia de la última vela cerrada. Leer no opera.
                self._t_lectura = int(self.velas[self.p.simbolos[0]].t[-1])
                self.lectura = self.objetivos_actuales() or self.lectura
            self._foto()
            self.ultimo_ciclo = time.time()
            self.guardar()

    def _toca_decidir(self) -> bool:
        """Hay vela nueva del ancla y las demás monedas ya la tienen (o pasó el margen de espera)."""
        ancla = self.velas.get(self.p.simbolos[0])
        if ancla is None or len(ancla) == 0:
            return False
        t = int(ancla.t[-1])
        if self.ultima_decision_t is not None and t <= self.ultima_decision_t:
            return False
        ms = datos.MS[self.p.intervalo]
        todas = all(len(v) and v.t[-1] >= t for v in self.velas.values())
        pasado_el_margen = time.time() * 1000 > t + ms + ESPERA_REZAGADAS_S * 1000
        return todas or pasado_el_margen

    def _lectura_atrasada(self) -> bool:
        ancla = self.velas.get(self.p.simbolos[0])
        return ancla is not None and len(ancla) > 0 and self._t_lectura != int(ancla.t[-1])

    def _foto(self) -> None:
        """Una línea por hora en punto con el patrimonio, para la curva y las ganancias del panel.

        En punto para que la medianoche de quien mira (en una zona de horas enteras) caiga justo
        entre dos fotos.
        """
        ahora = time.time()
        hora = int(ahora // 3600)
        if hora == self.hora_foto:
            return
        self.hora_foto = hora
        nuevo = not os.path.exists(self.ruta_patrimonio)
        with open(self.ruta_patrimonio, "a", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            if nuevo:
                w.writerow(COLUMNAS_PATRIMONIO)
            pesos = self.cartera.pesos(self.precios)
            neto = sum(a + b for a, b in pesos.values())
            w.writerow([datetime.fromtimestamp(ahora, timezone.utc).isoformat(timespec="seconds"),
                        round(self.cartera.patrimonio(self.precios), 2), round(self.cartera.usdt, 2),
                        round(self.cartera.valor_contado(self.precios), 2),
                        round(self.cartera.no_realizado(self.precios), 2), round(neto, 4),
                        self.precios.get(self.p.simbolos[0], ""),
                        round(self.cartera.financiacion, 4), round(self.cartera.comisiones, 4)])

    def _poner_al_dia_curva(self) -> None:
        """Una curva de una versión anterior (sin los acumulados) se reescribe con la cabecera nueva.

        Las filas viejas se quedan con esos dos campos vacíos: no se inventan.
        """
        ruta = self.ruta_patrimonio
        if not os.path.exists(ruta):
            return
        with open(ruta, newline="", encoding="utf-8") as fh:
            cabecera = next(csv.reader(fh), None)
        if not cabecera or cabecera == COLUMNAS_PATRIMONIO:
            return
        with open(ruta, newline="", encoding="utf-8") as fh:
            filas = list(csv.DictReader(fh))
        tmp = ruta + ".tmp"
        with open(tmp, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=COLUMNAS_PATRIMONIO, restval="", extrasaction="ignore")
            w.writeheader()
            w.writerows(filas)
        os.replace(tmp, ruta)
        log.info("Curva de patrimonio puesta al día (%d fotos)", len(filas))

    def _hora_de_la_ultima_foto(self) -> Optional[int]:
        """Para no repetir foto en la misma hora tras un reinicio."""
        puntos = resumen.leer_curva(self.ruta_patrimonio)
        return int(puntos[-1].t.timestamp() // 3600) if puntos else None

    def guardar(self) -> None:
        self.cartera.guardar(self.ruta_estado)
        config.escribir_json(self.ruta_bot, {"mando": self.mando, "ajustes": self.ajustes,
                                              "ultima_decision_t": self.ultima_decision_t})

    def _aviso(self, texto: str) -> None:
        log.warning(texto)
        self.avisos = (self.avisos + [{"utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                       "texto": texto}])[-20:]

    # ── mando desde el panel ──────────────────────────────────────────────────

    def poner_mando(self, mando: str) -> dict:
        if mando not in config.MANDOS:
            raise ValueError(f"mando desconocido: {mando}")
        with self.lock:
            anterior, self.mando = self.mando, mando
            log.info("Mando: %s → %s", anterior, mando)
            hechas = []
            if mando != "pausa" and self.precios:
                # Cubrir, salir o volver a automático se ejecuta ya, sin esperar a la vela.
                hechas = self.decidir(forzar=mando in ("neutral", "fuera"), motivo=f"mando_{mando}")
            self.guardar()
            return {"mando": self.mando, "operaciones": len(hechas)}

    def cambiar_ajustes(self, cambios: dict) -> dict:
        limpio = config.validar_ajustes(cambios)
        with self.lock:
            self.ajustes = {**self.ajustes, **limpio}
            self.p = config.parametros(self.ajustes)
            log.info("Ajustes: %s", limpio)
            self.guardar()
            return {"ajustes": self.ajustes}

    def instantanea(self) -> dict:
        """Todo lo que enseña el panel."""
        with self.lock:
            precios = dict(self.precios)
            pat = self.cartera.patrimonio(precios) if precios else self.cartera.usdt
            pesos = self.cartera.pesos(precios) if precios else {}
            monedas = []
            dec = (self.lectura or self.decision).get("monedas", {})
            for s in self.p.simbolos:
                wc, wp = pesos.get(s, (0.0, 0.0))
                d = dec.get(s, {})
                corto = self.cartera.perp.get(s)
                q_perp = corto.cantidad if corto else 0.0
                monedas.append({
                    "cantidad_base": self.cartera.contado.get(s, 0.0), "cantidad_perp": q_perp,
                    "entrada_perp": corto.entrada if corto and q_perp else None,
                    "no_realizado_perp": (q_perp * (precios[s] - corto.entrada)
                                          if corto and q_perp and s in precios else 0.0),
                    "simbolo": s, "precio": precios.get(s),
                    "puntuacion": d.get("puntuacion"), "vol": d.get("vol"),
                    "base": wc, "cobertura": -wp if wp < 0 else 0.0, "perp": wp, "neto": wc + wp,
                    "base_objetivo": d.get("base"), "neto_objetivo": d.get("neto"),
                    "relojes": d.get("relojes"),
                    "valor_base": wc * pat, "valor_cobertura": -wp * pat if wp < 0 else 0.0,
                })
            c = self.cartera
            return {
                "utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "simulacion": True,
                "mando": self.mando,
                "salud": self.salud(),
                "patrimonio": pat,
                "capital_inicial": c.capital_inicial,
                "ganancia": pat - c.capital_inicial,
                "ganancia_pct": (pat / c.capital_inicial - 1) * 100 if c.capital_inicial else 0.0,
                "usdt": c.usdt,
                "valor_base": c.valor_contado(precios) if precios else 0.0,
                "no_realizado": c.no_realizado(precios) if precios else 0.0,
                "comisiones": c.comisiones,
                "financiacion": c.financiacion,
                "exposicion_neta": sum(m["neto"] for m in monedas),
                "exposicion_base": sum(m["base"] for m in monedas),
                "colchon_margen": None if not precios or c.nocional_perp(precios) == 0
                                  else c.colchon_margen(precios),
                "monedas": monedas,
                "decision": {k: v for k, v in self.decision.items() if k != "monedas"},
                **self._calendario_de_velas(),
                "ajustes": {k: getattr(self.p, k) for k in config.AJUSTABLES},
                "ajustables": config.AJUSTABLES,
                "niveles": config.NIVELES,
                "niveles_periodo": config.NIVELES_PERIODO,
                "nivel": config.nivel_de(self.p),
                "avisos": self.avisos[-5:],
                "creada_utc": c.creada_utc,
            }


    def _calendario_de_velas(self) -> dict:
        """Cuándo cerró la vela de la última decisión y cuándo cierra la siguiente.

        La siguiente decisión es la de la vela que viene detrás de la última decidida: si el bot
        estuvo parado o espera a las rezagadas, esa hora ya pasó y el panel dice «ahora».
        """
        ms = datos.MS[self.p.intervalo]
        ancla = self.velas.get(self.p.simbolos[0])
        if self.ultima_decision_t is not None:
            proxima = self.ultima_decision_t + 2 * ms
        elif ancla is not None and len(ancla):
            proxima = int(ancla.t[-1]) + ms
        else:
            proxima = None

        def iso(t_ms):
            return None if t_ms is None else datetime.fromtimestamp(t_ms / 1000, timezone.utc).isoformat()

        return {
            "intervalo": self.p.intervalo,
            "decision_vela_utc": iso(None if self.ultima_decision_t is None else self.ultima_decision_t + ms),
            "proxima_decision_utc": iso(proxima),
        }

    def ganancias(self, zona: Optional[str]) -> dict:
        """Ganancia por día, semana y mes en la zona horaria de quien mira (ver `bot/resumen.py`)."""
        with self.lock:
            c = self.cartera
            pat = c.patrimonio(self.precios) if self.precios else c.usdt
            ahora = resumen.Punto(datetime.now(timezone.utc), pat, c.financiacion, c.comisiones)
            creada = resumen.instante(c.creada_utc) if c.creada_utc else None
        puntos = resumen.leer_curva(self.ruta_patrimonio)
        if creada is not None:
            inicio = resumen.Punto(creada, c.capital_inicial, 0.0, 0.0)
        elif puntos:
            inicio = puntos[0]
        else:
            inicio = ahora
        return resumen.calcular(puntos, inicio, ahora, zona)

    def grafica(self, simbolo: str, n: int = VELAS_GRAFICA) -> dict:
        """Velas cerradas de una moneda con lo que mira la estrategia, para la gráfica del panel.

        Las medias, los canales y la puntuación salen de la misma cuadrícula y las mismas funciones
        con las que decide el bot. Las operaciones del diario van como marcas en la vela que las
        decidió (la que acababa de cerrar).
        """
        if simbolo not in self.p.simbolos:
            raise ValueError(f"moneda desconocida: {simbolo}")
        ms = datos.MS[self.p.intervalo]
        vd = estrategia.VELAS_DIA[self.p.intervalo]
        vacio = {"simbolo": simbolo, "intervalo": self.p.intervalo, "t": [], "o": [], "h": [], "l": [], "c": [],
                 "medias": {}, "canales": {}, "puntuacion": [], "marcas": [], "precio": self.precios.get(simbolo)}
        v = self.velas.get(simbolo)
        m = self._matrices()
        if v is None or not len(v) or m is None:
            return vacio
        tg, H, L, C = m
        j = self.p.simbolos.index(simbolo)
        ok = ~np.isnan(C[:, j])
        if not ok.any():
            return vacio
        t, h, l, c = tg[ok], H[ok, j], L[ok, j], C[ok, j]
        k = slice(max(0, len(t) - n), len(t))
        aperturas = dict(zip(v.t.tolist(), v.o.tolist()))

        def ultimos(x):
            return [None if np.isnan(y) else round(float(y), 10) for y in x[k]]

        medias = {f"{r}/{s}": {"rapida": ultimos(indicadores.ema(c, r * vd)), "lenta": ultimos(indicadores.ema(c, s * vd))}
                  for r, s in self.p.cruces}
        canales = {}
        for d in self.p.rupturas:
            w = int(round(d * vd))
            alto = np.concatenate(([np.nan], indicadores.maximo(h, w)[:-1]))
            bajo = np.concatenate(([np.nan], indicadores.minimo(l, w)[:-1]))
            canales[str(d)] = {"alto": ultimos(alto), "bajo": ultimos(bajo)}
        t_k = [int(x) for x in t[k]]
        marcas = []
        if t_k and os.path.exists(self.ruta_diario):
            with open(self.ruta_diario, newline="", encoding="utf-8") as fh:
                for f in csv.DictReader(fh):
                    if f.get("simbolo") != simbolo:
                        continue
                    cuando = resumen.instante(f.get("utc"))
                    if cuando is None:
                        continue
                    # La última vela que ya había cerrado cuando se hizo la operación.
                    i = bisect.bisect_right(t_k, int(cuando.timestamp() * 1000) - ms) - 1
                    if i >= 0:
                        marcas.append({"t": t_k[i], "pata": f["pata"], "lado": f["lado"],
                                       "nocional": float(f.get("nocional") or 0), "motivo": f.get("motivo")})
        return {
            **vacio,
            "t": t_k, "o": [round(float(aperturas.get(x, np.nan)), 10) for x in t_k],
            "h": ultimos(h), "l": ultimos(l), "c": ultimos(c),
            "medias": medias, "canales": canales,
            "puntuacion": [round(float(x), 4) for x in estrategia.puntuacion(h, l, c, vd, self.p)[k]],
            "marcas": marcas,
        }

    def mercado(self) -> dict:
        """Cierres de la última semana de cada moneda, para las minigráficas del panel."""
        ms = datos.MS[self.p.intervalo]
        monedas = []
        for s in self.p.simbolos:
            v = self.velas.get(s)
            n = 0 if v is None else min(len(v), VELAS_SEMANA)
            monedas.append({
                "simbolo": s, "precio": self.precios.get(s),
                "t": [int(x) + ms for x in v.t[-n:]] if n else [],      # hora de cierre de cada vela
                "c": [float(x) for x in v.c[-n:]] if n else [],
            })
        return {"intervalo": self.p.intervalo, "monedas": monedas}


def configurar_registro() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
    logging.getLogger("ccxt").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def correr(intervalo_segundos: int = 60) -> None:
    configurar_registro()
    if not config.simulacion():
        raise SystemExit(
            "Este núcleo solo opera en simulación. JORGE_BOT_PAPER=false no está soportado: "
            "operar con dinero real es un paso aparte que no se activa por una variable.")
    bot = Bot()
    log.info("Bot en SIMULACIÓN | %d monedas | velas de %s | mando: %s",
             len(bot.p.simbolos), bot.p.intervalo, bot.mando)
    try:
        from bot import panel
        panel.arrancar(bot)
    except Exception as e:
        log.warning("El panel no arrancó: %s", e)

    ultimo_latido = 0.0
    while True:
        try:
            bot.ciclo()
            if time.time() - ultimo_latido > 900 and bot.precios:
                ultimo_latido = time.time()
                i = bot.instantanea()
                log.info("Patrimonio %.2f USDT (%+.2f %%) | neto %.0f %% | base %.0f %% | datos: %s vía %s",
                         i["patrimonio"], i["ganancia_pct"], i["exposicion_neta"] * 100,
                         i["exposicion_base"] * 100, i["salud"]["estado"], i["salud"]["mercado"])
        except KeyboardInterrupt:
            log.info("Detenido")
            break
        except Exception:
            log.exception("Error en el ciclo")
        time.sleep(intervalo_segundos)
