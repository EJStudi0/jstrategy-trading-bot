// Lo que devuelve el bot. Espejo de ejecutor.instantanea, resumen.calcular y compañía.

export type Mando = "auto" | "pausa" | "neutral" | "fuera";
export type EstadoSalud = "ok" | "viejo" | "ciego" | "arrancando";

export interface Relojes {
  cruces: number[];
  rupturas: number[];
  rodaje: boolean;
}

export interface Moneda {
  simbolo: string;
  precio: number | null;
  puntuacion: number | null;
  vol: number | null;
  base: number;
  cobertura: number;
  perp: number;
  neto: number;
  base_objetivo: number | null;
  neto_objetivo: number | null;
  valor_base: number;
  valor_cobertura: number;
  relojes: Relojes | null;
  cantidad_base: number;
  cantidad_perp: number;
  entrada_perp: number | null;
  no_realizado_perp: number;
}

export interface Nivel {
  nombre: string;
  ajustes: Record<string, number>;
  anual_pct: number;
  caida_pct: number;
  meses_positivos_pct: number;
  por_anio: Record<string, number>;
}

export interface Ajustable {
  min: number;
  max: number;
  paso: number;
  formato: "pct" | "x";
  etiqueta: string;
}

export interface Aviso {
  utc: string;
  texto: string;
}

export interface Estado {
  utc: string;
  simulacion: boolean;
  mando: Mando;
  salud: { estado: EstadoSalud; edad_segundos: number | null; mercado: string | null; ultimo_error: string | null };
  patrimonio: number;
  capital_inicial: number;
  ganancia: number;
  ganancia_pct: number;
  usdt: number;
  valor_base: number;
  no_realizado: number;
  comisiones: number;
  financiacion: number;
  exposicion_neta: number;
  exposicion_base: number;
  colchon_margen: number | null;
  monedas: Moneda[];
  decision: { utc?: string; operaciones?: number; vol_prevista?: number; escala?: number };
  ajustes: Record<string, number>;
  ajustables: Record<string, Ajustable>;
  niveles: Record<string, Nivel>;
  niveles_periodo: { desde: string; hasta: string };
  nivel: string | null;
  avisos: Aviso[];
  creada_utc: string;
  intervalo: string;
  decision_vela_utc: string | null;
  proxima_decision_utc: string | null;
}

export interface Tramo {
  inicio: number;
  fin: number;
  ganancia: number;
  pct: number;
  financiacion: number | null;
  comisiones: number | null;
  mercado: number | null;
  desde_utc: string;
  hasta_utc: string;
}

export interface Dia extends Tramo {
  fecha: string;
}

export interface Grupo {
  clave: string;
  inicio: number;
  fin: number;
  ganancia: number;
  pct: number;
  financiacion: number | null;
  comisiones: number | null;
  mercado: number | null;
  dias: number;
  dias_positivos: number;
  dias_negativos: number;
  mejor: { fecha: string; ganancia: number };
  peor: { fecha: string; ganancia: number };
}

export interface Ganancias {
  zona: string;
  hoy_fecha: string;
  inicio_utc: string;
  dias: Dia[];
  meses: Grupo[];
  resumen: {
    hoy: Grupo | null;
    semana: Grupo | null;
    mes: Grupo | null;
    total: Tramo;
    dias_completos: number;
    media_dia: number | null;
    dias_positivos: number;
    dias_negativos: number;
    mejor_dia: Dia | null;
    peor_dia: Dia | null;
    racha: { dias: number; signo: number };
  };
}

export interface PuntoCurva {
  utc: string;
  patrimonio: number;
  neto: number;
  btc: number | null;
}

export interface Mercado {
  intervalo: string;
  monedas: { simbolo: string; precio: number | null; t: number[]; c: number[] }[];
}

export type Serie = (number | null)[];

export interface Grafica {
  simbolo: string;
  intervalo: string;
  t: number[];
  o: Serie;
  h: Serie;
  l: Serie;
  c: Serie;
  medias: Record<string, { rapida: Serie; lenta: Serie }>;
  canales: Record<string, { alto: Serie; bajo: Serie }>;
  puntuacion: number[];
  marcas: { t: number; pata: "contado" | "perp"; lado: "compra" | "venta"; nocional: number; motivo: string }[];
  precio: number | null;
}

/** Una fila del diario de operaciones (viene de un CSV: todo texto). */
export interface Operacion {
  utc: string;
  simbolo: string;
  pata: "contado" | "perp";
  lado: "compra" | "venta";
  cantidad: string;
  precio: string;
  nocional: string;
  comision: string;
  pnl_realizado: string;
  motivo: string;
  usdt: string;
  patrimonio: string;
}
