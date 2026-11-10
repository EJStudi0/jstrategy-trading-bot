// Piezas de lectura rápida: medidor de tendencia, relojes, barra de partes y minigráfica.
import { useId } from "react";
import { cifra, pctFraccion, valido } from "../lib/formato";
import type { Relojes as TRelojes } from "../tipos";
import { cx } from "./ui";

export const etiquetaTendencia = (p: number | null | undefined) =>
  !valido(p) ? "Sin lectura" : p > 0.33 ? "Alcista" : p < -0.33 ? "Bajista" : "Sin tendencia";

/** De −1 a +1 desde el centro: azul a favor, rojo en contra. */
export function Medidor({ valor, ancho = "w-full" }: { valor: number | null | undefined; ancho?: string }) {
  const v = valido(valor) ? Math.max(-1, Math.min(1, valor)) : null;
  return (
    <div className={cx("flex items-center gap-2", ancho)}>
      <div className="relative h-1.5 flex-1 rounded-full bg-panel-3">
        <div className="absolute inset-y-[-3px] left-1/2 w-px bg-borde-2" />
        {v !== null && (
          <div
            className={cx("absolute inset-y-0 rounded-full", v >= 0 ? "left-1/2 bg-serie-1" : "right-1/2 bg-baja-marca")}
            style={{ width: `${Math.abs(v) * 50}%` }}
          />
        )}
      </div>
      <span className="num w-11 text-right text-xs font-semibold">{v === null ? "—" : cifra(v, 2, true)}</span>
    </div>
  );
}

const NOMBRES_CRUCES = ["2/8", "4/16", "5/20", "8/32", "10/40", "16/64"];
const NOMBRES_CANALES = ["5", "10", "20", "40"];

/** Los diez relojes: seis cruces de medias y cuatro canales. Lleno a favor, rojo en contra, hueco sin señal. */
export function Relojes({ relojes, detalle = false }: { relojes: TRelojes | null | undefined; detalle?: boolean }) {
  if (!relojes) return <span className="text-xs text-texto-3">—</span>;
  const favor = [...relojes.cruces, ...relojes.rupturas].filter((v) => v > 0).length;
  const total = relojes.cruces.length + relojes.rupturas.length;
  const punto = (v: number) => cx("inline-block size-2 rounded-full border",
    v > 0 ? "border-serie-1 bg-serie-1" : v < 0 ? "border-baja-marca bg-baja-marca" : "border-borde-2 bg-transparent");
  if (!detalle) {
    return (
      <div className="flex items-center gap-2" role="img" aria-label={`${favor} de ${total} relojes a favor`}>
        <span className="flex gap-[3px]">{relojes.cruces.map((v, i) => <span key={i} className={punto(v)} />)}</span>
        <span className="flex gap-[3px]">{relojes.rupturas.map((v, i) => <span key={i} className={punto(v)} />)}</span>
      </div>
    );
  }
  const fila = (nombre: string, v: number) => (
    <li key={nombre} className="flex items-center justify-between gap-2 rounded-md bg-panel-2 px-2 py-1">
      <span className="num text-[11px] text-texto-2">{nombre}</span>
      <span className={cx("text-[11px] font-semibold", v > 0 ? "text-serie-1" : v < 0 ? "text-baja" : "text-texto-3")}>
        {v > 0 ? "a favor" : v < 0 ? "en contra" : "sin señal"}
      </span>
    </li>
  );
  return (
    <div className="grid gap-3">
      <div>
        <p className="rotulo mb-1.5">Cruces de medias (días)</p>
        <ul className="grid grid-cols-2 gap-1">{relojes.cruces.map((v, i) => fila(NOMBRES_CRUCES[i] ?? String(i), v))}</ul>
      </div>
      <div>
        <p className="rotulo mb-1.5">Rupturas de canal (días)</p>
        <ul className="grid grid-cols-2 gap-1">{relojes.rupturas.map((v, i) => fila(NOMBRES_CANALES[i] ?? String(i), v))}</ul>
      </div>
    </div>
  );
}

/** Un todo partido en partes: cada parte con su cuota escrita dentro si cabe. */
export function BarraPartes({ partes, alto = "h-7" }: { partes: { nombre: string; valor: number; color: string }[]; alto?: string }) {
  const total = partes.reduce((s, p) => s + Math.max(0, p.valor), 0);
  if (!(total > 0)) return null;
  return (
    <div className={cx("flex gap-0.5 overflow-hidden rounded-md", alto)} role="img"
         aria-label={partes.map((p) => `${p.nombre} ${pctFraccion(p.valor / total)}`).join(", ")}>
      {partes.filter((p) => p.valor > 0).map((p) => (
        <div key={p.nombre} title={`${p.nombre}: ${pctFraccion(p.valor / total)}`}
             className="flex min-w-1 items-center overflow-hidden rounded-[4px] px-2" style={{ flexGrow: p.valor / total, background: p.color }}>
          {p.valor / total > 0.12 && <span className="num text-[11px] font-semibold text-white">{pctFraccion(p.valor / total)}</span>}
        </div>
      ))}
    </div>
  );
}

/** Cuánto de la base está cubierto (azul) y cuánto expuesto (naranja). */
export function BarraCobertura({ cubierta }: { cubierta: number }) {
  const c = Math.max(0, Math.min(1, cubierta));
  return (
    <div className="flex h-1.5 gap-0.5 overflow-hidden rounded-full bg-panel-3" role="img"
         aria-label={`${pctFraccion(c)} cubierta, ${pctFraccion(1 - c)} expuesta`}>
      {c > 0.001 && <span className="rounded-full bg-serie-1" style={{ flexGrow: c }} />}
      {c < 0.999 && <span className="rounded-full bg-serie-2" style={{ flexGrow: 1 - c }} />}
    </div>
  );
}

/** Barras pequeñas con signo (ganancia de cada día): verde arriba, rojo abajo. */
export function MiniBarras({ valores, alto = 30 }: { valores: (number | null)[]; alto?: number }) {
  const vs = valores.map((v) => (valido(v) ? v : 0));
  if (!vs.length) return <div style={{ height: alto }} />;
  const tope = Math.max(1e-9, ...vs.map(Math.abs));
  const ancho = 100 / vs.length;
  const medio = alto / 2;
  return (
    <svg viewBox={`0 0 100 ${alto}`} preserveAspectRatio="none" className="block w-full" style={{ height: alto }} aria-hidden="true">
      <line x1="0" x2="100" y1={medio} y2={medio} stroke="var(--c-borde-2)" strokeWidth="1" vectorEffect="non-scaling-stroke" />
      {vs.map((v, i) => {
        const h = Math.max(0.5, (Math.abs(v) / tope) * (medio - 1));
        return <rect key={i} x={i * ancho + ancho * 0.15} width={ancho * 0.7} y={v >= 0 ? medio - h : medio} height={h} rx="0.6"
                     fill={v >= 0 ? "var(--c-sube-marca)" : "var(--c-baja-marca)"} opacity={i === vs.length - 1 ? 0.55 : 0.9} />;
      })}
    </svg>
  );
}

/** Minigráfica de la última semana, con un degradado debajo y el último punto marcado. */
export function MiniLinea({ valores, ancho = 96, alto = 30, signo = "", fluida = false }: {
  valores: number[]; ancho?: number; alto?: number; signo?: string; fluida?: boolean;
}) {
  const id = useId().replace(/:/g, "");
  const vs = valores.filter(valido);
  if (vs.length < 2) return <svg width={ancho} height={alto} aria-hidden="true" />;
  const lo = Math.min(...vs), hi = Math.max(...vs);
  const X = (i: number) => 1 + (i / (vs.length - 1)) * (ancho - 6);
  const Y = (v: number) => 3 + ((hi - v) / Math.max(1e-12, hi - lo)) * (alto - 6);
  const d = vs.map((v, i) => `${i ? "L" : "M"}${X(i).toFixed(1)} ${Y(v).toFixed(1)}`).join(" ");
  const color = signo === "sube" ? "var(--c-sube-marca)" : signo === "baja" ? "var(--c-baja-marca)" : "var(--c-texto-3)";
  // Fluida: ocupa el ancho de su caja (el trazo no se deforma; el punto final sobra).
  return (
    <svg width={fluida ? "100%" : ancho} height={alto} viewBox={`0 0 ${ancho} ${alto}`} aria-hidden="true"
         preserveAspectRatio={fluida ? "none" : undefined} className={fluida ? "block" : "overflow-visible"}>
      <defs>
        <linearGradient id={`g${id}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={color} stopOpacity="0.28" />
          <stop offset="1" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={`${d} L${X(vs.length - 1).toFixed(1)} ${alto} L${X(0).toFixed(1)} ${alto} Z`} fill={`url(#g${id})`} />
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
      {!fluida && <circle cx={X(vs.length - 1)} cy={Y(vs[vs.length - 1])} r="2.5" fill={color} />}
    </svg>
  );
}
