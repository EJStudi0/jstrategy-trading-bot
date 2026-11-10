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


RUTAS_GET = ["/api/estado", "/api/operaciones", "/api/patrimonio", "/api/ganancias", "/api/mercado",
             "/api/grafica?simbolo=AAAUSDT"]
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
    piezas = panel.piezas()
    assert "index.html" in piezas and any(p.startswith("assets/") and p.endswith(".js") for p in piezas)
    for nombre, tipo in piezas.items():
        r = cliente.get("/" if nombre == "index.html" else "/" + nombre)
        assert r.status_code == 200, nombre
        assert r.headers["content-type"].split(";")[0] == tipo.split(";")[0], nombre
        assert TOKEN.encode() not in r.content
        cache = r.headers.get("cache-control", "")
        # Las piezas con huella en el nombre se guardan; la página nunca (siempre trae la última).
        assert ("immutable" in cache) if nombre.startswith("assets/") else ("no-store" in cache), nombre
    assert "10000" not in cliente.get("/").text and "10.000" not in cliente.get("/").text


def test_la_pagina_compilada_es_la_de_sus_fuentes():
    """bot/panel_estatico/ sale de compilar panel/ (npm run build). Si alguien cambia las fuentes y no
    compila, el bot serviría una página vieja: esta prueba lo caza con la misma huella que deja la
    compilación."""
    import hashlib
    import json
    import os
    raiz = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panel")
    if not os.path.isdir(raiz):
        pytest.skip("sin las fuentes del panel")
    ficheros = []
    for f in ("index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json", "src", "public"):
        ruta = os.path.join(raiz, f)
        if os.path.isdir(ruta):
            for base_, _, nombres in os.walk(ruta):
                ficheros += [os.path.join(base_, n) for n in nombres]
        else:
            ficheros.append(ruta)
    relativos = sorted(os.path.relpath(f, raiz).replace(os.sep, "/") for f in ficheros)
    h = hashlib.sha256()
    for r in relativos:
        with open(os.path.join(raiz, r), "rb") as fh:
            h.update((r + "\n" + hashlib.sha256(fh.read()).hexdigest() + "\n").encode())
    with open(os.path.join(panel.DIR_ESTATICO, "huella.json"), encoding="utf-8") as fh:
        compilada = json.load(fh)["fuentes"]
    assert compilada == h.hexdigest(), "el panel cambió y no se compiló: cd panel && npm run build"


def test_lo_que_pide_la_pagina_existe(cliente):
    import re
    html = cliente.get("/").text
    pedidos = re.findall(r'(?:src|href)="(/[^"]+)"', html)
    assert pedidos, "la página no pide nada"
    for ruta in pedidos:
        assert cliente.get(ruta).status_code == 200, ruta


@pytest.mark.parametrize("ruta", ["/panel.py", "/.env", "/estado_cartera.json", "/index.html", "/huella.json",
                                  "/..%2Fpanel.py", "/%2e%2e/config.py", "/api", "/favicon.ico",
                                  "/assets/..%2F..%2Fpanel.py", "/assets/.oculto.js", "/assets/no-existe.js"])
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
    g = cliente.get("/api/grafica?simbolo=AAAUSDT&n=100", headers=AUT).json()
    assert len(g["t"]) == len(g["c"]) == len(g["puntuacion"]) == 100
    assert set(g["medias"]) == {"2/8", "4/16", "5/20", "8/32", "10/40", "16/64"} and set(g["canales"]) == {"5", "10", "20", "40"}
    assert len(g["marcas"]) >= 1, "la primera decisión dejó operaciones en esta moneda"
    assert cliente.get("/api/grafica?simbolo=NOEXISTE", headers=AUT).status_code == 400
    assert cliente.get("/api/grafica?simbolo=AAAUSDT").status_code == 401


def test_sin_token_configurado_el_panel_no_arranca(monkeypatch):
    with pytest.raises(ValueError):
        panel.construir_app(object(), "")
    monkeypatch.setenv("JORGE_BOT_PANEL_TOKEN", "")
    assert panel.arrancar(object()) is None


def test_no_hay_documentacion_abierta(cliente):
    for ruta in ("/docs", "/redoc", "/openapi.json"):
        assert cliente.get(ruta).status_code == 404
