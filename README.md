# Bot Jorge

Bot de trading de criptomonedas. **Opera en simulación**: lee el mercado real, pero no envía
órdenes ni tiene claves de ningún mercado.

Desde noviembre de 2026 el bot es el paquete `bot/`. Los ficheros numerados (`01_…` a `13_…`,
`panel_web.py`, `panel_static/`) son el sistema anterior: se conservan como referencia y ya no
se ejecutan. Más abajo está por qué se cambió.

## Qué hace

Cada 4 horas, al cerrar la vela, para cada una de 10 monedas (BTC, ETH, SOL, BNB, XRP, DOGE, ADA,
AVAX, LINK, LTC):

1. **Mide la tendencia** con diez relojes a la vez — seis cruces de medias exponenciales (de 2/8 a
   16/64 días) y cuatro rupturas de canal (5, 10, 20 y 40 días) — y saca una nota entre −1 y +1.
2. **Las alts solo cuentan al alza si Bitcoin también está en tendencia positiva.**
3. **Mantiene una base** de cada moneda, más pequeña cuanto más volátil (todas arriesgan parecido),
   hasta el 75 % del capital, **y cubre con un corto** la parte que la tendencia no respalda:
   tendencia plena → sin cobertura; tendencia en contra → cubierta al 100 % (el precio deja de mover
   el patrimonio y la cobertura cobra financiación).
4. **Controla el riesgo de la cartera entera**: si la volatilidad prevista pasa del objetivo, cubre más.

Es la idea del material original (EMAs para leer la estructura, cobertura en vez de vender), pero
graduada por la tendencia y sin pasar del 100 %.

## Cuánto rinde, medido

Simulado sobre velas reales de Binance con comisiones (0,10 % contado, 0,05 % perpetuo),
deslizamiento (0,02 %) y la financiación real de cada perpetuo. Todo se **diseñó con 2020-2023** y
se **probó una sola vez con 2024 → nov 2026**, que no se usó para ajustar nada.

| | Diseño 2020-2023 | **Prueba 2024 → nov 2026** |
|---|---|---|
| Rentabilidad anual | +43 % | **+11,8 %** |
| Peor caída | −12,5 % | **−18 %** |
| Sharpe | 2,27 | **0,80** |
| Por año | +61 / +92 / −7 / +46 % | **+34 % (2024), −0,5 % (2025), +3 % (2026)** |

En la prueba, comprar Bitcoin y aguantar dio +22 % anual con una caída del −53 % (y −6 % y −15 % en
2025 y 2026); la cesta de las diez monedas, +2 % anual con una caída del −68 %.

**Lo que hay que esperar es la columna de la derecha, no la de la izquierda.** Que la prueba salga
peor que el diseño es lo normal; lo que importa es que sigue en positivo. Aun así son 2,9 años: no
es una garantía, y habrá años en negativo.

Niveles de riesgo (misma estrategia, más o menos exposición; se cambian en el panel):

| Nivel | Ajuste | Prueba 2024 → nov 2026 |
|---|---|---|
| Prudente | riesgo 15 % | +9 % anual, caída −13 % |
| **Moderado (por defecto)** | riesgo 25 %, sin apalancar | **+12 % anual, caída −18 %** |
| Decidido | riesgo 40 %, apalancamiento ×1,5 | +16 % anual, caída −27 % |
| Agresivo | riesgo 60 %, apalancamiento ×2 | +23 % anual, caída −37 % |

Por encima de ×2 la rentabilidad deja de subir y la caída no; por eso el panel no lo ofrece.

Sobre la cobertura: cubrir **hasta el 100 %** es lo que mejor sale. Cubrir al 200 % («si tu long es
de 100, la cobertura de 200») rinde menos y cae más en los dos periodos (+7,9 % anual y −26 % en la
prueba): deja la cartera en corto, y en corto se pierde cuando el precio rebota.

## Usarlo

```bash
systemctl --user status jstrategy-bot     # ¿está vivo?
systemctl --user restart jstrategy-bot    # reiniciar (conserva cartera, mando y ajustes)
tail -f bot_stdout.log                    # qué está haciendo
```

**Panel:** en el puerto 8787 del servidor, solo en la red de casa (dirección y puerto en `.env`:
`JORGE_BOT_PANEL_HOST` y `JORGE_BOT_PANEL_PORT`). Pide el token de `JORGE_BOT_PANEL_TOKEN`. Enseña patrimonio, exposición, cobertura por moneda y últimas
operaciones, y tiene el mando:

- **Automático** — el bot decide.
- **Pausa** — no opera; las posiciones se quedan como están.
- **Cubrir todo** — cubre el 100 % ahora, sin vender nada.
- **Salir a USDT** — vende la base y cierra coberturas (pide confirmación).

El mando y los ajustes sobreviven a un reinicio: un bot parado a mano no vuelve a operar solo.

Ficheros que escribe: `estado_cartera.json` (la cartera), `estado_bot.json` (mando y ajustes),
`diario_operaciones.csv` (cada operación) y `patrimonio_historico.csv` (una línea por hora).

Los datos vienen del primer mercado que conteste de `binanceusdm, okx, bitget, gate, kucoinfutures,
mexc` (se cambia con `JORGE_BOT_MERCADOS`). Binance responde 451 según la salida a internet del
servidor; el bot cambia solo.

## Comprobarlo

```bash
.venv/bin/python -m pytest          # ~25 s
```

Incluyen: que ningún indicador ni la estrategia miran al futuro; la contabilidad de comisiones,
financiación y coberturas; el mando y el reinicio; quién puede usar el panel; y
`tests/test_replica.py`, que alimenta el bot vela a vela con 60 días reales y exige que acabe
exactamente donde el simulador.

Repetir la investigación (baja ~40 MB la primera vez):

```bash
.venv/bin/python -m investigacion.descargar
.venv/bin/python -m investigacion.validacion todo    # diseño y prueba, con variantes
.venv/bin/python -m investigacion.perfiles           # niveles de riesgo
```

`investigacion/comun.py` fija la frontera (`FIN_DISEÑO = 2024-01-01`). Si algo se ajusta mirando lo
de después, deja de servir como prueba.

## Ideas probadas y descartadas

Cada idea se mide primero en el diseño (2020-2023). Solo pasa a la prueba (2024 →) si en el diseño
se distingue del azar, con el signo esperado y sin depender de un solo año. Lo que no pasa no entra
en el bot, por bien que suene.

Balance a 2026-11-10: de todo lo medido (las quince ideas de la tabla y la estrategia que corre),
solo esta última pasó la prueba. Las huellas de
posicionamiento («el rastro de los grandes») existen y tienen el signo que cabía esperar, pero son
demasiado débiles a este plazo para pagar sus comisiones. Quedan sin poder medirse por falta de
histórico anterior a 2024 o de datos gratuitos: flujos de los ETF y datos de la cadena.

| Idea | Qué salió | Dónde |
|---|---|---|
| Cubrir al 150-200 % (cobertura de Jorge) | Peor en diseño y en prueba: menos ganancia y más caída | `validacion.py` |
| Cortos sueltos siguiendo la tendencia bajista | No aportan: lo que ganan en 2022 lo devuelven el resto | diseño inicial |
| Todo en perpetuos, sin base en contado | 5 puntos menos al año: los largos pagan financiación | `validacion.py` |
| Comprar el retroceso en tendencia alcista | Tras una caída en tendencia alcista se gana MENOS que de media; lo que se premia es la fuerza | diseño |
| Tendencia relativa (cada alt medida en BTC) | Sharpe 1,33 en diseño, **−0,32 en la prueba**. Descartada por la prueba | `relativa.py` |
| Fuerza relativa entre monedas | Vive de 2020-21, con monedas elegidas a toro pasado | diseño inicial |
| Vender en vez de cubrir si la financiación es negativa | Lo que ahorra en financiación se lo comen las comisiones | diseño |
| Acelerar tras un tirón en tendencia plena | Igual que apalancar un poco siempre, con más comisiones | diseño |
| Posicionamiento: traders grandes menos multitud | Signo correcto (t ≈ 1,4-2,3 en BTC) pero añadido a la estrategia no mejora nada | `posicionamiento.py` |
| Cubrir más las monedas con más financiación | La más financiada rinde peor que las demás (t ≈ −3), pero el ajuste no mueve el resultado | `financiacion_relativa.py` |
| Manga neutral: vender lo más financiado, comprar lo menos | Cobra ~19 %/año de financiación, pero con 40 % de volatilidad y años en contra (2020: −13 %) | diseño |
| Interés abierto, purgas de liquidación, flujo de compras | Sin poder predictivo utilizable a 1-7 días | `estudio_huellas.py` |
| Prima de Coinbase (demanda de EE. UU.) | No predice a 1, 3 ni 7 días (\|t\| < 1,3) | `huellas.py` |
| Emisión de monedas estables | Signo esperado, pero t ≈ 1,4 y cambia de signo según el año | diseño |
| Señal del bot antiguo (10 argumentos) | Indistinguible del azar en 6,7 años | `estudio_senal_antigua.py` |

## Por qué se cambió el sistema anterior

- **Su backtest veía el futuro.** Filtraba las velas de 4 h y diarias por hora de apertura, así que
  la vela en curso entraba con su cierre definitivo. De ahí su factor de beneficio de 1,41 frente
  al 0,54 real en simulación.
- **Su señal no predecía nada.** Recalculada sobre 6,7 años de Bitcoin solo con velas cerradas: 12
  entradas largas filtradas (1,8 al año) y un rendimiento tras la señal indistinguible del azar
  (`python -m investigacion.estudio_senal_antigua`).
- **La cobertura no podía dispararse.** Saltaba a −20 % y el stop cerraba la posición a −3 %. Además
  la dimensionaba sobre una fracción de la posición y dividía su ganancia entre el apalancamiento.
- **La simulación no descontaba comisiones**, con objetivos de +0,8 %.
- **Tres implementaciones distintas** de la estrategia (bucle en vivo, backtest y `seed_buckets`):
  lo que se medía no era lo que se operaba.
- Y el servicio llevaba caído desde octubre: una actualización del sistema dejó sin librerías su
  entorno de Python.

## Antes de pensar en dinero real

Nada de esto está hecho, y no se activa con una variable (`JORGE_BOT_PAPER=false` hace que el bot se
niegue a arrancar):

1. Varios meses de simulación que se parezcan a lo medido.
2. Elegir un mercado donde se pueda operar contado y perpetuos desde donde vive la cuenta.
3. Escribir y probar la ejecución real: órdenes, reintentos, conciliación con el mercado y el
   traspaso de garantía entre la cartera de contado y la de futuros.
