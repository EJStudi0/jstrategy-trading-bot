"""Ganancia por día, semana y mes: que los días se corten en la hora de quien mira y que las cuentas cuadren."""
from datetime import datetime, timedelta, timezone

import pytest

from bot import resumen
from bot.resumen import Punto

UTC = timezone.utc


def t(texto):
    return datetime.fromisoformat(texto).replace(tzinfo=UTC)


def p(texto, patrimonio, fin=0.0, com=0.0):
    return Punto(t(texto), patrimonio, fin, com)


INICIO = p("2026-11-09T22:00:00", 1000.0, 0.0, 0.0)


def test_los_dias_se_cortan_en_la_medianoche_de_quien_mira():
    puntos = [p("2026-11-09T23:00:00", 1001.0), p("2026-11-10T03:00:00", 1003.0),
              p("2026-11-10T06:00:00", 1006.0), p("2026-11-10T12:00:00", 1010.0)]
    ahora = p("2026-11-10T13:00:00", 1011.0)
    utc = resumen.calcular(puntos, INICIO, ahora, "UTC")
    assert [(d["fecha"], d["ganancia"]) for d in utc["dias"]] == [("2026-11-09", 1.0), ("2026-11-10", 10.0)]
    # En Bogotá (UTC−5) el 10 empieza a las 05:00 UTC: las fotos de las 23:00 y las 03:00 son aún del 9.
    bogota = resumen.calcular(puntos, INICIO, ahora, "America/Bogota")
    assert [(d["fecha"], d["ganancia"]) for d in bogota["dias"]] == [("2026-11-09", 3.0), ("2026-11-10", 8.0)]
    # En Madrid (UTC+1 en noviembre) las 23:00 UTC ya son el día 10: todo cae en el 10.
    madrid = resumen.calcular(puntos, INICIO, ahora, "Europe/Madrid")
    assert [(d["fecha"], d["ganancia"]) for d in madrid["dias"]] == [("2026-11-10", 11.0)]
    for r in (utc, bogota, madrid):
        assert sum(d["ganancia"] for d in r["dias"]) == pytest.approx(11.0), "los días encadenan"


def test_el_primer_dia_arranca_en_el_capital_inicial():
    """Montar la cartera cuesta comisiones: cuentan en el primer día, no desaparecen."""
    inicio = p("2026-11-10T04:08:40", 4969.79, 0.0, 0.0)
    puntos = [p("2026-11-10T04:08:45", 4962.70, 0.0, 5.59)]
    ahora = p("2026-11-10T16:20:00", 4963.04, 0.34, 5.59)
    r = resumen.calcular(puntos, inicio, ahora, "UTC")
    (dia,) = r["dias"]
    assert dia["inicio"] == 4969.79 and dia["fin"] == 4963.04
    assert dia["ganancia"] == pytest.approx(-6.75)
    assert dia["comisiones"] == pytest.approx(5.59) and dia["financiacion"] == pytest.approx(0.34)
    assert r["resumen"]["total"]["ganancia"] == pytest.approx(-6.75)


def test_el_reparto_suma_exacto():
    puntos = [p("2026-11-10T00:00:00", 1000.0, 1.0, 2.0), p("2026-11-10T23:00:00", 1004.0, 1.5, 2.25),
              p("2026-11-11T10:00:00", 1003.0, 2.5, 4.0)]
    r = resumen.calcular(puntos, puntos[0], p("2026-11-11T11:00:00", 1003.5, 2.75, 4.0), "UTC")
    for d in r["dias"]:
        assert d["mercado"] + d["financiacion"] - d["comisiones"] == pytest.approx(d["ganancia"])
    assert r["dias"][1]["financiacion"] == pytest.approx(1.25) and r["dias"][1]["comisiones"] == pytest.approx(1.75)


def test_sin_acumulados_no_se_inventa_el_reparto():
    viejo = Punto(t("2026-11-09T23:00:00"), 1002.0, None, None)       # foto de antes de guardarlos
    r = resumen.calcular([viejo], INICIO, p("2026-11-10T20:00:00", 1005.0, 0.4, 0.1), "UTC")
    hoy_viejo, hoy = r["dias"][0], r["dias"][1]
    assert hoy_viejo["ganancia"] == 2.0 and hoy_viejo["financiacion"] is None and hoy_viejo["mercado"] is None
    assert hoy["ganancia"] == 3.0 and hoy["financiacion"] is None
    assert r["meses"][0]["financiacion"] is None, "un mes con un día sin reparto no se reparte"
    assert r["resumen"]["total"]["financiacion"] == pytest.approx(0.4), "del inicio a ahora sí se sabe"


def test_meses_semana_y_hoy():
    inicio = p("2026-10-28T00:00:00", 1000.0)
    puntos, valor = [], 1000.0
    dia = datetime(2026, 10, 28, 23, tzinfo=UTC)
    for g in (1.0, -2.0, 0.0, 3.0, 0.5, -0.25, 2.0, 1.0, -1.0, 4.0):   # del 28-oct al 6-nov
        valor += g
        puntos.append(Punto(dia, valor, 0.0, 0.0))
        dia += timedelta(days=1)
    ahora = Punto(datetime(2026, 11, 6, 23, 30, tzinfo=UTC), valor + 0.5, 0.0, 0.0)
    r = resumen.calcular(puntos, inicio, ahora, "UTC")
    octubre, noviembre = r["meses"]
    assert octubre["clave"] == "2026-10" and octubre["ganancia"] == pytest.approx(1 - 2 + 0 + 3)
    assert noviembre["ganancia"] == pytest.approx(0.5 - 0.25 + 2 + 1 - 1 + 4 + 0.5)
    assert octubre["dias_positivos"] == 2 and octubre["dias_negativos"] == 1, "un día plano no cuenta"
    assert octubre["mejor"] == {"fecha": "2026-10-31", "ganancia": 3.0}
    s = r["resumen"]
    assert s["hoy"]["ganancia"] == pytest.approx(4.5) and r["hoy_fecha"] == "2026-11-06"
    # El 6 de noviembre de 2026 es viernes: la semana empezó el lunes 2.
    assert s["semana"]["clave"] == "2026-11-02"
    assert s["semana"]["ganancia"] == pytest.approx(-0.25 + 2 + 1 - 1 + 4.5)
    assert s["mes"]["ganancia"] == pytest.approx(noviembre["ganancia"])
    assert s["dias_completos"] == 9
    assert s["media_dia"] == pytest.approx((1 - 2 + 0 + 3 + 0.5 - 0.25 + 2 + 1 - 1) / 9)
    assert s["racha"] == {"dias": 1, "signo": -1}
    assert s["peor_dia"]["fecha"] == "2026-10-29"


def test_sin_dias_completos_no_hay_media():
    r = resumen.calcular([], INICIO, p("2026-11-09T23:00:00", 1000.5), "UTC")
    assert r["resumen"]["media_dia"] is None and r["resumen"]["dias_completos"] == 0
    assert r["resumen"]["hoy"]["ganancia"] == pytest.approx(0.5)


def test_fotos_de_antes_del_inicio_no_cuentan():
    """Una curva que trae fotos de otra simulación anterior: se ignoran."""
    antiguas = [p("2026-11-01T10:00:00", 5000.0), p("2026-11-02T10:00:00", 5100.0)]
    r = resumen.calcular(antiguas + [p("2026-11-09T23:00:00", 1001.0)], INICIO,
                         p("2026-11-09T23:30:00", 1002.0), "UTC")
    assert [d["fecha"] for d in r["dias"]] == ["2026-11-09"] and r["dias"][0]["ganancia"] == 2.0


@pytest.mark.parametrize("nombre", [None, "", "Marte/Olimpo", "../../etc/passwd", "/etc/localtime",
                                    "America", "a" * 80, "Europe/Madrid; rm -rf"])
def test_una_zona_que_no_vale_es_utc(nombre):
    assert resumen.zona(nombre) is resumen.UTC


def test_leer_curva_salta_filas_rotas(tmp_path):
    ruta = tmp_path / "curva.csv"
    ruta.write_text("utc,patrimonio,financiacion,comisiones\n"
                    "2026-11-10T01:00:00+00:00,100.5,0.1,0.2\n"
                    "basura,1\n"
                    "2026-11-10T02:00:00+00:00,,0.1,0.2\n"
                    "2026-11-10T03:00:00+00:00,101,,\n", encoding="utf-8")
    puntos = resumen.leer_curva(str(ruta))
    assert [x.patrimonio for x in puntos] == [100.5, 101.0]
    assert puntos[1].financiacion is None


def test_una_linea_a_medio_escribir_no_cuenta(tmp_path):
    """El bot escribe la curva desde otro hilo: si se lee justo mientras añade una foto, esa no entra."""
    ruta = tmp_path / "curva.csv"
    ruta.write_text("utc,patrimonio,financiacion,comisiones\n"
                    "2026-11-10T01:00:00+00:00,100.5,0.1,0.2\n"
                    "2026-11-10T02:00:00+00:00,10", encoding="utf-8")
    assert [x.patrimonio for x in resumen.leer_curva(str(ruta))] == [100.5]
