"""Panel web del bot: ver el estado y mandar (pausar, cubrir, salir, ajustar el riesgo).

Corre en un hilo dentro del proceso del bot, porque lo que maneja vive en su
memoria.

Seguridad
---------
Toda la API exige el token en una CABECERA (`Authorization: Bearer …`). No hay
cookies. El panel anterior guardaba el token en una cookie y la aceptaba en los
POST: cualquier página abierta en el mismo navegador podía pulsarle los botones
(CSRF). Un navegador nunca añade por su cuenta una cabecera `Authorization`, así
que ese ataque deja de existir en vez de mitigarse. La página en sí no lleva
ningún dato: sin token solo enseña el formulario para escribirlo.

Además, cada respuesta lleva una política de contenido estricta: la página solo
ejecuta sus propios ficheros y solo habla con este mismo servidor. Si algún día
se colase texto con forma de código en un dato, el navegador no lo ejecutaría (y
el token, que vive en el almacenamiento del navegador, no tendría adónde ir).
"""

from __future__ import annotations

import csv
import hmac
import logging
import os
import re
import secrets
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from bot import config, puente_centinela

log = logging.getLogger("bot")
# La página es una compilación de `panel/` (React + TypeScript, ver su README): `npm run build`
# deja aquí index.html y sus piezas con nombre de huella en assets/.
DIR_ESTATICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_estatico")
CADUCIDAD_CONFIRMACION_S = 45

# Lo único que se sirve sin token: la página y sus piezas, por tipo y con nombre sencillo. Ningún
# otro fichero, ni nada fuera de esa carpeta.
TIPOS = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
         ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".woff2": "font/woff2",
         ".png": "image/png"}
_NOMBRE_PIEZA = re.compile(r"^(assets/)?[A-Za-z0-9][A-Za-z0-9._-]*$")
POLITICA = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; font-src 'self'; "
            "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
CABECERAS = {
    "Content-Security-Policy": POLITICA,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
}


def ruta_pieza(nombre: str) -> Optional[str]:
    """La ruta en disco de una pieza de la página, o None si no es de las que se sirven."""
    if not _NOMBRE_PIEZA.match(nombre or "") or ".." in nombre:
        return None
    raiz = os.path.realpath(DIR_ESTATICO)
    ruta = os.path.realpath(os.path.join(raiz, nombre))
    if not ruta.startswith(raiz + os.sep) or not os.path.isfile(ruta):
        return None
    return ruta if os.path.splitext(ruta)[1] in TIPOS else None


def piezas() -> dict:
    """Todas las piezas que se sirven, con su tipo (para las pruebas)."""
    out = {}
    for sub in ("", "assets/"):
        carpeta = os.path.join(DIR_ESTATICO, sub)
        if os.path.isdir(carpeta):
            for nombre in sorted(os.listdir(carpeta)):
                if ruta_pieza(sub + nombre):
                    out[sub + nombre] = TIPOS[os.path.splitext(nombre)[1]]
    return out


def _ultimas_filas(ruta: str, n: int) -> list:
    if not os.path.exists(ruta):
        return []
    with open(ruta, newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    return filas[-n:]


def _serie_patrimonio(ruta: str, maximo: int = 600, horas: int = 0) -> list:
    """La curva para la gráfica: las últimas `horas` (0 = toda), aclarada a `maximo` puntos."""
    filas = _ultimas_filas(ruta, 200_000)
    desde = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(timespec="seconds") if horas else ""
    puntos = []
    for f in filas:
        if desde and str(f.get("utc", "")) < desde:
            continue
        try:
            puntos.append({"utc": f["utc"], "patrimonio": float(f["patrimonio"]),
                           "neto": float(f.get("neto") or 0.0),
                           "btc": float(f["btc"]) if f.get("btc") else None})
        except (KeyError, ValueError):
            continue
    if len(puntos) > maximo:      # se aclara conservando siempre el último punto
        paso = len(puntos) / maximo
        puntos = [puntos[int(i * paso)] for i in range(maximo - 1)] + [puntos[-1]]
    return puntos


def _telegram(bot, d: dict) -> dict:
    """Conectar, probar o quitar Telegram. La clave llega en el cuerpo y no se devuelve ni se registra."""
    t = bot.telegram
    if t is None:
        raise ValueError("Telegram no está disponible en este arranque")
    paso = d.get("paso")
    if paso == "clave":
        return t.poner_clave(d.get("token"))
    if paso == "enlazar":
        return t.enlazar()
    if paso == "quitar":
        return t.quitar()
    if paso == "prueba":
        if not t.enviar("🔔 <b>Mensaje de prueba de Bot Jorge.</b>\nSi lees esto, los avisos te llegan bien."):
            raise ValueError("Telegram aún no está conectado")
        return t.estado()
    raise ValueError("paso desconocido")


def construir_app(bot, token: str, dir_centinela: Optional[str] = None):
    dir_centinela = dir_centinela or puente_centinela.DIR_ESTADO
    # Los tipos de FastAPI se importan arriba, a nivel de módulo: con las anotaciones
    # diferidas, `Request` importado aquí dentro no se resuelve y FastAPI lo toma por
    # un parámetro de la URL (todas las rutas contestaban 422).
    if not token:
        raise ValueError("El panel no arranca sin token")
    app = FastAPI(title="Bot Jorge", docs_url=None, redoc_url=None, openapi_url=None)
    pendiente: dict = {}      # confirmación de la orden de salir: {"codigo":…, "caduca":…}

    def exigir_token(request: Request) -> None:
        cabecera = request.headers.get("authorization", "")
        dado = cabecera[7:] if cabecera.lower().startswith("bearer ") else ""
        if not dado or not hmac.compare_digest(dado.encode(), token.encode()):
            raise HTTPException(status_code=401, detail="Token incorrecto")

    async def cuerpo_json(request: Request) -> dict:
        if "application/json" not in request.headers.get("content-type", ""):
            raise HTTPException(status_code=415, detail="Se espera JSON")
        try:
            datos = await request.json()
        except Exception:
            raise HTTPException(status_code=400, detail="JSON inválido")
        if not isinstance(datos, dict):
            raise HTTPException(status_code=400, detail="Se espera un objeto")
        return datos

    sin_cache = {"Cache-Control": "no-store"}

    @app.middleware("http")
    async def cabeceras(request: Request, siguiente):
        respuesta = await siguiente(request)
        for k, v in CABECERAS.items():
            respuesta.headers.setdefault(k, v)
        return respuesta

    def estatico(nombre: str):
        ruta = ruta_pieza(nombre)
        if ruta is None:
            raise HTTPException(status_code=404, detail="No existe")
        # Las piezas de assets/ llevan su huella en el nombre: si cambian, cambia el nombre.
        cache = ({"Cache-Control": "public, max-age=31536000, immutable"} if nombre.startswith("assets/")
                 else sin_cache)
        return FileResponse(ruta, media_type=TIPOS[os.path.splitext(ruta)[1]], headers=cache)

    @app.get("/")
    def raiz():
        return estatico("index.html")

    @app.get("/api/estado", dependencies=[Depends(exigir_token)])
    def estado():
        return JSONResponse(bot.instantanea(), headers=sin_cache)

    @app.get("/api/operaciones", dependencies=[Depends(exigir_token)])
    def operaciones(n: int = 40):
        return JSONResponse(list(reversed(_ultimas_filas(bot.ruta_diario, max(1, min(n, 500))))),
                            headers=sin_cache)

    @app.get("/api/patrimonio", dependencies=[Depends(exigir_token)])
    def patrimonio(horas: int = 0):
        return JSONResponse(_serie_patrimonio(bot.ruta_patrimonio, horas=max(0, min(horas, 200_000))),
                            headers=sin_cache)

    @app.get("/api/ganancias", dependencies=[Depends(exigir_token)])
    def ganancias(zona: str = "UTC"):
        return JSONResponse(bot.ganancias(zona), headers=sin_cache)

    @app.get("/api/mercado", dependencies=[Depends(exigir_token)])
    def mercado():
        return JSONResponse(bot.mercado(), headers=sin_cache)

    @app.get("/api/grafica", dependencies=[Depends(exigir_token)])
    def grafica(simbolo: str, n: int = 360):
        try:
            return JSONResponse(bot.grafica(simbolo, max(30, min(n, 1500))), headers=sin_cache)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/mando", dependencies=[Depends(exigir_token)])
    async def mando(request: Request):
        datos = await cuerpo_json(request)
        pedido = datos.get("mando")
        if pedido not in config.MANDOS:
            raise HTTPException(status_code=400, detail="Mando desconocido")
        # Salir a USDT vende toda la base: se pide dos veces, la segunda con un código.
        if pedido == "fuera" and bot.mando != "fuera":
            codigo = datos.get("confirmacion")
            vigente = pendiente.get("codigo") and pendiente.get("caduca", 0) > time.time()
            if not (codigo and vigente and hmac.compare_digest(str(codigo), pendiente["codigo"])):
                pendiente["codigo"] = secrets.token_urlsafe(12)
                pendiente["caduca"] = time.time() + CADUCIDAD_CONFIRMACION_S
                return JSONResponse({"confirmar": pendiente["codigo"],
                                     "caduca_en_s": CADUCIDAD_CONFIRMACION_S}, headers=sin_cache)
            pendiente.clear()
        try:
            return JSONResponse(bot.poner_mando(pedido, datos.get("horas") or 0), headers=sin_cache)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/ajustes", dependencies=[Depends(exigir_token)])
    async def ajustes(request: Request):
        datos = await cuerpo_json(request)
        try:
            return JSONResponse(bot.cambiar_ajustes(datos), headers=sin_cache)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Asistente: avisos de patrones, cuenta de operaciones a mano y vetos por moneda. Todo simulado.
    @app.get("/api/asistente", dependencies=[Depends(exigir_token)])
    def asistente():
        with bot.lock:
            i = bot.asistente.instantanea(dict(bot.precios))
            i["telegram"] = bot.telegram.estado() if bot.telegram else {"configurado": False, "bot": None, "codigo": None}
            return JSONResponse(i, headers=sin_cache)

    @app.post("/api/asistente/{accion}", dependencies=[Depends(exigir_token)])
    async def asistente_accion(accion: str, request: Request):
        d = await cuerpo_json(request)
        a = bot.asistente
        try:
            if accion == "telegram":   # habla con Telegram: fuera del candado, para no parar al bot
                return JSONResponse(_telegram(bot, d), headers=sin_cache)
            with bot.lock:
                precios = dict(bot.precios)
                if accion == "abrir":
                    r = a.abrir(d.get("simbolo"), d.get("lado"), d.get("usdt"), precios, d.get("stop"),
                                d.get("objetivo"), d.get("nota") or "", d.get("alerta"))
                elif accion == "cerrar":
                    r = a.cerrar(d.get("id"), precios, d.get("parte") or 1.0)
                elif accion == "mover":
                    r = a.mover(d.get("id"), precios, d.get("stop"), d.get("objetivo"))
                elif accion == "veto":
                    r = bot.poner_veto(d.get("simbolo"), d.get("modo"), d.get("horas") or 0)
                elif accion == "cerrar_todas":
                    r = a.cerrar_todas(precios)
                elif accion == "reiniciar":
                    r = a.reiniciar_cuenta(d.get("capital"))
                elif accion == "nivel":
                    r = a.quitar_nivel(d["id"]) if d.get("id") else a.poner_nivel(d.get("simbolo"), d.get("precio"), precios, d.get("nota") or "")
                elif accion == "prefs":
                    r = a.cambiar_prefs(d)
                elif accion == "vistas":
                    a.marcar_vistas()
                    r = {"ok": True}
                else:
                    raise HTTPException(status_code=404, detail="Acción desconocida")
            return JSONResponse(r, headers=sin_cache)
        except (ValueError, TypeError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # ── Centinela: el segundo bot. Corre en su proceso; aquí se lee su estado y se enciende o apaga.
    @app.get("/api/centinela", dependencies=[Depends(exigir_token)])
    def centinela():
        return JSONResponse(puente_centinela.instantanea(dir_centinela), headers=sin_cache)

    @app.get("/api/centinela/patrimonio", dependencies=[Depends(exigir_token)])
    def centinela_patrimonio(horas: int = 0):
        return JSONResponse(puente_centinela.curva(dir_centinela, horas=max(0, min(horas, 200_000))),
                            headers=sin_cache)

    @app.post("/api/centinela/interruptor", dependencies=[Depends(exigir_token)])
    async def centinela_interruptor(request: Request):
        datos = await cuerpo_json(request)
        pedido = datos.get("encendido")
        if not isinstance(pedido, bool):
            raise HTTPException(status_code=400, detail="Se espera encendido: true o false")
        try:
            return JSONResponse(puente_centinela.poner_interruptor(pedido, dir_centinela), headers=sin_cache)
        except (ValueError, OSError) as e:
            raise HTTPException(status_code=400, detail=str(e))

    # Al final, para que no tapen ninguna ruta de la API.
    @app.get("/assets/{nombre}")
    def pieza_assets(nombre: str):
        return estatico("assets/" + nombre)

    @app.get("/{nombre}")
    def pieza(nombre: str):
        if nombre == "index.html":
            raise HTTPException(status_code=404, detail="No existe")
        return estatico(nombre)

    return app


def arrancar(bot) -> Optional[threading.Thread]:
    cfg = config.panel()
    if not cfg["activo"]:
        return None
    if not cfg["token"]:
        log.warning("Panel apagado: falta JORGE_BOT_PANEL_TOKEN en .env")
        return None
    import uvicorn

    app = construir_app(bot, cfg["token"])
    servidor = uvicorn.Server(uvicorn.Config(app, host=cfg["host"], port=cfg["puerto"],
                                             log_level="warning", access_log=False))

    def servir():
        try:
            servidor.run()
        except Exception:
            log.exception("El panel se cayó")

    hilo = threading.Thread(target=servir, name="panel", daemon=True)
    hilo.start()
    # El token NO va al registro: lo lee más gente que .env.
    log.info("Panel en http://%s:%s/", cfg["host"], cfg["puerto"])
    return hilo
