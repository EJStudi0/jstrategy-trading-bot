// Piezas que comparten las sub-pestañas del asistente. Todo lo que se toca mide al menos 40 px de alto.
import * as RSwitch from "@radix-ui/react-switch";
import { ArrowDownRight, ArrowUpRight, Check, Minus } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Boton, Chip, cx } from "../../componentes/ui";
import { etiquetaLado } from "../../lib/asistente";

/** Lo que hay escrito en el formulario de operar (texto tal cual; se convierte al enviar). */
export interface Borrador {
  simbolo: string;
  lado: 1 | -1;
  usdt: string;
  stop: string;
  objetivo: string;
  nota: string;
  /** El aviso del que viene, si viene de uno, y el stop que proponía. */
  alerta: number | null;
  sugerido: number | null;
}
export const BORRADOR_VACIO: Borrador = { simbolo: "", lado: 1, usdt: "", stop: "", objetivo: "", nota: "", alerta: null, sugerido: null };

export type PrecioDe = (simbolo: string) => number | null;

// 16 px en el móvil: con letra más pequeña el teléfono amplía la página al tocar la casilla.
export const CASILLA = "h-10 w-full min-w-0 rounded-lg border border-borde-2 bg-panel-2 px-3 text-base text-texto placeholder:text-texto-3 disabled:opacity-50 sm:text-[13px]";
export const mensaje = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function Campo({ rotulo, children, className }: { rotulo: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx("grid min-w-0 content-start gap-1 text-xs text-texto-2", className)}>
      {rotulo}
      {children}
    </label>
  );
}

/** El botón de siempre, con altura de dedo. */
export function BotonT({ className, ...props }: React.ComponentProps<typeof Boton>) {
  return <Boton {...props} className={cx("h-10 px-3", className)} />;
}

/** Para lo que no se deshace: el primer toque lo arma (cambia el texto y el color) y el segundo lo hace.
 *  Si no llega el segundo toque en unos segundos, se desarma solo. */
export function BotonDosToques({ children, confirma, alConfirmar, className, disabled, variante = "normal" }: {
  children: ReactNode; confirma: ReactNode; alConfirmar: () => void; className?: string; disabled?: boolean;
  variante?: React.ComponentProps<typeof Boton>["variante"];
}) {
  const [armado, setArmado] = useState(false);
  useEffect(() => {
    if (!armado) return;
    const t = setTimeout(() => setArmado(false), 5000);
    return () => clearTimeout(t);
  }, [armado]);
  return (
    <BotonT variante={armado ? "peligro" : variante} disabled={disabled} className={className} aria-live="polite"
      onClick={() => { if (armado) { setArmado(false); alConfirmar(); } else setArmado(true); }}>
      {armado ? confirma : children}
    </BotonT>
  );
}

interface Envio {
  isPending: boolean;
  isError: boolean;
  isSuccess: boolean;
  error: unknown;
  submittedAt: number;
}

/** Lo que pasó con lo último que se mandó, para ponerlo junto al control: «Enviando…», el error del
 *  servidor tal cual, o un «Hecho» que se va solo. */
export function Resultado({ m, ok = "Hecho", className }: { m: Envio; ok?: string; className?: string }) {
  const [hecho, setHecho] = useState(false);
  useEffect(() => {
    if (!m.isSuccess) return setHecho(false);
    setHecho(true);
    const t = setTimeout(() => setHecho(false), 2500);
    return () => clearTimeout(t);
  }, [m.isSuccess, m.submittedAt]);
  if (m.isPending) return <span role="status" className={cx("text-xs text-texto-3", className)}>Enviando…</span>;
  if (m.isError) return <span role="alert" className={cx("text-xs break-words text-baja", className)}>No se pudo: {mensaje(m.error)}</span>;
  if (hecho) return <span role="status" className={cx("inline-flex items-center gap-1 text-xs font-semibold text-sube", className)}><Check className="size-3.5" />{ok}</span>;
  return null;
}

/** Fila de botones que rellenan una casilla (importes, stops, objetivos). */
export function Atajos({ etiqueta, opciones, alElegir, className }: {
  etiqueta: string; opciones: { texto: string; valor: string; apagado?: boolean; titulo?: string }[]; alElegir: (valor: string) => void; className?: string;
}) {
  return (
    <div role="group" aria-label={etiqueta} className={cx("flex min-w-0 gap-1.5", className)}>
      {opciones.map((o) => (
        <button key={o.texto} type="button" disabled={o.apagado} title={o.titulo} onClick={() => alElegir(o.valor)}
          className="num h-10 min-w-0 flex-1 rounded-lg border border-borde-2 bg-panel-2/60 px-1 text-xs font-semibold whitespace-nowrap text-texto-2 transition hover:bg-panel-3 hover:text-texto active:scale-[0.97] disabled:opacity-40">
          {o.texto}
        </button>
      ))}
    </div>
  );
}

/** Elegir una entre pocas, con botones altos (pestañas y filtros). */
export function Opciones<T extends string>({ etiqueta, valor, opciones, alCambiar, className }: {
  etiqueta: string; valor: T; opciones: { valor: T; texto: ReactNode; contador?: number }[]; alCambiar: (v: T) => void; className?: string;
}) {
  return (
    <div role="tablist" aria-label={etiqueta} className={cx("flex gap-1 rounded-xl border border-borde bg-panel-2 p-1", className)}>
      {opciones.map((o) => (
        <button key={o.valor} type="button" role="tab" aria-selected={valor === o.valor} onClick={() => alCambiar(o.valor)}
          className={cx("inline-flex h-10 min-w-0 flex-1 items-center justify-center gap-1.5 rounded-lg px-1.5 text-[13px] font-semibold text-texto-3 transition-colors hover:text-texto",
            valor === o.valor && "bg-panel-3 text-texto shadow-[0_0_0_1px_var(--c-borde-2)]")}>
          <span className="truncate">{o.texto}</span>
          {!!o.contador && (
            <span className="num grid h-4 min-w-4 shrink-0 place-items-center rounded-full bg-acento px-1 text-[10px] leading-none text-white">{o.contador}</span>
          )}
        </button>
      ))}
    </div>
  );
}

/** Un interruptor con toda la fila como zona de toque. */
export function InterruptorFila({ marcado, alCambiar, children, disabled, className }: {
  marcado: boolean; alCambiar: (v: boolean) => void; children: ReactNode; disabled?: boolean; className?: string;
}) {
  return (
    <label className={cx("flex min-h-10 min-w-0 cursor-pointer select-none items-center gap-2.5 text-xs text-texto-2", className)}>
      <RSwitch.Root checked={marcado} onCheckedChange={alCambiar} disabled={disabled}
        className="relative h-6 w-10 shrink-0 rounded-full border border-borde-2 bg-panel-3 transition-colors disabled:opacity-50 data-[state=checked]:border-acento data-[state=checked]:bg-acento">
        <RSwitch.Thumb className="block size-4.5 translate-x-0.5 rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[18px]" />
      </RSwitch.Root>
      <span className="min-w-0">{children}</span>
    </label>
  );
}

export function ChipLado({ lado, texto }: { lado: number; texto?: string }) {
  const Icono = lado === 1 ? ArrowUpRight : lado === -1 ? ArrowDownRight : Minus;
  return <Chip tono={lado === 1 ? "sube" : lado === -1 ? "baja" : "neutro"}><Icono className="size-3" />{texto ?? etiquetaLado(lado)}</Chip>;
}

/** Los dos accesos a operar: verde el largo, rojo el corto. */
export function LargoCorto({ alElegir, destacado = 0, className }: { alElegir: (lado: 1 | -1) => void; destacado?: number; className?: string }) {
  return (
    <div className={cx("grid grid-cols-2 gap-2", className)}>
      <BotonT onClick={() => alElegir(1)} className={cx("border-sube-marca/40 text-sube", destacado === 1 && "bg-sube-marca/20")}>
        <ArrowUpRight className="size-4" />Largo
      </BotonT>
      <BotonT onClick={() => alElegir(-1)} className={cx("border-baja-marca/40 text-baja", destacado === -1 && "bg-baja-marca/20")}>
        <ArrowDownRight className="size-4" />Corto
      </BotonT>
    </div>
  );
}
