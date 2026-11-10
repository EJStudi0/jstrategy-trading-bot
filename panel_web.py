"""Panel de control web del bot Jorge.

Corre como un hilo daemon DENTRO del proceso del bot, igual que el listener de
Telegram. No es una preferencia de arquitectura: el estado que este panel tiene
que manejar — la pausa global, el tracker diario, los managers de posición —
vive en memoria de ese proceso, y desde fuera no hay forma de tocarlo sin
inventar un canal aparte que habría que mantener sincronizado.

Se sirve solo en la LAN y detrás de un token. Aunque el acceso ya esté cerrado
por VPN, esto abre y cierra posiciones: no se deja sin llave.
"""

import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime
from typing import Any, Callable, Optional

logger = logging.getLogger("jorge_bot")

DIRECTORIO_ESTATICO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "panel_static")

# Parámetros que el panel puede tocar sin reiniciar, con su tipo y sus límites.
# `alcance` es una promesa al usuario, así que refleja la realidad del código:
# los managers guardan una REFERENCIA a su dict de config, de modo que mutarlo
# in situ llega a todo lo que se lee en tiempo de uso. Lo único que quedó
# congelado en el arranque es el símbolo, porque los managers se crean por
# símbolo antes de entrar al bucle.
PARAMETROS_EDITABLES: dict = {
    "min_score_to_enter":         {"tipo": "int",   "min": 0,    "max": 13,   "paso": 1,    "alcance": "caliente", "grupo": "Selectividad",   "etiqueta": "Score mínimo para entrar (largo)"},
    "min_score_short":            {"tipo": "int",   "min": 0,    "max": 13,   "paso": 1,    "alcance": "caliente", "grupo": "Selectividad",   "etiqueta": "Score mínimo en cortos"},
    "pending_min_score":          {"tipo": "int",   "min": 0,    "max": 13,   "paso": 1,    "alcance": "caliente", "grupo": "Selectividad",   "etiqueta": "Score mínimo para armar pendiente"},
    "high_conviction_score":      {"tipo": "int",   "min": 0,    "max": 13,   "paso": 1,    "alcance": "caliente", "grupo": "Selectividad",   "etiqueta": "Score de alta convicción"},
    "risk_capital_pct":           {"tipo": "float", "min": 0.01, "max": 0.5,  "paso": 0.01, "alcance": "caliente", "grupo": "Riesgo",         "etiqueta": "Riesgo por trade (fracción del capital)"},
    "leverage":                   {"tipo": "int",   "min": 1,    "max": 25,   "paso": 1,    "alcance": "caliente", "grupo": "Riesgo",         "etiqueta": "Apalancamiento"},
    "max_concurrent_positions":   {"tipo": "int",   "min": 1,    "max": 5,    "paso": 1,    "alcance": "caliente", "grupo": "Riesgo",         "etiqueta": "Posiciones simultáneas"},
    "daily_profit_target_usdt":   {"tipo": "float", "min": 1,    "max": 500,  "paso": 1,    "alcance": "caliente", "grupo": "Cortacircuitos", "etiqueta": "Objetivo diario (USDT)"},
    "daily_loss_limit_usdt":      {"tipo": "float", "min": 1,    "max": 500,  "paso": 1,    "alcance": "caliente", "grupo": "Cortacircuitos", "etiqueta": "Límite de pérdida diaria (USDT)"},
    "session_start_utc":          {"tipo": "int",   "min": 0,    "max": 23,   "paso": 1,    "alcance": "caliente", "grupo": "Cortacircuitos", "etiqueta": "Sesión desde (UTC)"},
    "session_end_utc":            {"tipo": "int",   "min": 0,    "max": 23,   "paso": 1,    "alcance": "caliente", "grupo": "Cortacircuitos", "etiqueta": "Sesión hasta (UTC)"},
    "blind_after_seconds":        {"tipo": "float", "min": 60,   "max": 7200, "paso": 60,   "alcance": "caliente", "grupo": "Vigilancia",     "etiqueta": "Datos viejos tras (s)"},
    "rebuild_client_after_failures": {"tipo": "int", "min": 1,   "max": 20,   "paso": 1,    "alcance": "caliente", "grupo": "Vigilancia",     "etiqueta": "Rehacer cliente tras N fallos"},
}


class ContextoPanel:
    """Lo que el panel necesita del bot, pasado explícitamente.

    Se recibe el módulo del bot en vez de importarlo para no crear un ciclo de
    imports, y porque así queda a la vista qué toca el panel exactamente.
    """

    def __init__(self, bot: Any, cfg: dict, managers: dict):
        self.bot = bot
        self.cfg = cfg
        self.managers = managers
        self.arrancado_utc = datetime.utcnow().isoformat()
        self._cierre_pendiente: Optional[tuple] = None   # (token, caduca_en)

    # ── lectura ────────────────────────────────────────────────────────────
    def salud(self) -> dict:
        return self.bot.salud_datos(self.cfg)

    def analisis(self) -> dict:
        instantaneas = getattr(self.bot, "_ULTIMO_ANALISIS", {})
        simbolo = self.cfg.get("symbol")
        return instantaneas.get(simbolo) or (next(iter(instantaneas.values()), None) or {})

    def metricas(self) -> dict:
        return self.bot._compute_trade_metrics(self.cfg)

    def pausado(self) -> bool:
        return bool(self.bot._BOT_PAUSED[0] or self.bot._DAILY_TRACKER.get("paused"))

    def posiciones(self) -> list:
        abiertas = []
        for simbolo, manager in self.managers.items():
            for nombre in ("active_long", "active_short", "active_standalone_short"):
                pos = getattr(manager, nombre, None)
                if pos:
                    abiertas.append({"symbol": simbolo, "tipo": nombre, "posicion": _jsonable(pos)})
        return abiertas

    def capital(self) -> dict:
        balance = 0.0
        equity = 0.0
        for manager in self.managers.values():
            try:
                balance += float(manager.get_balance())
            except Exception:
                pass
            try:
                equity += float(manager.get_equity())
            except Exception:
                pass
        inicial = float(self.cfg.get("total_capital_usdt", 0) or 0)
        tracker = self.bot._DAILY_TRACKER
        return {
            "inicial": inicial,
            "balance": round(balance, 2),
            "equity": round(equity or balance, 2),
            "variacion": round((equity or balance) - inicial, 2),
            "pnl_hoy": round(float(tracker.get("realized_pnl") or 0.0), 2),
            "objetivo_diario": float(self.cfg.get("daily_profit_target_usdt", 0) or 0),
            "limite_diario": float(self.cfg.get("daily_loss_limit_usdt", 0) or 0),
            "pausado_por_limite": bool(tracker.get("paused")),
        }

    def estado(self) -> dict:
        salud = self.salud()
        return {
            "salud": salud,
            "analisis": self.analisis(),
            "capital": self.capital(),
            "posiciones": self.posiciones(),
            "pausado": self.pausado(),
            "pausado_manual": bool(self.bot._BOT_PAUSED[0]),
            "modo": "paper" if self.cfg.get("paper_trading", True) else "real",
            "symbol": self.cfg.get("symbol"),
            "max_positions": int(self.cfg.get("max_positions", 1) or 1),
            "sesion": [self.cfg.get("session_start_utc"), self.cfg.get("session_end_utc")],
            "arrancado_utc": self.arrancado_utc,
            "ahora_utc": datetime.utcnow().isoformat(),
        }

    # ── escritura ──────────────────────────────────────────────────────────
    def aplicar_parametros(self, cambios: dict) -> dict:
        """Aplica parámetros sobre el proceso vivo.

        Muta el dict de config EN SITU (nunca lo reemplaza) porque los managers
        guardan una referencia a él: reasignarlo dejaría al bot leyendo el dict
        viejo sin que nada lo delatara.
        """
        aplicados, rechazados = {}, {}
        for clave, valor in cambios.items():
            spec = PARAMETROS_EDITABLES.get(clave)
            if spec is None:
                rechazados[clave] = "parámetro no editable desde el panel"
                continue
            try:
                convertido = int(valor) if spec["tipo"] == "int" else float(valor)
            except (TypeError, ValueError):
                rechazados[clave] = f"valor no numérico: {valor!r}"
                continue
            if not (spec["min"] <= convertido <= spec["max"]):
                rechazados[clave] = f"fuera de rango [{spec['min']}, {spec['max']}]"
                continue
            aplicados[clave] = convertido

        if aplicados:
            self.cfg.update(aplicados)
            for manager in self.managers.values():
                cfg_manager = getattr(manager, "cfg", None)
                if isinstance(cfg_manager, dict) and cfg_manager is not self.cfg:
                    cfg_manager.update(aplicados)
            logger.info(f"⚙️  Panel: parámetros aplicados en caliente → {aplicados}")

        return {"aplicados": aplicados, "rechazados": rechazados}

    def set_pausa(self, pausado: bool) -> dict:
        self.bot._BOT_PAUSED[0] = bool(pausado)
        logger.info(f"⏸️  Panel: bot {'PAUSADO' if pausado else 'REANUDADO'}")
        return {"pausado": self.pausado(), "pausado_manual": bool(pausado)}

    def armar_cierre(self) -> dict:
        """Primer paso del cierre. Devuelve un token de un solo uso."""
        token = secrets.token_urlsafe(12)
        self._cierre_pendiente = (token, time.time() + 60)
        return {"token": token, "caduca_en_segundos": 60, "posiciones": self.posiciones()}

    def confirmar_cierre(self, token: str) -> dict:
        pendiente = self._cierre_pendiente
        self._cierre_pendiente = None
        if not pendiente:
            return {"ok": False, "error": "no hay ningún cierre armado"}
        esperado, caduca = pendiente
        if time.time() > caduca:
            return {"ok": False, "error": "la confirmación caducó, vuelve a armar"}
        if not secrets.compare_digest(token or "", esperado):
            return {"ok": False, "error": "token de confirmación inválido"}

        cerrados, errores = [], []
        paper = bool(self.cfg.get("paper_trading", True))

        if paper:
            # En paper las posiciones viven en el manager, no en el exchange.
            # `_close_all_positions` consulta al exchange, así que en este modo
            # no encontraría nada que cerrar — el /close de Telegram tenía ese
            # mismo agujero y nunca cerró una posición simulada.
            for simbolo, manager in self.managers.items():
                cerrar = getattr(manager, "force_close_all", None)
                if not callable(cerrar):
                    errores.append(f"{simbolo}: el manager no expone force_close_all")
                    continue
                precio = (self.analisis() or {}).get("precio")
                if precio is None:
                    errores.append(f"{simbolo}: sin precio conocido, no se cierra a ciegas")
                    continue
                try:
                    cerrar(float(precio), reason="panel_manual")
                    cerrados.append(simbolo)
                except Exception as e:
                    errores.append(f"{simbolo}: {e}")
        else:
            try:
                resumen = self.bot._close_all_positions(self.cfg)
                cerrados.append(str(resumen))
            except Exception as e:
                errores.append(str(e))

        logger.warning(f"🔻 Panel: cierre manual — cerrados={cerrados} errores={errores}")
        return {"ok": not errores, "cerrados": cerrados, "errores": errores}


def _jsonable(valor):
    """Convierte lo que venga del bot en algo que json.dumps acepte."""
    if isinstance(valor, dict):
        return {k: _jsonable(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_jsonable(v) for v in valor]
    if isinstance(valor, (str, int, float, bool)) or valor is None:
        return valor
    return str(valor)


def construir_app(ctx: ContextoPanel, token: str):
    from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
    from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
    from fastapi.staticfiles import StaticFiles

    app = FastAPI(title="Panel Bot Jorge", docs_url=None, redoc_url=None, openapi_url=None)

    def exigir_token(request: Request) -> None:
        entrante = (request.headers.get("x-panel-token")
                    or request.cookies.get("panel_token")
                    or request.query_params.get("token") or "")
        if not secrets.compare_digest(entrante, token):
            raise HTTPException(status_code=401, detail="token inválido")

    @app.get("/")
    def raiz(response: Response, token_query: str = Query("", alias="token")):
        # El token entra por la URL una vez y se queda en una cookie; así las
        # llamadas del navegador no lo llevan colgando en cada petición.
        if secrets.compare_digest(token_query, token):
            respuesta = FileResponse(os.path.join(DIRECTORIO_ESTATICO, "index.html"))
            respuesta.set_cookie("panel_token", token, httponly=True, samesite="lax", max_age=60 * 60 * 24 * 30)
            return respuesta
        return FileResponse(os.path.join(DIRECTORIO_ESTATICO, "index.html"))

    @app.get("/api/estado", dependencies=[Depends(exigir_token)])
    def api_estado():
        return JSONResponse(_jsonable(ctx.estado()))

    @app.get("/api/metricas", dependencies=[Depends(exigir_token)])
    def api_metricas():
        return JSONResponse(_jsonable(ctx.metricas()))

    @app.get("/api/trades", dependencies=[Depends(exigir_token)])
    def api_trades():
        return JSONResponse(_jsonable(_trades_y_cortes(ctx)))

    @app.get("/api/parametros", dependencies=[Depends(exigir_token)])
    def api_parametros_get():
        return JSONResponse({
            "valores": {k: ctx.cfg.get(k) for k in PARAMETROS_EDITABLES},
            "spec": PARAMETROS_EDITABLES,
        })

    @app.post("/api/parametros", dependencies=[Depends(exigir_token)])
    async def api_parametros_post(request: Request):
        cuerpo = await request.json()
        return JSONResponse(ctx.aplicar_parametros(cuerpo.get("cambios") or {}))

    @app.post("/api/pausa", dependencies=[Depends(exigir_token)])
    async def api_pausa(request: Request):
        cuerpo = await request.json()
        return JSONResponse(ctx.set_pausa(bool(cuerpo.get("pausado"))))

    @app.post("/api/cerrar/armar", dependencies=[Depends(exigir_token)])
    def api_cerrar_armar():
        return JSONResponse(_jsonable(ctx.armar_cierre()))

    @app.post("/api/cerrar/confirmar", dependencies=[Depends(exigir_token)])
    async def api_cerrar_confirmar(request: Request):
        cuerpo = await request.json()
        return JSONResponse(_jsonable(ctx.confirmar_cierre(cuerpo.get("token", ""))))

    @app.get("/api/stream", dependencies=[Depends(exigir_token)])
    def api_stream():
        def eventos():
            while True:
                try:
                    yield f"data: {json.dumps(_jsonable(ctx.estado()))}\n\n"
                except Exception as e:
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                time.sleep(5)
        return StreamingResponse(eventos(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    app.mount("/static", StaticFiles(directory=DIRECTORIO_ESTATICO), name="static")
    return app


def _trades_y_cortes(ctx: ContextoPanel) -> dict:
    """Trades agrupados más los cortes de win rate que diagnostican la puntería."""
    import pandas as pd

    ruta = ctx.cfg.get("trade_journal_file", getattr(ctx.bot, "TRADE_JOURNAL_FILE", ""))
    if not ruta or not os.path.exists(ruta):
        return {"trades": [], "cortes": {}, "equity": []}

    df = pd.read_csv(ruta)
    trades = ctx.bot._group_journal_into_trades(df)
    cerrados = [t for t in trades if t["cerrado"]]

    equity, acumulado = [], float(ctx.cfg.get("total_capital_usdt", 0) or 0)
    for t in cerrados:
        acumulado += t["pnl_usdt"]
        equity.append({"utc": t["cerrado_utc"], "equity": round(acumulado, 2), "pnl": round(t["pnl_usdt"], 2)})

    def corte(campo: str) -> list:
        grupos: dict = {}
        for t in cerrados:
            clave = t.get(campo)
            clave = "sin registrar" if clave is None or clave == "" else str(clave)
            grupos.setdefault(clave, []).append(t["pnl_usdt"])
        filas = []
        for clave, pnls in grupos.items():
            ganadores = len([p for p in pnls if p > 0])
            filas.append({
                "clave": clave,
                "n": len(pnls),
                "ganadores": ganadores,
                "win_rate_pct": round(ganadores / len(pnls) * 100, 1),
                "neto": round(sum(pnls), 2),
                # Con esta muestra un solo trade da la vuelta al resultado: se
                # marca para que el panel no presente ruido como conclusión.
                "muestra_corta": len(pnls) < 5,
            })
        return sorted(filas, key=lambda f: -f["n"])

    return {
        "trades": [_jsonable(t) for t in trades],
        "equity": equity,
        "cortes": {c: corte(c) for c in ("regime", "score", "killzone", "side")},
    }


def arrancar(bot: Any, cfg: dict, managers: dict) -> Optional[ContextoPanel]:
    """Levanta el panel en un hilo daemon. Devuelve None si está desactivado."""
    if not cfg.get("panel_enabled", True):
        return None

    host = os.environ.get("JORGE_BOT_PANEL_HOST", cfg.get("panel_host", "127.0.0.1"))
    puerto = int(os.environ.get("JORGE_BOT_PANEL_PORT", cfg.get("panel_port", 8787)))
    token = os.environ.get("JORGE_BOT_PANEL_TOKEN", "").strip()
    generado = False
    if not token:
        # Nunca se sirve sin llave: si no hay token configurado se genera uno
        # y se deja en el log, que es donde el dueño puede leerlo.
        token = secrets.token_urlsafe(18)
        generado = True

    ctx = ContextoPanel(bot, cfg, managers)

    try:
        import uvicorn
        app = construir_app(ctx, token)
    except Exception as e:
        logger.error(f"Panel web no disponible: {e}")
        return None

    def _servir():
        # Si el bind falla (IP que cambió por DHCP, puerto ocupado) el hilo
        # moriría en silencio y el panel simplemente no existiría, que es
        # justo el tipo de fallo mudo que este trabajo intenta eliminar.
        try:
            config = uvicorn.Config(app, host=host, port=puerto, log_level="warning", access_log=False)
            uvicorn.Server(config).run()
        except Exception as e:
            logger.error(f"❌ El panel web se cayó ({host}:{puerto}): {type(e).__name__}: {e}")

    threading.Thread(target=_servir, daemon=True, name="panel-web").start()
    # El token NO va al log: jorge_bot.log es legible por más gente que .env,
    # y esta llave abre y cierra posiciones.
    logger.info(f"🖥️  Panel web en http://{host}:{puerto}/  (token en .env, JORGE_BOT_PANEL_TOKEN)")
    if generado:
        logger.warning(f"    ⚠️  Token generado al vuelo y NO persistido: {token[:4]}… — "
                       f"fija JORGE_BOT_PANEL_TOKEN en .env o cambiará en cada reinicio")
    return ctx
