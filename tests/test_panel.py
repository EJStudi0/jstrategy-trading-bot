"""El panel abre y cierra posiciones: lo primero que se prueba es quién puede pulsarlo."""
import pytest
from fastapi.testclient import TestClient

from bot import config, datos, ejecutor, panel
from bot.estrategia import Parametros
from tests.test_ejecutor import FeedFalso, SIMBOLOS, avanzar

TOKEN = "token-de-prueba-123"
AUT = {"Authorization": f"Bearer {TOKEN}"}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(datos, "DIR_CACHE", str(tmp_path / "cache"))
    monkeypatch.setattr(config, "capital_inicial", lambda: 10_000.0)
    b = ejecutor.Bot(feed=FeedFalso(), carpeta=str(tmp_path))
    b.p = Parametros(simbolos=SIMBOLOS)
    avanzar(b, 0)
    b.decidir()
    c = TestClient(panel.construir_app(b, TOKEN))
    c.bot = b
    return c


RUTAS_GET = ["/api/estado", "/api/operaciones", "/api/patrimonio", "/api/ganancias", "/api/mercado"]
RUTAS_POST = ["/api/mando", "/api/ajustes"]


@pytest.mark.parametrize("ruta", RUTAS_GET)
def test_sin_token_no_se_lee_nada(cliente, ruta):
    assert cliente.get(ruta).status_code == 401
    assert cliente.get(ruta, headers={"Authorization": "Bearer otro"}).status_code == 401
    assert cliente.get(ruta, headers={"Authorization": TOKEN}).status_code == 401      # sin 'Bearer'
    assert cliente.get(ruta + "?token=" + TOKEN).status_code == 401, "el token no vale en la URL"


@pytest.mark.parametrize("ruta", RUTAS_POST)
def test_sin_token_no_se_manda_nada(cliente, ruta):
    assert cliente.post(ruta, json={"mando": "fuera"}).status_code == 401
    assert cliente.bot.mando == "auto"


def test_una_cookie_no_autentica(cliente):
    """El fallo del panel anterior: aceptaba el token en una cookie, y un POST desde otra página colaba."""
    cliente.cookies.set("panel_token", TOKEN)
    assert cliente.get("/api/estado").status_code == 401
    assert cliente.post("/api/mando", json={"mando": "pausa"}).status_code == 401
    assert cliente.bot.mando == "auto"


def test_un_formulario_de_otra_pagina_no_sirve(cliente):
    """Aunque llevase el token, un formulario HTML (lo único que cruza orígenes sin permiso) se rechaza."""
    r = cliente.post("/api/mando", data={"mando": "pausa"}, headers=AUT)
    assert r.status_code == 415 and cliente.bot.mando == "auto"


def test_la_pagina_no_lleva_datos_ni_el_token(cliente):
    for nombre, tipo in panel.ESTATICOS.items():
        r = cliente.get("/" if nombre == "index.html" else "/" + nombre)
        assert r.status_code == 200, nombre
        assert r.headers["content-type"].split(";")[0] == tipo.split(";")[0], nombre
        assert TOKEN not in r.text
        assert "no-store" in r.headers.get("cache-control", "")
    assert "10000" not in cliente.get("/").text and "10.000" not in cliente.get("/").text


@pytest.mark.parametrize("ruta", ["/panel.py", "/.env", "/estado_cartera.json", "/index.html",
                                  "/..%2Fpanel.py", "/%2e%2e/config.py", "/api", "/favicon.ico"])
def test_no_se_sirve_nada_fuera_de_la_lista(cliente, ruta):
    assert cliente.get(ruta).status_code == 404


def test_cabeceras_de_seguridad_en_todo(cliente):
    """La página solo ejecuta sus ficheros y solo habla con este servidor, también en los errores."""
    for r in (cliente.get("/"), cliente.get("/panel.js"), cliente.get("/api/estado"),
              cliente.get("/api/estado", headers=AUT), cliente.get("/no-existe")):
        csp = r.headers.get("content-security-policy", "")
        assert "script-src 'self'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert r.headers.get("x-content-type-options") == "nosniff"
        assert r.headers.get("referrer-policy") == "no-referrer"


def test_el_html_no_lleva_codigo_ni_estilos_en_linea(cliente):
    """Con la política estricta, un <script> o un style= en la página no funcionaría: que no los haya."""
    import re
    html = cliente.get("/").text
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", html), "script en línea"
    assert "<style" not in html and " style=" not in html and "javascript:" not in html
    assert not re.search(r"\son[a-z]+=", html), "manejador de evento en línea"


def test_estado(cliente):
    e = cliente.get("/api/estado", headers=AUT).json()
    assert e["simulacion"] is True and e["mando"] == "auto"
    assert e["patrimonio"] == pytest.approx(10_000, rel=0.01)
    assert [m["simbolo"] for m in e["monedas"]] == list(SIMBOLOS)
    assert set(e["ajustables"]) == set(config.AJUSTABLES)
    assert TOKEN not in str(e)


def test_mando_pausa_y_auto(cliente):
    assert cliente.post("/api/mando", json={"mando": "pausa"}, headers=AUT).json()["mando"] == "pausa"
    assert cliente.bot.mando == "pausa"
    assert cliente.post("/api/mando", json={"mando": "auto"}, headers=AUT).json()["mando"] == "auto"
    assert cliente.post("/api/mando", json={"mando": "vender_todo_ya"}, headers=AUT).status_code == 400
    assert cliente.post("/api/mando", content="no soy json", headers={**AUT, "Content-Type": "application/json"}).status_code == 400


def test_salir_a_usdt_pide_confirmacion(cliente):
    b = cliente.bot
    r = cliente.post("/api/mando", json={"mando": "fuera"}, headers=AUT).json()
    assert "confirmar" in r and b.mando == "auto", "la primera petición no vende nada"
    assert b.cartera.valor_contado(b.precios) > 0
    malo = cliente.post("/api/mando", json={"mando": "fuera", "confirmacion": "inventado"}, headers=AUT).json()
    assert "confirmar" in malo and b.mando == "auto", "un código inventado tampoco"
    ok = cliente.post("/api/mando", json={"mando": "fuera", "confirmacion": malo["confirmar"]}, headers=AUT).json()
    assert ok["mando"] == "fuera" and b.cartera.valor_contado(b.precios) == 0


def test_la_confirmacion_caduca(cliente, monkeypatch):
    r = cliente.post("/api/mando", json={"mando": "fuera"}, headers=AUT).json()
    import time
    real = time.time
    monkeypatch.setattr(panel.time, "time", lambda: real() + panel.CADUCIDAD_CONFIRMACION_S + 1)
    otra = cliente.post("/api/mando", json={"mando": "fuera", "confirmacion": r["confirmar"]}, headers=AUT).json()
    assert "confirmar" in otra and cliente.bot.mando == "auto"


def test_ajustes(cliente):
    r = cliente.post("/api/ajustes", json={"vol_cartera": 0.15}, headers=AUT)
    assert r.status_code == 200 and cliente.bot.p.vol_cartera == 0.15
    for malo in ({"vol_cartera": 9}, {"leverage": 50}, {"simbolos": ["X"]}, {"cobertura_max": 2.0}):
        assert cliente.post("/api/ajustes", json=malo, headers=AUT).status_code == 400
    assert cliente.post("/api/ajustes", json=[1, 2], headers=AUT).status_code == 400
    assert cliente.bot.p.vol_cartera == 0.15 and cliente.bot.p.cobertura_max == 1.0


def test_operaciones_y_patrimonio(cliente):
    ops = cliente.get("/api/operaciones?n=5", headers=AUT).json()
    assert 1 <= len(ops) <= 5 and {"simbolo", "pata", "lado", "nocional"} <= set(ops[0])
    cliente.bot._foto()
    serie = cliente.get("/api/patrimonio", headers=AUT).json()
    assert len(serie) == 1 and serie[0]["patrimonio"] == pytest.approx(10_000, rel=0.01)


def test_ganancias_en_la_zona_de_quien_mira(cliente):
    cliente.bot._foto()
    g = cliente.get("/api/ganancias?zona=America/Bogota", headers=AUT).json()
    assert g["zona"] == "America/Bogota" and g["dias"] and g["resumen"]["total"]["inicio"] == 10_000
    assert cliente.get("/api/ganancias?zona=../../etc/passwd", headers=AUT).json()["zona"] == "UTC"
    assert cliente.get("/api/ganancias", headers=AUT).json()["zona"] == "UTC"


def test_curva_por_tramo_y_mercado(cliente):
    cliente.bot._foto()
    assert len(cliente.get("/api/patrimonio?horas=24", headers=AUT).json()) == 1
    assert cliente.get("/api/patrimonio?horas=-5", headers=AUT).status_code == 200
    m = cliente.get("/api/mercado", headers=AUT).json()
    assert [x["simbolo"] for x in m["monedas"]] == list(SIMBOLOS) and m["intervalo"] == "4h"


def test_sin_token_configurado_el_panel_no_arranca(monkeypatch):
    with pytest.raises(ValueError):
        panel.construir_app(object(), "")
    monkeypatch.setenv("JORGE_BOT_PANEL_TOKEN", "")
    assert panel.arrancar(object()) is None


def test_no_hay_documentacion_abierta(cliente):
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(ruta).status_code == 404
