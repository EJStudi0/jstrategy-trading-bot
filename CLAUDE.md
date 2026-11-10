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
- `01_…` a `13_…`, `panel_web.py`, `panel_static/` — el sistema anterior. No se ejecuta. No se
  arregla ni se borra sin que el dueño lo pida.
- Servicio: `jstrategy-bot.service` (systemd de usuario). Copia en `despliegue/`.

## Reglas

1. **Solo simulación.** Operar con dinero real es decisión del dueño y un trabajo aparte (ver el
   final del README). No se añade un interruptor que lo active.
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
