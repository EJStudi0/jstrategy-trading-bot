"""Avisos del bot al Telegram del dueño. Solo ENVÍA: no acepta órdenes por Telegram.

La clave del bot de Telegram la pone el dueño desde el panel y se guarda en `telegram.json` (fuera de
git, solo legible por el usuario). Para saber a qué chat escribir, el dueño le manda al bot un código
que enseña el panel: así nadie más puede quedarse con los avisos.

El envío va por una cola y un hilo aparte: una red lenta no frena el ciclo del bot. La clave va en la
dirección de la API (así lo pide Telegram), por eso de un fallo solo se registra el tipo, nunca el texto.
Los textos se arman con funciones puras para poder probarlos.
"""
from __future__ import annotations

import html
import logging
import os
import queue
import re
import secrets
import threading
import time
from typing import Callable, Optional

import requests

from bot import config

log = logging.getLogger("jorge.telegram")

NIVELES = ("todas", "importantes", "fuertes")          # qué avisos de patrones salen fuera
PREFS = {"activo": True, "nivel": "importantes", "operaciones": True, "resumen": True}
HORA_RESUMEN_UTC = 12
_PASA = {"todas": ("alta", "media", "baja"), "importantes": ("alta", "media"), "fuertes": ("alta",)}
_COLOR = {"alta": "🔴", "media": "🟠", "baja": "⚪"}
_FLECHA = {1: "↑ arriba", -1: "↓ abajo", 0: ""}
_MOTIVO = {"vela": "vela nueva", "mando_auto": "vuelta a automático", "mando_neutral": "mando «cubrir todo»",
           "mando_fuera": "mando «salir de todo»", "veto": "veto sobre una moneda", "ajustes": "cambio de ajustes",
           "reponer_garantia": "reponer garantía"}


def validar_prefs(d) -> dict:
    if not isinstance(d, dict) or not set(d) <= set(PREFS):
        raise ValueError("preferencias de Telegram no válidas")
    for k, v in d.items():
        if k == "nivel":
            if v not in NIVELES:
                raise ValueError("nivel de avisos desconocido")
        elif not isinstance(v, bool):
            raise ValueError("preferencias de Telegram no válidas")
    return d


def pasa(alerta: dict, nivel: str) -> bool:
    """¿Este aviso de patrón sale a Telegram con ese nivel? Los precios vigilados salen siempre."""
    if alerta.get("patron") == "nivel":
        return True
    return not alerta.get("callada") and alerta.get("fuerza") in _PASA.get(nivel, _PASA["importantes"])


# ── textos ────────────────────────────────────────────────────────────────────

def num(x, dec: Optional[int] = None) -> str:
    """Número a la española. Sin `dec`, los decimales que pide el tamaño del precio."""
    if x is None:
        return "—"
    x = float(x)
    if dec is None:
        a = abs(x)
        dec = 0 if a >= 10_000 else 2 if a >= 100 else 3 if a >= 1 else 5
    return f"{x:,.{dec}f}".replace(",", "§").replace(".", ",").replace("§", ".")


def con_signo(x, dec: int = 2) -> str:
    return ("+" if float(x) >= 0 else "−") + num(abs(float(x)), dec)


def moneda(simbolo: str) -> str:
    s = str(simbolo).split(":")[0].replace("/", "")
    return s[:-4] if s.endswith("USDT") else s


def _e(x) -> str:
    return html.escape(str(x), quote=False)


def texto_alerta(al: dict, catalogo: dict) -> str:
    if al.get("patron") == "nivel":
        nota = f"\n«{_e(al['nota'])}»" if al.get("nota") else ""
        return (f"🎯 <b>{moneda(al['simbolo'])} cruzó {num(al.get('nivel'))}</b>\n"
                f"Ahora está en {num(al['precio'])}. Es el precio que pediste vigilar.{nota}")
    c = catalogo.get(al["patron"], {})
    lado = al.get("lado", 0)
    lineas = [f"{_COLOR.get(al.get('fuerza'), '⚪')} <b>{moneda(al['simbolo'])} · {_e(c.get('nombre', al['patron']))}</b> {_FLECHA.get(lado, '')}".rstrip(),
              _e(c.get("que", ""))]
    fondo = {1: "alcista", -1: "bajista", 0: "sin dirección"}.get(al.get("fondo", 0), "sin dirección")
    lineas.append(f"Precio {num(al['precio'])} · fondo {fondo}")
    if lado and al.get("stop") is not None:
        lejos = abs(al["stop"] / al["precio"] - 1) * 100
        lineas.append(f"Stop orientativo {num(al['stop'])} (a {num(lejos, 1)} %)")
    p = al.get("previo")
    if lado and p and p.get("n"):
        lineas.append(f"Último mes: {p['n']} veces, {p['a_favor_pct']} % a favor a las 24 h, media {con_signo(p['media_pct'])} %")
    if c.get("medido"):
        lineas.append(f"<i>{_e(c['medido'])}</i>")
    return "\n".join(x for x in lineas if x)


def texto_cierre(fila: dict) -> str:
    por = {"stop": "saltó el stop", "objetivo": "llegó al objetivo", "liquidada": "la cuenta se quedó sin saldo"}.get(fila["motivo"], fila["motivo"])
    cara = "✅" if fila["neto"] > 0 else "❌"
    lado = "largo" if fila["lado"] > 0 else "corto"
    return (f"{cara} <b>Tu {lado} de {moneda(fila['simbolo'])} se cerró: {por}</b>\n"
            f"Entrada {num(fila['entrada'])} → salida {num(fila['salida'])}\n"
            f"Resultado {con_signo(fila['neto'])} USDT (cuenta manual, dinero ficticio)")


def texto_operaciones(hechas: list, motivo: str, patrimonio: Optional[float] = None, tope: int = 8) -> str:
    lineas = [f"🤖 <b>Jorge operó</b> · {_e(_MOTIVO.get(motivo, motivo))}"]
    for f in hechas[:tope]:
        pata = "contado" if f["pata"] == "contado" else "futuros"
        lineas.append(f"{'🟢 Compra' if f['lado'] == 'compra' else '🔻 Venta'} {moneda(f['simbolo'])} {pata} · {num(f['nocional'], 0)} USDT a {num(f['precio'])}")
    if len(hechas) > tope:
        lineas.append(f"… y {len(hechas) - tope} más")
    if patrimonio:
        lineas.append(f"Patrimonio {num(patrimonio, 2)} USDT (simulación)")
    return "\n".join(lineas)


def texto_resumen(i: dict, manual: dict, avisos_24h: int, cambio_24h: Optional[float]) -> str:
    """`i` = instantánea del bot; `manual` = la cuenta manual del asistente."""
    lineas = ["📊 <b>Resumen del día · Bot Jorge</b> (simulación)",
              f"Patrimonio {num(i['patrimonio'], 2)} USDT ({con_signo(i['ganancia_pct'])} % desde el inicio)"]
    if cambio_24h is not None:
        lineas.append(f"Últimas 24 h: {con_signo(cambio_24h)} %")
    lineas.append(f"Mando: {_e(i.get('mando', 'auto'))} · apuesta neta {num(100 * i.get('exposicion_neta', 0), 0)} %")
    n = len(manual.get("posiciones", []))
    lineas.append(f"Cuenta manual: {num(manual['patrimonio'], 2)} USDT ({con_signo(manual['ganancia'])}) · "
                  f"{n} {'operación abierta' if n == 1 else 'operaciones abiertas'}")
    lineas.append(f"Avisos en 24 h: {avisos_24h}")
    return "\n".join(lineas)


# ── envío ─────────────────────────────────────────────────────────────────────

RUTA = os.path.join(os.path.dirname(config.RUTA_BOT), "telegram.json")
_FORMA_CLAVE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,}$")


def _por_red(token: str, metodo: str, datos: dict) -> dict:
    """Una llamada a la API. Los fallos salen sin texto: llevan la dirección, y la dirección lleva la clave."""
    try:
        return requests.post(f"https://api.telegram.org/bot{token}/{metodo}", json=datos, timeout=15).json()
    except Exception as e:
        raise ConnectionError(type(e).__name__) from None


class Telegram:
    def __init__(self, ruta: Optional[str] = RUTA, api: Optional[Callable] = None, hilo: bool = True):
        self.ruta = ruta
        self._api = api or _por_red
        g = config.leer_json(ruta) if ruta else {}
        self.token: str = g.get("token", "")
        self.chat = g.get("chat")
        self.bot: str = g.get("bot", "")
        self.codigo: str = g.get("codigo", "")
        self.resumen_dia: str = g.get("resumen_dia", "")
        self._cola: queue.Queue = queue.Queue(maxsize=200)
        self._ultimo: dict = {}
        self.fallos = 0
        if hilo:
            threading.Thread(target=self._bucle, name="telegram", daemon=True).start()

    # ── conexión ──

    @property
    def configurado(self) -> bool:
        return bool(self.token and self.chat)

    def estado(self) -> dict:
        """Para el panel. La clave no sale nunca."""
        return {"configurado": self.configurado, "bot": self.bot or None,
                "codigo": self.codigo if self.token and not self.chat else None}

    def guardar(self) -> None:
        if self.ruta:
            config.escribir_json(self.ruta, {"token": self.token, "chat": self.chat, "bot": self.bot,
                                             "codigo": self.codigo, "resumen_dia": self.resumen_dia})

    def poner_clave(self, token) -> dict:
        """Paso 1: comprueba la clave con Telegram y prepara el código que el dueño mandará al bot."""
        token = str(token or "").strip()
        if not _FORMA_CLAVE.match(token):
            raise ValueError("Eso no parece una clave de bot de Telegram. Cópiala entera de BotFather.")
        try:
            r = self._api(token, "getMe", {})
        except ConnectionError:
            raise ValueError("No pude hablar con Telegram ahora mismo. Prueba otra vez.") from None
        if not r.get("ok"):
            raise ValueError("Telegram no reconoce esa clave. Revisa que esté completa.")
        self.token, self.chat, self.bot = token, None, r["result"].get("username", "")
        self.codigo = f"{secrets.randbelow(900_000) + 100_000}"
        self.guardar()
        log.info("Telegram: clave nueva puesta para @%s; falta enlazar el chat", self.bot)
        return self.estado()

    def enlazar(self) -> dict:
        """Paso 2: busca el mensaje con el código entre lo que le han escrito al bot y se queda con ese chat."""
        if not self.token:
            raise ValueError("Primero pon la clave del bot.")
        try:
            r = self._api(self.token, "getUpdates", {"timeout": 0, "allowed_updates": ["message"]})
        except ConnectionError:
            raise ValueError("No pude hablar con Telegram ahora mismo. Prueba otra vez.") from None
        for u in reversed(r.get("result") or []):
            m = u.get("message") or {}
            if (m.get("chat") or {}).get("type") == "private" and self.codigo and self.codigo in str(m.get("text", "")):
                self.chat, self.codigo = m["chat"]["id"], ""
                self.guardar()
                log.info("Telegram: chat enlazado")
                self.enviar("✅ <b>Bot Jorge conectado.</b>\nA partir de ahora los avisos te llegan aquí. "
                            "Es todo simulación: dinero ficticio.")
                return self.estado()
        raise ValueError(f"Todavía no veo tu mensaje. Abre @{self.bot} en Telegram, pulsa Iniciar y envíale el código {self.codigo}.")

    def quitar(self) -> dict:
        self.token, self.chat, self.bot, self.codigo = "", None, "", ""
        self.guardar()
        log.info("Telegram: desconectado")
        return self.estado()

    def marcar_resumen(self, dia: str) -> None:
        self.resumen_dia = dia
        self.guardar()

    # ── mensajes ──

    def enviar(self, texto: str, clave: Optional[str] = None, cada_s: float = 3600, silencio: bool = False) -> bool:
        """Encola un mensaje. `clave` agrupa los repetitivos: uno cada `cada_s` segundos como mucho."""
        if not self.configurado:
            return False
        if clave is not None:
            ahora = time.time()
            if ahora - self._ultimo.get(clave, 0.0) < cada_s:
                return False
            self._ultimo[clave] = ahora
        try:
            self._cola.put_nowait((texto[:4000], silencio))
            return True
        except queue.Full:
            return False

    def vaciar(self) -> None:
        """Manda lo que haya en la cola, en este hilo (pruebas)."""
        while not self._cola.empty():
            self._uno(*self._cola.get_nowait(), pausa=0)

    def _bucle(self) -> None:
        while True:
            self._uno(*self._cola.get())
            time.sleep(1.1)   # Telegram admite del orden de un mensaje por segundo a un mismo chat

    def _uno(self, texto: str, silencio: bool, pausa: float = 5) -> None:
        for intento in range(3):
            try:
                r = self._api(self.token, "sendMessage", {"chat_id": self.chat, "text": texto, "parse_mode": "HTML",
                                                          "disable_web_page_preview": True, "disable_notification": silencio})
            except Exception as e:
                self.fallos += 1
                log.warning("Telegram no contestó (%s), intento %d", type(e).__name__, intento + 1)
                time.sleep(pausa * (intento + 1))
                continue
            if r.get("ok"):
                return
            espera = (r.get("parameters") or {}).get("retry_after")
            if not espera:
                self.fallos += 1
                log.warning("Telegram rechazó un mensaje (código %s)", r.get("error_code"))
                return
            time.sleep(min(float(espera), 60) if pausa else 0)
