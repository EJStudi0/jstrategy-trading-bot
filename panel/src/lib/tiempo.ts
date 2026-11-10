// Lightweight Charts pinta en UTC. Para que el eje y la mira digan la hora de quien mira, cada
// instante se corre por la diferencia de su zona (la forma que recomienda la propia librería).
import type { UTCTimestamp } from "lightweight-charts";

export function aLocal(ms: number): UTCTimestamp {
  const desfase = new Date(ms).getTimezoneOffset() * 60;
  return (Math.floor(ms / 1000) - desfase) as UTCTimestamp;
}

/** Lo contrario: de un instante «local» de la gráfica al instante real en ms. */
export function desdeLocal(t: number): number {
  const aprox = t * 1000;
  return aprox + new Date(aprox).getTimezoneOffset() * 60000;
}

export const ZONA = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
