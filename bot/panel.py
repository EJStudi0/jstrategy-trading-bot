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
"""

from __future__ import annotations

import csv
import hmac
import logging
import os
import secrets
import threading
import time
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from bot import config

log = logging.getLogger("bot")
DIR_ESTATICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_estatico")
CADUCIDAD_CONFIRMACION_S = 45


def _ultimas_filas(ruta: str, n: int) -> list:
    if not os.path.exists(ruta):
        return []
    with open(ruta, newline="", encoding="utf-8") as fh:
        filas = list(csv.DictReader(fh))
    return filas[-n:]


def _serie_patrimonio(ruta: str, maximo: int = 600) -> list:
    filas = _ultimas_filas(ruta, 100_000)
    puntos = []
    for f in filas:
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


def construir_app(bot, token: str):
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

    @app.get("/")
    def raiz():
        return FileResponse(os.path.join(DIR_ESTATICO, "index.html"), headers=sin_cache)

    @app.get("/panel.css")
    def css():
        return FileResponse(os.path.join(DIR_ESTATICO, "panel.css"), headers=sin_cache)

    @app.get("/panel.js")
    def js():
        return FileResponse(os.path.join(DIR_ESTATICO, "panel.js"), headers=sin_cache)

    @app.get("/api/estado", dependencies=[Depends(exigir_token)])
    def estado():
        return JSONResponse(bot.instantanea(), headers=sin_cache)

    @app.get("/api/operaciones", dependencies=[Depends(exigir_token)])
    def operaciones(n: int = 40):
        return JSONResponse(list(reversed(_ultimas_filas(bot.ruta_diario, max(1, min(n, 500))))),
                            headers=sin_cache)

    @app.get("/api/patrimonio", dependencies=[Depends(exigir_token)])
    def patrimonio():
        return JSONResponse(_serie_patrimonio(bot.ruta_patrimonio), headers=sin_cache)

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
            return JSONResponse(bot.poner_mando(pedido), headers=sin_cache)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    @app.post("/api/ajustes", dependencies=[Depends(exigir_token)])
    async def ajustes(request: Request):
        datos = await cuerpo_json(request)
        try:
            return JSONResponse(bot.cambiar_ajustes(datos), headers=sin_cache)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

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
