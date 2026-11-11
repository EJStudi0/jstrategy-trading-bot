"""La interfaz de comandos, de extremo a extremo sobre datos sintéticos (sin red)."""

import json
import re

import pytest

from centinela import cli
from centinela.backtest import report, validation
from centinela.config import load
from centinela.data.store import DataStore
from centinela.live.state import is_stopped

from conftest import make_klines


@pytest.fixture(scope="module")
def project(tmp_path_factory):
    root = tmp_path_factory.mktemp("proyecto")
    DataStore(root / "data").save("btcusdt_1h", make_klines(n=24 * 500, seed=21))
    cfg = root / "config.yaml"
    cfg.write_text(
        f"capital_papel: 5000\n"
        f"estrategia:\n  calentamiento_dias: 30\n"
        f"directorios:\n  datos: {root / 'data'}\n  estado: {root / 'state'}\n  informes: {root / 'reports'}\n",
        encoding="utf-8",
    )
    return root, str(cfg)


def run(cfg_path, *args):
    return cli.main(["--config", cfg_path, *args])


def test_backtest_command_prints_results(project, capsys):
    _, cfg = project
    assert run(cfg, "backtest") == 0
    out = capsys.readouterr().out
    assert "Periodo completo" in out and "Ratio de Sharpe" in out and "Año a año" in out


def test_backtest_profile_and_fee_overrides(project, capsys):
    _, cfg = project
    assert run(cfg, "backtest", "--perfil", "agresivo", "--comision", "0.004") == 0
    out = capsys.readouterr().out
    assert "agresivo" in out and "0,40 %" in out


def test_report_is_self_contained_html(project, capsys):
    root, cfg = project
    path = root / "reports" / "informe.html"
    assert run(cfg, "backtest", "--informe", str(path), "--sin-robustez") == 0
    html = path.read_text(encoding="utf-8")
    assert html.startswith("<!doctype html>") and "/*__DATA__*/" not in html
    assert "<title>" in html and "http://" not in html.replace("http://www.w3.org/2000/svg", "")
    assert not re.search(r"https://(?!www\.w3\.org)", html)  # ni fuentes ni scripts externos: funciona sin conexión
    data = json.loads(re.search(r"var D = (\{.*?\});\n", html, re.S).group(1))
    assert len(data["t"]) == len(data["eq"]) == len(data["bh"]) == len(data["w"]) > 300
    assert data["periods"][0]["id"] == "todo" and data["periods"][0]["s"]["sharpe"] is not None
    assert all(0 <= w <= 100 for w in data["w"])


def test_report_fragment_has_no_document_tags(project):
    root, cfg_path = project
    cfg = load(cfg_path)
    bars = DataStore(cfg.data_dir).market()
    from centinela import pipeline

    res = pipeline.backtest(cfg, bars, start=bars.index[24 * 40])
    data = report.build_data(cfg, bars, res, robustness=False)
    frag = report.render(data, standalone=False)
    assert frag.lstrip().startswith("<title>") and "<html" not in frag and "<!doctype" not in frag.lower()
    json.dumps(data)  # serializable: sin NaN ni tipos de numpy


def test_robustness_helpers_run_on_small_data(project):
    _, cfg_path = project
    cfg = load(cfg_path)
    bars = DataStore(cfg.data_dir).market()
    start = bars.index[24 * 40]
    fees = validation.fee_sensitivity(cfg, bars, (0.0, 0.004), start)
    assert fees[1]["cagr"] <= fees[0]["cagr"]  # más comisión nunca mejora el resultado
    delays = validation.delay_sensitivity(cfg, bars, (0, 24), start)
    assert len(delays) == 2 and delays[0]["delay_h"] == 0
    params = validation.parameter_sensitivity(cfg, bars, start)
    assert params[0]["variant"] == "configuración actual" and len(params) >= 10


def test_status_command_works_offline_without_context_data(project, capsys):
    _, cfg = project
    assert run(cfg, "estado", "--sin-actualizar") == 0
    out = capsys.readouterr().out
    assert "Decisión del bot" in out and "Peso objetivo en BTC" in out
    assert "nan" not in out.lower()  # los datos de contexto ausentes se muestran como tales, no como «nan»


def test_stop_and_resume_commands(project, capsys):
    root, cfg = project
    assert run(cfg, "parar") == 0 and is_stopped(root / "state")
    assert run(cfg, "reanudar") == 0 and not is_stopped(root / "state")


def test_real_mode_requires_both_config_and_flag(project, capsys):
    root, cfg = project
    assert run(cfg, "real") == 2  # la configuración dice papel
    assert "modo: papel" in capsys.readouterr().out
    real_cfg = root / "real.yaml"
    real_cfg.write_text((root / "config.yaml").read_text(encoding="utf-8") + "modo: real\n", encoding="utf-8")
    assert run(str(real_cfg), "real") == 2  # falta la confirmación explícita
    assert "confirmación explícita" in capsys.readouterr().out
    assert run(str(real_cfg), "liquidar", "--real") == 2


def test_invalid_config_is_reported_not_crashed(project, capsys, tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("perfil: equilibrado\nbandaa: 0.2\n", encoding="utf-8")
    assert run(str(bad), "backtest") == 2
    assert "Configuración inválida" in capsys.readouterr().out


def test_missing_data_gives_a_helpful_message(tmp_path, capsys):
    cfg = tmp_path / "c.yaml"
    cfg.write_text(f"directorios:\n  datos: {tmp_path / 'nada'}\n", encoding="utf-8")
    assert run(str(cfg), "backtest") == 2
    assert "centinela datos" in capsys.readouterr().out


def test_demo_environment_keeps_its_own_state():
    from centinela.config import from_dict

    demo = from_dict({"modo": "real", "ejecucion": {"exchange": "bitget", "sandbox": True}})
    live = from_dict({"modo": "real", "ejecucion": {"exchange": "bitget"}})
    assert cli._state_name(demo, "real") == "real-demo"  # la prueba con dinero ficticio no toca el estado real
    assert cli._state_name(live, "real") == "real"
    assert cli._state_name(demo, "papel") == "papel"


def test_the_suite_never_loads_the_users_real_credentials(project):
    """Regresión: `cli.main` cargaba el `.env` del directorio de trabajo también durante los tests."""
    import os

    from conftest import SECRET_VARS

    _, cfg = project
    assert run(cfg, "reanudar") == 0  # cualquier orden pasa por `main`, que es quien carga el `.env`
    leaked = [v for v in SECRET_VARS if os.environ.get(v)]  # solo nombres: nunca valores en un mensaje de error
    assert leaked == []


# ------------------------------------------------------------ probar-orden
def _real_project(project, monkeypatch, **fake_kw):
    """Configuración en modo real cuyo broker habla con un exchange simulado."""
    from centinela.live.broker import CcxtBroker
    from test_broker import FakeExchange

    root, _ = project
    real_cfg = root / "real-prueba.yaml"
    real_cfg.write_text((root / "config.yaml").read_text(encoding="utf-8") + "modo: real\n", encoding="utf-8")
    ex = FakeExchange(**fake_kw)

    def fake_broker(cfg, state):
        return CcxtBroker(cfg.execution, {}, exchange=ex, load_pending=lambda: state.get("pending_order"),
                          save_pending=lambda p: state.set("pending_order", p))  # fmt: skip

    monkeypatch.setattr(cli, "_real_broker", fake_broker)
    monkeypatch.setattr(cli.time, "sleep", lambda s: None)
    return str(real_cfg), ex


def test_order_smoke_test_buys_a_little_and_sells_it_back(project, monkeypatch, capsys):
    cfg, ex = _real_project(project, monkeypatch, quote=100.0)
    assert run(cfg, "probar-orden") == 2 and not ex.created  # falta la confirmación explícita
    assert run(cfg, "probar-orden", "--confirmo-dinero-real", "--importe", "500") == 2 and not ex.created  # no es una forma de operar
    assert run(cfg, "probar-orden", "--confirmo-dinero-real") == 0
    (_, t1, s1, q1, _), (_, t2, s2, q2, _) = ex.created
    assert (t1, t2) == ("limit", "limit") and (s1, s2) == ("buy", "sell")
    assert q1 == pytest.approx(10 / 50_010, abs=1e-6) and q2 == pytest.approx(q1)  # vende justo lo que compró
    assert ex.bal["BTC"] == pytest.approx(0.0, abs=1e-9)
    assert 0 < 100.0 - ex.bal["USDT"] < 0.05  # la prueba solo cuesta comisiones y spread
    assert "funciona de punta a punta" in capsys.readouterr().out


def test_order_smoke_test_sends_nothing_without_funds_or_in_paper_mode(project, monkeypatch, capsys):
    cfg, ex = _real_project(project, monkeypatch, quote=0.42)
    assert run(cfg, "probar-orden", "--confirmo-dinero-real") == 1 and not ex.created
    assert "Saldo insuficiente" in capsys.readouterr().out
    _, paper_cfg = project
    assert run(paper_cfg, "probar-orden", "--confirmo-dinero-real") == 2 and not ex.created


def test_order_smoke_test_says_so_if_btc_is_left_behind(project, monkeypatch, capsys):
    cfg, ex = _real_project(project, monkeypatch, quote=100.0)
    original = ex.create_order

    def only_buys(symbol, type_, side, amount, price, params=None):
        if side == "sell":
            raise RuntimeError("mercado cerrado")
        return original(symbol, type_, side, amount, price, params)

    ex.create_order = only_buys
    assert run(cfg, "probar-orden", "--confirmo-dinero-real") == 1
    out = capsys.readouterr().out
    assert "La compra sí se había ejecutado" in out and ex.bal["BTC"] > 0
