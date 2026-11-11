// Sub-pestaña «Ajustes»: qué patrones avisan, la cuenta manual, el marcador y una ayuda corta.
import { BellRing, CircleHelp, RotateCcw, Trophy } from "lucide-react";
import { useState } from "react";
import { Chip, Panel, Vacio, colorSigno, cx } from "../../componentes/ui";
import { usePrefsAsistente, useReiniciarCuenta } from "../../hooks/datos";
import { leerNumero } from "../../lib/asistente";
import { dinero, pct, signoDe, valido } from "../../lib/formato";
import type { Asistente, Previo } from "../../tipos";
import { BotonDosToques, CASILLA, Campo, InterruptorFila, Resultado } from "./comunes";

function Patrones({ as }: { as: Asistente }) {
  const prefs = usePrefsAsistente();
  const callados = as.prefs?.patrones_callados ?? [];
  // El patrón «nivel» son los precios que pide vigilar el dueño: esos avisan siempre.
  const lista = Object.entries(as.catalogo).filter(([k]) => k !== "nivel");
  const cambiar = (k: string, avisa: boolean) =>
    prefs.mutate({ patrones_callados: avisa ? callados.filter((x) => x !== k) : [...new Set([...callados, k])] });
  return (
    <Panel titulo="Qué patrones te avisan" icono={<BellRing />} className="col-span-12 xl:col-span-6" cuerpo="p-0"
      acciones={<Resultado m={prefs} />}>
      <ul className="divide-y divide-borde/70">
        {lista.map(([k, c]) => {
          const avisa = !callados.includes(k);
          return (
            <li key={k} className="px-4 py-2.5">
              <InterruptorFila marcado={avisa} disabled={prefs.isPending} alCambiar={(x) => cambiar(k, x)}>
                <span className={cx("block text-[13px] font-semibold", avisa ? "text-texto" : "text-texto-3")}>{c.nombre}</span>
                <span className="block text-xs leading-snug text-texto-3">{c.que}</span>
              </InterruptorFila>
            </li>
          );
        })}
      </ul>
      <p className="border-t border-borde px-4 py-3 text-xs leading-relaxed text-texto-3">
        Uno apagado se sigue apuntando en el marcador, pero no te avisa ni cuenta como «sin ver». Los precios que pides vigilar avisan siempre.
      </p>
    </Panel>
  );
}

function Cuenta({ as }: { as: Asistente }) {
  const reiniciar = useReiniciarCuenta();
  const m = as.manual;
  const [texto, setTexto] = useState("");
  const [fallo, setFallo] = useState<string>();
  const abiertas = m.posiciones.length;
  const capital = texto.trim() ? leerNumero(texto) : m.capital_inicial;
  const enviar = () => {
    if (!valido(capital) || capital < 100 || capital > 1_000_000) return setFallo("El capital va de 100 a 1.000.000, solo con números.");
    setFallo(undefined);
    reiniciar.mutate({ capital }, { onSuccess: () => setTexto("") });
  };
  return (
    <Panel titulo="Cuenta manual" icono={<RotateCcw />} className="col-span-12 xl:col-span-6" acciones={<Chip tono="acento">SIMULACIÓN · dinero ficticio</Chip>}>
      <div className="grid gap-3 text-[13px]">
        <p className="text-texto-2">
          Empezó con <span className="num font-semibold text-texto">{dinero(m.capital_inicial, { decimales: 0 })}</span> y ahora tiene{" "}
          <span className="num font-semibold text-texto">{dinero(m.patrimonio)}</span> (<span className={cx("num", colorSigno(signoDe(m.ganancia)))}>{dinero(m.ganancia, { signo: true })}</span>),
          con {m.operaciones} {m.operaciones === 1 ? "operación cerrada" : "operaciones cerradas"}.
        </p>
        <Campo rotulo="Empezar de cero con… (dólares ficticios, de 100 a 1.000.000)">
          <input className={cx(CASILLA, "num")} inputMode="decimal" autoComplete="off" placeholder={String(Math.round(m.capital_inicial))} value={texto}
            onChange={(ev) => { setTexto(ev.target.value); setFallo(undefined); }} />
        </Campo>
        <div className="flex flex-wrap items-center gap-3">
          <BotonDosToques disabled={reiniciar.isPending || abiertas > 0} alConfirmar={enviar}
            confirma={valido(capital) ? `¿Seguro? Borrar y empezar con ${dinero(capital, { decimales: 0 })}` : "¿Seguro? Borrar y empezar"}>
            {reiniciar.isPending ? "Reiniciando…" : "Empezar de cero"}
          </BotonDosToques>
          {fallo ? <span role="alert" className="text-xs text-baja">{fallo}</span> : <Resultado m={reiniciar} ok="Hecho: cuenta nueva" />}
        </div>
        <p className="text-xs leading-relaxed text-texto-3">
          {abiertas > 0 && <span className="text-aviso">Antes cierra {abiertas === 1 ? "la operación abierta" : `las ${abiertas} operaciones abiertas`} en «Operar». </span>}
          Borra el historial de la cuenta manual (operaciones y resultado) y la deja nueva. Es dinero ficticio: no toca al bot, ni a Centinela, ni a los avisos.
        </p>
      </div>
    </Panel>
  );
}

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

function Marcador({ as }: { as: Asistente }) {
  const patrones = [...new Set([...Object.keys(as.catalogo), ...Object.keys(as.marcador), ...Object.keys(as.previo)])]
    .filter((k) => as.marcador[k]?.n || as.previo[k]?.n);
  return (
    <Panel titulo="Marcador de patrones" icono={<Trophy />} className="col-span-12 xl:col-span-6" cuerpo="p-0">
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
        «A favor»: 24 horas después, el precio había ido hacia donde apuntaba el aviso. «Avisos dados» son los que te ha dado el
        asistente; «Último mes», todas las veces que salió el patrón. Esto es lo que ha pasado, no una promesa.
      </p>
    </Panel>
  );
}

const AYUDA: [string, string][] = [
  ["Arriba del todo", "paras o cubres el bot cuatro horas con un toque, y lo devuelves a automático cuando quieras."],
  ["Avisos", "lo que el asistente ha visto en las diez monedas. Toca uno para entenderlo; él nunca opera solo."],
  ["Avísame si…", "pones un precio y te avisa una vez cuando la moneda llegue ahí."],
  ["Operar", "abres y cierras operaciones tuyas en una cuenta aparte, con dinero ficticio. El stop limita lo que pierdes."],
  ["Monedas", "le dices al bot que no toque una moneda, que la cubra o que salga de ella, y silencias las que no te interesan."],
  ["Ajustes", "eliges qué patrones avisan, reinicias la cuenta manual y miras cómo les ha ido a los avisos."],
];

function Ayuda() {
  return (
    <Panel titulo="Cómo se usa" icono={<CircleHelp />} className="col-span-12 xl:col-span-6">
      <ul className="grid gap-2 text-[13px] leading-relaxed text-texto-2">
        {AYUDA.map(([que, texto]) => <li key={que}><span className="font-semibold text-texto">{que}:</span> {texto}</li>)}
      </ul>
    </Panel>
  );
}

export function Ajustes({ as }: { as: Asistente }) {
  return (
    <div className="grid grid-cols-12 items-start gap-3 sm:gap-4">
      <Patrones as={as} />
      <Cuenta as={as} />
      <Marcador as={as} />
      <Ayuda />
    </div>
  );
}
