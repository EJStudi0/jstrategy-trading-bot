// Piezas básicas de la interfaz: paneles, cifras, interruptores y controles segmentados.
import * as RSwitch from "@radix-ui/react-switch";
import * as RToggle from "@radix-ui/react-toggle-group";
import clsx, { type ClassValue } from "clsx";
import type { ReactNode } from "react";
import { extendTailwindMerge } from "tailwind-merge";
import { cifra, dinero, pct, pctFraccion, signoDe, type Signo } from "../lib/formato";

// Los colores propios (bg-panel-2, text-texto-3…) cuentan como colores para resolver choques.
const COLORES = ["fondo", "panel", "panel-2", "panel-3", "borde", "borde-2", "rejilla", "texto", "texto-2", "texto-3", "acento",
                 "acento-2", "sube", "baja", "sube-marca", "baja-marca", "aviso", "serie-1", "serie-2", "serie-3", "serie-4"];
const unir = extendTailwindMerge({ extend: { theme: { color: COLORES } } });
export const cx = (...clases: ClassValue[]) => unir(clsx(clases));

export function Panel({ titulo, icono, acciones, className, cuerpo = "p-4", children, id }: {
  titulo?: ReactNode; icono?: ReactNode; acciones?: ReactNode; className?: string; cuerpo?: string; children: ReactNode; id?: string;
}) {
  return (
    <section className={cx("panel flex min-w-0 flex-col", className)} aria-labelledby={id}>
      {(titulo || acciones) && (
        <header className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-borde px-4 py-2.5">
          <h2 id={id} className="flex items-center gap-2 text-[13px] font-semibold tracking-tight text-texto">
            {icono && <span className="text-texto-3 [&>svg]:size-4">{icono}</span>}
            {titulo}
          </h2>
          {acciones && <div className="flex flex-wrap items-center gap-2">{acciones}</div>}
        </header>
      )}
      <div className={cx("min-w-0 flex-1", cuerpo)}>{children}</div>
    </section>
  );
}

export const colorSigno = (s: Signo) => (s === "sube" ? "text-sube" : s === "baja" ? "text-baja" : "");

type TipoCifra = "dinero" | "pct" | "fraccion" | "num";

/** Una cifra monoespaciada; con `colorear`, verde si sube y rojo si baja. */
export function Cifra({ valor, tipo = "dinero", decimales, signo = false, colorear = false, className }: {
  valor: number | null | undefined; tipo?: TipoCifra; decimales?: number; signo?: boolean; colorear?: boolean; className?: string;
}) {
  const texto =
    tipo === "dinero" ? dinero(valor, { signo, decimales }) :
    tipo === "pct" ? pct(valor, decimales ?? 2, signo) :
    tipo === "fraccion" ? pctFraccion(valor, decimales ?? 1, signo) :
    cifra(valor, decimales ?? 2, signo);
  const s = colorear ? signoDe(valor, tipo === "fraccion" ? 0.00005 : 0.005) : "";
  return <span className={cx("num", colorSigno(s), className)}>{texto}</span>;
}

export function Stat({ rotulo, valor, sub, signo, icono, className, destacado, extra }: {
  rotulo: string; valor: ReactNode; sub?: ReactNode; signo?: Signo; icono?: ReactNode; className?: string; destacado?: boolean;
  extra?: ReactNode;
}) {
  return (
    <div className={cx("panel relative flex min-w-0 flex-col justify-between gap-2 overflow-hidden p-4", className)}>
      {destacado && <div className="pointer-events-none absolute -top-10 -right-10 size-32 rounded-full bg-acento/10 blur-2xl" />}
      <div className="flex items-center justify-between gap-2">
        <span className="rotulo">{rotulo}</span>
        {icono && <span className="text-texto-3 [&>svg]:size-4">{icono}</span>}
      </div>
      <div className={cx("num truncate text-[22px] font-semibold leading-none tracking-tight sm:text-2xl", colorSigno(signo ?? ""))}>
        {valor}
      </div>
      {sub !== undefined && <div className="min-h-4 text-xs leading-snug break-words text-texto-3">{sub}</div>}
      {extra && <div className="mt-auto pt-1">{extra}</div>}
    </div>
  );
}

export function Segmentado<T extends string>({ valor, opciones, alCambiar, etiqueta, pequeno }: {
  valor: T; opciones: { valor: T; etiqueta: ReactNode; titulo?: string }[]; alCambiar: (v: T) => void; etiqueta: string; pequeno?: boolean;
}) {
  return (
    <RToggle.Root
      type="single"
      value={valor}
      onValueChange={(v) => v && alCambiar(v as T)}
      aria-label={etiqueta}
      className="inline-flex shrink-0 rounded-lg border border-borde bg-panel-2 p-0.5"
    >
      {opciones.map((o) => (
        <RToggle.Item
          key={o.valor}
          value={o.valor}
          title={o.titulo}
          className={cx(
            "inline-flex items-center gap-1.5 rounded-md font-medium text-texto-3 transition-colors hover:text-texto",
            "data-[state=on]:bg-panel-3 data-[state=on]:text-texto data-[state=on]:shadow-[0_0_0_1px_var(--c-borde-2)]",
            pequeno ? "h-6 px-2 text-[11px]" : "h-7 px-2.5 text-xs",
          )}
        >
          {o.etiqueta}
        </RToggle.Item>
      ))}
    </RToggle.Root>
  );
}

export function Interruptor({ marcado, alCambiar, etiqueta }: { marcado: boolean; alCambiar: (v: boolean) => void; etiqueta: string }) {
  return (
    <label className="inline-flex cursor-pointer select-none items-center gap-2 text-xs text-texto-2">
      <RSwitch.Root
        checked={marcado}
        onCheckedChange={alCambiar}
        className="relative h-[18px] w-8 shrink-0 rounded-full border border-borde-2 bg-panel-3 transition-colors data-[state=checked]:border-acento data-[state=checked]:bg-acento"
      >
        <RSwitch.Thumb className="block size-3.5 translate-x-px rounded-full bg-white shadow transition-transform data-[state=checked]:translate-x-[14px]" />
      </RSwitch.Root>
      {etiqueta}
    </label>
  );
}

type Tono = "neutro" | "acento" | "sube" | "baja" | "aviso";
const TONOS: Record<Tono, string> = {
  neutro: "border-borde-2 bg-panel-2 text-texto-2",
  acento: "border-acento/30 bg-acento/10 text-acento claro:text-acento",
  sube: "border-sube-marca/30 bg-sube-marca/10 text-sube",
  baja: "border-baja-marca/30 bg-baja-marca/10 text-baja",
  aviso: "border-aviso/30 bg-aviso/10 text-aviso",
};

export function Chip({ tono = "neutro", children, className, titulo }: { tono?: Tono; children: ReactNode; className?: string; titulo?: string }) {
  return (
    <span title={titulo} className={cx("inline-flex h-6 items-center gap-1.5 whitespace-nowrap rounded-md border px-2 text-[11px] font-semibold", TONOS[tono], className)}>
      {children}
    </span>
  );
}

type Variante = "normal" | "primario" | "peligro" | "fantasma";
const VARIANTES: Record<Variante, string> = {
  normal: "border-borde-2 bg-panel-2 text-texto hover:bg-panel-3",
  primario: "border-acento bg-acento text-white hover:brightness-110",
  peligro: "border-baja-marca bg-baja-marca text-white hover:brightness-110",
  fantasma: "border-transparent bg-transparent text-texto-2 hover:bg-panel-2 hover:text-texto",
};

export function Boton({ variante = "normal", className, ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante }) {
  return (
    <button
      type="button"
      {...props}
      className={cx(
        "inline-flex h-9 items-center justify-center gap-2 rounded-lg border px-3.5 text-[13px] font-semibold transition active:scale-[0.98] disabled:opacity-50",
        VARIANTES[variante],
        className,
      )}
    />
  );
}

export function PuntoEstado({ estado }: { estado: "ok" | "viejo" | "ciego" | "arrancando" | "error" }) {
  const color = estado === "ok" ? "bg-sube-marca latido" : estado === "ciego" || estado === "error" ? "bg-baja-marca" : "bg-aviso";
  return <span className={cx("inline-block size-2 shrink-0 rounded-full", color)} aria-hidden="true" />;
}

export function Vacio({ children }: { children: ReactNode }) {
  return <p className="px-3 py-12 text-center text-sm text-texto-3">{children}</p>;
}
