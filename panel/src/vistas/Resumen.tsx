import { Activity, Gauge, LayoutGrid, Wallet } from "lucide-react";
import { useMemo } from "react";
import { BarraCobertura, BarraPartes, Medidor, MiniBarras, MiniLinea, etiquetaTendencia } from "../componentes/piezas";
import { Chip, Cifra, Interruptor, Panel, Segmentado, Stat, colorSigno, cx } from "../componentes/ui";
import { GraficaPatrimonio, type PuntoP } from "../graficas/GraficaPatrimonio";
import { useAhora } from "../marco/Marco";
import { MANDOS, base, cubiertaDe, frase, frenadaPorBtc, nivelActual, nombre, partesCartera } from "../lib/derivados";
import { cifra, claveDia, cuando, dia, dinero, duracion, mesLargo, fechaLocal, pctFraccion, precio, signoDe, valido } from "../lib/formato";
import { alDia } from "../lib/niveles";
import type { Prefs } from "../lib/prefs";
import type { Estado, Ganancias, Mercado, PuntoCurva } from "../tipos";

/** Ganancia de cada día desde `desde` (clave AAAA-MM-DD) hasta hoy, con hueco (null) los días sin datos. */
function diasDesde(g: Ganancias | undefined, desde: string): (number | null)[] {
  if (!g) return [];
  const porDia = new Map(g.dias.map((d) => [d.fecha, d.ganancia]));
  const out: (number | null)[] = [];
  for (let d = fechaLocal(desde); claveDia(d) <= g.hoy_fecha; d.setDate(d.getDate() + 1)) out.push(porDia.get(claveDia(d)) ?? null);
  return out;
}

export function StatsGanancia({ g, conMedia = true, curvaHoy }: { g: Ganancias | undefined; conMedia?: boolean; curvaHoy?: number[] }) {
  const r = g?.resumen;
  const hace30 = (() => { const d = fechaLocal(g?.hoy_fecha ?? claveDia(new Date())); d.setDate(d.getDate() - 29); return claveDia(d); })();
  const fin = r?.hoy && valido(r.hoy.financiacion) ? `${dinero(r.hoy.financiacion, { signo: true })} de financiación` : "";
  const pctTxt = (x: { pct: number } | null | undefined) => (x ? `${cifra(x.pct, 2, true)} %` : "");
  return (
    <>
      <Stat rotulo="Hoy" valor={dinero(r?.hoy?.ganancia, { signo: true })} signo={signoDe(r?.hoy?.ganancia)}
            sub={[pctTxt(r?.hoy), fin].filter(Boolean).join(" · ")}
            extra={curvaHoy && curvaHoy.length > 1 ? <MiniLinea valores={curvaHoy} ancho={200} alto={30} signo={signoDe(r?.hoy?.ganancia)} fluida /> : undefined} />
      <Stat rotulo="Esta semana" valor={dinero(r?.semana?.ganancia, { signo: true })} signo={signoDe(r?.semana?.ganancia)}
            sub={r?.semana ? `${pctTxt(r.semana)} · desde el lunes` : ""}
            extra={r?.semana ? <MiniBarras valores={diasDesde(g, r.semana.clave)} /> : undefined} />
      <Stat rotulo="Este mes" valor={dinero(r?.mes?.ganancia, { signo: true })} signo={signoDe(r?.mes?.ganancia)}
            sub={r?.mes ? `${pctTxt(r.mes)} · ${mesLargo(fechaLocal(r.mes.clave)).split(" ")[0]}` : ""}
            extra={r?.mes ? <MiniBarras valores={diasDesde(g, r.mes.clave + "-01")} /> : undefined} />
      {conMedia && (
        <Stat rotulo="Media por día" valor={valido(r?.media_dia) ? dinero(r.media_dia, { signo: true }) : "—"} signo={signoDe(r?.media_dia)}
              sub={r && r.dias_completos ? `${r.dias_completos} ${r.dias_completos === 1 ? "día completo" : "días completos"}${r.dias_completos < 7 ? " · aún pocos" : ""}` : "Hace falta un día completo"}
              extra={g?.dias.length && r?.dias_completos ? <MiniBarras valores={diasDesde(g, hace30 < g.dias[0].fecha ? g.dias[0].fecha : hace30)} /> : undefined} />
      )}
    </>
  );
}

function Heroe({ e }: { e: Estado }) {
  const texto = cifra(e.patrimonio, 2);
  const coma = texto.lastIndexOf(",");
  const s = signoDe(e.ganancia);
  return (
    <div className="panel relative col-span-12 flex min-w-0 flex-col justify-between gap-4 overflow-hidden p-5 xl:col-span-4">
      <div className="pointer-events-none absolute -top-24 -right-16 size-64 rounded-full bg-acento/15 blur-3xl" />
      <div className="pointer-events-none absolute inset-0 fondo-rejilla opacity-60 [mask-image:linear-gradient(to_bottom,black,transparent)]" />
      <div className="relative flex items-center justify-between">
        <span className="rotulo">Patrimonio</span>
        <Chip tono="acento"><Wallet className="size-3" />USDT ≈ $</Chip>
      </div>
      <div className="relative">
        <p className="num text-[40px] leading-none font-semibold tracking-tighter sm:text-5xl">
          {coma > 0 ? texto.slice(0, coma) : texto}
          <span className="text-[0.5em] text-texto-2">{coma > 0 ? texto.slice(coma) : ""}</span>
          <span className="ml-2 text-[0.42em] font-medium text-texto-3">$</span>
        </p>
        <p className={cx("num mt-3 flex flex-wrap items-center gap-x-2 text-sm font-semibold", colorSigno(s))}>
          <span>{s === "sube" ? "▲" : s === "baja" ? "▼" : "•"} {dinero(e.ganancia, { signo: true })}</span>
          <span className="rounded-md bg-panel-2 px-1.5 py-0.5 text-xs">{cifra(e.ganancia_pct, 2, true)} %</span>
          <span className="font-normal text-texto-3">desde el inicio</span>
        </p>
        <p className="mt-1.5 text-xs text-texto-3">
          Empezó con <span className="num text-texto-2">{dinero(e.capital_inicial)}</span>
          {e.creada_utc ? ` el ${dia(e.creada_utc)}` : ""}. Mercado real, dinero ficticio.
        </p>
      </div>
      <p className="relative rounded-lg border border-borde bg-panel-2/70 px-3 py-2.5 text-[13px] leading-relaxed text-texto-2">
        <Activity className="mr-1.5 inline size-3.5 -translate-y-px text-acento" />{frase(e)}
      </p>
    </div>
  );
}

function EstadoBot({ e }: { e: Estado }) {
  const ahora = useAhora();
  const n = nivelActual(e);
  const horas = parseInt(e.intervalo, 10) || 4;
  const prox = e.proxima_decision_utc ? Date.parse(e.proxima_decision_utc) : null;
  const falta = prox ? prox - ahora : null;
  const hecho = falta === null ? 0 : 1 - Math.max(0, Math.min(1, falta / (horas * 36e5)));
  return (
    <Panel titulo="Estado del bot" icono={<Gauge />} acciones={<Chip tono={e.mando === "auto" ? "sube" : "aviso"}>{MANDOS[e.mando].nombre}</Chip>}>
      <div className="grid gap-4">
        <div className="flex items-end justify-between gap-3">
          <div>
            <p className="rotulo">Próxima decisión</p>
            <p className="num mt-1 text-2xl font-semibold tracking-tight">{falta === null ? "—" : falta > 0 ? "en " + duracion(falta) : "ahora"}</p>
          </div>
          <div className="text-right text-xs text-texto-3">
            <p>Nivel <span className="font-semibold text-texto">{n ? n.nombre : "a medida"}</span></p>
            <p>vela de {horas} h</p>
          </div>
        </div>
        <div className="h-1.5 overflow-hidden rounded-full bg-panel-3">
          <div className="h-full rounded-full bg-gradient-to-r from-acento to-acento-2 transition-[width] duration-1000" style={{ width: `${(hecho * 100).toFixed(1)}%` }} />
        </div>
        <p className="text-xs leading-relaxed text-texto-3">
          Decide al cerrar cada vela{e.decision_vela_utc ? `; la última, ${cuando(e.decision_vela_utc)}` : ""}
          {valido(e.decision?.operaciones) ? ` con ${e.decision.operaciones} ${e.decision.operaciones === 1 ? "operación" : "operaciones"}` : ""}.
          {e.mando === "pausa" ? " En pausa no opera aunque toque." : ""}
        </p>
      </div>
    </Panel>
  );
}

function Cartera({ e }: { e: Estado }) {
  const partes = partesCartera(e);
  const baseFr = Math.max(0, e.exposicion_base);
  return (
    <Panel titulo="Cartera" icono={<Wallet />}>
      <BarraPartes partes={partes} />
      <ul className="mt-3 grid gap-1.5 text-[13px]">
        {partes.map((p) => (
          <li key={p.nombre} className="flex items-center gap-2">
            <span className="size-2.5 rounded-[3px]" style={{ background: p.color }} />
            <span className="text-texto-2">{p.nombre}</span>
            <span className="num ml-auto font-semibold">{dinero(p.valor * e.patrimonio, { decimales: 0 })}</span>
          </li>
        ))}
      </ul>
      <dl className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-borde bg-borde text-[13px]">
        {[
          ["Expuesto", <Cifra key="a" valor={e.exposicion_neta} tipo="fraccion" />],
          ["Base cubierta", <span key="b" className="num">{baseFr > 0 ? pctFraccion(partes[0].valor / baseFr) : "—"}</span>],
          ["Financiación", <Cifra key="c" valor={e.financiacion} signo colorear />],
          ["Comisiones", <Cifra key="d" valor={-e.comisiones} signo />],
          ["Garantía", <span key="e" className="num">{valido(e.colchon_margen) ? pctFraccion(e.colchon_margen) : "—"}</span>],
          ["No realizado", <Cifra key="f" valor={e.no_realizado} signo colorear />],
        ].map(([t, v]) => (
          <div key={String(t)} className="bg-panel px-3 py-2">
            <dt className="text-[11px] text-texto-3">{t}</dt>
            <dd className="mt-0.5 font-semibold">{v}</dd>
          </div>
        ))}
      </dl>
    </Panel>
  );
}

function Vistazo({ e, m, alElegir }: { e: Estado; m: Mercado | undefined; alElegir: (s: string) => void }) {
  const porSimbolo = new Map((m?.monedas ?? []).map((x) => [x.simbolo, x]));
  return (
    <Panel titulo="Mercado de un vistazo" icono={<LayoutGrid />} className="col-span-12"
           acciones={<span className="text-xs text-texto-3">7 días · tendencia del bot · cobertura</span>}>
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3 xl:grid-cols-5">
        {e.monedas.map((mo) => {
          const serie = porSimbolo.get(mo.simbolo)?.c ?? [];
          const vals = [...serie, ...(valido(mo.precio) ? [mo.precio] : [])];
          const cambio = vals.length > 1 ? vals[vals.length - 1] / vals[0] - 1 : null;
          const s = signoDe(cambio, 0.0005);
          return (
            <button key={mo.simbolo} type="button" onClick={() => alElegir(mo.simbolo)}
              className="group flex min-w-0 flex-col gap-2.5 rounded-lg border border-borde bg-panel-2/60 p-3 text-left transition hover:border-borde-2 hover:bg-panel-2">
              <div className="flex items-center justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-[13px] font-semibold">{base(mo.simbolo)}</p>
                  <p className="truncate text-[11px] text-texto-3">{nombre(mo.simbolo)}</p>
                </div>
                <MiniLinea valores={vals} ancho={64} alto={26} signo={s} />
              </div>
              <div className="flex items-baseline justify-between gap-2">
                <span className="num text-sm font-semibold">{precio(mo.precio)}</span>
                <span className={cx("num text-xs", colorSigno(s))}>{valido(cambio) ? pctFraccion(cambio, 1, true) : "—"}</span>
              </div>
              <Medidor valor={mo.puntuacion} />
              <div className="flex items-center justify-between gap-2 text-[11px] text-texto-3">
                <span>{etiquetaTendencia(mo.puntuacion)}{frenadaPorBtc(e, mo) ? " · frenada" : ""}</span>
                <span>{mo.base > 0 ? (cubiertaDe(mo) > 0.995 ? "cubierta" : pctFraccion(cubiertaDe(mo)) + " cub.") : "sin base"}</span>
              </div>
              <BarraCobertura cubierta={cubiertaDe(mo)} />
            </button>
          );
        })}
      </div>
    </Panel>
  );
}

export function Resumen({ e, g, curva, m, prefs, poner, tema, alElegirMoneda }: {
  e: Estado; g: Ganancias | undefined; curva: PuntoCurva[] | undefined; m: Mercado | undefined; prefs: Prefs;
  poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; tema: string; alElegirMoneda: (s: string) => void;
}) {
  const puntos = useMemo<PuntoP[]>(() => {
    const p = (curva ?? []).map((x) => ({ t: Date.parse(x.utc), v: x.patrimonio, neto: x.neto, btc: x.btc }));
    p.push({ t: Date.parse(e.utc), v: e.patrimonio, neto: Math.max(0, e.exposicion_neta), btc: e.monedas[0]?.precio ?? null });
    return p;
  }, [curva, e.utc, e.patrimonio, e.exposicion_neta, e.monedas]);
  const n = nivelActual(e);
  const curvaHoy = useMemo(() => {
    const hoy = g?.hoy_fecha;
    return hoy ? puntos.filter((p) => claveDia(new Date(p.t)) === hoy).map((p) => p.v) : [];
  }, [puntos, g?.hoy_fecha]);
  return (
    <div className="grid grid-cols-12 gap-3 sm:gap-4">
      <Heroe e={e} />
      <div className="col-span-12 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-4 xl:col-span-8 xl:grid-cols-2 xl:grid-rows-2">
        <StatsGanancia g={g} curvaHoy={curvaHoy} />
      </div>

      <Panel titulo="Evolución del patrimonio" icono={<Activity />} className="col-span-12 xl:col-span-8" cuerpo="p-0 flex flex-col"
        acciones={<>
          <Segmentado etiqueta="Periodo" valor={String(prefs.horas)} alCambiar={(v) => poner("horas", Number(v) as Prefs["horas"])}
            opciones={[{ valor: "24", etiqueta: "24H" }, { valor: "168", etiqueta: "7D" }, { valor: "720", etiqueta: "30D" }, { valor: "0", etiqueta: "Todo" }]} />
          <Interruptor marcado={prefs.vsBtc} alCambiar={(v) => poner("vsBtc", v)} etiqueta="vs BTC" />
        </>}>
        <GraficaPatrimonio puntos={puntos} comparar={prefs.vsBtc} tema={tema} />
        {n && (
          <p className="border-t border-borde px-4 py-2.5 text-xs text-texto-3">
            Lo medido para {n.nombre}: <span className="num text-texto-2">{dinero(alDia(n.anual_pct, e.patrimonio), { signo: true })}</span> al día de media
            ({cifra(n.anual_pct, 1, true)} % al año), con un {100 - n.meses_positivos_pct} % de los meses sin ganar. No es una promesa.
          </p>
        )}
      </Panel>
      <div className="col-span-12 grid content-start gap-3 sm:gap-4 md:grid-cols-2 xl:col-span-4 xl:grid-cols-1">
        <EstadoBot e={e} />
        <Cartera e={e} />
      </div>
      <Vistazo e={e} m={m} alElegir={alElegirMoneda} />
    </div>
  );
}
