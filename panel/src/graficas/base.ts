// Ajustes comunes de las gráficas (TradingView Lightweight Charts) con los colores del tema.
import {
  ColorType, CrosshairMode, LineStyle, type ChartOptions, type DeepPartial, type Time, type UTCTimestamp,
} from "lightweight-charts";
import { dia, diaSemanaCorto, hora, mesCorto } from "../lib/formato";
import type { Colores } from "../lib/tema";

const FUENTE = '"JetBrains Mono Variable", ui-monospace, SFMono-Regular, Menlo, monospace';

/** Un instante «local» de la gráfica (segundos) vuelto a Date para escribirlo. */
const aFecha = (t: Time): Date => {
  if (typeof t === "string") { const [a, m, d] = t.split("-").map(Number); return new Date(a, m - 1, d); }
  if (typeof t === "object") return new Date(t.year, t.month - 1, t.day);
  const f = new Date((t as UTCTimestamp) * 1000);
  return new Date(f.getUTCFullYear(), f.getUTCMonth(), f.getUTCDate(), f.getUTCHours(), f.getUTCMinutes());
};

export const textoMomento = (t: Time, conHora = true) =>
  conHora ? `${diaSemanaCorto(aFecha(t))}, ${hora(aFecha(t))}` : diaSemanaCorto(aFecha(t));

export function opcionesBase(c: Colores, { interaccion = false } = {}): DeepPartial<ChartOptions> {
  return {
    autoSize: true,
    layout: {
      background: { type: ColorType.Solid, color: "transparent" },
      textColor: c.texto3,
      fontFamily: FUENTE,
      fontSize: 11,
      // El logotipo de la librería se pinta con una hoja de estilos en línea, que la política de
      // contenido del panel bloquea; la atribución (aviso y enlace) va en el pie de la página.
      attributionLogo: false,
      panes: { separatorColor: c.borde, separatorHoverColor: c.borde, enableResize: false },
    },
    grid: { vertLines: { color: c.rejilla }, horzLines: { color: c.rejilla } },
    crosshair: {
      mode: CrosshairMode.Normal,
      vertLine: { color: c.texto3, width: 1, style: LineStyle.Dashed, labelBackgroundColor: c.borde },
      horzLine: { color: c.texto3, width: 1, style: LineStyle.Dashed, labelBackgroundColor: c.borde },
    },
    rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.14, bottom: 0.08 } },
    timeScale: {
      borderVisible: false, timeVisible: true, secondsVisible: false, rightOffset: 3, lockVisibleTimeRangeOnResize: true,
      tickMarkFormatter: (t: Time, tipo: number) => {
        const f = aFecha(t);
        // 0 año, 1 mes, 2 día, 3 hora, 4 hora con minutos
        if (tipo <= 1) return mesCorto(f);
        if (tipo === 2) return dia(f);
        return hora(f);
      },
    },
    // Cada serie lleva su formato de precio; aquí solo el idioma y la hora de la mira.
    localization: {
      locale: "es-ES",
      timeFormatter: (t: Time) => textoMomento(t, typeof t === "number"),
    },
    handleScroll: interaccion ? { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false } : false,
    handleScale: interaccion ? { axisPressedMouseMove: true, mouseWheel: true, pinch: true } : false,
  };
}
