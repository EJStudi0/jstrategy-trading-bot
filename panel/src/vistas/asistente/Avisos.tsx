// Sub-pestaña «Avisos»: lo que ha visto el asistente y los precios que el dueño le pide vigilar.
import { BellOff, BellRing, ChevronDown, Target, Trash2 } from "lucide-react";
import { useState } from "react";
import { Chip, Cifra, Panel, Vacio, cx } from "../../componentes/ui";
import { useNivel } from "../../hooks/datos";
import { distanciaPct, importante, leerNumero } from "../../lib/asistente";
import { base, nombre } from "../../lib/derivados";
import { cuando, pct, precio, valido } from "../../lib/formato";
import type { Alerta, Asistente, Previo } from "../../tipos";
import { BotonT, CASILLA, Campo, ChipLado, LargoCorto, Opciones, Resultado, type PrecioDe } from "./comunes";

const fraseOtrasVeces = (p: Previo | null | undefined) =>
  p && p.n > 0
    ? `Las otras ${p.n} veces este mes: ${pct(p.a_favor_pct, 0)} siguió a favor, media ${pct(p.media_pct, 2, true)} a 24 h.`
    : "Este mes no ha salido otras veces: no hay con qué comparar.";

function TarjetaAviso({ a, as, nuevo, abierta, alAbrir, alOperar }: {
  a: Alerta; as: Asistente; nuevo: boolean; abierta: boolean; alAbrir: () => void; alOperar: (a: Alerta, lado: 1 | -1) => void;
}) {
  const cat = as.catalogo[a.patron];
  const esNivel = a.patron === "nivel";
  const previo = a.previo ?? as.previo[a.patron];
  const seguido = valido(a.a_4h) || valido(a.a_24h);
  return (
    <li className={cx("rounded-xl border bg-panel-2/50", esNivel ? "border-aviso/60 bg-aviso/10" : a.fuerza === "alta" && !a.callada ? "border-acento/50" : "border-borde-2",
                      a.callada && "opacity-70")}>
      <button type="button" onClick={alAbrir} aria-expanded={abierta} className="grid w-full gap-1.5 p-3 text-left">
        <span className="flex min-w-0 items-baseline gap-2">
          {nuevo && <span className="size-2 shrink-0 self-center rounded-full bg-acento" title="Nuevo"><span className="sr-only">Nuevo: </span></span>}
          <span className="shrink-0 text-sm font-semibold">{base(a.simbolo)}</span>
          <span className="min-w-0 flex-1 truncate text-[13px] text-texto-2">
            {esNivel ? <>Llegó a tu precio <span className="num font-semibold text-texto">{precio(a.nivel ?? a.precio)}</span></> : cat?.nombre ?? a.patron}
          </span>
          <time className="num shrink-0 text-[11px] text-texto-3">{cuando(a.utc)}</time>
        </span>
        {esNivel && a.nota && <span className="text-[13px] break-words text-texto">«{a.nota}»</span>}
        <span className="flex min-w-0 flex-wrap items-center gap-1.5">
          {esNivel ? <Chip tono="aviso"><Target className="size-3" />{a.lado === 1 ? "subió hasta ahí" : "bajó hasta ahí"}</Chip> : <ChipLado lado={a.lado} />}
          {!esNivel && <Chip tono={a.fuerza === "alta" ? "acento" : "neutro"} className={cx(a.fuerza === "baja" && "text-texto-3")}>fuerza {a.fuerza}</Chip>}
          {a.callada && <Chip className="text-texto-3"><BellOff className="size-3" />silenciado</Chip>}
          <span className="num ml-auto text-[13px] text-texto-2">a {precio(a.precio)}</span>
          <ChevronDown className={cx("size-4 shrink-0 text-texto-3 transition-transform", abierta && "rotate-180")} />
        </span>
      </button>
      {abierta && (
        <div className="grid gap-2 border-t border-borde px-3 pt-2.5 pb-3 text-xs leading-relaxed text-texto-2">
          {cat && <p><span className="font-semibold text-texto">Qué es.</span> {cat.que}</p>}
          {cat && !esNivel && <p><span className="font-semibold text-texto">Lo medido.</span> {cat.medido}</p>}
          {!esNivel && <p>{fraseOtrasVeces(previo)}</p>}
          {a.lado !== 0 && (
            <p>
              <span className="font-semibold text-texto">Qué pasó después.</span>{" "}
              {seguido ? (
                <>
                  {valido(a.a_4h) && <>a las 4 h <Cifra valor={a.a_4h} tipo="pct" signo colorear /></>}
                  {valido(a.a_4h) && valido(a.a_24h) && " · "}
                  {valido(a.a_24h) && <>a las 24 h <Cifra valor={a.a_24h} tipo="pct" signo colorear /></>}
                  {" "}(en positivo si siguió en la misma dirección).
                </>
              ) : "Todavía es pronto: se apunta a las 4 y a las 24 horas."}
            </p>
          )}
          {valido(a.stop) && (
            <p><span className="font-semibold text-texto">Stop sugerido.</span> <span className="num">{precio(a.stop)}</span> (a dos veces lo que se mueve normalmente).</p>
          )}
          <LargoCorto alElegir={(l) => alOperar(a, l)} destacado={esNivel ? 0 : a.lado} className="mt-1" />
          <p className="text-[11px] text-texto-3">Te lleva a «Operar» con todo relleno; no abre nada hasta que lo confirmes. Dinero ficticio.</p>
        </div>
      )}
    </li>
  );
}

function ListaAvisos({ as, nuevos, alOperar }: { as: Asistente; nuevos: Set<number>; alOperar: (a: Alerta, lado: 1 | -1) => void }) {
  const [filtro, setFiltro] = useState<"importantes" | "todos">("importantes");
  const [abierta, setAbierta] = useState<number | null>(null);
  const [cuantos, setCuantos] = useState(6);
  const lista = filtro === "todos" ? as.alertas : as.alertas.filter(importante);
  const ocultos = as.alertas.length - lista.length;
  return (
    <Panel titulo="Avisos" icono={<BellRing />} className="col-span-12 xl:col-span-7" cuerpo="p-3">
      <Opciones etiqueta="Qué avisos se ven" valor={filtro} alCambiar={setFiltro} className="mb-3"
        opciones={[{ valor: "importantes", texto: "Importantes" }, { valor: "todos", texto: `Todos (${as.alertas.length})` }]} />
      {!lista.length ? (
        <Vacio>
          {as.alertas.length
            ? `Ningún aviso importante por ahora. Hay ${ocultos} flojos o silenciados en «Todos».`
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
            <BotonT variante="fantasma" className="mt-2 w-full" onClick={() => setCuantos(cuantos + 12)}>
              Ver más antiguos ({lista.length - cuantos})
            </BotonT>
          )}
        </>
      )}
      <p className="mt-3 px-1 text-[11px] leading-relaxed text-texto-3">Un aviso no es una orden: el asistente no opera solo. Toca uno para ver qué es.</p>
    </Panel>
  );
}

function Niveles({ as, precioDe }: { as: Asistente; precioDe: PrecioDe }) {
  const nivel = useNivel();
  const [simbolo, setSimbolo] = useState("");
  const [texto, setTexto] = useState("");
  const [nota, setNota] = useState("");
  const [fallo, setFallo] = useState<string>();
  const s = as.monedas.includes(simbolo) ? simbolo : as.monedas[0] ?? "";
  const px = precioDe(s);
  const pedido = leerNumero(texto);
  const falta = valido(pedido) ? distanciaPct(px, pedido) : null;
  const niveles = as.niveles ?? [];
  const creando = nivel.isPending && !!nivel.variables && "simbolo" in nivel.variables;

  const crear = (ev: React.FormEvent) => {
    ev.preventDefault();
    if (nivel.isPending) return;
    if (!valido(pedido) || pedido <= 0) return setFallo("Escribe el precio solo con números.");
    setFallo(undefined);
    nivel.mutate({ simbolo: s, precio: pedido, nota: nota.trim() }, { onSuccess: () => { setTexto(""); setNota(""); } });
  };
  return (
    <Panel titulo="Avísame si…" icono={<Target />} className="col-span-12 xl:col-span-5">
      <form className="grid grid-cols-2 gap-3" onSubmit={crear}>
        <Campo rotulo="Moneda">
          <select className={CASILLA} value={s} onChange={(ev) => setSimbolo(ev.target.value)}>
            {as.monedas.map((m) => <option key={m} value={m}>{base(m)} · {nombre(m)}</option>)}
          </select>
        </Campo>
        <Campo rotulo="llega a este precio">
          <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder={valido(px) ? precio(px) : "precio"} value={texto}
            onChange={(ev) => { setTexto(ev.target.value); setFallo(undefined); }} />
        </Campo>
        <Campo rotulo="Nota para ti (opcional)" className="col-span-2">
          <input className={CASILLA} maxLength={120} autoComplete="off" placeholder="p. ej. mirar si rompe" value={nota} onChange={(ev) => setNota(ev.target.value)} />
        </Campo>
        <p className="col-span-2 text-xs text-texto-3">
          {base(s)} ahora: <span className="num text-texto-2">{valido(px) ? precio(px) : "sin precio"}</span>
          {valido(falta) && Math.abs(falta) > 0 && (
            <> · te avisará cuando {falta > 0 ? "suba" : "baje"} hasta ahí (<span className="num text-texto-2">{pct(falta, 1, true)}</span>)</>
          )}
        </p>
        <div className="col-span-2 flex flex-wrap items-center gap-3">
          <BotonT type="submit" variante="primario" disabled={nivel.isPending}>{creando ? "Guardando…" : "Avisarme"}</BotonT>
          {fallo ? <span role="alert" className="text-xs text-baja">{fallo}</span> : <Resultado m={nivel} />}
        </div>
      </form>

      <h3 className="rotulo mt-5 mb-1">Precios vigilados ({niveles.length})</h3>
      {!niveles.length ? <p className="py-3 text-xs text-texto-3">Ninguno. Cuando el precio llegue a uno, sale arriba como aviso y se borra de aquí.</p> : (
        <ul className="divide-y divide-borde/70">
          {niveles.map((n) => {
            const d = distanciaPct(precioDe(n.simbolo), n.precio);
            return (
              <li key={n.id} className="flex min-w-0 items-center gap-3 py-2">
                <div className="min-w-0 flex-1">
                  <p className="flex min-w-0 flex-wrap items-baseline gap-x-2 text-[13px]">
                    <span className="font-semibold">{base(n.simbolo)}</span>
                    <span className={n.sentido === 1 ? "text-sube" : "text-baja"}>{n.sentido === 1 ? "sube hasta" : "baja hasta"}</span>
                    <span className="num font-semibold">{precio(n.precio)}</span>
                    {valido(d) && <span className="num text-xs text-texto-3">falta {pct(d, 1, true)}</span>}
                  </p>
                  {n.nota && <p className="truncate text-xs text-texto-3">«{n.nota}»</p>}
                </div>
                <BotonT variante="fantasma" className="w-10 shrink-0 px-0" disabled={nivel.isPending} aria-label={`Borrar el aviso de ${base(n.simbolo)} a ${precio(n.precio)}`}
                  onClick={() => nivel.mutate({ id: n.id })}>
                  <Trash2 className="size-4" />
                </BotonT>
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export function Avisos({ as, nuevos, precioDe, alOperar }: {
  as: Asistente; nuevos: Set<number>; precioDe: PrecioDe; alOperar: (a: Alerta, lado: 1 | -1) => void;
}) {
  return (
    <div className="grid grid-cols-12 items-start gap-3 sm:gap-4">
      <ListaAvisos as={as} nuevos={nuevos} alOperar={alOperar} />
      <Niveles as={as} precioDe={precioDe} />
    </div>
  );
}
