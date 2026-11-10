"""El bot en vivo, alimentado vela a vela con el histórico real, debe dar lo mismo que el simulador.

Es la prueba que le faltaba al bot antiguo: su backtest y su bucle en vivo eran
códigos distintos, y lo que medía uno no era lo que hacía el otro.
"""
import os

import numpy as np
import pytest

from bot import config, datos, ejecutor
from bot.estrategia import Parametros

pytestmark = pytest.mark.lento
HAY_DATOS = os.path.exists(os.path.join(datos.DIR_CACHE, "BTCUSDT_15m.npz"))


class SinRed:
    mercado_activo = "histórico"
    ultimo_ok_utc = None
    ultimo_error = None

    def financiacion(self, *a):
        return []


@pytest.mark.skipif(not HAY_DATOS, reason="falta datos_cache/ (python -m investigacion.descargar)")
def test_el_bot_paso_a_paso_coincide_con_el_simulador(tmp_path, monkeypatch):
    from investigacion import laboratorio as lab
    from investigacion.validacion import simular

    p = Parametros()
    g = lab.cuadricula(p.intervalo, list(p.simbolos))
    pasos = 360                                   # 60 días de velas de 4 h
    ini = g.n - pasos
    desde = str(np.datetime64(int(g.t[ini]), "ms"))
    ref = simular(p, desde=desde)                 # el simulador de la investigación, mismo tramo

    monkeypatch.setattr(config, "capital_inicial", lambda: 100_000.0)
    monkeypatch.setattr(datos, "DIR_CACHE", str(tmp_path / "cache"))
    bot = ejecutor.Bot(feed=SinRed(), carpeta=str(tmp_path))
    bot.p = p
    N = len(p.simbolos)
    validas = [~np.isnan(g.C[:, j]) for j in range(N)]
    patrimonio = []
    for k in range(ini, g.n):
        for j, s in enumerate(p.simbolos):
            m = validas[j].copy()
            m[k + 1:] = False
            idx = np.nonzero(m)[0][-ejecutor.VELAS_HISTORIA:]
            bot.velas[s] = datos.Velas(s, p.intervalo, g.t[idx], g.O[idx, j], g.H[idx, j],
                                       g.L[idx, j], g.C[idx, j], g.V[idx, j])
            if validas[j][k]:
                bot.precios[s] = float(g.C[k, j])
        if k > ini:
            # Financiación de lo mantenido desde la decisión anterior (la F de la vela k-1).
            for j, s in enumerate(p.simbolos):
                if g.F[k - 1, j] and bot.cartera.perp.get(s) and bot.cartera.perp[s].cantidad:
                    bot.cartera.ultimo_funding_ms[s] = 0
                    bot.cartera.aplicar_financiacion(s, float(g.F[k - 1, j]), float(g.C[k - 1, j]), k)
        patrimonio.append(bot.cartera.patrimonio(bot.precios))
        bot.decidir()

    vivo = np.array(patrimonio) / patrimonio[0]
    sim = ref.patrimonio / ref.patrimonio[0]
    assert len(vivo) == len(sim)
    r_vivo, r_sim = np.diff(np.log(vivo)), np.diff(np.log(sim))
    correlacion = np.corrcoef(r_vivo[5:], r_sim[5:])[0, 1]
    print(f"\n  bot {vivo[-1]:.5f} | simulador {sim[-1]:.5f} | correlación {correlacion:.4f} | "
          f"mayor distancia {np.max(np.abs(vivo - sim)):.5f}")
    assert correlacion > 0.999, f"correlación de rendimientos {correlacion:.4f}"
    assert vivo[-1] == pytest.approx(sim[-1], abs=0.0005), (
        f"en 60 días el bot acaba en {vivo[-1]:.4f} y el simulador en {sim[-1]:.4f}")
    # Y el bot no hizo nada raro por el camino.
    assert bot.cartera.colchon_margen(bot.precios) > ejecutor.MARGEN_MINIMO
    assert not any("Garantía" in a["texto"] for a in bot.avisos)
