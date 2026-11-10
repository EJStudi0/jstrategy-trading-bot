// Formato de cifras y fechas del panel. Todo en español y en la hora del aparato que mira.

export const MENOS = "−";
const ES = "es-ES";

const conDecimales = new Map();
function numero(decimales) {
  if (!conDecimales.has(decimales)) {
    conDecimales.set(decimales, new Intl.NumberFormat(ES, {
      minimumFractionDigits: decimales, maximumFractionDigits: decimales, useGrouping: "always",
    }));
  }
  return conDecimales.get(decimales);
}

export function valido(x) {
  return typeof x === "number" && Number.isFinite(x);
}

/** 1.234,56 — con el signo menos tipográfico. `signo` añade "+" a los positivos. */
export function cifra(x, decimales = 2, signo = false) {
  if (!valido(x)) return "—";
  const redondo = Number(x.toFixed(decimales));
  const texto = numero(decimales).format(Math.abs(redondo));
  if (redondo < 0) return MENOS + texto;
  if (signo && redondo > 0) return "+" + texto;
  return texto;
}

/** Dinero en dólares (USDT ≈ dólar): "4.963,04 $", "+0,31 $". */
export function dinero(x, { signo = false, decimales = 2 } = {}) {
  if (!valido(x)) return "—";
  return cifra(x, decimales, signo) + " $";
}

/** Dinero corto para ejes: "+2 $", "1,5 $", "12 k$". */
export function dineroEje(x) {
  const a = Math.abs(x);
  if (a >= 10000) return cifra(x / 1000, 0, false) + " k$";
  if (a >= 100 || Number.isInteger(x)) return cifra(x, 0) + " $";
  if (a >= 10) return cifra(x, 1) + " $";
  return cifra(x, 2) + " $";
}

/** Porcentaje a partir de una fracción (0,123 → "12,3 %"). */
export function pctFraccion(x, decimales = 0, signo = false) {
  if (!valido(x)) return "—";
  return cifra(x * 100, decimales, signo) + " %";
}

/** Porcentaje que ya viene en puntos (8,2 → "8,2 %"). */
export function pct(x, decimales = 1, signo = false) {
  if (!valido(x)) return "—";
  return cifra(x, decimales, signo) + " %";
}

export function signoDe(x, umbral = 0.005) {
  return !valido(x) ? "" : x > umbral ? "sube" : x < -umbral ? "baja" : "";
}

// ── fechas ───────────────────────────────────────────────────────────────────

const fDia = new Intl.DateTimeFormat(ES, { day: "numeric", month: "short" });
const fDiaSemana = new Intl.DateTimeFormat(ES, { weekday: "long", day: "numeric", month: "long" });
const fDiaSemanaCorto = new Intl.DateTimeFormat(ES, { weekday: "short", day: "numeric", month: "short" });
const fHora = new Intl.DateTimeFormat(ES, { hour: "2-digit", minute: "2-digit" });
const fMomento = new Intl.DateTimeFormat(ES, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
const fMes = new Intl.DateTimeFormat(ES, { month: "long", year: "numeric" });
const fMesCorto = new Intl.DateTimeFormat(ES, { month: "short" });
const fMesAnio = new Intl.DateTimeFormat(ES, { month: "short", year: "2-digit" });

const limpia = (s) => s.replace(/\.$/, "").replace(" de ", " ");

export const dia = (t) => limpia(fDia.format(t));
export const diaSemana = (t) => fDiaSemana.format(t);
export const diaSemanaCorto = (t) => fDiaSemanaCorto.format(t).replace(/\./g, "");
export const hora = (t) => fHora.format(t);
export const momento = (t) => fMomento.format(t).replace(/\./g, "");
export const mesLargo = (t) => fMes.format(t).replace(" de ", " ");
export const mesCorto = (t) => fMesCorto.format(t).replace(/\.$/, "");
export const mesAnio = (t) => fMesAnio.format(t).replace(/\./g, "").replace(" de ", " ");

/** "2026-11-10" → Date a medianoche LOCAL de ese día (no UTC). */
export function fechaLocal(iso) {
  const [a, m, d] = iso.split("-").map(Number);
  return new Date(a, m - 1, d || 1);
}

export function claveDia(fecha) {
  const m = String(fecha.getMonth() + 1).padStart(2, "0");
  const d = String(fecha.getDate()).padStart(2, "0");
  return `${fecha.getFullYear()}-${m}-${d}`;
}

/** "hoy, 16:05", "ayer, 08:10" o "10 nov, 16:05". */
export function cuando(t) {
  const fecha = new Date(t);
  const hoy = new Date();
  const ayer = new Date(); ayer.setDate(hoy.getDate() - 1);
  if (fecha.toDateString() === hoy.toDateString()) return "hoy, " + hora(fecha);
  if (fecha.toDateString() === ayer.toDateString()) return "ayer, " + hora(fecha);
  return momento(fecha);
}

/** Duración legible: "3 h 12 min", "45 min", "20 s". */
export function duracion(ms) {
  if (!valido(ms)) return "—";
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return s + " s";
  const min = Math.round(s / 60);
  if (min < 60) return min + " min";
  const h = Math.floor(min / 60), resto = min % 60;
  if (h < 48) return h + " h" + (resto ? " " + resto + " min" : "");
  return Math.round(h / 24) + " días";
}

export function haceCuanto(ms) {
  return ms < 5000 ? "ahora mismo" : "hace " + duracion(ms);
}
