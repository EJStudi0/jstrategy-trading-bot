// Cuentas y frases del asistente: todo funciones puras, para poder probarlas.
import { hora, dia, valido } from "./formato";
import type { Alerta, ModoVeto } from "../tipos";

/** Cuánto se mueve una moneda frente a lo suyo normal (1 = normal). */
export function etiquetaMovimiento(x: number | null | undefined): "tranquilo" | "normal" | "movido" | "—" {
  if (!valido(x)) return "—";
  return x < 0.8 ? "tranquilo" : x >= 1.3 ? "movido" : "normal";
}

export const etiquetaFondo = (f: number | null | undefined) => (f === 1 ? "alcista" : f === -1 ? "bajista" : "sin definir");
export const etiquetaLado = (l: number) => (l === 1 ? "al alza" : l === -1 ? "a la baja" : "sin dirección");

/** Lo que se pierde si salta el stop: en USDT y como % de la cuenta. null si no se puede calcular
 *  (falta algún dato o el stop está del lado equivocado del precio). No cuenta comisiones. */
export function riesgoDeStop(lado: 1 | -1, precio: number | null | undefined, stop: number | null | undefined,
                             usdt: number | null | undefined, patrimonio: number | null | undefined): { usdt: number; pct: number | null } | null {
  if (!valido(precio) || !valido(stop) || !valido(usdt) || precio <= 0 || stop <= 0 || usdt <= 0) return null;
  const distancia = (lado * (precio - stop)) / precio;
  if (!(distancia > 0)) return null;
  const perdida = usdt * distancia;
  return { usdt: perdida, pct: valido(patrimonio) && patrimonio > 0 ? (100 * perdida) / patrimonio : null };
}

/** Lee un número escrito a mano: admite coma o punto decimal. Vacío → null; si no es un número → NaN. */
export function leerNumero(texto: string): number | null {
  const t = texto.trim().replace(/\s/g, "");
  if (!t) return null;
  // "1.234,5" (miles con punto y coma decimal) o "1234.5" / "1234,5".
  const limpio = t.includes(",") ? t.replace(/\./g, "").replace(",", ".") : t;
  return /^\d*\.?\d+$/.test(limpio) ? Number(limpio) : NaN;
}

/** Un precio para rellenar una casilla: con coma y los decimales que pide su tamaño, sin puntos de miles. */
export function precioParaCasilla(x: number | null | undefined): string {
  if (!valido(x)) return "";
  const a = Math.abs(x);
  const decimales = a >= 1000 ? 1 : a >= 10 ? 2 : a >= 1 ? 3 : 5;
  return String(Number(x.toFixed(decimales))).replace(".", ",");
}

/** Avisos que merecen mirarse: fuerza alta o media. */
export const importante = (a: Pick<Alerta, "fuerza">) => a.fuerza !== "baja";

/** El stop sugerido solo vale si queda al otro lado del precio para el lado elegido. */
export function stopPara(a: Pick<Alerta, "precio" | "stop">, lado: 1 | -1): number | null {
  return valido(a.stop) && lado * (a.precio - a.stop) > 0 ? a.stop : null;
}

/** "a las 16:05", "mañana a las 02:10" o "el 14 nov a las 09:00". */
export function hastaCuando(ms: number, ahora = Date.now()): string {
  const f = new Date(ms);
  const hoy = new Date(ahora);
  const manana = new Date(ahora);
  manana.setDate(hoy.getDate() + 1);
  if (f.toDateString() === hoy.toDateString()) return "a las " + hora(f);
  if (f.toDateString() === manana.toDateString()) return "mañana a las " + hora(f);
  return "el " + dia(f) + " a las " + hora(f);
}

export const DURACIONES = [
  { valor: "0", etiqueta: "Sin caducidad" },
  { valor: "4", etiqueta: "4 h" },
  { valor: "12", etiqueta: "12 h" },
  { valor: "24", etiqueta: "24 h" },
] as const;
export type Duracion = (typeof DURACIONES)[number]["valor"];

export const VETOS: Record<ModoVeto, { nombre: string; texto: string }> = {
  congelar: { nombre: "No tocar", texto: "el bot la deja como esté: ni compra ni vende esa moneda." },
  cubrir: { nombre: "Sin apuesta", texto: "conserva la moneda pero la cubre entera: su precio deja de mover tu patrimonio." },
  cerrar: { nombre: "Fuera", texto: "vende esa moneda y cierra su cobertura; no vuelve a entrar mientras dure." },
};

export const MOTIVOS_CIERRE: Record<string, string> = {
  manual: "Cerrada a mano", stop: "Saltó el stop", objetivo: "Llegó al objetivo", liquidada: "Liquidada",
};
