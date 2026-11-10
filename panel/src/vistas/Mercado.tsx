import * as Tabs from "@radix-ui/react-tabs";
import { ChartCandlestick, Crosshair, History, Layers, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { BarraCobertura, Medidor, MiniLinea, Relojes, etiquetaTendencia } from "../componentes/piezas";
import { Chip, Cifra, Interruptor, Panel, Segmentado, colorSigno, cx } from "../componentes/ui";
import { GraficaVelas } from "../graficas/GraficaVelas";
import { MOTIVOS, base, cubiertaDe, expuesta, frenadaPorBtc, nombre } from "../lib/derivados";
import { cifra, cuando, dinero, pctFraccion, precio, signoDe, valido } from "../lib/formato";
import { useMedia } from "../lib/media";
import type { Prefs } from "../lib/prefs";
import type { Estado, Grafica, Mercado as TM, Moneda, Operacion } from "../tipos";

const RELOJES = ["2/8", "4/16", "5/20", "8/32", "10/40", "16/64"];
const CANALES = ["5", "10", "20", "40"];

function cambioSemana(m: TM | undefined, mo: Moneda) {
  const serie = m?.monedas.find((x) => x.simbolo === mo.simbolo)?.c ?? [];
  const vals = [...serie, ...(valido(mo.precio) ? [mo.precio] : [])];
  return { vals, cambio: vals.length > 1 ? vals[vals.length - 1] / vals[0] - 1 : null };
}

function ListaSeguimiento({ e, m, elegida, alElegir }: { e: Estado; m: TM | undefined; elegida: string; alElegir: (s: string) => void }) {
  return (
    <Panel titulo="Seguimiento" icono={<Crosshair />} cuerpo="p-1.5" className="h-full">
      <ul className="grid gap-0.5" role="listbox" aria-label="Monedas">
        {e.monedas.map((mo) => {
          const { vals, cambio } = cambioSemana(m, mo);
          const s = signoDe(cambio, 0.0005);
          const activa = mo.simbolo === elegida;
          return (
            <li key={mo.simbolo}>
              <button type="button" role="option" aria-selected={activa} onClick={() => alElegir(mo.simbolo)}
                className={cx("relative grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 rounded-lg px-3 py-2 text-left transition-colors",
                              activa ? "bg-panel-3" : "hover:bg-panel-2")}>
                {activa && <span className="absolute inset-y-2 left-0 w-0.5 rounded-full bg-acento" />}
                <span className="flex min-w-0 items-center gap-2">
                  <span className="text-[13px] font-semibold">{base(mo.simbolo)}</span>
                  <span className="truncate text-[11px] text-texto-3">{nombre(mo.simbolo)}</span>
                  {expuesta(mo) && <span className="size-1.5 rounded-full bg-serie-2" title="con exposición" />}
                </span>
                <span className="num text-right text-[13px]">{precio(mo.precio)}</span>
                <span className="flex items-center gap-2">
                  <MiniLinea valores={vals} ancho={56} alto={16} signo={s} />
                  <span className="text-[11px] text-texto-3">{etiquetaTendencia(mo.puntuacion)}</span>
                </span>
                <span className={cx("num text-right text-[11px]", colorSigno(s))}>{valido(cambio) ? pctFraccion(cambio, 1, true) : "—"}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

function Detalle({ e, mo, m }: { e: Estado; mo: Moneda; m: TM | undefined }) {
  const { cambio } = cambioSemana(m, mo);
  const cub = cubiertaDe(mo);
  const filas: [string, React.ReactNode][] = [
    ["Base (contado)", <span key="b" className="num">{cifra(mo.cantidad_base, mo.cantidad_base >= 100 ? 1 : 4)} <span className="text-texto-3">{base(mo.simbolo)}</span></span>],
    ["Valor de la base", <span key="v" className="num">{dinero(mo.valor_base)}</span>],
    ["Cobertura (corto)", <span key="c" className="num">{cifra(Math.abs(mo.cantidad_perp), Math.abs(mo.cantidad_perp) >= 100 ? 1 : 4)} <span className="text-texto-3">{base(mo.simbolo)}</span></span>],
    ["Entrada del corto", <span key="e" className="num">{precio(mo.entrada_perp)}</span>],
    ["Resultado del corto", <Cifra key="r" valor={mo.no_realizado_perp} signo colorear />],
    ["Exposición neta", <Cifra key="n" valor={mo.neto} tipo="fraccion" decimales={2} />],
  ];
  return (
    <Panel titulo={<span className="flex items-baseline gap-2">{base(mo.simbolo)}<span className="text-xs font-normal text-texto-3">{nombre(mo.simbolo)}</span></span>}
           icono={<Layers />} className="h-full" acciones={<span className={cx("num text-xs", colorSigno(signoDe(cambio, 0.0005)))}>{valido(cambio) ? pctFraccion(cambio, 1, true) + " 7d" : ""}</span>}>
      <div className="grid gap-5 md:grid-cols-3 2xl:grid-cols-1">
        <div>
          <div className="flex items-baseline justify-between">
            <span className="rotulo">Tendencia</span>
            <span className={cx("text-xs font-semibold", (mo.puntuacion ?? 0) > 0.33 ? "text-serie-1" : (mo.puntuacion ?? 0) < -0.33 ? "text-baja" : "text-texto-2")}>
              {etiquetaTendencia(mo.puntuacion)}
            </span>
          </div>
          <div className="mt-2"><Medidor valor={mo.puntuacion} /></div>
          {frenadaPorBtc(e, mo) && <p className="mt-2 text-[11px] text-texto-3"><Chip tono="aviso" className="mr-1.5">frenada por BTC</Chip>Bitcoin no está a favor: no sube exposición.</p>}
        </div>
        <Relojes relojes={mo.relojes} detalle />
        <div>
          <div className="mb-1.5 flex items-baseline justify-between">
            <span className="rotulo">Posición</span>
            <span className="text-[11px] text-texto-3">{mo.base > 0 ? (cub > 0.995 ? "cubierta del todo" : `${pctFraccion(cub)} cubierta`) : "sin base"}</span>
          </div>
          <BarraCobertura cubierta={cub} />
          <dl className="mt-3 grid gap-1.5 text-[13px]">
            {filas.map(([t, v]) => (
              <div key={t} className="flex items-baseline justify-between gap-3"><dt className="text-texto-3">{t}</dt><dd>{v}</dd></div>
            ))}
          </dl>
        </div>
      </div>
    </Panel>
  );
}

function Posiciones({ e, alElegir }: { e: Estado; alElegir: (s: string) => void }) {
  const total = e.monedas.reduce((s, m) => s + m.no_realizado_perp, 0);
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[760px] text-[13px]">
        <thead>
          <tr className="text-left text-[11px] text-texto-3">
            {["Moneda", "Precio", "Base", "Cobertura", "Cubierta", "Neto", "Entrada corto", "Resultado corto", "Tendencia"].map((t, i) => (
              <th key={t} className={cx("px-4 py-2.5 font-medium", i > 0 && i < 8 && "text-right")}>{t}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {e.monedas.map((m) => (
            <tr key={m.simbolo} className="cursor-pointer border-t border-borde hover:bg-panel-2/60" onClick={() => alElegir(m.simbolo)}>
              <td className="px-4 py-2.5"><span className="font-semibold">{base(m.simbolo)}</span><span className="ml-2 text-[11px] text-texto-3">{nombre(m.simbolo)}</span></td>
              <td className="num px-4 py-2.5 text-right">{precio(m.precio)}</td>
              <td className="num px-4 py-2.5 text-right">{dinero(m.valor_base, { decimales: 0 })}</td>
              <td className="num px-4 py-2.5 text-right">{dinero(m.valor_cobertura, { decimales: 0 })}</td>
              <td className="px-4 py-2.5"><div className="ml-auto w-20"><BarraCobertura cubierta={cubiertaDe(m)} /></div></td>
              <td className="num px-4 py-2.5 text-right">{pctFraccion(m.neto, 1)}</td>
              <td className="num px-4 py-2.5 text-right text-texto-2">{precio(m.entrada_perp)}</td>
              <td className="px-4 py-2.5 text-right"><Cifra valor={m.no_realizado_perp} signo colorear /></td>
              <td className="px-4 py-2.5"><div className="w-36"><Medidor valor={m.puntuacion} /></div></td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t border-borde-2 text-[13px]">
            <td className="px-4 py-2.5 font-semibold">Total</td>
            <td />
            <td className="num px-4 py-2.5 text-right font-semibold">{dinero(e.valor_base, { decimales: 0 })}</td>
            <td className="num px-4 py-2.5 text-right font-semibold">{dinero(e.monedas.reduce((s, m) => s + m.valor_cobertura, 0), { decimales: 0 })}</td>
            <td />
            <td className="num px-4 py-2.5 text-right font-semibold">{pctFraccion(e.exposicion_neta, 1)}</td>
            <td />
            <td className="px-4 py-2.5 text-right font-semibold"><Cifra valor={total} signo colorear /></td>
            <td />
          </tr>
        </tfoot>
      </table>
      <p className="border-t border-borde px-4 py-2.5 text-xs text-texto-3">
        El resultado del corto compensa lo que la base gana o pierde por precio: cubierto, el patrimonio no se mueve.
      </p>
    </div>
  );
}

function Operaciones({ ops }: { ops: Operacion[] }) {
  const [abiertos, setAbiertos] = useState<Record<string, boolean>>({});
  const [cuantos, setCuantos] = useState(6);
  const lotes = useMemo(() => {
    const out: { clave: string; t: number; utc: string; motivo: string; filas: Operacion[] }[] = [];
    for (const o of ops) {
      const t = Date.parse(o.utc);
      const u = out[out.length - 1];
      if (!u || u.motivo !== o.motivo || Math.abs(u.t - t) > 10000) out.push({ clave: o.utc + o.motivo, t, utc: o.utc, motivo: o.motivo, filas: [] });
      out[out.length - 1].filas.push(o);
    }
    return out;
  }, [ops]);
  if (!lotes.length) return <p className="px-4 py-10 text-center text-sm text-texto-3">Todavía no hay operaciones.</p>;
  return (
    <div>
      <ul>
        {lotes.slice(0, cuantos).map((l, i) => {
          // La última decisión sale abierta si es corta; luego manda lo que haga quien mira.
          const abierto = abiertos[l.clave] ?? (i === 0 && l.filas.length <= 8);
          const comision = l.filas.reduce((s, o) => s + Number(o.comision || 0), 0);
          const nocional = l.filas.reduce((s, o) => s + Number(o.nocional || 0), 0);
          return (
            <li key={l.clave} className="border-t border-borde first:border-t-0">
              <button type="button" aria-expanded={abierto}
                onClick={() => setAbiertos((a) => ({ ...a, [l.clave]: !abierto }))}
                className="grid w-full grid-cols-[minmax(0,1fr)_auto] items-center gap-x-4 gap-y-0.5 px-4 py-2.5 text-left hover:bg-panel-2/60 sm:grid-cols-[150px_minmax(0,1fr)_auto_auto]">
                <span className="num text-[13px] font-semibold">{cuando(l.utc)}</span>
                <span className="text-[13px] text-texto-2 sm:order-none">{MOTIVOS[l.motivo] ?? l.motivo}</span>
                <span className="text-xs text-texto-3">{l.filas.length} {l.filas.length === 1 ? "operación" : "operaciones"}</span>
                <span className="num text-xs text-texto-3">{dinero(nocional, { decimales: 0 })} · comisión {dinero(comision)}</span>
              </button>
              {abierto && (
                <div className="overflow-x-auto px-4 pb-3">
                  <table className="w-full min-w-[520px] text-[13px]">
                    <tbody>
                      {l.filas.map((o, k) => {
                        const que = o.pata === "contado" ? (o.lado === "compra" ? "Compra base" : "Vende base") : (o.lado === "venta" ? "Sube cobertura" : "Baja cobertura");
                        const tono = o.pata === "contado" ? (o.lado === "compra" ? "text-sube" : "text-baja") : "text-serie-1";
                        return (
                          <tr key={k} className="border-t border-borde/70">
                            <td className="py-1.5 pr-4 font-semibold">{base(o.simbolo)}</td>
                            <td className={cx("py-1.5 pr-4", tono)}>{que}</td>
                            <td className="num py-1.5 pr-4 text-right">{dinero(Number(o.nocional))}</td>
                            <td className="num py-1.5 pr-4 text-right text-texto-2">a {precio(Number(o.precio))}</td>
                            <td className="num py-1.5 text-right text-texto-3">{dinero(Number(o.comision), { decimales: 3 })}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </li>
          );
        })}
      </ul>
      {lotes.length > cuantos && (
        <button type="button" onClick={() => setCuantos((c) => c + 10)} className="w-full border-t border-borde py-2.5 text-xs font-semibold text-acento hover:bg-panel-2/60">
          Ver más decisiones
        </button>
      )}
    </div>
  );
}

export function Mercado({ e, m, g, ops, prefs, poner, tema }: {
  e: Estado; m: TM | undefined; g: Grafica | undefined; ops: Operacion[] | undefined; prefs: Prefs;
  poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; tema: string;
}) {
  const mo = e.monedas.find((x) => x.simbolo === prefs.moneda) ?? e.monedas[0];
  const ancho = useMedia("(min-width: 640px)");
  const elegir = (s: string) => poner("moneda", s);
  return (
    <div className="grid grid-cols-12 gap-3 sm:gap-4">
      {/* En el móvil la lista es una fila de fichas. */}
      <div className="barra-desliza col-span-12 -mx-3 flex gap-1.5 overflow-x-auto px-3 lg:hidden">
        {e.monedas.map((x) => (
          <button key={x.simbolo} type="button" onClick={() => elegir(x.simbolo)}
            className={cx("shrink-0 rounded-lg border px-3 py-1.5 text-xs font-semibold", x.simbolo === mo.simbolo ? "border-acento bg-acento/15 text-texto" : "border-borde bg-panel text-texto-2")}>
            {base(x.simbolo)}
          </button>
        ))}
      </div>
      <div className="col-span-12 hidden lg:col-span-3 lg:block 2xl:col-span-2">
        <ListaSeguimiento e={e} m={m} elegida={mo.simbolo} alElegir={elegir} />
      </div>
      <Panel className="col-span-12 lg:col-span-9 2xl:col-span-7" cuerpo="p-0" icono={<ChartCandlestick />}
        titulo={<span className="flex items-baseline gap-2">{base(mo.simbolo)}/USDT <span className="num text-xs font-normal text-texto-2">{precio(mo.precio)}</span></span>}
        acciones={<>
          <Segmentado pequeno etiqueta="Cruce de medias (días)" valor={prefs.reloj} alCambiar={(v) => poner("reloj", v)}
            opciones={RELOJES.map((r) => ({ valor: r, etiqueta: r, titulo: `Medias de ${r.replace("/", " y ")} días` }))} />
          <Segmentado pequeno etiqueta="Canal (días)" valor={prefs.canal} alCambiar={(v) => poner("canal", v)}
            opciones={CANALES.map((c) => ({ valor: c, etiqueta: c + "d", titulo: `Canal de ${c} días` }))} />
          <Interruptor marcado={prefs.marcas} alCambiar={(v) => poner("marcas", v)} etiqueta="Operaciones" />
        </>}>
        <GraficaVelas g={g && g.simbolo === mo.simbolo ? g : undefined} reloj={prefs.reloj} canal={prefs.canal} marcas={prefs.marcas}
                      tema={tema} alto={ancho ? 540 : 420} />
        <p className="border-t border-borde px-4 py-2.5 text-xs text-texto-3">
          Velas de 4 horas, cerradas. Naranja y morado: el cruce de medias elegido; discontinuas: el canal. Abajo, la tendencia con la que decide el bot (de −1 a +1).
          {prefs.marcas ? " Las marcas son sus operaciones en esta moneda." : ""}
        </p>
      </Panel>
      <div className="col-span-12 2xl:col-span-3">
        <Detalle e={e} mo={mo} m={m} />
      </div>

      <section className="panel col-span-12 min-w-0">
        <Tabs.Root defaultValue="posiciones">
          <Tabs.List className="flex gap-1 border-b border-borde px-2" aria-label="Posiciones y operaciones">
            {[["posiciones", "Posiciones", <ShieldCheck key="p" />], ["operaciones", "Operaciones", <History key="o" />]].map(([v, t, ic]) => (
              <Tabs.Trigger key={v as string} value={v as string}
                className="relative flex h-11 items-center gap-2 px-3 text-[13px] font-medium text-texto-3 hover:text-texto data-[state=active]:text-texto [&>svg]:size-4 data-[state=active]:after:absolute data-[state=active]:after:inset-x-2 data-[state=active]:after:bottom-0 data-[state=active]:after:h-0.5 data-[state=active]:after:rounded-full data-[state=active]:after:bg-acento">
                {ic}{t}
              </Tabs.Trigger>
            ))}
          </Tabs.List>
          <Tabs.Content value="posiciones"><Posiciones e={e} alElegir={elegir} /></Tabs.Content>
          <Tabs.Content value="operaciones"><Operaciones ops={ops ?? []} /></Tabs.Content>
        </Tabs.Root>
      </section>
    </div>
  );
}
