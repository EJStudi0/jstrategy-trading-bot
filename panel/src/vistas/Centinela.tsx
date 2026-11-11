// Centinela: el segundo bot. Solo Bitcoin, al contado y sin deuda: o tiene BTC o tiene efectivo.
// Corre aparte de Jorge, con su propia cartera simulada; aquí se ve y se enciende o apaga.
import { Activity, Bitcoin, ListOrdered, Power, ScrollText, TriangleAlert, Wallet } from "lucide-react";
import { useMemo } from "react";
import { useConfirmar } from "../componentes/Dialogo";
import { Boton, Chip, Interruptor, Panel, PuntoEstado, Segmentado, Stat, Vacio, cx } from "../componentes/ui";
import { GraficaPatrimonio, type PuntoP } from "../graficas/GraficaPatrimonio";
import { usePonerCentinela } from "../hooks/datos";
import { cifra, cuando, dinero, pct, pctFraccion, precio, signoDe, valido } from "../lib/formato";
import type { Prefs } from "../lib/prefs";
import type { Centinela as TCentinela, PuntoCurva } from "../tipos";

function Encendido({ c }: { c: TCentinela }) {
  const confirmar = useConfirmar();
  const poner = usePonerCentinela();
  const cambiar = async () => {
    if (poner.isPending) return;
    const ok = await confirmar(c.encendido
      ? { titulo: "¿Apagar Centinela?", texto: "Deja de comprar y vender. No vende lo que tenga: conserva la posición tal cual hasta que lo enciendas. Jorge no se toca.", si: "Apagar" }
      : { titulo: "¿Encender Centinela?", texto: "Vuelve a operar en su próxima decisión (al cierre de cada hora), con dinero ficticio. Jorge no se toca.", si: "Encender" });
    if (ok) poner.mutate(!c.encendido);
  };
  const estado = !c.en_marcha ? "error" : c.encendido ? "ok" : "viejo";
  const texto = !c.en_marcha ? "Su proceso no está corriendo" : c.encendido ? "Encendido y operando" : "Apagado: no opera";
  return (
    <Panel titulo="Centinela" icono={<Bitcoin />} className="col-span-12 xl:col-span-4"
      acciones={<Chip tono="acento">{c.modo === "real-demo" ? "DEMO BITGET" : "SIMULACIÓN"}</Chip>}>
      <div className="grid gap-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="flex items-center gap-2.5 text-sm font-semibold" role="status">
            <PuntoEstado estado={estado} />{texto}
          </span>
          <Boton variante={c.encendido ? "normal" : "primario"} onClick={cambiar} disabled={poner.isPending}>
            <Power className="size-4" />{c.encendido ? "Apagar" : "Encender"}
          </Boton>
        </div>
        {poner.isError && <p role="alert" className="text-sm text-baja">No se pudo: {(poner.error as Error).message}</p>}
        <p className="text-xs leading-relaxed text-texto-3">
          Solo Bitcoin, al contado y sin deuda. Sigue la tendencia: entra cuando sube con fuerza y sale a efectivo cuando no.
          Decide una vez por hora. Es independiente de Jorge: cada uno con su cartera y su interruptor (el de Jorge está en Mando).
        </p>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 border-t border-borde pt-3 text-xs">
          <dt className="text-texto-3">Última decisión</dt>
          <dd className="num text-right text-texto-2">{c.latido_utc ? cuando(c.latido_utc) : "—"}</dd>
          <dt className="text-texto-3">Próxima</dt>
          <dd className="num text-right text-texto-2">{c.proxima_decision_utc ? cuando(c.proxima_decision_utc) : "—"}</dd>
          <dt className="text-texto-3">Datos</dt>
          <dd className="text-right text-texto-2">
            {c.fuente || "—"}{valido(c.horas_retraso) && c.horas_retraso >= 1 ? ` · ${cifra(c.horas_retraso, 0)} h de retraso` : ""}
          </dd>
        </dl>
        {c.cortafuegos_hasta_utc && (
          <p className="flex items-center gap-2 rounded-lg border border-aviso/30 bg-aviso/10 px-3 py-2 text-xs">
            <TriangleAlert className="size-4 shrink-0 text-aviso" />Cortafuegos activo: en efectivo hasta {cuando(c.cortafuegos_hasta_utc)}.
          </p>
        )}
      </div>
    </Panel>
  );
}

function Decision({ c }: { c: TCentinela }) {
  return (
    <Panel titulo="Qué ve y qué decide" icono={<ScrollText />} className="col-span-12 xl:col-span-4">
      <div className="grid gap-3 text-[13px]">
        <div className="flex flex-wrap items-center gap-2">
          {c.regimen && <Chip>{c.regimen}</Chip>}
          {c.accion && <Chip tono={c.accion === "mantener" ? "neutro" : "acento"}>{c.accion}</Chip>}
        </div>
        {c.explicacion?.length ? (
          <ul className="grid gap-1.5 text-xs leading-relaxed text-texto-2">
            {c.explicacion.map((x) => <li key={x}>{x}</li>)}
          </ul>
        ) : <p className="text-xs text-texto-3">Todavía no ha decidido nada.</p>}
        {(c.notas ?? []).map((x) => (
          <p key={x} className="flex items-center gap-2 text-xs text-aviso"><TriangleAlert className="size-3.5 shrink-0" />{x}</p>
        ))}
      </div>
    </Panel>
  );
}

function Operaciones({ c }: { c: TCentinela }) {
  const ops = c.operaciones ?? [];
  return (
    <Panel titulo="Operaciones" icono={<ListOrdered />} className="col-span-12 xl:col-span-4" cuerpo="p-0"
      acciones={<span className="text-xs text-texto-3">{c.n_operaciones ?? 0} en total</span>}>
      {!ops.length ? <Vacio>Aún no ha operado. Está en efectivo esperando tendencia.</Vacio> : (
        <div className="overflow-x-auto px-4 py-2">
          <table className="w-full text-[13px]">
            <tbody>
              {ops.map((o, k) => (
                <tr key={k} className={cx(k > 0 && "border-t border-borde/70")}>
                  <td className="num py-1.5 pr-4 text-xs text-texto-3">{cuando(o.utc)}</td>
                  <td className={cx("py-1.5 pr-4 font-semibold", o.lado === "buy" ? "text-sube" : "text-baja")}>{o.lado === "buy" ? "Compra" : "Venta"}</td>
                  <td className="num py-1.5 pr-4 text-right">{dinero(o.cantidad * o.precio)}</td>
                  <td className="num py-1.5 text-right text-texto-2 sm:pr-4">a {precio(o.precio)}</td>
                  <td className="num hidden py-1.5 text-right text-texto-3 sm:table-cell">{dinero(o.comision, { decimales: 3 })}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

export function Centinela({ c, curva, prefs, poner, tema }: {
  c: TCentinela | undefined; curva: PuntoCurva[] | undefined; prefs: Prefs;
  poner: <K extends keyof Prefs>(k: K, v: Prefs[K]) => void; tema: string;
}) {
  const puntos = useMemo<PuntoP[]>(
    () => (curva ?? []).map((x) => ({ t: Date.parse(x.utc), v: x.patrimonio, neto: x.neto, btc: x.btc })),
    [curva],
  );
  if (!c) return <Vacio>Cargando Centinela…</Vacio>;
  if (!c.instalado) {
    return (
      <Panel titulo="Centinela" icono={<Bitcoin />}>
        <Vacio>Centinela todavía no ha arrancado en este servidor. Jorge funciona igual.</Vacio>
      </Panel>
    );
  }
  return (
    <div className="grid grid-cols-12 gap-3 sm:gap-4">
      {(c.avisos ?? []).length > 0 && (
        <div className="col-span-12 grid gap-2">
          {(c.avisos ?? []).map((a) => (
            <p key={a.utc + a.texto} className="flex items-center gap-3 rounded-lg border border-aviso/30 bg-aviso/10 px-3.5 py-2.5 text-[13px]">
              <TriangleAlert className="size-4 shrink-0 text-aviso" />
              <span className="flex-1 break-words">{a.texto}</span>
              <time className="num shrink-0 text-xs text-texto-3">{cuando(a.utc)}</time>
            </p>
          ))}
        </div>
      )}
      <Encendido c={c} />
      <div className="col-span-12 grid grid-cols-2 gap-3 sm:gap-4 xl:col-span-8 xl:grid-cols-4">
        <Stat rotulo="Patrimonio" icono={<Wallet />} destacado valor={dinero(c.patrimonio)}
          sub={<>empezó con {dinero(c.capital, { decimales: 0 })}</>} />
        <Stat rotulo="Ganancia" signo={signoDe(c.ganancia)} valor={dinero(c.ganancia, { signo: true })}
          sub={<>{pct(c.ganancia_pct, 2, true)} · bajo su máximo {pct(c.caida_pct, 1)}</>} />
        <Stat rotulo="En Bitcoin" icono={<Bitcoin />} valor={pctFraccion(c.peso, 0)}
          sub={<>objetivo {pctFraccion(c.objetivo, 0)} · {cifra(c.btc, 5)} BTC</>} />
        <Stat rotulo="Bitcoin" valor={precio(c.precio)} sub={<>en efectivo {dinero(c.efectivo, { decimales: 0 })}</>} />
      </div>

      <Panel titulo="Evolución del patrimonio" icono={<Activity />} className="col-span-12" cuerpo="p-0 flex flex-col"
        acciones={<>
          <Segmentado etiqueta="Periodo" valor={String(prefs.horas)} alCambiar={(v) => poner("horas", Number(v) as Prefs["horas"])}
            opciones={[{ valor: "24", etiqueta: "24H" }, { valor: "168", etiqueta: "7D" }, { valor: "720", etiqueta: "30D" }, { valor: "0", etiqueta: "Todo" }]} />
          <Interruptor marcado={prefs.vsBtc} alCambiar={(v) => poner("vsBtc", v)} etiqueta="vs BTC" />
        </>}>
        <GraficaPatrimonio puntos={puntos} comparar={prefs.vsBtc} tema={tema} />
        <p className="border-t border-borde px-4 py-2.5 text-xs text-texto-3">
          Lo medido: con los datos hasta 2024, <span className="num text-texto-2">+46 %</span>{" "}al año con una peor caída del{" "}
          <span className="num text-baja">−26 %</span>. En la prueba posterior (2025 → nov 2026),{" "}
          <span className="num text-texto-2">≈ 0 %</span>: sin tendencia alcista se queda en efectivo. Gana a rachas; no es una promesa.
        </p>
      </Panel>

      <Decision c={c} />
      <Operaciones c={c} />
      <Panel titulo="Los dos bots" icono={<Power />} className="col-span-12 xl:col-span-4">
        <p className="text-xs leading-relaxed text-texto-2">
          Jorge reparte entre diez monedas con base cubierta y cobra financiación; Centinela solo sigue la tendencia de Bitcoin.
          No comparten dinero: lo que gana o pierde uno no mueve al otro, y apagar uno no toca al otro.
        </p>
      </Panel>
    </div>
  );
}
