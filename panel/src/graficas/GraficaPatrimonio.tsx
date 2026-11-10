// Curva de patrimonio con la exposición en su propio panel. «Comparar» la pone en % junto a Bitcoin
// (los dos indexados al principio del tramo, en un mismo eje: nunca dos escalas en una gráfica).
import {
  AreaSeries, createChart, HistogramSeries, LineSeries, PriceScaleMode, type IChartApi, type ISeriesApi,
  type MouseEventParams, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { Vacio, cx } from "../componentes/ui";
import { cifra, dinero, pctFraccion, valido } from "../lib/formato";
import { colores, conAlfa } from "../lib/tema";
import { aLocal } from "../lib/tiempo";
import { opcionesBase, textoMomento } from "./base";

export interface PuntoP { t: number; v: number; neto: number; btc: number | null }

interface Lectura { t: Time; v: number; btc?: number | null; neto: number; pctV?: number; pctB?: number }

export function GraficaPatrimonio({ puntos, comparar, tema }: { puntos: PuntoP[]; comparar: boolean; tema: string }) {
  const caja = useRef<HTMLDivElement>(null);
  const grafica = useRef<IChartApi | null>(null);
  const series = useRef<{ principal?: ISeriesApi<"Area"> | ISeriesApi<"Line">; btc?: ISeriesApi<"Line">; neto?: ISeriesApi<"Histogram"> }>({});
  const [lectura, setLectura] = useState<Lectura | null>(null);

  // Un punto por segundo «local», en orden (la librería no admite repetidos).
  const datos = useMemo(() => {
    const porT = new Map<number, PuntoP & { tl: UTCTimestamp }>();
    for (const p of puntos) if (valido(p.t) && valido(p.v)) porT.set(aLocal(p.t), { ...p, tl: aLocal(p.t) });
    return [...porT.values()].sort((a, b) => a.tl - b.tl);
  }, [puntos]);
  const datosRef = useRef(datos);
  datosRef.current = datos;

  useEffect(() => {
    if (!caja.current || datos.length < 2) return;
    const c = colores();
    const chart = createChart(caja.current, opcionesBase(c));
    grafica.current = chart;
    if (comparar) {
      chart.priceScale("right").applyOptions({ mode: PriceScaleMode.Percentage });
      series.current.btc = chart.addSeries(LineSeries, {
        color: c.texto3, lineWidth: 1, priceLineVisible: false, lastValueVisible: true, title: "BTC", crosshairMarkerRadius: 3,
      });
      series.current.principal = chart.addSeries(LineSeries, {
        color: c.serie1, lineWidth: 2, priceLineVisible: false, title: "Bot", crosshairMarkerRadius: 4,
        crosshairMarkerBorderColor: c.panel,
      });
    } else {
      series.current.principal = chart.addSeries(AreaSeries, {
        lineColor: c.serie1, lineWidth: 2, topColor: conAlfa(c.serie1, 0.32), bottomColor: conAlfa(c.serie1, 0.0),
        priceLineVisible: true, priceLineColor: conAlfa(c.serie1, 0.6), priceLineStyle: 3, crosshairMarkerRadius: 4,
        crosshairMarkerBorderColor: c.panel, priceFormat: { type: "custom", formatter: (p: number) => cifra(p, 2), minMove: 0.01 },
      });
      series.current.btc = undefined;
    }
    series.current.neto = chart.addSeries(HistogramSeries, {
      color: conAlfa(c.texto3, 0.55), priceLineVisible: false, lastValueVisible: false,
      priceFormat: { type: "custom", formatter: (p: number) => pctFraccion(p, 0), minMove: 0.001 },
    }, 1);
    chart.panes()[1]?.setHeight(70);
    chart.panes()[1]?.priceScale("right").applyOptions({ scaleMargins: { top: 0.2, bottom: 0 } });

    const alMover = (p: MouseEventParams) => {
      if (!p.time || !series.current.principal) { setLectura(null); return; }
      const d = datosRef.current.find((x) => x.tl === p.time);
      if (d) setLectura({ t: p.time, v: d.v, btc: d.btc, neto: d.neto });
    };
    chart.subscribeCrosshairMove(alMover);
    return () => {
      chart.unsubscribeCrosshairMove(alMover);
      chart.remove();
      grafica.current = null;
      series.current = {};
    };
  }, [comparar, tema, datos.length < 2]);

  useEffect(() => {
    const s = series.current;
    if (!grafica.current || !s.principal || datos.length < 2) return;
    s.principal.setData(datos.map((d) => ({ time: d.tl, value: d.v })));
    if (s.btc) s.btc.setData(datos.filter((d) => valido(d.btc)).map((d) => ({ time: d.tl, value: d.btc as number })));
    s.neto?.setData(datos.map((d) => ({ time: d.tl, value: Math.max(0, d.neto) })));
    grafica.current.timeScale().fitContent();
  }, [datos, comparar, tema]);

  if (datos.length < 2) return <Vacio>La curva aparece en cuanto haya un par de horas de historia.</Vacio>;

  const ultimo = datos[datos.length - 1];
  const primero = datos[0];
  const l: Lectura = lectura ?? { t: ultimo.tl, v: ultimo.v, btc: ultimo.btc, neto: ultimo.neto };
  const pctV = (l.v / primero.v - 1) * 100;
  const b0 = datos.find((d) => valido(d.btc))?.btc;
  const pctB = valido(l.btc) && valido(b0) ? (l.btc / b0 - 1) * 100 : null;

  return (
    <div className="relative min-h-[360px] flex-1 sm:min-h-[400px]">
      <div className="pointer-events-none absolute top-2 left-3 z-10 flex flex-wrap items-baseline gap-x-4 gap-y-0.5 text-xs">
        <span className="num text-texto-3">{textoMomento(l.t)}</span>
        <span className="flex items-baseline gap-1.5">
          <span className="inline-block h-0.5 w-3 translate-y-[-3px] rounded bg-serie-1" />
          <span className="num font-semibold text-texto">{dinero(l.v)}</span>
          <span className={cx("num", pctV >= 0 ? "text-sube" : "text-baja")}>{cifra(pctV, 2, true)} %</span>
        </span>
        {comparar && (
          <span className="flex items-baseline gap-1.5">
            <span className="inline-block h-0.5 w-3 translate-y-[-3px] rounded bg-texto-3" />
            <span className="text-texto-3">BTC</span>
            <span className={cx("num", (pctB ?? 0) >= 0 ? "text-sube" : "text-baja")}>{pctB === null ? "—" : cifra(pctB, 2, true) + " %"}</span>
          </span>
        )}
        <span className="text-texto-3">expuesto <span className="num text-texto-2">{pctFraccion(l.neto, 1)}</span></span>
      </div>
      <span className="pointer-events-none absolute bottom-[96px] left-3 z-10 text-[10.5px] font-semibold tracking-wide text-texto-3 uppercase">Exposición</span>
      <div ref={caja} className="absolute inset-0" />
    </div>
  );
}
