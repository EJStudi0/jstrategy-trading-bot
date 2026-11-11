// Asistente: avisa de los patrones que ve en las diez monedas, deja operar a mano en una cuenta
// aparte (simulada) y dar órdenes sobre monedas sueltas al bot. Avisa; no opera por su cuenta.
// Arriba, los mandos rápidos del bot; debajo, cuatro sub-pestañas (cada una en su fichero).
import { Pause, Play, ShieldCheck, Zap } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useConfirmar } from "../componentes/Dialogo";
import { Chip, Vacio } from "../componentes/ui";
import { useMarcarVistas, usePonerMando } from "../hooks/datos";
import { fraseMando, precioParaCasilla, stopPara } from "../lib/asistente";
import { MANDOS } from "../lib/derivados";
import { valido } from "../lib/formato";
import type { Prefs } from "../lib/prefs";
import { useAhora } from "../marco/Marco";
import type { Alerta, Asistente as TAsistente, Estado } from "../tipos";
import { Ajustes } from "./asistente/Ajustes";
import { Avisos } from "./asistente/Avisos";
import { BORRADOR_VACIO, BotonT, Opciones, Resultado, type Borrador } from "./asistente/comunes";
import { Monedas } from "./asistente/Monedas";
import { Operar } from "./asistente/Operar";

const HORAS_RAPIDAS = 4;

/** El estado del bot en una frase y los tres mandos de todos los días. Salir de todo no está aquí:
 *  sigue en Mando, con su doble confirmación. */
function BarraRapida({ e, alIr }: { e: Estado; alIr: (v: Prefs["vista"]) => void }) {
  const confirmar = useConfirmar();
  const poner = usePonerMando();
  const ahora = useAhora(30_000);
  const vetos = Object.keys(e.vetos ?? {}).length;
  const temporal = `Dura ${HORAS_RAPIDAS} horas; después el bot vuelve solo a Automático.`;
  // Pausar no compra ni vende nada: va directo. Cubrir y volver a automático pueden operar: se preguntan.
  const pausar = () => !poner.isPending && poner.mutate({ mando: "pausa", horas: HORAS_RAPIDAS });
  const cubrir = async () => {
    if (poner.isPending) return;
    if (await confirmar({ titulo: `¿Cubrir todo ${HORAS_RAPIDAS} horas?`, texto: `${MANDOS.neutral.confirma} ${temporal}`, si: "Cubrir todo" })) {
      poner.mutate({ mando: "neutral", horas: HORAS_RAPIDAS });
    }
  };
  const automatico = async () => {
    if (poner.isPending) return;
    if (await confirmar({ titulo: "¿Volver a automático?", texto: MANDOS.auto.confirma, si: "Volver a automático" })) poner.mutate({ mando: "auto" });
  };
  return (
    <section className="panel grid gap-3 p-3 sm:p-4" aria-label="Mandos rápidos del bot">
      <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1.5">
        <span className="rotulo flex items-center gap-1.5"><Zap className="size-3.5" />El bot ahora</span>
        <Chip tono={e.mando === "auto" ? "sube" : e.mando === "fuera" ? "baja" : "aviso"} className="h-auto min-h-7 px-2.5 py-0.5 text-xs whitespace-normal">
          {fraseMando(e.mando, e.mando_hasta_ms, ahora)}
        </Chip>
        {vetos > 0 && <span className="text-xs text-aviso">{vetos === 1 ? "1 moneda con orden tuya" : `${vetos} monedas con orden tuya`}</span>}
        <Resultado m={poner} />
        <button type="button" onClick={() => alIr("mando")}
          className="ml-auto inline-flex min-h-10 items-center text-xs font-semibold text-acento underline decoration-acento/40 underline-offset-2">
          Más mandos
        </button>
      </div>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        <BotonT className="h-12" disabled={poner.isPending} onClick={pausar}><Pause className="size-4" />Pausar {HORAS_RAPIDAS} h</BotonT>
        <BotonT className="h-12" disabled={poner.isPending} onClick={cubrir}><ShieldCheck className="size-4" />Cubrir todo {HORAS_RAPIDAS} h</BotonT>
        <BotonT className="col-span-2 h-12 sm:col-span-1" variante={e.mando === "auto" ? "normal" : "primario"} disabled={poner.isPending || e.mando === "auto"} onClick={automatico}>
          <Play className="size-4" />{e.mando === "auto" ? "Ya está en automático" : "Volver a automático"}
        </BotonT>
      </div>
    </section>
  );
}

export function Asistente({ a, e, sub, alSub, alIr }: {
  a: TAsistente | undefined; e: Estado; sub: Prefs["sub"]; alSub: (s: Prefs["sub"]) => void; alIr: (v: Prefs["vista"]) => void;
}) {
  const { mutate: marcarVistas } = useMarcarVistas();
  const [borrador, setBorrador] = useState<Borrador>(BORRADOR_VACIO);
  const [nuevos, setNuevos] = useState<Set<number>>(() => new Set());
  const ancla = useRef<HTMLDivElement>(null);

  // Al mirar los avisos quedan vistos; los que estaban sin ver conservan su punto mientras la vista siga abierta.
  const sinVer = a?.sin_ver ?? 0;
  useEffect(() => { if (sub === "avisos" && sinVer > 0) marcarVistas(); }, [sub, sinVer, marcarVistas]);
  useEffect(() => {
    const ids = (a?.alertas ?? []).filter((x) => x.vista === false).map((x) => x.id);
    if (ids.length) setNuevos((antes) => (ids.every((id) => antes.has(id)) ? antes : new Set([...antes, ...ids])));
  }, [a?.alertas]);

  if (!a) {
    return (
      <div className="grid gap-3 sm:gap-4">
        <BarraRapida e={e} alIr={alIr} />
        <Vacio>Cargando el asistente…</Vacio>
      </div>
    );
  }
  const m = a.manual;
  const b = a.monedas.includes(borrador.simbolo) ? borrador : { ...borrador, simbolo: a.monedas[0] ?? "" };

  // El precio de ahora: el que trae el bot; si falta, el de una posición abierta de esa moneda.
  const precioDe = (s: string): number | null => {
    const delBot = e.monedas.find((x) => x.simbolo === s)?.precio;
    if (valido(delBot)) return delBot;
    const dePosicion = m.posiciones.find((p) => p.simbolo === s)?.precio;
    return valido(dePosicion) ? dePosicion : null;
  };
  // Al cambiar de sub-pestaña con la página ya bajada, se vuelve al principio de la parte nueva
  // (las pestañas quedan pegadas arriba), no al principio de toda la página.
  const irASub = (s: Prefs["sub"]) => {
    alSub(s);
    requestAnimationFrame(() => {
      const el = ancla.current;
      if (el && el.getBoundingClientRect().top < 56) el.scrollIntoView({ block: "start" });
    });
  };
  const operar = (cambios: Partial<Borrador>) => { setBorrador({ ...b, stop: "", objetivo: "", nota: "", alerta: null, sugerido: null, ...cambios }); irASub("operar"); };
  const operarDesdeAviso = (al: Alerta, lado: 1 | -1) => operar({
    simbolo: al.simbolo, lado, alerta: al.id, sugerido: al.stop, stop: precioParaCasilla(stopPara(al, lado)),
    nota: al.patron === "nivel" ? `Llegó a mi precio${al.nota ? ": " + al.nota : ""}` : `Aviso: ${a.catalogo[al.patron]?.nombre ?? al.patron}`,
  });

  return (
    <div className="grid gap-3 sm:gap-4">
      <BarraRapida e={e} alIr={alIr} />
      <div ref={ancla} className="-mb-3 scroll-mt-[calc(3.5rem+env(safe-area-inset-top))] sm:-mb-4" aria-hidden="true" />
      <div className="sticky top-[calc(3.5rem+env(safe-area-inset-top))] z-20 -mx-3 bg-fondo/90 px-3 py-2 backdrop-blur-xl sm:-mx-5 sm:px-5">
        <Opciones etiqueta="Partes del asistente" valor={sub} alCambiar={irASub} className="mx-auto max-w-3xl" opciones={[
          { valor: "avisos", texto: "Avisos", contador: sub === "avisos" ? 0 : a.sin_ver },
          { valor: "operar", texto: "Operar", contador: m.posiciones.length },
          { valor: "monedas", texto: "Monedas", contador: Object.keys(a.vetos).length },
          { valor: "ajustes", texto: "Ajustes" },
        ]} />
      </div>
      {a.velas_al_dia < a.monedas.length && (
        <p className="rounded-lg border border-aviso/30 bg-aviso/10 px-3.5 py-2.5 text-[13px]">
          El asistente tiene datos al día de {a.velas_al_dia} de {a.monedas.length} monedas; de las demás no puede avisar todavía.
        </p>
      )}
      <div key={sub} className="entra">
        {sub === "avisos" && <Avisos as={a} nuevos={nuevos} precioDe={precioDe} alOperar={operarDesdeAviso} />}
        {sub === "operar" && <Operar as={a} b={b} setB={setBorrador} precioDe={precioDe} />}
        {sub === "monedas" && <Monedas as={a} precioDe={precioDe} alOperar={(simbolo, lado) => operar({ simbolo, lado })} />}
        {sub === "ajustes" && <Ajustes as={a} />}
      </div>
    </div>
  );
}
