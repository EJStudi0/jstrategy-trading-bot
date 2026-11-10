import * as Slider from "@radix-ui/react-slider";
import { Check, LogOut, Monitor, Moon, Pause, Play, ShieldCheck, SlidersHorizontal, Sun, Tablet } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useConfirmar } from "../componentes/Dialogo";
import { Boton, Chip, Panel, Segmentado, colorSigno, cx } from "../componentes/ui";
import { useCambiarAjustes, usePonerMando } from "../hooks/datos";
import { MANDOS } from "../lib/derivados";
import { cifra, dinero, pct, pctFraccion, signoDe } from "../lib/formato";
import { alDia } from "../lib/niveles";
import type { Prefs } from "../lib/prefs";
import type { Estado, Mando as TMando } from "../tipos";

const ICONOS: Record<TMando, ReactNode> = { auto: <Play />, pausa: <Pause />, neutral: <ShieldCheck />, fuera: <LogOut /> };

function Modos({ e }: { e: Estado }) {
  const confirmar = useConfirmar();
  const poner = usePonerMando();
  const elegir = async (m: TMando) => {
    if (m === e.mando || poner.isPending) return;
    const ok = await confirmar({
      titulo: m === "fuera" ? "¿Salir a USDT?" : `¿Cambiar a «${MANDOS[m].nombre}»?`,
      texto: MANDOS[m].confirma, si: m === "fuera" ? "Sí, salir a USDT" : "Cambiar", peligro: m === "fuera",
    });
    if (ok) poner.mutate(m);
  };
  return (
    <Panel titulo="Modo" icono={<Play />} acciones={<span className="text-xs text-texto-3">Se aplica al momento</span>}>
      <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-4" role="radiogroup" aria-label="Modo de operación">
        {(Object.keys(MANDOS) as TMando[]).map((m) => {
          const activo = e.mando === m;
          return (
            <button key={m} type="button" role="radio" aria-checked={activo} onClick={() => elegir(m)}
              className={cx("relative grid grid-cols-[auto_1fr] items-start gap-x-3 gap-y-1 rounded-xl border p-4 text-left transition",
                activo ? (m === "fuera" ? "border-baja-marca bg-baja-marca/10" : "border-acento bg-acento/10 shadow-[0_0_0_1px_var(--c-acento)_inset]")
                       : "border-borde-2 bg-panel-2/50 hover:bg-panel-2")}>
              <span className={cx("row-span-2 grid size-9 place-items-center rounded-lg border [&>svg]:size-4",
                activo ? "border-acento/40 bg-acento/15 text-acento" : m === "fuera" ? "border-baja-marca/30 text-baja" : "border-borde-2 text-texto-2")}>
                {ICONOS[m]}
              </span>
              <span className={cx("flex items-center gap-2 text-sm font-semibold", m === "fuera" && "text-baja")}>
                {MANDOS[m].nombre}
                {activo && <Chip tono={m === "fuera" ? "baja" : "acento"} className="ml-auto h-5"><Check className="size-3" />activo</Chip>}
              </span>
              <span className="text-xs leading-relaxed text-texto-3">{MANDOS[m].texto}</span>
            </button>
          );
        })}
      </div>
      {poner.isError && <p role="alert" className="mt-3 text-sm text-baja">No se pudo: {(poner.error as Error).message}</p>}
    </Panel>
  );
}

function Niveles({ e }: { e: Estado }) {
  const confirmar = useConfirmar();
  const cambiar = useCambiarAjustes();
  const lista = Object.entries(e.niveles);
  const elegir = async (clave: string) => {
    const n = e.niveles[clave];
    if (clave === e.nivel || cambiar.isPending) return;
    const ok = await confirmar({
      titulo: `¿Pasar al nivel ${n.nombre}?`,
      texto: `En la prueba ganó ${pct(n.anual_pct, 1, true)} al año (≈ ${dinero(alDia(n.anual_pct, e.patrimonio), { signo: true })} al día con tu patrimonio) y su peor caída fue del ${pct(n.caida_pct, 1)} (≈ ${dinero(e.patrimonio * n.caida_pct / 100, { decimales: 0 })}). Se aplica en la próxima decisión.`,
      si: "Cambiar a " + n.nombre,
    });
    if (ok) cambiar.mutate(n.ajustes);
  };
  return (
    <Panel titulo="Nivel de riesgo" icono={<SlidersHorizontal />}
      acciones={<span className="text-xs text-texto-3">Medido en la prueba (2024 → nov 2026), en dólares con tu patrimonio de hoy. No es una promesa.</span>}>
      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5" role="radiogroup" aria-label="Nivel de riesgo">
        {lista.map(([clave, n], i) => {
          const activo = e.nivel === clave;
          return (
            <button key={clave} type="button" role="radio" aria-checked={activo} onClick={() => elegir(clave)}
              className={cx("grid content-start gap-1 rounded-xl border p-4 text-left transition",
                activo ? "border-acento bg-acento/10 shadow-[0_0_0_1px_var(--c-acento)_inset]" : "border-borde-2 bg-panel-2/50 hover:bg-panel-2")}>
              <span className="mb-1 flex items-center justify-between">
                <span className="text-sm font-semibold">{n.nombre}</span>
                <span className="flex gap-0.5" aria-hidden="true">
                  {lista.map((_, k) => <span key={k} className={cx("h-3.5 w-1.5 rounded-sm", k <= i ? "bg-acento" : "bg-panel-3")} />)}
                </span>
              </span>
              <span className="num text-lg font-semibold tracking-tight text-sube">≈ {dinero(alDia(n.anual_pct, e.patrimonio), { signo: true })}<span className="text-xs font-normal text-texto-3"> /día</span></span>
              <span className="text-xs text-texto-2">{pct(n.anual_pct, 1, true)} al año</span>
              <span className="text-xs text-texto-2">peor caída <span className="num text-baja">{pct(n.caida_pct, 1)}</span> <span className="whitespace-nowrap text-texto-3">(≈ {dinero(e.patrimonio * n.caida_pct / 100, { decimales: 0 })})</span></span>
              <span className="text-xs text-texto-2">{n.meses_positivos_pct} % de meses en positivo</span>
              <span className="mt-2 flex flex-wrap gap-1">
                {Object.entries(n.por_anio).map(([a, p]) => (
                  <span key={a} className="num rounded bg-panel-3 px-1.5 py-0.5 text-[10.5px] text-texto-3">{a} <span className={colorSigno(signoDe(p))}>{cifra(p, 1, true)}</span></span>
                ))}
              </span>
            </button>
          );
        })}
      </div>
      <p className="mt-3 text-xs text-texto-3">
        {e.nivel ? `Ahora: ${e.niveles[e.nivel].nombre}.` : "Ahora: riesgo puesto a medida; no coincide con ningún nivel medido."} Un cambio se aplica en la próxima decisión (cada {parseInt(e.intervalo, 10) || 4} horas).
        {cambiar.isError ? ` No se guardó: ${(cambiar.error as Error).message}` : ""}
      </p>
      <AjusteFino e={e} />
    </Panel>
  );
}

function AjusteFino({ e }: { e: Estado }) {
  const cambiar = useCambiarAjustes();
  const [valores, setValores] = useState<Record<string, number>>(e.ajustes);
  const [abierto, setAbierto] = useState(false);
  useEffect(() => { if (!abierto) setValores(e.ajustes); }, [e.ajustes, abierto]);
  return (
    <details className="mt-4 rounded-xl border border-borde bg-panel-2/40" open={abierto} onToggle={(ev) => setAbierto((ev.target as HTMLDetailsElement).open)}>
      <summary className="cursor-pointer px-4 py-3 text-[13px] font-semibold text-texto-2 hover:text-texto">Ajuste fino</summary>
      <form className="grid gap-5 px-4 pb-4 md:grid-cols-2" onSubmit={(ev) => { ev.preventDefault(); cambiar.mutate(valores); }}>
        {Object.entries(e.ajustables).map(([clave, lim]) => (
          <div key={clave} className="grid gap-2">
            <div className="flex items-baseline justify-between gap-3 text-[13px]">
              <label htmlFor={"aj-" + clave} className="text-texto-2">{lim.etiqueta}</label>
              <output className="num font-semibold">{lim.formato === "x" ? "×" + cifra(valores[clave], 2) : pctFraccion(valores[clave])}</output>
            </div>
            <Slider.Root id={"aj-" + clave} min={lim.min} max={lim.max} step={lim.paso} value={[valores[clave]]}
              onValueChange={([v]) => setValores((x) => ({ ...x, [clave]: v }))} className="relative flex h-5 touch-none select-none items-center" aria-label={lim.etiqueta}>
              <Slider.Track className="relative h-1.5 grow rounded-full bg-panel-3"><Slider.Range className="absolute h-full rounded-full bg-acento" /></Slider.Track>
              <Slider.Thumb className="block size-4 rounded-full border-2 border-acento bg-white shadow focus-visible:outline-2" />
            </Slider.Root>
          </div>
        ))}
        <div className="flex items-center gap-3 md:col-span-2">
          <Boton type="submit" variante="primario" disabled={cambiar.isPending}>Guardar el riesgo</Boton>
          <span className="text-xs text-texto-3" role="status">{cambiar.isSuccess ? "Guardado. Se aplica en la próxima decisión." : cambiar.isError ? "No se guardó: " + (cambiar.error as Error).message : ""}</span>
        </div>
      </form>
    </details>
  );
}

function Aparato({ prefs, poner, alOlvidar }: { prefs: Prefs; poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; alOlvidar: () => void }) {
  const confirmar = useConfirmar();
  return (
    <Panel titulo="Este aparato" icono={<Tablet />}>
      <div className="grid gap-3 text-[13px]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-texto-2">Tema</span>
          <Segmentado etiqueta="Tema" valor={prefs.tema} alCambiar={(v) => poner("tema", v)} opciones={[
            { valor: "auto", etiqueta: <><Monitor className="size-3.5" />Auto</> },
            { valor: "oscuro", etiqueta: <><Moon className="size-3.5" />Oscuro</> },
            { valor: "claro", etiqueta: <><Sun className="size-3.5" />Claro</> },
          ]} />
        </div>
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-borde pt-3">
          <span className="text-texto-2">Acceso</span>
          <Boton onClick={async () => {
            if (await confirmar({ titulo: "¿Olvidar el token aquí?", texto: "Este aparato dejará de ver el panel hasta que vuelvas a escribirlo. El bot sigue funcionando igual.", si: "Olvidarlo" })) alOlvidar();
          }}>Olvidar el token aquí</Boton>
        </div>
      </div>
    </Panel>
  );
}

export function Mando({ e, prefs, poner, alOlvidar }: {
  e: Estado; prefs: Prefs; poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; alOlvidar: () => void;
}) {
  return (
    <div className="grid gap-3 sm:gap-4">
      <Modos e={e} />
      <Niveles e={e} />
      <Aparato prefs={prefs} poner={poner} alOlvidar={alOlvidar} />
    </div>
  );
}
