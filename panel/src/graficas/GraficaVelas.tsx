// Velas de 4 h de una moneda con lo que mira el bot: el cruce de medias y el canal elegidos, las
// operaciones que hizo (marcas) y, debajo, su puntuación de tendencia de −1 a +1.
import {
  CandlestickSeries, createChart, createSeriesMarkers, HistogramSeries, LineSeries, LineStyle,
  type IChartApi, type IPriceLine, type ISeriesApi, type ISeriesMarkersPluginApi, type MouseEventParams, type SeriesMarkerBar,
  type SeriesMarkerBarPosition, type SeriesMarkerShape, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";
import { Vacio, cx } from "../componentes/ui";
import { cifra, decimalesDePrecio, precio, valido } from "../lib/formato";
import { colores, conAlfa } from "../lib/tema";
import { aLocal } from "../lib/tiempo";
import type { Grafica } from "../tipos";
import { opcionesBase, textoMomento } from "./base";

interface Barra { tl: UTCTimestamp; o: number; h: number; l: number; c: number; i: number }

export function GraficaVelas({ g, reloj, canal, marcas, tema, alto = 520 }: {
  g: Grafica | undefined; reloj: string; canal: string; marcas: boolean; tema: string; alto?: number;
}) {
  const caja = useRef<HTMLDivElement>(null);
  const chart = useRef<IChartApi | null>(null);
  const s = useRef<{ velas?: ISeriesApi<"Candlestick">; rapida?: ISeriesApi<"Line">; lenta?: ISeriesApi<"Line">;
                     alto?: ISeriesApi<"Line">; bajo?: ISeriesApi<"Line">; tendencia?: ISeriesApi<"Histogram">;
                     marcas?: ISeriesMarkersPluginApi<Time>; ahora?: IPriceLine }>({});
  const [cursor, setCursor] = useState<number | null>(null);
  const ultimoSimbolo = useRef<string | null>(null);

  const barras = useMemo<Barra[]>(() => {
    if (!g) return [];
    const out: Barra[] = [];
    g.t.forEach((t, i) => {
      const [o, h, l, c] = [g.o[i], g.h[i], g.l[i], g.c[i]];
      if (valido(o) && valido(h) && valido(l) && valido(c)) out.push({ tl: aLocal(t), o, h, l, c, i });
    });
    return out;
  }, [g]);
  const barrasRef = useRef(barras);
  barrasRef.current = barras;
  const hay = barras.length > 10;
  const dec = barras.length ? decimalesDePrecio(barras[barras.length - 1].c) : 2;

  useEffect(() => {
    if (!caja.current || !hay) return;
    const c = colores();
    const ch = createChart(caja.current, opcionesBase(c, { interaccion: true }));
    chart.current = ch;
    ultimoSimbolo.current = null;
    const formato = { type: "custom" as const, formatter: (p: number) => cifra(p, dec), minMove: Math.pow(10, -dec) };
    s.current.velas = ch.addSeries(CandlestickSeries, {
      upColor: c.subeMarca, downColor: c.bajaMarca, wickUpColor: c.subeMarca, wickDownColor: c.bajaMarca,
      borderVisible: false, priceFormat: formato, priceLineColor: c.texto3,
    });
    s.current.marcas = createSeriesMarkers(s.current.velas, []);
    const canal = { color: conAlfa(c.texto2, 0.55), lineWidth: 1 as const, lineStyle: LineStyle.Dashed, priceLineVisible: false,
                    lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: formato, autoscaleInfoProvider: () => null };
    s.current.alto = ch.addSeries(LineSeries, canal);
    s.current.bajo = ch.addSeries(LineSeries, canal);
    s.current.rapida = ch.addSeries(LineSeries, { color: c.serie2, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: formato });
    s.current.lenta = ch.addSeries(LineSeries, { color: c.serie4, lineWidth: 2, priceLineVisible: false,
      lastValueVisible: false, crosshairMarkerVisible: false, priceFormat: formato });
    s.current.tendencia = ch.addSeries(HistogramSeries, {
      priceLineVisible: false, lastValueVisible: true,
      priceFormat: { type: "custom", formatter: (p: number) => cifra(p, 2, true), minMove: 0.01 },
      autoscaleInfoProvider: () => ({ priceRange: { minValue: -1, maxValue: 1 } }),
    }, 1);
    ch.panes()[1]?.setHeight(88);
    const alMover = (p: MouseEventParams) => {
      if (!p.time) { setCursor(null); return; }
      const b = barrasRef.current.find((x) => x.tl === p.time);
      setCursor(b ? b.i : null);
    };
    ch.subscribeCrosshairMove(alMover);
    return () => {
      ch.unsubscribeCrosshairMove(alMover);
      ch.remove();
      chart.current = null;
      s.current = {};
    };
  }, [hay, tema, dec, g?.simbolo]);

  // Datos: al cambiar de moneda se encuadran las últimas ~3 semanas; al refrescar, se queda donde estaba.
  useEffect(() => {
    const ch = chart.current;
    const se = s.current;
    if (!ch || !g || !se.velas || !hay) return;
    const c = colores();
    se.velas.setData(barras.map((b) => ({ time: b.tl, open: b.o, high: b.h, low: b.l, close: b.c })));
    const linea = (serie: (number | null)[] | undefined) =>
      barras.map((b) => (valido(serie?.[b.i]) ? { time: b.tl, value: serie![b.i] as number } : { time: b.tl }));
    const m = g.medias[reloj];
    se.rapida?.setData(linea(m?.rapida));
    se.lenta?.setData(linea(m?.lenta));
    const k = g.canales[canal];
    se.alto?.setData(linea(k?.alto));
    se.bajo?.setData(linea(k?.bajo));
    se.tendencia?.setData(barras.map((b) => {
      const v = g.puntuacion[b.i] ?? 0;
      return { time: b.tl, value: v, color: conAlfa(v >= 0 ? c.serie1 : c.bajaMarca, 0.35 + 0.5 * Math.abs(v)) };
    }));
    // Marcas: una por vela y tipo de operación.
    const grupos = new Map<string, { t: UTCTimestamp; tipo: string; nocional: number; n: number }>();
    if (marcas) {
      for (const op of g.marcas) {
        const tipo = op.pata === "contado" ? (op.lado === "compra" ? "base+" : "base-") : (op.lado === "venta" ? "cubre+" : "cubre-");
        const clave = op.t + tipo;
        const x = grupos.get(clave) ?? { t: aLocal(op.t), tipo, nocional: 0, n: 0 };
        x.nocional += op.nocional;
        x.n += 1;
        grupos.set(clave, x);
      }
    }
    const ESTILO: Record<string, { position: SeriesMarkerBarPosition; shape: SeriesMarkerShape; color: string; texto: string }> = {
      "base+": { position: "belowBar", shape: "arrowUp", color: c.subeMarca, texto: "Compra" },
      "base-": { position: "aboveBar", shape: "arrowDown", color: c.bajaMarca, texto: "Vende" },
      "cubre+": { position: "aboveBar", shape: "circle", color: c.serie1, texto: "Cubre" },
      "cubre-": { position: "belowBar", shape: "circle", color: c.serie2, texto: "Descubre" },
    };
    const lista: SeriesMarkerBar<Time>[] = [...grupos.values()].sort((a, b) => a.t - b.t).map((x) => {
      const e = ESTILO[x.tipo];
      return { time: x.t, position: e.position, shape: e.shape, color: e.color, text: `${e.texto} ${cifra(x.nocional, 0)} $`, size: 1 };
    });
    se.marcas?.setMarkers(lista);
    if (valido(g.precio)) {
      if (se.ahora) se.ahora.applyOptions({ price: g.precio });
      else se.ahora = se.velas.createPriceLine({ price: g.precio, color: c.acento, lineWidth: 1, lineStyle: LineStyle.Dotted,
                                                 axisLabelVisible: true, title: "ahora" });
    }
    if (ultimoSimbolo.current !== g.simbolo) {
      ultimoSimbolo.current = g.simbolo;
      const n = barras.length;
      ch.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - 132), to: n + 3 });
    }
  }, [g, barras, reloj, canal, marcas, tema, hay]);

  if (!g) return <div style={{ height: alto }} className="grid place-items-center text-sm text-texto-3">Cargando velas…</div>;
  if (!hay) return <Vacio>Todavía no hay velas de esta moneda.</Vacio>;

  const i = cursor ?? barras[barras.length - 1].i;
  const b = barras.find((x) => x.i === i) ?? barras[barras.length - 1];
  const cambio = (b.c / b.o - 1) * 100;
  const m = g.medias[reloj];
  const k = g.canales[canal];
  const [rap, len] = reloj.split("/");
  const punt = g.puntuacion[i];

  return (
    <div className="relative" style={{ height: alto }}>
      <div className="pointer-events-none absolute top-2 left-3 z-10 grid gap-1 text-[11px] sm:text-xs">
        <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5">
          <span className="font-semibold text-texto">{g.simbolo.replace(/USDT$/, "")}<span className="text-texto-3">/USDT · 4h</span></span>
          <span className="num text-texto-3">{textoMomento(b.tl)}</span>
          <span className="num hidden text-texto-3 sm:inline">Ap <span className="text-texto-2">{precio(b.o)}</span></span>
          <span className="num hidden text-texto-3 sm:inline">Máx <span className="text-texto-2">{precio(b.h)}</span></span>
          <span className="num hidden text-texto-3 sm:inline">Mín <span className="text-texto-2">{precio(b.l)}</span></span>
          <span className="num text-texto-3">Cierre <span className={cx(cambio >= 0 ? "text-sube" : "text-baja")}>{precio(b.c)}</span></span>
          <span className={cx("num", cambio >= 0 ? "text-sube" : "text-baja")}>{cifra(cambio, 2, true)} %</span>
        </div>
        <div className="hidden flex-wrap items-baseline gap-x-3 gap-y-0.5 text-texto-3 sm:flex">
          <span className="flex items-baseline gap-1"><span className="inline-block h-0.5 w-3 translate-y-[-3px] rounded bg-serie-2" />media {rap} d <span className="num text-texto-2">{precio(m?.rapida[i])}</span></span>
          <span className="flex items-baseline gap-1"><span className="inline-block h-0.5 w-3 translate-y-[-3px] rounded bg-serie-4" />media {len} d <span className="num text-texto-2">{precio(m?.lenta[i])}</span></span>
          <span>canal {canal} d <span className="num text-texto-2">{precio(k?.alto[i])} / {precio(k?.bajo[i])}</span></span>
          <span>tendencia <span className={cx("num", (punt ?? 0) > 0 ? "text-serie-1" : (punt ?? 0) < 0 ? "text-baja" : "text-texto-2")}>{cifra(punt, 2, true)}</span></span>
        </div>
      </div>
      <div ref={caja} className="absolute inset-0" />
    </div>
  );
}
