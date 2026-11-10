// Lo que se calcula a partir del estado para enseñarlo: nombres, frases en llano y repartos.
import type { Estado, Moneda, Nivel } from "../tipos";
import { pctFraccion } from "./formato";

export const NOMBRES: Record<string, string> = {
  BTC: "Bitcoin", ETH: "Ethereum", SOL: "Solana", BNB: "BNB", XRP: "XRP", DOGE: "Dogecoin",
  ADA: "Cardano", AVAX: "Avalanche", LINK: "Chainlink", LTC: "Litecoin",
};

export const base = (simbolo: string) => simbolo.replace(/USDT$/, "");
export const nombre = (simbolo: string) => NOMBRES[base(simbolo)] ?? base(simbolo);

export const nivelActual = (e: Estado | undefined): Nivel | null => (e?.nivel ? e.niveles[e.nivel] ?? null : null);

export const MANDOS = {
  auto: { nombre: "Automático", corto: "Auto", texto: "El bot decide: sigue la tendencia y cubre lo que haga falta.",
          confirma: "El bot vuelve a decidir solo: sigue la tendencia y cubre lo que haga falta. Puede operar ahora mismo." },
  pausa: { nombre: "Pausa", corto: "Pausa", texto: "No opera. Las posiciones se quedan como están.",
           confirma: "El bot deja de operar. Las posiciones se quedan exactamente como están." },
  neutral: { nombre: "Cubrir todo", corto: "Cubierto", texto: "Cubre el 100 % ahora, sin vender nada. El precio deja de mover tu patrimonio.",
             confirma: "Cubre ahora el 100 % de la base sin vender nada. Paga las comisiones de las coberturas que falten." },
  fuera: { nombre: "Salir a USDT", corto: "Fuera", texto: "Vende la base y cierra las coberturas. Pide confirmación.",
           confirma: "Vende TODA la base y cierra las coberturas ahora mismo. Para volver a operar, elige Automático." },
} as const;

export const MOTIVOS: Record<string, string> = {
  vela: "Decisión de la vela", mando_neutral: "Cubrir todo", mando_fuera: "Salir a USDT",
  mando_auto: "Vuelta a automático", reponer_garantia: "Reponer garantía",
};

export const expuesta = (m: Moneda) => (m.neto || 0) > 0.002;
export const cubiertaDe = (m: Moneda) => (m.base > 0 ? Math.min(1, Math.max(0, m.cobertura / m.base)) : 0);

/** Qué está haciendo el bot, en una frase. */
export function frase(e: Estado): string {
  if (e.mando === "pausa") return "En pausa: no opera y las posiciones se quedan como están.";
  if (e.mando === "fuera") return "Todo en USDT: sin monedas ni coberturas. Vuelve a Automático para operar.";
  if (e.mando === "neutral") return "Todo cubierto a mano: el precio no mueve tu patrimonio. Lo que gana sale de la financiación de las coberturas.";
  const ex = e.monedas.filter(expuesta);
  if (!ex.length) {
    return "Cubierto del todo: ninguna moneda tiene la tendencia a favor. El precio casi no mueve tu patrimonio y lo que gana sale de la financiación de las coberturas.";
  }
  const nombres = ex.map((m) => base(m.simbolo)).join(", ");
  return `Expuesto un ${pctFraccion(e.exposicion_neta)} al mercado en ${ex.length === 1 ? "una moneda" : ex.length + " monedas"} con la tendencia a favor (${nombres}). El resto está cubierto.`;
}

/** Cartera partida: base cubierta, base expuesta y USDT (con la garantía de los cortos). */
export function partesCartera(e: Estado) {
  const b = Math.max(0, e.exposicion_base || 0);
  const ex = Math.min(b, Math.max(0, e.exposicion_neta || 0));
  return [
    { nombre: "Base cubierta", valor: Math.max(0, b - ex), color: "var(--c-serie-1)" },
    { nombre: "Base expuesta", valor: ex, color: "var(--c-serie-2)" },
    { nombre: "USDT y garantía", valor: Math.max(0, 1 - b), color: "var(--c-serie-3)" },
  ];
}

/** BTC manda: una alt con tendencia a favor no sube exposición si Bitcoin no lo está. */
export function frenadaPorBtc(e: Estado, m: Moneda): boolean {
  const btc = e.monedas[0];
  return m.simbolo !== btc?.simbolo && (m.puntuacion ?? 0) > 0 && !((btc?.puntuacion ?? 0) > 0);
}
