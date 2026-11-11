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
