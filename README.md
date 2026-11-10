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

La cobertura de una moneda se reajusta cuando su exposición se aparta del objetivo más de un 10 % de
su base. En los extremos no hay tolerancia: sin tendencia se cubre todo lo que hay, y con tendencia
plena no queda ninguna cobertura.

Es la idea del material original (EMAs para leer la estructura, cobertura en vez de vender), pero
graduada por la tendencia y sin pasar del 100 %.

## Cuánto rinde, medido

Simulado sobre velas reales de Binance con comisiones (0,10 % contado, 0,05 % perpetuo),
deslizamiento (0,02 %) y la financiación real de cada perpetuo. Todo se **diseñó con 2020-2023** y
se **probó una sola vez con 2024 → nov 2026**, que no se usó para ajustar nada.

| | Diseño 2020-2023 | **Prueba 2024 → nov 2026** |
|---|---|---|
| Rentabilidad anual | +43 % | **+12,4 %** |
| Peor caída | −11,7 % | **−17,6 %** |
| Sharpe | 2,29 | **0,84** |
| Por año | +61 / +93 / −6 / +46 % | **+33 % (2024), +0,4 % (2025), +4,4 % (2026)** |

En la prueba, comprar Bitcoin y aguantar dio +22 % anual con una caída del −53 % (y −6 % y −15 % en
2025 y 2026); la cesta de las diez monedas, +2 % anual con una caída del −68 %.

**Lo que hay que esperar es la columna de la derecha, no la de la izquierda.** Que la prueba salga
peor que el diseño es lo normal; lo que importa es que sigue en positivo. Aun así son 2,9 años: no
es una garantía, y habrá años en negativo.

**No gana todos los meses, ni mucho menos todos los días.** En la prueba fueron positivos 4 de cada
10 meses: la ganancia llega a rachas, cuando hay tendencia, y entre racha y racha el bot está cubierto
y casi quieto. Las ganancias se reinvierten solas: cada posición es un porcentaje del patrimonio del
momento, así que lo ganado entra a trabajar en la decisión siguiente (interés compuesto).

Niveles de riesgo (misma estrategia, más o menos exposición; se cambian en el panel):

| Nivel | Ajuste | Prueba 2024 → nov 2026 | Por año (2024 / 2025 / 2026) |
|---|---|---|---|
| Constante | riesgo 10 % | +8,2 % anual, caída −8,7 % | +21 / +0,1 / +3,3 % |
| Prudente | riesgo 15 % | +9,5 % anual, caída −12,1 % | +25 / −0,1 / +3,7 % |
| **Moderado (por defecto)** | riesgo 25 %, sin apalancar | **+12,4 % anual, caída −17,6 %** | +33 / +0,4 / +4,4 % |
| Decidido | riesgo 40 %, apalancamiento ×1,5 | +16,6 % anual, caída −27,4 % | +54 / −3,8 / +4,7 % |
| Agresivo | riesgo 60 %, apalancamiento ×2 | +22,7 % anual, caída −37,3 % | +79 / −5,5 / +5,9 % |

Por encima de ×2 la rentabilidad deja de subir y la caída no; por eso el panel no lo ofrece.

Bajar el nivel no hace la ganancia pareja: la hace más pequeña y con caídas más pequeñas. Cuanto más
bajo, más pesa lo que cobra la cobertura y menos la tendencia, y por unidad de riesgo rinde más
(Sharpe 1,09 en Constante frente a 0,84 en Moderado). El extremo es el mando «Cubrir todo», sin
tendencia ninguna: +3,4 % anual con una caída del −0,2 %, pero 7,0 % en 2024 y solo 1,7 % y 1,2 % en
2025 y 2026, porque la financiación que cobra la cobertura ha bajado mucho.

Sobre la cobertura: cubrir **hasta el 100 %** es lo que mejor sale. Cubrir al 200 % («si tu long es
de 100, la cobertura de 200») rinde menos y cae más en los dos periodos (+6,6 % anual y −26 % en la
prueba): deja la cartera en corto, y en corto se pierde cuando el precio rebota.

## Usarlo

```bash
systemctl --user status jstrategy-bot     # ¿está vivo?
systemctl --user restart jstrategy-bot    # reiniciar (conserva cartera, mando y ajustes)
tail -f bot_stdout.log                    # qué está haciendo
```

**Panel:** en el puerto 8787 del servidor, solo en la red de casa (dirección y puerto en `.env`:
`JORGE_BOT_PANEL_HOST` y `JORGE_BOT_PANEL_PORT`). Pide el token de `JORGE_BOT_PANEL_TOKEN`. Enseña patrimonio, exposición, cobertura por moneda y últimas
operaciones; deja elegir el nivel de riesgo con un botón por nivel (o a medida, con los deslizadores), y tiene el mando:

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
.venv/bin/python -m pytest          # ~40 s
```

Incluyen: que ningún indicador ni la estrategia miran al futuro; la contabilidad de comisiones,
financiación y coberturas; el mando y el reinicio; quién puede usar el panel; y
`tests/test_replica.py`, que alimenta el bot vela a vela con 60 días reales y exige que acabe
exactamente donde el simulador; y `tests/test_niveles.py`, que recalcula las cifras de cada nivel de
riesgo que enseña el panel y falla si dejan de ser ciertas.

Repetir la investigación (baja ~40 MB la primera vez):

```bash
.venv/bin/python -m investigacion.descargar
.venv/bin/python -m investigacion.validacion todo    # diseño y prueba, con variantes
.venv/bin/python -m investigacion.perfiles           # niveles de riesgo
.venv/bin/python -m investigacion.banda_cobertura    # la regla de la cobertura, antes y ahora
```

`investigacion/comun.py` fija la frontera (`FIN_DISEÑO = 2024-01-01`). Si algo se ajusta mirando lo
de después, deja de servir como prueba.

## Ideas probadas y descartadas

Cada idea se mide primero en el diseño (2020-2023). Solo pasa a la prueba (2024 →) si en el diseño
se distingue del azar, con el signo esperado y sin depender de un solo año. Lo que no pasa no entra
en el bot, por bien que suene.

Balance a 2026-11-10: de todo lo medido (las ideas de la tabla y la estrategia que corre), solo han
pasado la prueba esta última y un arreglo de cómo ajusta su cobertura (`banda_cobertura.py`: medía
la tolerancia sobre la cobertura y no sobre la base, y con la tendencia en contra podía dejar sin
cubrir hasta un 20 % de la base; arreglado, gana igual o más y cae menos en los cuatro niveles de
riesgo y en los dos periodos). Un aviso: cada idea nueva se mide contra los mismos 2,9 años de
prueba, y cuantas más se miden, menos vale esa prueba para la siguiente. Lo que de verdad cuenta
desde aquí es que la simulación en vivo se parezca a lo medido. Las huellas de
posicionamiento («el rastro de los grandes») existen y tienen el signo que cabía esperar, pero son
demasiado débiles a este plazo para pagar sus comisiones. Un aviso sobre esa conclusión: los ratios de
los traders grandes solo existen desde finales de 2022, así que su diseño es poco más de un año. Quedan sin poder medirse por falta de
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
| Un modelo que combina las catorce huellas a la vez | Ajustado con un año y medido con el otro no se distingue del azar (t ≈ 1). No llegó a la prueba | `modelo.py` |
| Interés abierto, purgas de liquidación, flujo de compras | Sin poder predictivo utilizable a 1-7 días | `estudio_huellas.py` |
| Prima de Coinbase (demanda de EE. UU.) | No predice a 1, 3 ni 7 días (\|t\| < 1,3) | `huellas.py` |
| Emisión de monedas estables | Signo esperado, pero t ≈ 1,4 y cambia de signo según el año | diseño |
| Señal del bot antiguo (10 argumentos) | Indistinguible del azar en 6,7 años | `estudio_senal_antigua.py` |
| Renta: la base cubierta, en las monedas que más financiación pagan | Diseño: de +43 a +51 % anual, con toda la vecindad entre +48 y +53 %. **Prueba: +11,4 % frente a +11,8 %**, con más caída. Desde 2024 la financiación es baja y parecida entre monedas: elegir da 1,1 puntos y los cambios de moneda cuestan 2,4 | `renta.py` |
| Más tamaño cuanto más confirmada la entrada | La ventaja aparece con las primeras señales y no crece con más: el reparto convexo rinde algo menos y el cóncavo algo más, todo dentro del ruido (Sharpe 2,18 a 2,35 frente a 2,29) | `tamano.py` |
| Promediar la caída: descubrir un poco de la base por cada tramo que cae | Solo añade exposición. Con una cuarta parte de la base apenas mueve la ganancia y ya empeora la caída (−14 a −22 % frente a −11,7 %); con más, es de donde salen las caídas (−19 a −49 %). Y no supera a estar largo lo mismo sin mirar cuánto ha caído | `tamano.py` |
| Jugar el rango y reversión de corto plazo | Pierden incluso sin comisiones (Sharpe −0,2 a −1,2): a estos plazos hay inercia, no rebote | `reversion.py` |
| Pesar los relojes según cuál acierta últimamente | Depende de cómo se pese: una forma mejora (2,48) y las otras dos empeoran (2,07 a 2,28). Sin consistencia | `adaptacion.py` |
| Frenar cuando la propia estrategia viene perdiendo | Peor en todas las variantes: frena tarde y se pierde la vuelta | `adaptacion.py` |

## Las reglas de Jorge, comprobadas una por una

Las reglas que se pueden escribir sin ambigüedad, medidas sobre Bitcoin (`investigacion/reglas_jorge.py`;
las tres últimas, sobre las diez monedas, en `tamano.py` y `reversion.py`).
Las que predicen, solo con 2020-2023; las afirmaciones de hecho, con todo el histórico. No son las
reglas del bot: son material del que aprender, y entra lo que los datos respaldan.

| Regla | Lo que dicen los datos | Veredicto |
|---|---|---|
| EMA10 sobre EMA55 en 4 h y en diario como guía | Con la EMA10 arriba en diario, BTC rindió +205 % anualizado; por debajo, +15 % | **Se cumple.** Es el corazón del bot: dos de sus diez relojes son estas EMAs |
| Cobertura en vez de vender | En el diseño, mantener la base y cubrirla rindió algo más que vender y recomprar (cobra financiación y paga menos comisión) | **Se cumple**, cubriendo hasta el 100 % |
| Cobertura al doble («nunca pierdes») | Al doble queda en corto y pierde cuando rebota: menos ganancia y más caída | No se cumple. Su propia regla avanzada (1:1 pasado el −10 %) sí |
| Bitcoin manda sobre las alts | En el diseño, comprar alts solo con BTC en tendencia positiva redujo la peor caída del −26 % al −14 % | **Se cumple** (es el filtro del bot) |
| «Soy 98 % largo» | Los cortos sueltos no aportan | **Se cumple** |
| No entrar si el precio está >3 % sobre la EMA10 diaria | Lejos de la EMA10: +3,6 % a 7 días; cerca: +1,1 % | Al revés |
| Comprar el retroceso a la EMA | Tras una caída en tendencia alcista se gana menos que de media | No se cumple |
| Vela 7 tras el cruce | Velas 5-8: +0,32 % a 3 días; las demás: +0,30 % | Sin diferencia |
| Cada máximo se retestea «por ley» | Vuelve al nivel el 86 % de las veces; esperar no rinde más y deja fuera el resto | A medias |
| Volumen de parada, disparo del squeeze | Igual que entrar en un momento cualquiera | No se distinguen del azar |
| Lunes alcista, ventana de Chicago | Lunes +0,38 % frente a +0,15 % (t = 1,3); la ventana, nada | No se distinguen del azar |
| «Nunca cae un 20 % en un día» | BTC: 6 días (peor, −45 %). ETH: 15. SOL: 30 | Falso |
| Base escrita: ×100, recompras dobladas cada −1,6 %, sin stop | En 6,9 años de BTC: 1 730 operaciones ganadoras y la cuenta de futuros liquidada 24 veces (con su filtro de EMAs) | Gana casi siempre y cada pocos meses lo pierde todo |
| Entrar con el 0,1 % mientras cae e ir promediando | Tras caer con la tendencia en contra se gana menos que de media (BTC: entre −0,8 y +1,3 % a 7 días frente a +1,3 % en un momento cualquiera, salvo en el suelo de 2022, que es un único episodio; alts: −0,1 a +0,9 % frente a +2,6 %). Promediar no gana por sí mismo | Lo que protege es el tamaño pequeño, no el promedio. El bot hace lo equivalente: nada expuesto mientras cae |
| Más porcentaje cuando la entrada está confirmada | La ventaja está desde las primeras señales y no crece con más confirmación | No se distingue; el bot gradúa de forma lineal |
| Jugar el rango: comprar en el soporte, vender en la resistencia | Escrito con reglas fijas (extremos de los últimos 3 a 20 días, sin tendencia) pierde, incluso sin comisiones | No se cumple con reglas; a mano depende de leer el gráfico |

No se pueden comprobar así, porque dependen de mirar el gráfico: order blocks, zonas de liquidez, perfil
de volumen, «vender la noticia» y la lectura de techos y suelos. Ahí es donde la mano de Jorge puede
valer algo que ninguna regla escrita recoge. Su material original (capturas, textos y Excel) no trae un
registro de sus operaciones con fechas y resultados, así que no hay nada de lo que un algoritmo pueda
aprender directamente: lo que hay son reglas, y son las de la tabla.

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
