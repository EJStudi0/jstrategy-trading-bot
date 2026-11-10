"""El panel antiguo ya no se ejecuta, pero sigue pudiéndose lanzar: que no acepte órdenes de otra página."""
import pytest
from fastapi.testclient import TestClient

import panel_web

TOKEN = "token-antiguo-de-prueba"


class Contexto:
    def __init__(self):
        self.pausas = []

    def set_pausa(self, pausado):
        self.pausas.append(pausado)
        return {"pausado": pausado}

    def estado(self):
        return {"ok": True}


@pytest.fixture
def cliente():
    ctx = Contexto()
    c = TestClient(panel_web.construir_app(ctx, TOKEN), base_url="http://panel.local:8787")
    c.ctx = ctx
    c.cookies.set("panel_token", TOKEN)        # la víctima ya tenía la sesión abierta
    return c


def test_un_formulario_ajeno_no_pausa(cliente):
    r = cliente.post("/api/pausa", data={"pausado": "true"})
    assert r.status_code == 415 and cliente.ctx.pausas == []


def test_otra_pagina_con_json_tampoco(cliente):
    r = cliente.post("/api/pausa", json={"pausado": True}, headers={"Origin": "http://panel.local:9999"})
    assert r.status_code == 403 and cliente.ctx.pausas == []
    r = cliente.post("/api/pausa", json={"pausado": True}, headers={"Origin": "http://otra.web"})
    assert r.status_code == 403 and cliente.ctx.pausas == []


def test_el_propio_panel_sigue_funcionando(cliente):
    r = cliente.post("/api/pausa", json={"pausado": True}, headers={"Origin": "http://panel.local:8787"})
    assert r.status_code == 200 and len(cliente.ctx.pausas) == 1
    assert cliente.get("/api/estado").status_code == 200


def test_sin_token_nada(cliente):
    cliente.cookies.clear()
    assert cliente.post("/api/pausa", json={"pausado": True}).status_code == 401
    assert cliente.get("/api/estado").status_code == 401


def test_la_cookie_es_estricta():
    c = TestClient(panel_web.construir_app(Contexto(), TOKEN))
    cabecera = c.get("/", params={"token": TOKEN}).headers.get("set-cookie", "").lower()
    assert "samesite=strict" in cabecera and "httponly" in cabecera
