import { CalendarDays, ChartColumn, ChevronLeft, ChevronRight, Scale, Split, Table2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Boton, Chip, Panel, Segmentado, Stat, colorSigno, cx } from "../componentes/ui";
import { Calendario } from "../graficas/Calendario";
import { GraficaDias, type Barra } from "../graficas/GraficaDias";
import { nivelActual } from "../lib/derivados";
import { cifra, claveDia, dia, diaSemana, diaSemanaCorto, dinero, fechaLocal, mayuscula, mesLargo, pct, signoDe, valido } from "../lib/formato";
import { alDia, aniosParaDoblar, diasDelAnio } from "../lib/niveles";
import type { Prefs } from "../lib/prefs";
import type { Dia, Estado, Ganancias as TG, Grupo } from "../tipos";
import { StatsGanancia } from "./Resumen";

function Reparto({ r }: { r: { mercado: number | null; financiacion: number | null; comisiones: number | null } }) {
  if (!valido(r.financiacion)) return null;
  return (
    <span className="num text-texto-3">
      mercado <span className={colorSigno(signoDe(r.mercado))}>{cifra(r.mercado, 2, true)}</span> · financiación{" "}
      <span className={colorSigno(signoDe(r.financiacion))}>{cifra(r.financiacion, 2, true)}</span> · comisiones{" "}
      <span className={colorSigno(signoDe(-(r.comisiones ?? 0)))}>{cifra(-(r.comisiones ?? 0), 2, true)}</span>
    </span>
  );
}

function Origen({ m, titulo }: { m: Grupo | undefined; titulo: string }) {
  if (!m) return <p className="py-8 text-center text-sm text-texto-3">Sin datos en este mes.</p>;
  if (!valido(m.financiacion)) return <p className="py-8 text-center text-sm text-texto-3">A algún día de {titulo} le falta el reparto.</p>;
  const partes = [
    { nombre: "Mercado", valor: m.mercado ?? 0, nota: "precio de lo expuesto y deslizamiento" },
    { nombre: "Financiación", valor: m.financiacion ?? 0, nota: "lo que cobran o pagan las coberturas" },
    { nombre: "Comisiones", valor: -(m.comisiones ?? 0), nota: "lo que cuesta cada operación" },
  ];
  const tope = Math.max(0.01, ...partes.map((p) => Math.abs(p.valor)), Math.abs(m.ganancia));
  const fila = (nombreF: string, valor: number, nota?: string, total = false) => (
    <div key={nombreF} className={cx("grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_auto] items-center gap-3", total && "border-t border-borde pt-3")}>
      <div className="min-w-0">
        <p className={cx("text-[13px]", total ? "font-semibold" : "text-texto")}>{nombreF}</p>
        {nota && <p className="truncate text-[11px] text-texto-3">{nota}</p>}
      </div>
      <div className="relative h-2.5">
        <div className="absolute inset-y-[-4px] left-1/2 w-px bg-borde-2" />
        <div className={cx("absolute inset-y-0", valor >= 0 ? "left-1/2 rounded-r bg-sube-marca" : "right-1/2 rounded-l bg-baja-marca")}
             style={{ width: `${(Math.abs(valor) / tope) * 50}%` }} />
      </div>
      <span className={cx("num w-24 text-right text-[13px] font-semibold", colorSigno(signoDe(valor)))}>{dinero(valor, { signo: true })}</span>
    </div>
  );
  return (
    <div className="grid gap-3.5">
      {partes.map((p) => fila(p.nombre, p.valor, p.nota))}
      {fila("Total", m.ganancia, undefined, true)}
    </div>
  );
}

function LoMedido({ e, g }: { e: Estado; g: TG }) {
  const n = nivelActual(e);
  const r = g.resumen;
  const ref = n ? alDia(n.anual_pct, e.patrimonio) : null;
  const hasta = e.niveles_periodo?.hasta ?? "2026-11-09";
  return (
    <Panel titulo="Lo medido y lo real" icono={<Scale />} acciones={<Chip tono="acento">{n ? n.nombre : "A medida"}</Chip>}>
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg border border-borde bg-panel-2/70 p-3">
          <p className="rotulo">Medido, al día</p>
          <p className="num mt-1.5 text-xl font-semibold">{ref === null ? "—" : dinero(ref, { signo: true })}</p>
          <p className="mt-1 text-[11px] text-texto-3">{n ? `${cifra(n.anual_pct, 1, true)} % al año · ${n.meses_positivos_pct} % de meses +` : "riesgo sin medir"}</p>
        </div>
        <div className="rounded-lg border border-borde bg-panel-2/70 p-3">
          <p className="rotulo">Real, al día</p>
          <p className={cx("num mt-1.5 text-xl font-semibold", colorSigno(signoDe(r.media_dia)))}>{valido(r.media_dia) ? dinero(r.media_dia, { signo: true }) : "—"}</p>
          <p className="mt-1 text-[11px] text-texto-3">{r.dias_completos ? `${r.dias_completos} días · ${r.dias_positivos} en positivo` : "aún sin días completos"}</p>
        </div>
      </div>
      {n && (
        <table className="mt-3 w-full text-[13px]">
          <thead>
            <tr className="text-left text-[11px] text-texto-3">
              <th className="py-1.5 font-medium">Año medido</th><th className="py-1.5 text-right font-medium">Ganancia</th><th className="py-1.5 text-right font-medium">≈ al día</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(n.por_anio).map(([anio, p]) => (
              <tr key={anio} className="border-t border-borde">
                <td className="py-2">{anio}{anio === hasta.slice(0, 4) ? <span className="text-texto-3"> (hasta {dia(fechaLocal(hasta))})</span> : ""}</td>
                <td className={cx("num py-2 text-right font-semibold", colorSigno(signoDe(p)))}>{pct(p, 1, true)}</td>
                <td className="num py-2 text-right">{dinero(alDia(p, e.patrimonio, diasDelAnio(anio, hasta)), { signo: true })}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mt-3 text-xs leading-relaxed text-texto-3">
        La media esconde rachas: mira la diferencia entre años.{" "}
        {n ? `Al ${cifra(n.anual_pct, 1)} % al año, el dinero se dobla en unos ${cifra(aniosParaDoblar(n.anual_pct), 0)} años. ` : ""}
        {r.dias_completos < 30 ? "Con menos de un mes todavía no se puede comparar; lo que vale es que, mes a mes, lo real se parezca a lo medido."
                               : "Lo que vale es que, mes a mes, lo real se parezca a lo medido."}
      </p>
    </Panel>
  );
}

export function Ganancias({ e, g, prefs, poner, tema }: {
  e: Estado; g: TG | undefined; prefs: Prefs; poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; tema: string;
}) {
  const [mesVisto, setMesVisto] = useState<string | null>(null);
  const [elegido, setElegido] = useState<string | null>(null);
  const porDia = useMemo(() => new Map((g?.dias ?? []).map((d) => [d.fecha, d])), [g]);

  const barras = useMemo<Barra[]>(() => {
    if (!g) return [];
    const hoy = g.hoy_fecha;
    const claves: string[] = [];
    for (let d = fechaLocal(g.dias[0]?.fecha ?? hoy); claveDia(d) <= hoy; d.setDate(d.getDate() + 1)) claves.push(claveDia(d));
    const vis = prefs.dias ? claves.slice(-prefs.dias) : claves;
    return vis.map((c) => ({ clave: c, valor: porDia.get(c)?.ganancia ?? null, parcial: c === hoy }));
  }, [g, porDia, prefs.dias]);

  if (!g) return <p className="py-20 text-center text-texto-3">Cargando ganancias…</p>;
  const n = nivelActual(e);
  const ref = n ? alDia(n.anual_pct, e.patrimonio) : null;
  const hoy = g.hoy_fecha;
  const mes = mesVisto ?? hoy.slice(0, 7);
  const [anio, mm] = mes.split("-").map(Number);
  const primerDia = g.dias[0]?.fecha ?? hoy;
  const diaElegido = elegido ?? hoy;
  const dElegido: Dia | undefined = porDia.get(diaElegido);
  const grupoMes = g.meses.find((x) => x.clave === mes);
  const tituloMes = mesLargo(new Date(anio, mm - 1, 1));
  const moverMes = (paso: number) => setMesVisto(claveDia(new Date(anio, mm - 1 + paso, 1)).slice(0, 7));
  const r = g.resumen;

  const lecturaDia = (clave: string | null) => {
    const d = clave ? porDia.get(clave) : undefined;
    if (!clave) return null;
    return (
      <div className="grid gap-0.5">
        <span className="flex flex-wrap items-baseline gap-x-3">
          <span className="num text-texto-3">{diaSemanaCorto(fechaLocal(clave))}{clave === hoy ? " · hoy, en curso" : ""}</span>
          <span className={cx("num font-semibold", colorSigno(signoDe(d?.ganancia)))}>{d ? dinero(d.ganancia, { signo: true }) : "sin datos"}</span>
          {d && <span className="num text-texto-3">{cifra(d.pct, 3, true)} %</span>}
        </span>
        {d && <Reparto r={d} />}
      </div>
    );
  };

  return (
    <div className="grid grid-cols-12 gap-3 sm:gap-4">
      <div className="col-span-12 grid grid-cols-2 gap-3 sm:gap-4 md:grid-cols-3 2xl:grid-cols-6">
        <StatsGanancia g={g} conMedia={false} />
        <Stat rotulo="Desde el inicio" valor={dinero(r.total.ganancia, { signo: true })} signo={signoDe(r.total.ganancia)}
              sub={`${cifra(r.total.pct, 2, true)} % · desde el ${dia(g.inicio_utc)}`} />
        <Stat rotulo="Días en positivo" valor={`${r.dias_positivos} de ${r.dias_completos}`}
              sub={r.racha.dias ? `racha: ${r.racha.dias} ${r.racha.dias === 1 ? "día" : "días"} ${r.racha.signo > 0 ? "ganando" : r.racha.signo < 0 ? "perdiendo" : "planos"}` : "sin días completos"} />
        <Stat rotulo="Media por día" valor={valido(r.media_dia) ? dinero(r.media_dia, { signo: true }) : "—"} signo={signoDe(r.media_dia)}
              sub={r.mejor_dia ? `mejor ${dia(fechaLocal(r.mejor_dia.fecha))}: ${dinero(r.mejor_dia.ganancia, { signo: true })}` : "hace falta un día completo"} />
      </div>

      <Panel titulo="Ganancia por día" icono={<ChartColumn />} className="col-span-12 xl:col-span-8" cuerpo="p-0"
        acciones={<Segmentado etiqueta="Días" valor={String(prefs.dias)} alCambiar={(v) => poner("dias", Number(v) as Prefs["dias"])}
          opciones={[{ valor: "14", etiqueta: "14D" }, { valor: "30", etiqueta: "30D" }, { valor: "90", etiqueta: "90D" }, { valor: "0", etiqueta: "Todo" }]} />}>
        <GraficaDias barras={barras} referencia={ref} etiquetaReferencia="medido" tema={tema} alto={300} lectura={lecturaDia} />
        <p className="border-t border-borde px-4 py-2.5 text-xs text-texto-3">
          Verde, días que ganó; rojo, días que perdió; la de hoy, más clara, sigue abierta. Cuenta desde tu medianoche ({g.zona}).
          {n ? ` La línea discontinua es lo que ${n.nombre} ganó de media al día en la prueba, con tu patrimonio de hoy.` : ""}
        </p>
      </Panel>
      <div className="col-span-12 xl:col-span-4">
        <LoMedido e={e} g={g} />
      </div>

      <Panel titulo="Calendario" icono={<CalendarDays />} className="col-span-12 lg:col-span-6"
        acciones={<div className="flex items-center gap-1.5">
          <Boton variante="fantasma" className="size-8 px-0" aria-label="Mes anterior" disabled={mes <= primerDia.slice(0, 7)} onClick={() => moverMes(-1)}><ChevronLeft className="size-4" /></Boton>
          <span className="min-w-32 text-center text-[13px] font-semibold" aria-live="polite">{mayuscula(tituloMes)}</span>
          <Boton variante="fantasma" className="size-8 px-0" aria-label="Mes siguiente" disabled={mes >= hoy.slice(0, 7)} onClick={() => moverMes(1)}><ChevronRight className="size-4" /></Boton>
        </div>}>
        <Calendario anio={anio} mes={mm - 1} porDia={porDia} hoy={hoy} primerDia={primerDia} elegido={diaElegido} alElegir={setElegido} />
        <div className="mt-4 grid gap-1 border-t border-borde pt-3 text-[13px]">
          <p className="flex items-baseline justify-between gap-3">
            <span className="font-semibold">{mayuscula(diaSemana(fechaLocal(diaElegido)))}{diaElegido === hoy ? " (hoy)" : ""}</span>
            <span className={cx("num font-semibold", colorSigno(signoDe(dElegido?.ganancia)))}>{dElegido ? dinero(dElegido.ganancia, { signo: true }) : "sin datos"}</span>
          </p>
          {dElegido && <p className="text-xs"><Reparto r={dElegido} /></p>}
          {grupoMes && (
            <p className="text-xs text-texto-3">
              Todo el mes: <span className={cx("num font-semibold", colorSigno(signoDe(grupoMes.ganancia)))}>{dinero(grupoMes.ganancia, { signo: true })}</span>
              {" "}({cifra(grupoMes.pct, 2, true)} %) · {grupoMes.dias_positivos} de {grupoMes.dias} días en positivo
            </p>
          )}
        </div>
      </Panel>
      <div className="col-span-12 grid content-start gap-3 sm:gap-4 lg:col-span-6">
        <Panel titulo="De dónde sale" icono={<Split />} className="" acciones={<span className="text-xs text-texto-3">{tituloMes}</span>}>
          <Origen m={grupoMes} titulo={tituloMes} />
        </Panel>
        <Panel titulo="Por mes" icono={<Table2 />} cuerpo="p-0">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[420px] text-[13px] whitespace-nowrap">
              <thead>
                <tr className="text-left text-[11px] text-texto-3">
                  {["Mes", "Ganancia", "", "%", "Días +"].map((t, i) => (
                    <th key={i} className={cx("px-4 py-2.5 font-medium", i > 0 && i !== 2 && "text-right")}>{t}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(() => {
                  const tope = Math.max(0.01, ...g.meses.map((x) => Math.abs(x.ganancia)));
                  return [...g.meses].reverse().map((x) => (
                    <tr key={x.clave} className="border-t border-borde hover:bg-panel-2/60" title={valido(x.financiacion) ? `financiación ${cifra(x.financiacion, 2, true)} · comisiones ${cifra(-(x.comisiones ?? 0), 2, true)} · mejor día ${dia(fechaLocal(x.mejor.fecha))} ${cifra(x.mejor.ganancia, 2, true)}` : undefined}>
                      <td className="px-4 py-2.5 font-medium">{mayuscula(mesLargo(fechaLocal(x.clave + "-01")))}{x.clave === hoy.slice(0, 7) && <span className="ml-2 text-[11px] text-texto-3">en curso</span>}</td>
                      <td className={cx("num px-4 py-2.5 text-right font-semibold", colorSigno(signoDe(x.ganancia)))}>{dinero(x.ganancia, { signo: true })}</td>
                      <td className="w-28 px-2 py-2.5">
                        <div className="relative h-2">
                          <div className="absolute inset-y-[-3px] left-1/2 w-px bg-borde-2" />
                          <div className={cx("absolute inset-y-0", x.ganancia >= 0 ? "left-1/2 rounded-r bg-sube-marca" : "right-1/2 rounded-l bg-baja-marca")}
                               style={{ width: `${(Math.abs(x.ganancia) / tope) * 50}%` }} />
                        </div>
                      </td>
                      <td className="num px-4 py-2.5 text-right text-texto-2">{cifra(x.pct, 2, true)} %</td>
                      <td className="num px-4 py-2.5 text-right">{x.dias_positivos}/{x.dias}</td>
                    </tr>
                  ));
                })()}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}
