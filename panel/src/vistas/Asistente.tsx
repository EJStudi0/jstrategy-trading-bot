// Asistente: avisa de los patrones que ve en las diez monedas, deja operar a mano en una cuenta
// aparte (simulada) y dar órdenes sobre monedas sueltas al bot. Avisa; no opera por su cuenta.
import { ArrowDownRight, ArrowUpRight, BellRing, ChevronDown, Coins, Hand, History, ListChecks, Minus, Trophy, Wallet } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { useConfirmar } from "../componentes/Dialogo";
import { Boton, Chip, Cifra, Panel, Segmentado, Stat, Vacio, colorSigno, cx } from "../componentes/ui";
import { useAbrirManual, useCerrarManual, useMarcarVistas, useMoverManual, usePonerVeto } from "../hooks/datos";
import {
  DURACIONES, MOTIVOS_CIERRE, VETOS, etiquetaFondo, etiquetaLado, etiquetaMovimiento, hastaCuando, importante, leerNumero,
  precioParaCasilla, riesgoDeStop, stopPara, type Duracion,
} from "../lib/asistente";
import { base, nombre } from "../lib/derivados";
import { cifra, cuando, dinero, pct, precio, signoDe, valido } from "../lib/formato";
import type { Alerta, Asistente as TAsistente, CuentaManual, Estado, ModoVeto, PosicionManual, Previo } from "../tipos";

/** Lo que hay escrito en el formulario de operar (texto tal cual, se convierte al enviar). */
interface Borrador {
  simbolo: string;
  lado: 1 | -1;
  usdt: string;
  stop: string;
  objetivo: string;
  nota: string;
  alerta: number | null;
}

// 16 px en el móvil: con letra más pequeña el teléfono amplía la página al tocar la casilla.
const CASILLA = "h-10 w-full min-w-0 rounded-lg border border-borde-2 bg-panel-2 px-3 text-base text-texto placeholder:text-texto-3 sm:h-9 sm:text-[13px]";
const mensaje = (e: unknown) => (e instanceof Error ? e.message : String(e));

function Campo({ rotulo, children, className }: { rotulo: string; children: ReactNode; className?: string }) {
  return (
    <label className={cx("grid min-w-0 gap-1 text-xs text-texto-2", className)}>
      {rotulo}
      {children}
    </label>
  );
}

function ChipLado({ lado }: { lado: number }) {
  const Icono = lado === 1 ? ArrowUpRight : lado === -1 ? ArrowDownRight : Minus;
  return <Chip tono={lado === 1 ? "sube" : lado === -1 ? "baja" : "neutro"}><Icono className="size-3" />{etiquetaLado(lado)}</Chip>;
}

const fraseOtrasVeces = (p: Previo | null | undefined) =>
  p && p.n > 0
    ? `Las otras ${p.n} veces este mes: ${pct(p.a_favor_pct, 0)} siguió a favor, media ${pct(p.media_pct, 2, true)} a 24 h.`
    : "Este mes no ha salido otras veces: no hay con qué comparar.";

// ── a. Avisos ────────────────────────────────────────────────────────────────

function TarjetaAviso({ a, as, nuevo, abierta, alAbrir, alOperar }: {
  a: Alerta; as: TAsistente; nuevo: boolean; abierta: boolean; alAbrir: () => void; alOperar: (a: Alerta, lado: 1 | -1) => void;
}) {
  const cat = as.catalogo[a.patron];
  const previo = a.previo ?? as.previo[a.patron];
  const seguido = valido(a.a_4h) || valido(a.a_24h);
  return (
    <li className={cx("rounded-xl border bg-panel-2/50", a.fuerza === "alta" ? "border-acento/50" : "border-borde-2")}>
      <button type="button" onClick={alAbrir} aria-expanded={abierta} className="grid w-full gap-1.5 p-3 text-left">
        <span className="flex min-w-0 items-baseline gap-2">
          {nuevo && <span className="size-2 shrink-0 self-center rounded-full bg-acento" title="Nuevo"><span className="sr-only">Nuevo: </span></span>}
          <span className="shrink-0 text-sm font-semibold">{base(a.simbolo)}</span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-texto-2">{cat?.nombre ?? a.patron}</span>
          <time className="num shrink-0 text-[11px] text-texto-3">{cuando(a.utc)}</time>
        </span>
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          <ChipLado lado={a.lado} />
          <Chip tono={a.fuerza === "alta" ? "acento" : "neutro"} className={cx(a.fuerza === "baja" && "text-texto-3")}>fuerza {a.fuerza}</Chip>
          <span className="num ml-auto text-[13px] text-texto-2">a {precio(a.precio)}</span>
          <ChevronDown className={cx("size-4 shrink-0 text-texto-3 transition-transform", abierta && "rotate-180")} />
        </span>
      </button>
      {abierta && (
        <div className="grid gap-2 border-t border-borde px-3 pt-2.5 pb-3 text-xs leading-relaxed text-texto-2">
          {cat && <p><span className="font-semibold text-texto">Qué es.</span> {cat.que}</p>}
          {cat && <p><span className="font-semibold text-texto">Lo medido.</span> {cat.medido}</p>}
          <p>{fraseOtrasVeces(previo)}</p>
          {a.lado !== 0 && (
            <p>
              <span className="font-semibold text-texto">Cómo le fue a este aviso.</span>{" "}
              {seguido ? (
                <>
                  {valido(a.a_4h) && <>a las 4 h <Cifra valor={a.a_4h} tipo="pct" signo colorear /></>}
                  {valido(a.a_4h) && valido(a.a_24h) && " · "}
                  {valido(a.a_24h) && <>a las 24 h <Cifra valor={a.a_24h} tipo="pct" signo colorear /></>}
                  {" "}(en positivo si fue hacia donde apuntaba).
                </>
              ) : "Todavía es pronto: se apunta a las 4 y a las 24 horas."}
            </p>
          )}
          {valido(a.stop) && (
            <p><span className="font-semibold text-texto">Stop sugerido.</span> <span className="num">{precio(a.stop)}</span> (a dos veces lo que se mueve normalmente).</p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <Boton variante={a.lado === 1 ? "primario" : "normal"} onClick={() => alOperar(a, 1)}><ArrowUpRight className="size-4" />Largo</Boton>
            <Boton variante={a.lado === -1 ? "primario" : "normal"} onClick={() => alOperar(a, -1)}><ArrowDownRight className="size-4" />Corto</Boton>
            <span className="min-w-0 flex-1 basis-40 text-[11px] text-texto-3">Abre el formulario ya relleno; no opera hasta que lo confirmes. Dinero ficticio.</span>
          </div>
        </div>
      )}
    </li>
  );
}

function Avisos({ as, nuevos, alOperar }: { as: TAsistente; nuevos: Set<number>; alOperar: (a: Alerta, lado: 1 | -1) => void }) {
  const [filtro, setFiltro] = useState<"importantes" | "todos">("importantes");
  const [abierta, setAbierta] = useState<number | null>(null);
  const [cuantos, setCuantos] = useState(12);
  const lista = filtro === "todos" ? as.alertas : as.alertas.filter(importante);
  const ocultos = as.alertas.length - lista.length;
  return (
    <Panel titulo="Avisos" icono={<BellRing />} className="col-span-12 xl:col-span-5" cuerpo="p-3"
      acciones={<Segmentado etiqueta="Qué avisos se ven" valor={filtro} alCambiar={setFiltro}
        opciones={[{ valor: "importantes", etiqueta: "Importantes", titulo: "Fuerza alta y media" }, { valor: "todos", etiqueta: "Todos" }]} />}>
      {!lista.length ? (
        <Vacio>
          {as.alertas.length
            ? `Ningún aviso importante por ahora. Hay ${ocultos} de fuerza baja en «Todos».`
            : "Sin avisos todavía. El asistente mira las diez monedas cada media hora."}
        </Vacio>
      ) : (
        <>
          <ul className="grid gap-2">
            {lista.slice(0, cuantos).map((a) => (
              <TarjetaAviso key={a.id} a={a} as={as} nuevo={nuevos.has(a.id)} abierta={abierta === a.id}
                alAbrir={() => setAbierta(abierta === a.id ? null : a.id)} alOperar={alOperar} />
            ))}
          </ul>
          {lista.length > cuantos && (
            <Boton variante="fantasma" className="mt-2 w-full" onClick={() => setCuantos(cuantos + 12)}>
              Ver más antiguos ({lista.length - cuantos})
            </Boton>
          )}
        </>
      )}
      <p className="mt-3 px-1 text-[11px] leading-relaxed text-texto-3">
        Un aviso no es una orden: el asistente no opera solo. Toca uno para ver qué es y cómo le ha ido otras veces.
      </p>
    </Panel>
  );
}

// ── b. Operar a mano ─────────────────────────────────────────────────────────

function Formulario({ as, b, setB, precioDe, refPanel }: {
  as: TAsistente; b: Borrador; setB: (b: Borrador) => void; precioDe: (s: string) => number | null;
  refPanel: React.RefObject<HTMLDivElement | null>;
}) {
  const abrir = useAbrirManual();
  const [fallo, setFallo] = useState<string>();
  const m = as.manual;
  const px = precioDe(b.simbolo);
  const usdt = leerNumero(b.usdt);
  const stop = leerNumero(b.stop);
  const objetivo = leerNumero(b.objetivo);
  const riesgo = riesgoDeStop(b.lado, px, stop, usdt, m.patrimonio);
  const stopAlReves = valido(px) && valido(stop) && !(b.lado * (px - stop) > 0);
  const tope = m.palanca_max * Math.max(0, m.patrimonio);
  const cambiar = <K extends keyof Borrador>(k: K, v: Borrador[K]) => { setB({ ...b, [k]: v }); setFallo(undefined); abrir.reset(); };

  const enviar = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (abrir.isPending) return;
    if (!valido(usdt)) return setFallo("Escribe el importe en USDT, solo con números.");
    if (Number.isNaN(stop) || Number.isNaN(objetivo)) return setFallo("El stop y el objetivo son precios: escríbelos solo con números, o déjalos vacíos.");
    setFallo(undefined);
    abrir.mutate(
      { simbolo: b.simbolo, lado: b.lado, usdt, stop, objetivo, nota: b.nota.trim(), alerta: b.alerta },
      { onSuccess: () => setB({ ...b, stop: "", objetivo: "", nota: "", alerta: null }) },
    );
  };

  return (
    <div ref={refPanel} className="col-span-12 scroll-mt-20 lg:col-span-5">
      <Panel titulo="Abrir una operación" icono={<Coins />} className="h-full" acciones={<Chip tono="acento">SIMULACIÓN</Chip>}>
        <form className="grid grid-cols-2 gap-3" onSubmit={enviar}>
          <Campo rotulo="Moneda">
            <select className={CASILLA} value={b.simbolo} onChange={(ev) => cambiar("simbolo", ev.target.value)}>
              {as.monedas.map((s) => <option key={s} value={s}>{base(s)} · {nombre(s)}</option>)}
            </select>
          </Campo>
          <div className="grid min-w-0 gap-1 text-xs text-texto-2">
            <span>Dirección</span>
            <div className="grid h-10 grid-cols-2 gap-1 rounded-lg border border-borde-2 bg-panel-2 p-0.5 sm:h-9" role="radiogroup" aria-label="Dirección">
              {([1, -1] as const).map((l) => (
                <button key={l} type="button" role="radio" aria-checked={b.lado === l} onClick={() => cambiar("lado", l)}
                  className={cx("rounded-md text-[13px] font-semibold text-texto-3 transition-colors",
                    b.lado === l && (l === 1 ? "bg-sube-marca/15 text-sube shadow-[0_0_0_1px_var(--c-sube-marca)]" : "bg-baja-marca/15 text-baja shadow-[0_0_0_1px_var(--c-baja-marca)]"))}>
                  {l === 1 ? "Largo" : "Corto"}
                </button>
              ))}
            </div>
          </div>
          <Campo rotulo="Importe (USDT)" className="col-span-2">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="p. ej. 200" value={b.usdt}
              onChange={(ev) => cambiar("usdt", ev.target.value)} />
          </Campo>
          <Campo rotulo="Stop (opcional)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="precio" value={b.stop}
              onChange={(ev) => cambiar("stop", ev.target.value)} />
          </Campo>
          <Campo rotulo="Objetivo (opcional)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="precio" value={b.objetivo}
              onChange={(ev) => cambiar("objetivo", ev.target.value)} />
          </Campo>
          <Campo rotulo="Nota (opcional)" className="col-span-2">
            <input className={CASILLA} maxLength={200} autoComplete="off" placeholder="por qué la abres" value={b.nota}
              onChange={(ev) => cambiar("nota", ev.target.value)} />
          </Campo>

          <div className="col-span-2 grid gap-1 text-xs leading-relaxed text-texto-3">
            <p>
              {base(b.simbolo)} ahora: <span className="num text-texto-2">{valido(px) ? precio(px) : "sin precio"}</span>
              {" · "}{b.lado === 1 ? "largo: ganas si sube" : "corto: ganas si baja"}
              {b.alerta !== null && " · viene de un aviso"}
            </p>
            {riesgo ? (
              <p className="text-texto-2">
                Si salta el stop pierdes ~<span className="num font-semibold text-baja">{cifra(riesgo.usdt, 2)} USDT</span>
                {valido(riesgo.pct) && <>, el <span className="num font-semibold text-baja">{pct(riesgo.pct, 2)}</span> de la cuenta</>}.
              </p>
            ) : stopAlReves ? (
              <p className="text-aviso">Ese stop queda del lado equivocado: en un {b.lado === 1 ? "largo va por debajo" : "corto va por encima"} del precio.</p>
            ) : (
              <p>Sin stop no hay límite a lo que puede perder esta operación.</p>
            )}
            <p>Mínimo 5 USDT · tope abierto a la vez {dinero(tope, { decimales: 0 })} · comisión {pct(m.comision_pct, 2)} al entrar y al salir.</p>
          </div>

          <div className="col-span-2 flex flex-wrap items-center gap-3">
            <Boton type="submit" variante="primario" disabled={abrir.isPending}>
              {abrir.isPending ? "Abriendo…" : `Abrir ${b.lado === 1 ? "largo" : "corto"} de ${base(b.simbolo)}`}
            </Boton>
            <span className="min-w-0 flex-1 basis-40 text-xs break-words" role="status">
              {fallo ? <span className="text-baja">{fallo}</span>
                : abrir.isError ? <span className="text-baja">No se abrió: {mensaje(abrir.error)}</span>
                : abrir.isSuccess ? <span className="text-sube">Abierta. La tienes abajo, en «Abiertas».</span>
                : <span className="text-texto-3">Dinero ficticio: no toca al bot ni a Centinela.</span>}
            </span>
          </div>
        </form>
      </Panel>
    </div>
  );
}

function Posicion({ p }: { p: PosicionManual }) {
  const confirmar = useConfirmar();
  const cerrar = useCerrarManual();
  const mover = useMoverManual();
  const [editando, setEditando] = useState(false);
  const [stop, setStop] = useState("");
  const [objetivo, setObjetivo] = useState("");
  const [fallo, setFallo] = useState<string>();
  const ocupado = cerrar.isPending || mover.isPending;
  const que = `${p.lado === 1 ? "largo" : "corto"} de ${base(p.simbolo)}`;

  const pedirCierre = async (parte: number) => {
    if (ocupado) return;
    const ok = await confirmar({
      titulo: parte >= 1 ? `¿Cerrar el ${que}?` : `¿Cerrar la mitad del ${que}?`,
      texto: <>Se cierra al precio de ahora. Va{" "}<Cifra valor={p.no_realizado * parte} signo colorear />{" "}antes de la comisión de salida. Dinero ficticio.</>,
      si: parte >= 1 ? "Cerrar todo" : "Cerrar la mitad",
    });
    if (ok) cerrar.mutate({ id: p.id, parte });
  };
  const abrirEdicion = () => {
    setStop(precioParaCasilla(p.stop));
    setObjetivo(precioParaCasilla(p.objetivo));
    setFallo(undefined);
    mover.reset();
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
  const error = fallo ?? (mover.isError ? "No se cambió: " + mensaje(mover.error) : cerrar.isError ? "No se cerró: " + mensaje(cerrar.error) : undefined);

  return (
    <li className="grid gap-2 px-4 py-3">
      <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
        <span className="text-sm font-semibold">{base(p.simbolo)}</span>
        <Chip tono={p.lado === 1 ? "sube" : "baja"} className="h-5">{p.lado === 1 ? "Largo" : "Corto"}</Chip>
        <span className="num text-xs text-texto-3">{dinero(p.usdt, { decimales: 0 })}</span>
        <span className="ml-auto text-right">
          <Cifra valor={p.no_realizado} signo colorear className="text-sm font-semibold" />
          <Cifra valor={p.pct} tipo="pct" decimales={2} signo colorear className="ml-2 text-xs" />
        </span>
      </div>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-texto-3 sm:grid-cols-4">
        <div className="flex justify-between gap-2"><dt>Entrada</dt><dd className="num text-texto-2">{precio(p.entrada)}</dd></div>
        <div className="flex justify-between gap-2"><dt>Ahora</dt><dd className="num text-texto-2">{precio(p.precio)}</dd></div>
        <div className="flex justify-between gap-2"><dt>Stop</dt><dd className="num text-texto-2">{valido(p.stop) ? precio(p.stop) : "sin stop"}</dd></div>
        <div className="flex justify-between gap-2"><dt>Objetivo</dt><dd className="num text-texto-2">{valido(p.objetivo) ? precio(p.objetivo) : "sin objetivo"}</dd></div>
      </dl>
      <p className="text-[11px] break-words text-texto-3">
        Abierta {cuando(p.abierta_utc)} · comisiones {dinero(p.comisiones)}
        {Math.abs(p.financiacion) >= 0.005 && <> · financiación <Cifra valor={p.financiacion} signo colorear /></>}
        {p.nota && <> · «{p.nota}»</>}
      </p>
      <div className="flex flex-wrap gap-2">
        <Boton className="h-8 px-3 text-xs" disabled={ocupado} onClick={() => pedirCierre(1)}>Cerrar todo</Boton>
        <Boton className="h-8 px-3 text-xs" disabled={ocupado} onClick={() => pedirCierre(0.5)}>Cerrar la mitad</Boton>
        <Boton className="h-8 px-3 text-xs" variante={editando ? "normal" : "fantasma"} aria-expanded={editando} onClick={abrirEdicion}>
          Cambiar stop u objetivo
        </Boton>
      </div>
      {editando && (
        <form className="grid grid-cols-2 gap-2 rounded-lg border border-borde bg-panel-2/40 p-3" onSubmit={guardar}>
          <Campo rotulo="Stop (vacío = quitarlo)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin stop" value={stop} onChange={(ev) => setStop(ev.target.value)} />
          </Campo>
          <Campo rotulo="Objetivo (vacío = quitarlo)">
            <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder="sin objetivo" value={objetivo} onChange={(ev) => setObjetivo(ev.target.value)} />
          </Campo>
          <div className="col-span-2 flex flex-wrap gap-2">
            <Boton type="submit" variante="primario" className="h-8 px-3 text-xs" disabled={mover.isPending}>Guardar</Boton>
            <Boton className="h-8 px-3 text-xs" onClick={() => setEditando(false)}>Cancelar</Boton>
          </div>
        </form>
      )}
      {error && <p role="alert" className="text-xs break-words text-baja">{error}</p>}
    </li>
  );
}

function Abiertas({ m }: { m: CuentaManual }) {
  const total = m.posiciones.reduce((s, p) => s + p.no_realizado, 0);
  return (
    <Panel titulo="Abiertas" icono={<ListChecks />} className="col-span-12 lg:col-span-7" cuerpo="p-0"
      acciones={m.posiciones.length > 0 && <span className="text-xs text-texto-3">van <Cifra valor={total} signo colorear /> en total</span>}>
      {!m.posiciones.length ? <Vacio>No tienes ninguna operación abierta en la cuenta manual.</Vacio> : (
        <ul className="divide-y divide-borde/70">
          {m.posiciones.map((p) => <Posicion key={p.id} p={p} />)}
        </ul>
      )}
    </Panel>
  );
}

function Cerradas({ m }: { m: CuentaManual }) {
  const [todas, setTodas] = useState(false);
  const lista = todas ? m.cerradas : m.cerradas.slice(0, 8);
  return (
    <Panel titulo="Últimas cerradas" icono={<History />} className="col-span-12" cuerpo="p-0"
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
                  <td className="py-1.5 pr-3">
                    <span className="font-semibold">{base(c.simbolo)}</span>{" "}
                    <span className={c.lado === 1 ? "text-sube" : "text-baja"}>{c.lado === 1 ? "largo" : "corto"}</span>
                  </td>
                  <td className="num hidden py-1.5 pr-3 text-texto-2 md:table-cell">{dinero(c.usdt, { decimales: 0 })}</td>
                  <td className="num hidden py-1.5 pr-3 text-texto-2 md:table-cell">{precio(c.entrada)} → {precio(c.salida)}</td>
                  <td className="py-1.5 pr-3 text-xs break-words text-texto-2">
                    <span className={cx(c.motivo === "liquidada" && "text-baja")}>{MOTIVOS_CIERRE[c.motivo] ?? c.motivo}</span>
                    <span className="block text-[11px] text-texto-3">{cuando(c.cerrada_utc)}</span>
                  </td>
                  <td className="py-1.5 text-right"><Cifra valor={c.neto} signo colorear className="font-semibold" /></td>
                </tr>
              ))}
            </tbody>
          </table>
          {m.cerradas.length > 8 && (
            <Boton variante="fantasma" className="mt-1 w-full" onClick={() => setTodas(!todas)}>
              {todas ? "Ver menos" : `Ver las ${m.cerradas.length} últimas`}
            </Boton>
          )}
        </div>
      )}
    </Panel>
  );
}

// ── c. Monedas: lo que el dueño manda sobre cada una ─────────────────────────

function Monedas({ as }: { as: TAsistente }) {
  const poner = usePonerVeto();
  const [duracion, setDuracion] = useState<Duracion>("0");
  const [porConfirmar, setPorConfirmar] = useState<string | null>(null);   // «Fuera» vende: segundo toque
  const horas = Number(duracion);
  const elegir = (simbolo: string, valor: string) => {
    poner.reset();
    if (valor === "cerrar") return setPorConfirmar(simbolo);
    setPorConfirmar(null);
    poner.mutate({ simbolo, modo: valor === "normal" ? null : (valor as ModoVeto), horas });
  };
  const confirmarFuera = (simbolo: string) => {
    setPorConfirmar(null);
    poner.mutate({ simbolo, modo: "cerrar", horas });
  };
  return (
    <Panel titulo="Monedas" icono={<Hand />} className="col-span-12 xl:col-span-7" cuerpo="p-0"
      acciones={<>
        <span className="text-xs text-texto-3">Lo que mandes dura</span>
        <Segmentado etiqueta="Cuánto dura lo que mandes" pequeno valor={duracion} alCambiar={setDuracion}
          opciones={DURACIONES.map((d) => ({ valor: d.valor, etiqueta: d.etiqueta }))} />
      </>}>
      <ul className="divide-y divide-borde/70">
        {as.monedas.map((s) => {
          const l = as.lectura[s];
          const v = as.vetos[s];
          const mov = etiquetaMovimiento(l?.movimiento);
          const pide = porConfirmar === s;
          return (
            <li key={s} className="grid gap-2 px-4 py-2.5">
              <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="w-11 shrink-0 text-sm font-semibold">{base(s)}</span>
                  {l ? (
                    <>
                      <Chip tono={l.fondo === 1 ? "sube" : l.fondo === -1 ? "baja" : "neutro"} className="h-5" titulo="Tendencia de fondo">{etiquetaFondo(l.fondo)}</Chip>
                      <Chip tono={mov === "movido" ? "aviso" : "neutro"} className="h-5" titulo="Cuánto se mueve frente a lo suyo normal">{mov}</Chip>
                    </>
                  ) : <span className="text-xs text-texto-3">sin lectura todavía</span>}
                </div>
                <select aria-label={`Qué hace el bot con ${base(s)}`} disabled={poner.isPending}
                  value={pide ? "cerrar" : v?.modo ?? "normal"} onChange={(ev) => elegir(s, ev.target.value)}
                  className={cx(CASILLA, "w-34 px-2", (v || pide) && "border-aviso/60 text-aviso")}>
                  <option value="normal">Normal</option>
                  <option value="congelar">{VETOS.congelar.nombre}</option>
                  <option value="cubrir">{VETOS.cubrir.nombre}</option>
                  <option value="cerrar">{VETOS.cerrar.nombre}</option>
                </select>
              </div>
              {pide && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border border-baja-marca/30 bg-baja-marca/10 px-3 py-2 text-xs" role="alert">
                  <span className="min-w-0 flex-1 basis-44">
                    «Fuera» vende {base(s)} ahora {horas ? `y no vuelve a entrar en ${horas} horas` : "y no vuelve a entrar hasta que lo quites"}. ¿Seguro?
                  </span>
                  <Boton variante="peligro" className="h-8 px-3 text-xs" onClick={() => confirmarFuera(s)}>Sí, vender {base(s)}</Boton>
                  <Boton className="h-8 px-3 text-xs" onClick={() => setPorConfirmar(null)}>Cancelar</Boton>
                </div>
              )}
              {v && !pide && (
                <p className="text-[11px] text-aviso">
                  {VETOS[v.modo]?.nombre ?? v.modo} desde {cuando(v.desde_utc)} · {valido(v.hasta_ms) ? `vuelve a normal ${hastaCuando(v.hasta_ms)}` : "sin caducidad: hasta que lo pongas en Normal"}
                </p>
              )}
            </li>
          );
        })}
      </ul>
      <div className="grid gap-1 border-t border-borde px-4 py-3 text-xs leading-relaxed text-texto-3">
        {poner.isError && <p role="alert" className="text-baja">No se pudo: {mensaje(poner.error)}</p>}
        <p><span className="font-semibold text-texto-2">Normal:</span> el bot decide solo, como siempre.</p>
        {(Object.keys(VETOS) as ModoVeto[]).map((k) => (
          <p key={k}><span className="font-semibold text-texto-2">{VETOS[k].nombre}:</span> {VETOS[k].texto}</p>
        ))}
        <p>Esto manda sobre el bot Jorge (su cartera simulada), no sobre tu cuenta manual. Se aplica al momento.</p>
      </div>
    </Panel>
  );
}

// ── d. Marcador de patrones ──────────────────────────────────────────────────

function CeldaMarcador({ p, sin }: { p: Previo | undefined; sin: string }) {
  if (!p || !p.n) return <span className="text-xs text-texto-3">{sin}</span>;
  return (
    <>
      <span className="num block">
        <span className="font-semibold">{pct(p.a_favor_pct, 0)}</span> <span className="text-[11px] text-texto-3">a favor</span>
      </span>
      <span className="num block text-[11px] text-texto-3">
        media <span className={colorSigno(signoDe(p.media_pct))}>{pct(p.media_pct, 2, true)}</span> · {p.n} {p.n === 1 ? "vez" : "veces"}
      </span>
    </>
  );
}

function Marcador({ as }: { as: TAsistente }) {
  const patrones = [...new Set([...Object.keys(as.catalogo), ...Object.keys(as.marcador), ...Object.keys(as.previo)])]
    .filter((k) => as.marcador[k]?.n || as.previo[k]?.n);
  return (
    <Panel titulo="Marcador de patrones" icono={<Trophy />} className="col-span-12 xl:col-span-5" cuerpo="p-0">
      {!patrones.length ? <Vacio>Todavía no hay avisos con 24 horas cumplidas para puntuarlos.</Vacio> : (
        <div className="px-4 py-2">
          <table className="w-full table-fixed text-[13px]">
            <thead>
              <tr className="text-left text-[11px] text-texto-3">
                <th className="w-[36%] py-1.5 pr-2 font-medium">Patrón</th>
                <th className="py-1.5 pr-2 font-medium">Avisos dados</th>
                <th className="py-1.5 font-medium">Último mes</th>
              </tr>
            </thead>
            <tbody>
              {patrones.map((k) => (
                <tr key={k} className="border-t border-borde/70 align-top">
                  <td className="py-2 pr-2 text-xs leading-snug break-words text-texto-2">{as.catalogo[k]?.nombre ?? k}</td>
                  <td className="py-2 pr-2"><CeldaMarcador p={as.marcador[k]} sin="aún ninguno" /></td>
                  <td className="py-2"><CeldaMarcador p={as.previo[k]} sin="no salió" /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="border-t border-borde px-4 py-3 text-xs leading-relaxed text-texto-3">
        «A favor» es que, 24 horas después, el precio había ido hacia donde apuntaba el aviso. «Avisos dados» cuenta los que
        te ha dado el asistente; «Último mes», todas las veces que salió el patrón en las velas del último mes.
        Esto es lo que ha pasado, no una promesa.
      </p>
    </Panel>
  );
}

// ── la vista ─────────────────────────────────────────────────────────────────

export function Asistente({ a, e }: { a: TAsistente | undefined; e: Estado }) {
  const marcar = useMarcarVistas();
  const refFormulario = useRef<HTMLDivElement>(null);
  const [borrador, setBorrador] = useState<Borrador>({ simbolo: "", lado: 1, usdt: "", stop: "", objetivo: "", nota: "", alerta: null });
  const [nuevos, setNuevos] = useState<Set<number>>(() => new Set());

  // Al abrir la vista (y si llega uno nuevo mientras se mira) los avisos quedan vistos; los que
  // estaban sin ver conservan su punto mientras la vista siga abierta.
  const sinVer = a?.sin_ver ?? 0;
  const { mutate: marcarVistas } = marcar;
  useEffect(() => { if (sinVer > 0) marcarVistas(); }, [sinVer, marcarVistas]);
  useEffect(() => {
    const ids = (a?.alertas ?? []).filter((x) => x.vista === false).map((x) => x.id);
    if (ids.length) setNuevos((antes) => (ids.every((id) => antes.has(id)) ? antes : new Set([...antes, ...ids])));
  }, [a?.alertas]);

  if (!a) return <Vacio>Cargando el asistente…</Vacio>;
  const m = a.manual;
  const b = a.monedas.includes(borrador.simbolo) ? borrador : { ...borrador, simbolo: a.monedas[0] ?? "" };

  // El precio de ahora: el que trae el bot; si falta, el de una posición abierta de esa moneda.
  const precioDe = (s: string): number | null => {
    const delBot = e.monedas.find((x) => x.simbolo === s)?.precio;
    if (valido(delBot)) return delBot;
    const dePosicion = m.posiciones.find((p) => p.simbolo === s)?.precio;
    return valido(dePosicion) ? dePosicion : null;
  };
  const operarDesdeAviso = (al: Alerta, lado: 1 | -1) => {
    setBorrador({ ...b, simbolo: al.simbolo, lado, stop: precioParaCasilla(stopPara(al, lado)), objetivo: "", alerta: al.id,
                  nota: `Aviso: ${a.catalogo[al.patron]?.nombre ?? al.patron}` });
    requestAnimationFrame(() => refFormulario.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
  };

  return (
    <div className="grid grid-cols-12 gap-3 sm:gap-4">
      {a.velas_al_dia < a.monedas.length && (
        <p className="col-span-12 rounded-lg border border-aviso/30 bg-aviso/10 px-3.5 py-2.5 text-[13px]">
          El asistente tiene datos al día de {a.velas_al_dia} de {a.monedas.length} monedas; de las demás no puede avisar todavía.
        </p>
      )}
      <Avisos as={a} nuevos={nuevos} alOperar={operarDesdeAviso} />

      <div className="col-span-12 grid grid-cols-12 content-start gap-3 sm:gap-4 xl:col-span-7">
        <div className="col-span-12 flex flex-wrap items-center justify-between gap-2 px-1">
          <h2 className="rotulo">Operar a mano · cuenta aparte</h2>
          <Chip tono="acento">SIMULACIÓN · dinero ficticio</Chip>
        </div>
        <div className="col-span-12 grid grid-cols-2 gap-3 sm:gap-4 lg:grid-cols-4 xl:grid-cols-2 2xl:grid-cols-4">
          <Stat rotulo="Patrimonio" icono={<Wallet />} destacado valor={dinero(m.patrimonio)}
            sub={<>empezó con {dinero(m.capital_inicial, { decimales: 0 })}</>} />
          <Stat rotulo="Ganancia" signo={signoDe(m.ganancia)} valor={dinero(m.ganancia, { signo: true })}
            sub={<>{pct(m.ganancia_pct, 2, true)} · ficticia</>} />
          <Stat rotulo="Operaciones" valor={cifra(m.operaciones, 0)}
            sub={<>cerradas · {m.posiciones.length} {m.posiciones.length === 1 ? "abierta" : "abiertas"}</>} />
          <Stat rotulo="Acierto" valor={valido(m.acierto_pct) ? pct(m.acierto_pct, 0) : "—"}
            sub={valido(m.acierto_pct) ? "de las cerradas acabaron en ganancia" : "aún no hay cerradas"} />
        </div>
        <Formulario as={a} b={b} setB={setBorrador} precioDe={precioDe} refPanel={refFormulario} />
        <Abiertas m={m} />
        <Cerradas m={m} />
      </div>

      <Monedas as={a} />
      <Marcador as={a} />
    </div>
  );
}
