"""Los niveles de riesgo que ofrece el panel: que existan, que se reconozcan y que sus cifras sean las medidas."""
import os
from dataclasses import replace

import pytest

from bot import config, datos
from bot.estrategia import Parametros

HAY_DATOS = os.path.exists(os.path.join(datos.DIR_CACHE, "BTCUSDT_15m.npz"))
# Las cifras de `config.NIVELES` se midieron con los datos que había hasta este día. Fijarlo aquí
# hace que la prueba no cambie por bajar datos nuevos: solo falla si cambia la estrategia.
MEDIDO_HASTA = config.NIVELES_PERIODO["hasta"]


def test_cada_nivel_se_puede_poner_desde_el_panel():
    for clave, nivel in config.NIVELES.items():
        assert config.validar_ajustes(nivel["ajustes"]) == nivel["ajustes"], clave
        assert config.nivel_de(config.parametros(nivel["ajustes"])) == clave


def test_el_riesgo_por_defecto_es_el_nivel_moderado():
    assert config.nivel_de(Parametros()) == "moderado"


def test_un_riesgo_a_medida_no_es_ningun_nivel():
    assert config.nivel_de(replace(Parametros(), vol_cartera=0.33)) is None
    assert config.nivel_de(replace(Parametros(), apalancamiento=1.25)) is None
    # Mismo riesgo que «moderado», pero con otra base u otra cobertura: ya no es lo que se midió.
    assert config.nivel_de(replace(Parametros(), tope_base=0.50)) is None
    assert config.nivel_de(replace(Parametros(), cobertura_max=1.5)) is None


def test_los_niveles_van_de_menos_a_mas_riesgo():
    riesgos = [n["ajustes"]["vol_cartera"] for n in config.NIVELES.values()]
    caidas = [n["caida_pct"] for n in config.NIVELES.values()]
    assert riesgos == sorted(riesgos)
    assert caidas == sorted(caidas, reverse=True), "a más riesgo, peor caída medida"


@pytest.mark.lento
@pytest.mark.skipif(not HAY_DATOS, reason="falta datos_cache/ (python -m investigacion.descargar)")
def test_las_cifras_de_los_niveles_son_las_medidas():
    from investigacion import comun
    from investigacion.validacion import simular

    for clave, nivel in config.NIVELES.items():
        r = simular(replace(Parametros(), **nivel["ajustes"]), desde=comun.FIN_DISEÑO, hasta=MEDIDO_HASTA)
        m = r.metricas()
        assert m["cagr_pct"] == pytest.approx(nivel["anual_pct"], abs=0.15), f"{clave}: ganancia anual"
        assert m["max_dd_pct"] == pytest.approx(nivel["caida_pct"], abs=0.15), f"{clave}: peor caída"
        assert m["meses_positivos_pct"] == pytest.approx(nivel["meses_positivos_pct"], abs=1), f"{clave}: meses"
        anios = r.por_anio()["rend_pct"]
        assert {str(a) for a in anios.index} == set(nivel["por_anio"]), f"{clave}: años"
        for anio, pct in nivel["por_anio"].items():
            assert anios[int(anio)] == pytest.approx(pct, abs=0.15), f"{clave}: {anio}"
