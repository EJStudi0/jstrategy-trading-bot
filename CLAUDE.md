# CLAUDE.md — Bot Jorge

Bot de trading de criptomonedas en **simulación**. Lee `README.md` primero: explica la estrategia,
lo medido y cómo se usa. Aquí solo está lo que hay que respetar al tocarlo.

Al dueño se le habla en español, corto, sin nombres de ficheros ni de funciones.

## Qué es qué

- `bot/` — el bot. `estrategia.py` (decide, función pura de velas cerradas), `cartera.py`
  (contabilidad simulada), `ejecutor.py` (bucle), `datos.py` (velas), `resumen.py` (ganancia por
  día y mes para el panel), `panel.py` (sirve la API y la página).
- `panel/` — la página: React + TypeScript + Tailwind + Lightweight Charts. `npm run build` (con
  `nice -n 19`) la compila a `bot/panel_estatico/`, que SÍ va a git; tras tocar `panel/` hay que
  compilar o falla la prueba de la huella. Política de contenido estricta: nada de scripts ni
  estilos en línea, ni `<style>` inyectados (por eso el logotipo de la librería va apagado y la
  atribución está en el pie). Versiones fijadas, con más de dos semanas publicadas.
- `investigacion/` — simulador y estudios. `salidas/` y `datos_cache/` se regeneran y no van a git.
- `tests/` — `.venv/bin/python -m pytest` (~40 s).
- `centinela/` — **segundo bot** (añadido el 2026-11-11): solo Bitcoin, al contado, sin deuda, sigue la
  tendencia. Proceso aparte (`jstrategy-centinela.service`, `python -m centinela --config centinela.yaml
  real --confirmo-dinero-real` con `sandbox: true`): desde el 2026-11-11, por decisión del dueño, opera
  en la **cuenta DEMO de Bitget** (dinero ficticio, contado). Las claves demo se leen de
  `~/proyectos/nuevo/.env` (no se copian). Candado: con claves, `centinela/live/broker.connect` se niega
  si no es la demo; todo lo que escribe va a `centinela_vivo/` y `logs/` (fuera de git).
  Sus pruebas, `centinela_pruebas/` (entran en el mismo `pytest`). El panel lo enseña en la sección
  «Centinela» a través de `bot/puente_centinela.py`, que solo LEE su base de datos y pone o quita su
  fichero `STOP` (apagar no vende). Los mandos de un bot no tocan al otro. El panel enseña su cuenta
  demo (`real-demo.db`); la simulación vieja (`papel.db`) se conserva.
- `01_…` a `13_…`, `panel_web.py`, `panel_static/` — el sistema anterior. No se ejecuta. No se
  arregla ni se borra sin que el dueño lo pida.
- Servicios: `jstrategy-bot.service` (Jorge y el panel) y `jstrategy-centinela.service` (systemd de
  usuario). Copias en `despliegue/`.

## Reglas

1. **Solo simulación o demo.** Operar con dinero real es decisión del dueño y un trabajo aparte (ver el
   final del README). No se añade un interruptor que lo active. La demo de Bitget (dinero ficticio) sí
   la autorizó el dueño el 2026-11-11: Centinela al contado; Jorge irá solo a futuros (intradía), cuando
   su estrategia nueva pase diseño y prueba. Contado y futuros son carteras separadas en Bitget.
2. **La frontera diseño/prueba no se toca.** `investigacion/comun.py: FIN_DISEÑO`. Cualquier idea
   nueva se diseña con datos anteriores y se prueba UNA vez con los posteriores. Ajustar un
   parámetro mirando la prueba la invalida; si pasa, se dice.
3. **El simulador y el bot son la misma regla.** Si cambia cómo decide u opera el bot
   (`estrategia.calcular`, `cartera.ordenes`), cambia igual `laboratorio.simular_cubierta`, y
   `tests/test_replica.py` tiene que seguir dando distancia cero.
4. **Solo velas cerradas.** Nada decide con la vela en formación.
5. **Nada gratis en la simulación**: comisión, deslizamiento y financiación en cada operación.
6. **Secretos**: `.env` no se imprime ni se copia; el token del panel no va al registro ni a una URL.
   El panel autentica por cabecera, sin cookies.
7. Lo que sale fuera (subir a GitHub, cambiar de red) lo decide el dueño.

## Entorno

- Python 3.12 en `.venv` (`/usr/bin/python3.12 -m venv .venv`; el `python3` del sistema es 3.14 y no
  trae `venv`). Dependencias fijadas en `requirements.txt`; las de pruebas en `requirements-dev.txt`.
- La máquina es pequeña y compartida (4 núcleos, 8 GB): lo pesado con `nice -n 19` y
  `OMP_NUM_THREADS=1`, de uno en uno.
- Binance responde 451 desde la salida actual del servidor. Los volcados históricos
  (`data.binance.vision`) sí bajan; en vivo el bot usa el primer mercado que conteste.
- `ccxt` 4.5.54 fallaba al cargar OKX (`TypeError` al ordenar mercados) y caía en Bitget; desde la
  tarde del 2026-11-10, al reiniciar, OKX contesta y es el que se usa.
