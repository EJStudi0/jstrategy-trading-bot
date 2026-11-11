# Jorge en futuros, intradía — plan y cuaderno

Rumbo fijado por el dueño (2026-11-11): Jorge solo en futuros, intradía; contexto en diario y 4 h, zona
en 1 h, decisión en 30 min. La prueba (2024 en adelante) **no se ha tocado** para nada de lo que sigue.

## Reglas del estudio
- Diseño con 2020-2023, diez monedas, velas de 15 min de futuros; 30 min, 1 h, 4 h y diario salen de ahí.
- Costes: 0,02 % orden limitada, 0,06 % a mercado, 0,02 % de deslizamiento al cruzar, y financiación.
- Solo velas cerradas. Si en una vela caben stop y objetivo, cuenta el stop. Una orden limitada solo se da
  por hecha si el precio la atraviesa.
- Gestión: riesgo fijo y pequeño por operación, siempre con stop. La martingala a 100x del material
  queda descartada (se liquida).

## Lo fijado antes de mirar resultados (`intradia.py`)
Fondo = cierre diario frente a su media de 10 **y** cierre de 4 h frente a su media de 55, los dos del mismo lado.
- **A · ruptura con retroceso**: rango estrecho de 8 h en 30 min, cierre fuera con volumen, orden limitada en el borde roto.
- **B · rebote en la media de 10** de 30 min con la de 10 sobre la de 55.
- **C · primer regreso a una zona virgen**: última vela contraria de 1 h antes de un impulso que rompe estructura.

## Resultados de diseño (2026-11-11)
1. **A, B y C pierden** en 2020-2023, en los cuatro años y en las diez monedas: −0,14 R, −0,17 R y −0,12 R
   por operación. Acierto ~39-41 % con objetivo 1,5 R: es lo que da entrar al azar.
2. **216 variantes** (objetivo 1/1,5/2,5 R; aguante 6 h/16 h; ADX 0/23/30; horario Londres-EE. UU.; solo
   laborables): **ninguna positiva**. Sin comisiones quedan en ~0: no es que los costes se coman una
   ventaja, es que no la hay (`intradia_variantes.py`).
3. **Entrar al romper, a mercado, sin esperar el retroceso** (`intradia_inercia.py`): también pierde si se
   cobra rápido (1,5 R en 6 h: −0,08 R), pero mejora de forma ordenada cuanto más se deja correr y más
   volumen se exige. Lo mejor: máximo/mínimo de 24 h roto con volumen 2,5× y sin objetivo, salida a las
   48 h o por stop de 1 ATR: +0,14 R (+0,16 % neto) por operación, 3 944 operaciones, acierto 22 %;
   por año +0,28 / +0,22 / −0,01 / +0,12. Coincide con lo ya medido en el README: a estos plazos hay
   inercia, no rebote. Es una ventaja pequeña, de pocas ganadoras grandes, y más floja en 2022-2023.

## Siguiente paso
Trabajar SOLO la inercia en diseño: stop que sigue al precio, filtro de días de mucho movimiento, cartera
con riesgo fijo e interés compuesto, caída máxima. Fijar UNA versión y probarla UNA vez con 2024 en adelante.

## Segunda vuelta de diseño de la inercia (2026-11-11, `intradia_inercia2.py`)
576 combinaciones, solo 2020-2023. Lo que enseñan, en orden:
- El **stop que sigue al precio empeora** siempre (corta las pocas ganadoras grandes). Fuera.
- Cuanto **más se aguanta**, mejor (4 días > 2 días). Ya no es intradía puro: mediana 11 h, media 32 h.
- El **fondo a favor** (diario y 4 h) ayuda; el **stop ancho** (2 ATR) es más firme que el estrecho.
- Exigir **movimiento por encima de lo normal** deja menos operaciones, con menos caída.
- Ganan los **largos**; los cortos quedan cerca de cero.

## VERSIÓN FIJADA para la prueba única (escrita ANTES de mirar 2024+)
Diez monedas. Vela de 30 min que cierra fuera del máximo/mínimo de 48 h (96 velas) con volumen ≥ 2,5× su media,
fondo a favor, movimiento de 1 h ≥ su media de 30 días. Entrada a mercado, stop fijo a 2 ATR de 30 min,
sin objetivo, salida a los 4 días. Largos y cortos. Cuenta: riesgo 0,5 % por operación, hasta 4 abiertas,
palanca máxima 3× por posición.
Se eligió del centro de la rejilla, no el mejor resultado: sus 18 vecinas son positivas.
Diseño: 1 441 operaciones (30 al mes), acierto 21 %, +0,30 R por operación; cuenta +38 % anual,
caída máxima −30 %, 49 % de meses en positivo; por año +0,37 / +0,61 / +0,24 / +0,12 R.
El 5 % de las operaciones aporta más que el total: depende de pocas ganadoras grandes.

**Criterio, fijado ahora**: pasa si en 2024+ da ≥ +0,10 R por operación y la cuenta gana con caída no peor
que −40 %. Si no, se descarta y no se retoca.

## PRUEBA ÚNICA (2026-11-11, `intradia_prueba.py`) — NO PASA
2024-01 a 2026-11, la versión fijada sin tocar: 1 333 operaciones, acierto 17,6 %, **+0,045 R** por operación
(criterio: ≥ +0,10). Cuenta: +11,5 % anual, caída máxima −32,5 %, 47 % de meses en positivo, peor mes −12,4 %.
Por año: 2024 +0,14 R · 2025 −0,26 R · 2026 +0,33 R. Largos +0,48 R, cortos −0,26 R.
Gana algo, pero menos de lo exigido y con una caída que no compensa: **descartada tal cual**.
Aviso: «solo largos» salía mejor también en diseño (+0,49 frente a +0,08), pero se fijó con los dos lados.
Quedarse ahora solo con los largos sería ajustar mirando la prueba; si alguna vez se estudia, su prueba
honrada es el futuro (demo o datos nuevos), no estos mismos años.
