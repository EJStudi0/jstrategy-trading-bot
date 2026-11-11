// Sub-pestaña «Operar»: la cuenta manual (dinero ficticio), aparte de la del bot.
import { Coins, History, ListChecks, TriangleAlert, Wallet } from "lucide-react";
import { useState } from "react";
import { Chip, Cifra, Panel, Stat, Vacio, cx } from "../../componentes/ui";
import { useAbrirManual, useCerrarManual, useCerrarTodas, useMoverManual } from "../../hooks/datos";
import {
  MOTIVOS_CIERRE, distanciaPct, gananciaDeObjetivo, leerNumero, objetivoPorMultiplo, precioParaCasilla, riesgoDeStop, stopPara, stopPorPct,
} from "../../lib/asistente";
import { base, nombre } from "../../lib/derivados";
import { cifra, cuando, dinero, pct, precio, signoDe, valido } from "../../lib/formato";
import type { Asistente, CuentaManual, PosicionManual } from "../../tipos";
import { Atajos, BotonDosToques, BotonT, CASILLA, Campo, Resultado, mensaje, type Borrador, type PrecioDe } from "./comunes";

function Formulario({ as, b, setB, precioDe }: { as: Asistente; b: Borrador; setB: (b: Borrador) => void; precioDe: PrecioDe }) {
  const abrir = useAbrirManual();
  const [fallo, setFallo] = useState<string>();
  const m = as.manual;
  const px = precioDe(b.simbolo);
  const usdt = leerNumero(b.usdt);
  const stop = leerNumero(b.stop);
  const objetivo = leerNumero(b.objetivo);
  const riesgo = riesgoDeStop(b.lado, px, stop, usdt, m.patrimonio);
  const ganancia = gananciaDeObjetivo(b.lado, px, objetivo, usdt);
  const stopBueno = valido(px) && valido(stop) && b.lado * (px - stop) > 0;
  const stopAlReves = valido(px) && valido(stop) && !stopBueno;
  const objetivoAlReves = valido(px) && valido(objetivo) && !(b.lado * (objetivo - px) > 0);
  const sugerido = b.sugerido !== null && valido(px) ? stopPara({ precio: px, stop: b.sugerido }, b.lado) : null;
  const tope = m.palanca_max * Math.max(0, m.patrimonio);
  const poner = (cambios: Partial<Borrador>) => { setB({ ...b, ...cambios }); setFallo(undefined); if (!abrir.isPending) abrir.reset(); };
  const largo = b.lado === 1;

  const enviar = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (abrir.isPending) return;
    if (!valido(usdt)) return setFallo("Pon el importe: toca uno de los botones o escríbelo con números.");
    if (Number.isNaN(stop) || Number.isNaN(objetivo)) return setFallo("El stop y el objetivo son precios: solo números, o déjalos vacíos.");
    setFallo(undefined);
    abrir.mutate(
      { simbolo: b.simbolo, lado: b.lado, usdt, stop, objetivo, nota: b.nota.trim(), alerta: b.alerta },
      { onSuccess: () => setB({ ...b, stop: "", objetivo: "", nota: "", alerta: null, sugerido: null }) },
    );
  };

  return (
    <Panel titulo="Abrir una operación" icono={<Coins />} className="col-span-12 lg:order-1 lg:col-span-5" acciones={<Chip tono="acento">SIMULACIÓN</Chip>}>
      <form className="grid grid-cols-2 gap-3" onSubmit={enviar}>
        <Campo rotulo="Moneda">
          {/* Al cambiar de moneda los precios escritos ya no valen. */}
          <select className={CASILLA} value={b.simbolo} onChange={(ev) => poner({ simbolo: ev.target.value, stop: "", objetivo: "", alerta: null, sugerido: null })}>
            {as.monedas.map((s) => <option key={s} value={s}>{base(s)} · {nombre(s)}</option>)}
          </select>
        </Campo>
        <div className="grid min-w-0 gap-1 text-xs text-texto-2">
          <span>Dirección</span>
          <div className="grid h-10 grid-cols-2 gap-1 rounded-lg border border-borde-2 bg-panel-2 p-0.5" role="radiogroup" aria-label="Dirección">
            {([1, -1] as const).map((l) => (
              // El stop y el objetivo van a un lado u otro del precio según la dirección: al cambiarla se vacían.
              <button key={l} type="button" role="radio" aria-checked={b.lado === l} onClick={() => b.lado !== l && poner({ lado: l, stop: "", objetivo: "" })}
                className={cx("rounded-md text-[13px] font-semibold text-texto-3 transition-colors",
                  b.lado === l && (l === 1 ? "bg-sube-marca/15 text-sube shadow-[0_0_0_1px_var(--c-sube-marca)]" : "bg-baja-marca/15 text-baja shadow-[0_0_0_1px_var(--c-baja-marca)]"))}>
                {l === 1 ? "Largo" : "Corto"}
              </button>
            ))}
          </div>
        </div>
        <p className="col-span-2 -mt-1 text-xs text-texto-3">
          {base(b.simbolo)} ahora <span className="num text-texto-2">{valido(px) ? precio(px) : "sin precio"}</span>
          {" · "}{largo ? "largo: ganas si sube" : "corto: ganas si baja"}{b.alerta !== null && " · viene de un aviso"}
        </p>

        <div className="col-span-2 grid gap-1.5">
          <Campo rotulo="Importe (USDT)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="cuánto pones" value={b.usdt} onChange={(ev) => poner({ usdt: ev.target.value })} />
          </Campo>
          <Atajos etiqueta="Importes rápidos" alElegir={(v) => poner({ usdt: v })} opciones={[
            ...[50, 100, 250, 500].map((n) => ({ texto: String(n), valor: String(n) })),
            { texto: "10 %", valor: String(Math.max(0, Math.floor(m.patrimonio * 0.1))), titulo: "El 10 % de la cuenta manual" },
          ]} />
        </div>

        <div className="col-span-2 grid gap-1.5">
          <Campo rotulo="Stop: el precio al que se cierra sola si va mal (opcional)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin stop" value={b.stop} onChange={(ev) => poner({ stop: ev.target.value })} />
          </Campo>
          <Atajos etiqueta="Stop rápido" alElegir={(v) => poner({ stop: v })} opciones={[
            ...[1, 2, 3].map((n) => ({ texto: n + " %", valor: precioParaCasilla(stopPorPct(b.lado, px, n)), apagado: !valido(px), titulo: `A un ${n} % del precio de ahora` })),
            ...(b.sugerido !== null ? [{ texto: "Sugerido", valor: precioParaCasilla(sugerido), apagado: sugerido === null, titulo: "El stop que proponía el aviso" }] : []),
          ]} />
        </div>

        <div className="col-span-2 grid gap-1.5">
          <Campo rotulo="Objetivo: el precio al que se cierra sola si va bien (opcional)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin objetivo" value={b.objetivo} onChange={(ev) => poner({ objetivo: ev.target.value })} />
          </Campo>
          <Atajos etiqueta="Objetivo rápido" alElegir={(v) => poner({ objetivo: v })} opciones={[1, 2, 3].map((n) => ({
            texto: n + "× el riesgo", valor: precioParaCasilla(objetivoPorMultiplo(b.lado, px, stop, n)), apagado: !stopBueno,
            titulo: stopBueno ? `Ganar ${n} ${n === 1 ? "vez" : "veces"} lo que arriesgas` : "Primero pon un stop",
          }))} />
        </div>

        <Campo rotulo="Nota (opcional)" className="col-span-2">
          <input className={CASILLA} maxLength={200} autoComplete="off" placeholder="por qué la abres" value={b.nota} onChange={(ev) => poner({ nota: ev.target.value })} />
        </Campo>

        <div className="col-span-2 grid gap-1.5 rounded-lg border border-borde bg-panel-2/50 px-3 py-2.5 text-[13px] leading-relaxed" role="status">
          {stopAlReves ? (
            <p className="flex gap-2 text-aviso"><TriangleAlert className="mt-0.5 size-4 shrink-0" />Ese stop está del lado equivocado: en un {largo ? "largo va por debajo" : "corto va por encima"} del precio.</p>
          ) : riesgo ? (
            <p>
              Arriesgas ~<span className="num font-semibold text-baja">{cifra(riesgo.usdt, 2)} USDT</span>
              {valido(riesgo.pct) && <> (<span className="num">{pct(riesgo.pct, 2)}</span> de la cuenta)</>}
              {ganancia !== null ? <> para ganar ~<span className="num font-semibold text-sube">{cifra(ganancia, 2)} USDT</span>.</> : ". Sin objetivo: la cierras tú cuando quieras."}
            </p>
          ) : (
            <p className="flex gap-2 text-aviso"><TriangleAlert className="mt-0.5 size-4 shrink-0" />Sin stop no hay límite a lo que puede perder.{ganancia !== null && <> Ganarías ~{cifra(ganancia, 2)} USDT si llega al objetivo.</>}</p>
          )}
          {objetivoAlReves && <p className="flex gap-2 text-aviso"><TriangleAlert className="mt-0.5 size-4 shrink-0" />Ese objetivo está del lado equivocado: en un {largo ? "largo va por encima" : "corto va por debajo"} del precio.</p>}
          <p className="text-[11px] text-texto-3">Mínimo 5 USDT · tope abierto a la vez {dinero(tope, { decimales: 0 })} · comisión {pct(m.comision_pct, 2)} al entrar y al salir.</p>
        </div>

        <button type="submit" disabled={abrir.isPending}
          className={cx("col-span-2 min-h-13 rounded-xl border px-3 py-2 text-[15px] font-semibold text-white transition hover:brightness-110 active:scale-[0.99] disabled:opacity-50",
            largo ? "border-sube-marca bg-sube-marca claro:border-sube claro:bg-sube" : "border-baja-marca bg-baja-marca claro:border-baja claro:bg-baja")}>
          {abrir.isPending ? "Abriendo…" : <>Abrir {largo ? "largo" : "corto"} de {base(b.simbolo)}{valido(usdt) && <> · <span className="num">{cifra(usdt, usdt % 1 ? 2 : 0)} USDT</span></>}</>}
        </button>
        <p className="col-span-2 min-h-4 text-xs break-words">
          {fallo ? <span role="alert" className="text-baja">{fallo}</span>
            : abrir.isError ? <span role="alert" className="text-baja">No se abrió: {mensaje(abrir.error)}</span>
            : <Resultado m={abrir} ok="Abierta. La tienes en «Abiertas»." /> }
          {!fallo && !abrir.isError && !abrir.isSuccess && !abrir.isPending && <span className="text-texto-3">Dinero ficticio: no toca al bot ni a Centinela.</span>}
        </p>
      </form>
    </Panel>
  );
}

type Cerrar = ReturnType<typeof useCerrarManual>;
type Mover = ReturnType<typeof useMoverManual>;

function Posicion({ p, cerrar, mover, ocupado }: { p: PosicionManual; cerrar: Cerrar; mover: Mover; ocupado: boolean }) {
  const [editando, setEditando] = useState(false);
  const [stop, setStop] = useState("");
  const [objetivo, setObjetivo] = useState("");
  const [fallo, setFallo] = useState<string>();
  const ganando = valido(p.precio) && p.lado * (p.precio - p.entrada) > 0;
  const stopEnEntrada = valido(p.stop) && Math.abs(p.stop - p.entrada) <= Math.abs(p.entrada) * 1e-9;
  const alStop = distanciaPct(p.precio, p.stop);
  const alObjetivo = distanciaPct(p.precio, p.objetivo);

  const abrirEdicion = () => {
    setStop(precioParaCasilla(p.stop));
    setObjetivo(precioParaCasilla(p.objetivo));
    setFallo(undefined);
    setEditando(!editando);
  };
  const guardar = (ev: React.FormEvent) => {
    ev.preventDefault();
    const s = leerNumero(stop);
    const o = leerNumero(objetivo);
    if (Number.isNaN(s) || Number.isNaN(o)) return setFallo("Escribe los precios solo con números, o deja la casilla vacía para quitarlo.");
    setFallo(undefined);
    mover.mutate({ id: p.id, stop: s, objetivo: o }, { onSuccess: () => setEditando(false) });
  };
  // El error del servidor, solo en la operación que lo causó.
  const error = fallo
    ?? (mover.isError && mover.variables?.id === p.id ? "No se cambió: " + mensaje(mover.error) : undefined)
    ?? (cerrar.isError && cerrar.variables?.id === p.id ? "No se cerró: " + mensaje(cerrar.error) : undefined);
  const enviando = (cerrar.isPending && cerrar.variables?.id === p.id) || (mover.isPending && mover.variables?.id === p.id);

  return (
    <li className="grid gap-2.5 px-4 py-3.5">
      <div className="flex min-w-0 items-start justify-between gap-3">
        <div className="grid min-w-0 gap-1">
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-[15px] font-semibold">{base(p.simbolo)}</span>
            <Chip tono={p.lado === 1 ? "sube" : "baja"} className="h-5">{p.lado === 1 ? "Largo" : "Corto"}</Chip>
          </span>
          <span className="num text-xs text-texto-3">{dinero(p.usdt, { decimales: 0 })} · entró a {precio(p.entrada)}</span>
        </div>
        <div className="grid shrink-0 justify-items-end">
          <Cifra valor={p.no_realizado} signo colorear className="text-xl leading-tight font-semibold tracking-tight" />
          <Cifra valor={p.pct} tipo="pct" decimales={2} signo colorear className="text-xs" />
        </div>
      </div>
      <dl className="grid grid-cols-3 gap-2 text-xs">
        <div className="grid min-w-0 gap-0.5 rounded-lg bg-panel-2/60 px-2.5 py-1.5">
          <dt className="text-[11px] text-texto-3">Ahora</dt>
          <dd className="num truncate text-texto">{precio(p.precio)}</dd>
        </div>
        <div className="grid min-w-0 gap-0.5 rounded-lg bg-panel-2/60 px-2.5 py-1.5">
          <dt className="text-[11px] text-texto-3">Stop</dt>
          <dd className="num truncate text-texto">{valido(p.stop) ? precio(p.stop) : <span className="text-aviso">no tiene</span>}</dd>
          {valido(alStop) && <dd className="num text-[11px] text-baja">a {pct(Math.abs(alStop), 1)}</dd>}
        </div>
        <div className="grid min-w-0 gap-0.5 rounded-lg bg-panel-2/60 px-2.5 py-1.5">
          <dt className="text-[11px] text-texto-3">Objetivo</dt>
          <dd className="num truncate text-texto">{valido(p.objetivo) ? precio(p.objetivo) : <span className="text-texto-3">no tiene</span>}</dd>
          {valido(alObjetivo) && <dd className="num text-[11px] text-sube">a {pct(Math.abs(alObjetivo), 1)}</dd>}
        </div>
      </dl>
      <p className="text-[11px] break-words text-texto-3">
        Abierta {cuando(p.abierta_utc)} · comisiones {dinero(p.comisiones)}
        {Math.abs(p.financiacion) >= 0.005 && <> · financiación <Cifra valor={p.financiacion} signo colorear /></>}
        {p.nota && <> · «{p.nota}»</>}
      </p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <BotonDosToques disabled={ocupado} confirma="¿Seguro? Cerrar" alConfirmar={() => cerrar.mutate({ id: p.id, parte: 1 })}>Cerrar</BotonDosToques>
        <BotonDosToques disabled={ocupado} confirma="¿Seguro? Mitad" alConfirmar={() => cerrar.mutate({ id: p.id, parte: 0.5 })}>Cerrar mitad</BotonDosToques>
        <BotonT disabled={ocupado || !ganando || stopEnEntrada}
          title={stopEnEntrada ? "El stop ya está en la entrada" : ganando ? "Sube el stop al precio de entrada: ya no puede acabar en pérdida (salvo comisiones)" : "Solo se puede cuando va en ganancia"}
          onClick={() => mover.mutate({ id: p.id, stop: p.entrada, objetivo: p.objetivo })}>
          Stop a entrada
        </BotonT>
        <BotonT variante={editando ? "primario" : "normal"} aria-expanded={editando} onClick={abrirEdicion}>Cambiar</BotonT>
      </div>
      {!ganando && !stopEnEntrada && <p className="text-[11px] text-texto-3">«Stop a entrada» se enciende cuando la operación va en ganancia.</p>}
      {editando && (
        <form className="grid grid-cols-2 gap-2 rounded-lg border border-borde bg-panel-2/40 p-3" onSubmit={guardar}>
          <Campo rotulo="Stop (vacío = quitarlo)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin stop" value={stop} onChange={(ev) => setStop(ev.target.value)} />
          </Campo>
          <Campo rotulo="Objetivo (vacío = quitarlo)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin objetivo" value={objetivo} onChange={(ev) => setObjetivo(ev.target.value)} />
          </Campo>
          <BotonT type="submit" variante="primario" disabled={ocupado}>Guardar</BotonT>
          <BotonT onClick={() => setEditando(false)}>Cancelar</BotonT>
        </form>
      )}
      {enviando && <p role="status" className="text-xs text-texto-3">Enviando…</p>}
      {error && <p role="alert" className="text-xs break-words text-baja">{error}</p>}
    </li>
  );
}

function Abiertas({ m }: { m: CuentaManual }) {
  const cerrar = useCerrarManual();
  const mover = useMoverManual();
  const todas = useCerrarTodas();
  const ocupado = cerrar.isPending || mover.isPending || todas.isPending;
  const total = m.posiciones.reduce((s, p) => s + p.no_realizado, 0);
  return (
    <Panel titulo={`Abiertas (${m.posiciones.length})`} icono={<ListChecks />} className="col-span-12 lg:order-2 lg:col-span-7" cuerpo="p-0">
      {(m.posiciones.length > 0 || todas.isSuccess || cerrar.isSuccess || mover.isSuccess) && (
        <div className="flex min-h-14 flex-wrap items-center justify-between gap-x-3 gap-y-2 border-b border-borde px-4 py-2">
          <span className="text-[13px] text-texto-2">
            {m.posiciones.length > 0 && <>Van <Cifra valor={total} signo colorear className="font-semibold" /> entre todas</>}
            <Resultado m={todas} className="ml-2" /><Resultado m={cerrar} ok="Cerrada" className="ml-2" /><Resultado m={mover} ok="Cambiado" className="ml-2" />
          </span>
          {m.posiciones.length > 1 && (
            <BotonDosToques disabled={ocupado} confirma={`¿Seguro? Cerrar las ${m.posiciones.length}`} alConfirmar={() => todas.mutate({})}>Cerrar todas</BotonDosToques>
          )}
        </div>
      )}
      {!m.posiciones.length ? <Vacio>No tienes ninguna operación abierta en la cuenta manual.</Vacio> : (
        <ul className="divide-y divide-borde/70">
          {m.posiciones.map((p) => <Posicion key={p.id} p={p} cerrar={cerrar} mover={mover} ocupado={ocupado} />)}
        </ul>
      )}
    </Panel>
  );
}

function Cerradas({ m }: { m: CuentaManual }) {
  const [todas, setTodas] = useState(false);
  const lista = todas ? m.cerradas : m.cerradas.slice(0, 5);
  return (
    <Panel titulo="Últimas cerradas" icono={<History />} className="col-span-12 lg:order-3" cuerpo="p-0"
      acciones={<span className="text-xs text-texto-3">{m.operaciones} en total</span>}>
      {!lista.length ? <Vacio>Todavía no has cerrado ninguna operación.</Vacio> : (
        <div className="px-4 py-2">
          <table className="w-full table-fixed text-[13px] sm:table-auto">
            <thead className="sr-only sm:not-sr-only">
              <tr className="text-left text-[11px] text-texto-3">
                <th className="py-1.5 pr-3 font-medium">Operación</th>
                <th className="hidden py-1.5 pr-3 font-medium md:table-cell">Importe</th>
                <th className="hidden py-1.5 pr-3 font-medium md:table-cell">Entrada → salida</th>
                <th className="py-1.5 pr-3 font-medium">Cómo acabó</th>
                <th className="py-1.5 text-right font-medium">Neto</th>
              </tr>
            </thead>
            <tbody>
              {lista.map((c, k) => (
                <tr key={c.id + "-" + c.cerrada_utc + "-" + k} className={cx(k > 0 && "border-t border-borde/70")}>
                  <td className="py-2 pr-3">
                    <span className="font-semibold">{base(c.simbolo)}</span>{" "}
                    <span className={c.lado === 1 ? "text-sube" : "text-baja"}>{c.lado === 1 ? "largo" : "corto"}</span>
                  </td>
                  <td className="num hidden py-2 pr-3 text-texto-2 md:table-cell">{dinero(c.usdt, { decimales: 0 })}</td>
                  <td className="num hidden py-2 pr-3 text-texto-2 md:table-cell">{precio(c.entrada)} → {precio(c.salida)}</td>
                  <td className="py-2 pr-3 text-xs break-words text-texto-2">
                    <span className={cx(c.motivo === "liquidada" && "text-baja")}>{MOTIVOS_CIERRE[c.motivo] ?? c.motivo}</span>
                    <span className="block text-[11px] text-texto-3">{cuando(c.cerrada_utc)}</span>
                  </td>
                  <td className="py-2 text-right"><Cifra valor={c.neto} signo colorear className="font-semibold" /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.cerradas.length > 5 && (
            <BotonT variante="fantasma" className="mt-1 w-full" onClick={() => setTodas(!todas)}>
              {todas ? "Ver menos" : `Ver las ${m.cerradas.length} últimas`}
            </BotonT>
          )}
        </div>
      )}
    </Panel>
  );
}

export function Operar({ as, b, setB, precioDe }: { as: Asistente; b: Borrador; setB: (b: Borrador) => void; precioDe: PrecioDe }) {
  const m = as.manual;
  return (
    <div className="grid grid-cols-12 items-start gap-3 sm:gap-4">
      <div className="col-span-12 flex flex-wrap items-center justify-between gap-2 px-1">
        <h2 className="rotulo">Cuenta manual · aparte de la del bot</h2>
        <Chip tono="acento">SIMULACIÓN · dinero ficticio</Chip>
      </div>
      <div className="col-span-12 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4">
        <Stat rotulo="Patrimonio" icono={<Wallet />} destacado valor={dinero(m.patrimonio)}
          sub={<>empezó con {dinero(m.capital_inicial, { decimales: 0 })}</>} />
        <Stat rotulo="Ganancia" signo={signoDe(m.ganancia)} valor={dinero(m.ganancia, { signo: true })}
          sub={<>{pct(m.ganancia_pct, 2, true)} · ficticia</>} />
        <Stat rotulo="Operaciones" valor={cifra(m.operaciones, 0)}
          sub={<>cerradas · {m.posiciones.length} {m.posiciones.length === 1 ? "abierta" : "abiertas"}</>} />
        <Stat rotulo="Acierto" valor={valido(m.acierto_pct) ? pct(m.acierto_pct, 0) : "—"}
          sub={valido(m.acierto_pct) ? "de las cerradas, en ganancia" : "aún no hay cerradas"} />
      </div>
      {/* En el móvil, lo que ya está abierto va antes que el formulario: es lo que hay que poder cerrar rápido. */}
      {m.posiciones.length > 0 && <Abiertas m={m} />}
      <Formulario as={as} b={b} setB={setB} precioDe={precioDe} />
      {m.posiciones.length === 0 && <Abiertas m={m} />}
      <Cerradas m={m} />
    </div>
  );
}
