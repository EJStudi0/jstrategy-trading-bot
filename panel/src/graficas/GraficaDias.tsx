// Ganancia de cada día (o mes) en barras: verde gana, rojo pierde; la de hoy, más clara, sigue
// abierta. La línea discontinua es lo medido en la prueba para el nivel en uso.
import {
  createChart, HistogramSeries, LineStyle, type IChartApi, type IPriceLine, type ISeriesApi, type MouseEventParams, type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Vacio } from "../componentes/ui";
import { cifra, dinero, valido } from "../lib/formato";
import { colores, conAlfa } from "../lib/tema";
import { opcionesBase } from "./base";

export interface Barra {
  clave: string;          // "2026-11-10" o "2026-11-01" para un mes
  valor: number | null;   // null = sin datos ese día
  parcial?: boolean;
}

export function GraficaDias({ barras, referencia, etiquetaReferencia, tema, alto = 300, lectura }: {
  barras: Barra[]; referencia?: number | null; etiquetaReferencia?: string; tema: string; alto?: number;
  lectura: (clave: string | null) => ReactNode;
}) {
  const caja = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const serie = useRef<ISeriesApi<"Histogram"> | null>(null);
  const linea = useRef<IPriceLine | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const hay = barras.some((b) => valido(b.valor));
  const datos = useMemo(() => barras, [barras]);

  useEffect(() => {
    if (!caja.current || !hay) return;
    const c = colores();
    const ch = createChart(caja.current, {
      ...opcionesBase(c),
      timeScale: { ...opcionesBase(c).timeScale, timeVisible: false, rightOffset: 1, fixLeftEdge: true, fixRightEdge: true },
    });
    chart.current = ch;
    serie.current = ch.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: false, base: 0,
      priceFormat: { type: "custom", formatter: (p: number) => cifra(p, Math.abs(p) >= 10 ? 0 : 2) + " $", minMove: 0.01 },
    });
    const alMover = (p: MouseEventParams) => setCursor(p.time ? String(p.time) : null);
    ch.subscribeCrosshairMove(alMover);
    return () => {
      ch.unsubscribeCrosshairMove(alMover);
      ch.remove();
      chart.current = null;
      serie.current = null;
      linea.current = null;
    };
  }, [hay, tema]);

  useEffect(() => {
    const se = serie.current;
    if (!chart.current || !se) return;
    const c = colores();
    se.setData(datos.map((b) => valido(b.valor)
      ? { time: b.clave as Time, value: b.valor,
          color: conAlfa(b.valor >= 0 ? c.subeMarca : c.bajaMarca, b.parcial ? 0.45 : 0.95) }
      : { time: b.clave as Time }));
    if (valido(referencia) && referencia !== 0) {
      const opciones = { price: referencia, color: c.acento, lineWidth: 1 as const, lineStyle: LineStyle.Dashed,
                         axisLabelVisible: true, title: etiquetaReferencia ?? "" };
      if (linea.current) linea.current.applyOptions(opciones);
      else linea.current = se.createPriceLine(opciones);
    } else if (linea.current) {
      se.removePriceLine(linea.current);
      linea.current = null;
    }
    chart.current.timeScale().fitContent();
  }, [datos, referencia, etiquetaReferencia, tema]);

  if (!hay) return <Vacio>Aún no hay días que enseñar.</Vacio>;
  const activo = cursor ?? [...datos].reverse().find((b) => valido(b.valor))?.clave ?? null;

  // La lectura va encima de la gráfica, no sobre las barras: en el móvil las tapaba.
  return (
    <div>
      <div className="min-h-11 px-4 pt-3 text-xs" aria-live="polite">{lectura(activo)}</div>
      <div className="relative" style={{ height: alto }}>
        <div ref={caja} className="absolute inset-0" />
      </div>
    </div>
  );
}

export const textoDinero = (x: number | null | undefined) => dinero(x, { signo: true });
