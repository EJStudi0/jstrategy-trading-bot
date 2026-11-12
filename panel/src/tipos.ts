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
  /** Cuándo caduca la pausa o el «cubrir todo» y el bot vuelve solo a automático (ms); null = no caduca. */
  mando_hasta_ms?: number | null;
  vetos?: Record<string, Veto>;
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

/** Centinela: el segundo bot (Bitcoin al contado), que corre en su propio proceso. */
export interface Centinela {
  instalado: boolean;
  encendido: boolean;
  en_marcha: boolean;
  modo: string;
  latido_utc?: string | null;
  proxima_decision_utc?: string | null;
  capital?: number | null;
  patrimonio?: number | null;
  ganancia?: number | null;
  ganancia_pct?: number | null;
  caida_pct?: number | null;
  precio?: number | null;
  peso?: number | null;
  objetivo?: number | null;
  btc?: number | null;
  efectivo?: number | null;
  regimen?: string;
  accion?: string;
  notas?: string[];
  explicacion?: string[];
  vela?: string | null;
  horas_retraso?: number | null;
  fuente?: string;
  cortafuegos_hasta_utc?: string | null;
  n_operaciones?: number;
  operaciones?: { utc: string; lado: string; cantidad: number; precio: number; comision: number; motivo: string }[];
  avisos?: { utc: string; nivel: string; texto: string }[];
}

// ── Asistente: avisos de patrones, cuenta de operar a mano y vetos por moneda ───────────────────

export type ModoVeto = "congelar" | "cubrir" | "cerrar";

export interface Veto {
  modo: ModoVeto;
  desde_utc: string;
  hasta_ms: number | null;
}

/** Qué pasó 24 h después las otras veces que salió el mismo patrón. */
export interface Previo {
  n: number;
  a_favor_pct: number | null;
  media_pct: number | null;
}

export interface Alerta {
  id: number;
  utc: string;
  t: number;
  simbolo: string;
  patron: string;
  lado: 1 | -1 | 0;
  precio: number;
  fuerza: "alta" | "media" | "baja";
  stop: number | null;
  atr_pct?: number | null;
  fondo?: 1 | -1 | 0;
  a_4h?: number | null;
  a_24h?: number | null;
  vista?: boolean;
  previo?: Previo | null;
  /** Silenciado por el dueño (su patrón o su moneda): se apunta, pero no cuenta como «sin ver». */
  callada?: boolean;
  /** Solo en los avisos de patrón «nivel»: el precio que pidió vigilar y su nota. */
  nivel?: number;
  nota?: string;
}

/** «Avísame si…»: un precio que el dueño pidió vigilar. */
export interface NivelPrecio {
  id: number;
  simbolo: string;
  precio: number;
  sentido: 1 | -1;
  nota: string;
  creado_utc: string;
}

export interface PrefsTelegram {
  activo: boolean;
  nivel: "todas" | "importantes" | "fuertes";
  operaciones: boolean;
  resumen: boolean;
}

export interface EstadoTelegram {
  configurado: boolean;
  bot: string | null;
  /** Nombre de la cuenta de Telegram enlazada, para que el dueño vea que es la suya. */
  nombre?: string | null;
  /** Solo mientras falta enlazar el chat: lo que el dueño le manda al bot. */
  codigo: string | null;
}

export interface PrefsAsistente {
  patrones_callados: string[];
  monedas_calladas: string[];
  telegram?: PrefsTelegram;
}

export interface PosicionManual {
  id: number;
  simbolo: string;
  lado: 1 | -1;
  cantidad: number;
  entrada: number;
  stop: number | null;
  objetivo: number | null;
  abierta_utc: string;
  nota: string;
  precio: number | null;
  usdt: number;
  no_realizado: number;
  pct: number | null;
  comisiones: number;
  financiacion: number;
}

export interface CerradaManual {
  id: number;
  simbolo: string;
  lado: 1 | -1;
  entrada: number;
  salida: number;
  usdt: number;
  abierta_utc: string;
  cerrada_utc: string;
  motivo: "manual" | "stop" | "objetivo" | "liquidada";
  neto: number;
  nota: string;
}

export interface CuentaManual {
  capital_inicial: number;
  patrimonio: number;
  ganancia: number;
  ganancia_pct: number;
  saldo: number;
  operaciones: number;
  acierto_pct: number | null;
  palanca_max: number;
  comision_pct: number;
  creada_utc: string | null;
  posiciones: PosicionManual[];
  cerradas: CerradaManual[];
}

export interface Asistente {
  utc: string;
  simulacion: boolean;
  alertas: Alerta[];
  sin_ver: number;
  catalogo: Record<string, { nombre: string; que: string; medido: string }>;
  previo: Record<string, Previo>;
  marcador: Record<string, Previo & { a_favor?: number; suma?: number }>;
  lectura: Record<string, { fondo: 1 | -1 | 0; movimiento: number | null }>;
  manual: CuentaManual;
  vetos: Record<string, Veto>;
  mando_hasta_ms: number | null;
  velas_al_dia: number;
  monedas: string[];
  niveles?: NivelPrecio[];
  prefs?: PrefsAsistente;
  telegram?: EstadoTelegram;
}

/** Lo que se manda para abrir una operación a mano. */
export interface OrdenManual {
  simbolo: string;
  lado: 1 | -1;
  usdt: number;
  stop?: number | null;
  objetivo?: number | null;
  nota?: string;
  alerta?: number | null;
}
