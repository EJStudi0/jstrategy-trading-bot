// Cifras y fechas en español, en la hora del aparato que mira.

export const MENOS = "−";
const NBSP = " ";
const ES = "es-ES";

const formatos = new Map<number, Intl.NumberFormat>();
function numero(decimales: number) {
  let f = formatos.get(decimales);
  if (!f) {
    f = new Intl.NumberFormat(ES, { minimumFractionDigits: decimales, maximumFractionDigits: decimales, useGrouping: "always" });
    formatos.set(decimales, f);
  }
  return f;
}

export const valido = (x: unknown): x is number => typeof x === "number" && Number.isFinite(x);

/** 1.234,56 con el signo menos tipográfico; `signo` pone "+" a los positivos. */
export function cifra(x: number | null | undefined, decimales = 2, signo = false): string {
  if (!valido(x)) return "—";
  const redondo = Number(x.toFixed(decimales));
  const texto = numero(decimales).format(Math.abs(redondo));
  if (redondo < 0) return MENOS + texto;
  if (signo && redondo > 0) return "+" + texto;
  return texto;
}

/** Dólares (USDT ≈ dólar): "4.963,04 $", "+0,31 $". */
export function dinero(x: number | null | undefined, opciones: { signo?: boolean; decimales?: number } = {}): string {
  if (!valido(x)) return "—";
  return cifra(x, opciones.decimales ?? 2, opciones.signo ?? false) + NBSP + "$";
}

/** Fracción a porcentaje: 0,123 → "12,3 %". */
export function pctFraccion(x: number | null | undefined, decimales = 0, signo = false): string {
  if (!valido(x)) return "—";
  return cifra(x * 100, decimales, signo) + NBSP + "%";
}

/** Porcentaje que ya viene en puntos: 8,2 → "8,2 %". */
export function pct(x: number | null | undefined, decimales = 1, signo = false): string {
  if (!valido(x)) return "—";
  return cifra(x, decimales, signo) + NBSP + "%";
}

/** Precio con los decimales que pide su tamaño (74.016 · 86,02 · 0,1776). */
export function precio(x: number | null | undefined): string {
  if (!valido(x)) return "—";
  const a = Math.abs(x);
  return cifra(x, a >= 1000 ? 0 : a >= 10 ? 2 : a >= 1 ? 3 : 4);
}

export function decimalesDePrecio(x: number): number {
  const a = Math.abs(x);
  return a >= 10000 ? 0 : a >= 1000 ? 1 : a >= 10 ? 2 : a >= 1 ? 3 : 5;
}

export type Signo = "sube" | "baja" | "";

export function signoDe(x: number | null | undefined, umbral = 0.005): Signo {
  if (!valido(x)) return "";
  return x > umbral ? "sube" : x < -umbral ? "baja" : "";
}

// ── fechas ───────────────────────────────────────────────────────────────────

const fDia = new Intl.DateTimeFormat(ES, { day: "numeric", month: "short" });
const fDiaSemana = new Intl.DateTimeFormat(ES, { weekday: "long", day: "numeric", month: "long" });
const fDiaSemanaCorto = new Intl.DateTimeFormat(ES, { weekday: "short", day: "numeric", month: "short" });
const fHora = new Intl.DateTimeFormat(ES, { hour: "2-digit", minute: "2-digit" });
const fHoraSeg = new Intl.DateTimeFormat(ES, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fMomento = new Intl.DateTimeFormat(ES, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const fMes = new Intl.DateTimeFormat(ES, { month: "long", year: "numeric" });
const fMesCorto = new Intl.DateTimeFormat(ES, { month: "short" });
const fMesAnio = new Intl.DateTimeFormat(ES, { month: "short", year: "2-digit" });

const sinPunto = (s: string) => s.replace(/\./g, "");
type Fecha = Date | number | string;
const d = (t: Fecha) => (t instanceof Date ? t : new Date(t));

export const dia = (t: Fecha) => sinPunto(fDia.format(d(t)));
export const diaSemana = (t: Fecha) => fDiaSemana.format(d(t));
export const diaSemanaCorto = (t: Fecha) => sinPunto(fDiaSemanaCorto.format(d(t)));
export const hora = (t: Fecha) => fHora.format(d(t));
export const horaSegundos = (t: Fecha) => fHoraSeg.format(d(t));
export const momento = (t: Fecha) => sinPunto(fMomento.format(d(t)));
export const mesLargo = (t: Fecha) => fMes.format(d(t)).replace(" de ", " ");
export const mesCorto = (t: Fecha) => sinPunto(fMesCorto.format(d(t)));
export const mesAnio = (t: Fecha) => sinPunto(fMesAnio.format(d(t))).replace(" de ", " ");
export const mayuscula = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

/** "2026-11-10" → Date a medianoche LOCAL de ese día. */
export function fechaLocal(iso: string): Date {
  const [a, m, dd] = iso.split("-").map(Number);
  return new Date(a, (m || 1) - 1, dd || 1);
}

export function claveDia(f: Date): string {
  return `${f.getFullYear()}-${String(f.getMonth() + 1).padStart(2, "0")}-${String(f.getDate()).padStart(2, "0")}`;
}

/** "hoy, 16:05", "ayer, 08:10" o "10 nov, 16:05". */
export function cuando(t: Fecha, ahora = new Date()): string {
  const f = d(t);
  const ayer = new Date(ahora);
  ayer.setDate(ahora.getDate() - 1);
  if (f.toDateString() === ahora.toDateString()) return "hoy, " + hora(f);
  if (f.toDateString() === ayer.toDateString()) return "ayer, " + hora(f);
  return momento(f);
}

/** "3 h 12 min", "45 min", "20 s", "3 días". */
export function duracion(ms: number | null | undefined): string {
  if (!valido(ms)) return "—";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + NBSP + "s";
  const min = Math.round(s / 60);
  if (min < 60) return min + NBSP + "min";
  const h = Math.floor(min / 60);
  const resto = min % 60;
  if (h < 48) return h + NBSP + "h" + (resto ? " " + resto + NBSP + "min" : "");
  return Math.round(h / 24) + NBSP + "días";
}

/** Cuenta atrás de reloj: "02:41:07". */
export function cuentaAtras(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

export const haceCuanto = (ms: number) => (ms < 5000 ? "ahora mismo" : "hace " + duracion(ms));
