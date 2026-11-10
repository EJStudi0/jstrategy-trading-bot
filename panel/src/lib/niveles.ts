// Lo medido en la prueba, pasado a dólares con el patrimonio de hoy.

/** Ganancia media al día (compuesta) de un `pct` repartido en `dias` días. */
export function alDia(pct: number, patrimonio: number, dias = 365): number {
  return patrimonio * (Math.pow(1 + pct / 100, 1 / dias) - 1);
}

/** Días que cubre un año medido: entero, salvo el último, que acaba en `hasta` (exclusivo). */
export function diasDelAnio(anio: string, hasta: string): number {
  const [a, m, d] = hasta.split("-").map(Number);
  const fin = anio === hasta.slice(0, 4) ? new Date(a, m - 1, d) : new Date(Number(anio) + 1, 0, 1);
  return Math.round((fin.getTime() - new Date(Number(anio), 0, 1).getTime()) / 864e5);
}

/** Años que tarda en doblarse el dinero a un `pct` anual compuesto. */
export const aniosParaDoblar = (pct: number) => Math.log(2) / Math.log(1 + pct / 100);
