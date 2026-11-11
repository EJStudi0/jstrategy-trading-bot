// Sub-pestaña «Monedas»: cómo está cada una y lo que el dueño manda sobre ella al bot.
import { Hand } from "lucide-react";
import { useState } from "react";
import { Chip, Panel, cx } from "../../componentes/ui";
import { usePonerVeto, usePrefsAsistente } from "../../hooks/datos";
import { DURACIONES, VETOS, etiquetaFondo, etiquetaMovimiento, hastaCuando, type Duracion } from "../../lib/asistente";
import { base } from "../../lib/derivados";
import { cuando, precio, valido } from "../../lib/formato";
import type { Asistente, ModoVeto } from "../../tipos";
import { BotonT, CASILLA, InterruptorFila, LargoCorto, Opciones, Resultado, type PrecioDe } from "./comunes";

export function Monedas({ as, precioDe, alOperar }: { as: Asistente; precioDe: PrecioDe; alOperar: (simbolo: string, lado: 1 | -1) => void }) {
  const poner = usePonerVeto();
  const prefs = usePrefsAsistente();
  const [duracion, setDuracion] = useState<Duracion>("0");
  const [porConfirmar, setPorConfirmar] = useState<string | null>(null);   // «Fuera» vende: segundo toque
  const horas = Number(duracion);
  const calladas = as.prefs?.monedas_calladas ?? [];

  const elegir = (simbolo: string, valor: string) => {
    if (valor === "cerrar") return setPorConfirmar(simbolo);
    setPorConfirmar(null);
    poner.mutate({ simbolo, modo: valor === "normal" ? null : (valor as ModoVeto), horas });
  };
  const silenciar = (simbolo: string, callar: boolean) =>
    prefs.mutate({ monedas_calladas: callar ? [...new Set([...calladas, simbolo])] : calladas.filter((x) => x !== simbolo) });

  return (
    <div className="grid gap-3 sm:gap-4">
      <Panel titulo="Qué hace el bot con cada moneda" icono={<Hand />} cuerpo="p-0">
        <div className="grid gap-1.5 border-b border-borde px-4 py-3">
          <span className="text-xs text-texto-2">Lo que mandes ahora dura</span>
          <Opciones etiqueta="Cuánto dura lo que mandes" valor={duracion} alCambiar={setDuracion}
            opciones={DURACIONES.map((d) => ({ valor: d.valor, texto: d.valor === "0" ? "Siempre" : d.etiqueta }))} />
          <span className="text-[11px] text-texto-3">{horas ? `Pasadas ${horas} horas la moneda vuelve sola a «Normal».` : "Se queda así hasta que la pongas en «Normal»."}</span>
        </div>
        <ul className="grid divide-y divide-borde/70 lg:grid-cols-2 lg:divide-y-0">
          {as.monedas.map((s) => {
            const l = as.lectura[s];
            const v = as.vetos[s];
            const mov = etiquetaMovimiento(l?.movimiento);
            const pide = porConfirmar === s;
            const callada = calladas.includes(s);
            const px = precioDe(s);
            return (
              <li key={s} className="grid content-start gap-2 px-4 py-3 lg:border-b lg:border-borde/70">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="text-[15px] font-semibold">{base(s)}</span>
                  {valido(px) && <span className="num text-xs text-texto-3">{precio(px)}</span>}
                  <span className="ml-auto flex flex-wrap justify-end gap-1.5">
                    {l ? (
                      <>
                        <Chip tono={l.fondo === 1 ? "sube" : l.fondo === -1 ? "baja" : "neutro"} className="h-5" titulo="Tendencia de fondo">fondo {etiquetaFondo(l.fondo)}</Chip>
                        <Chip tono={mov === "movido" ? "aviso" : "neutro"} className="h-5" titulo="Cuánto se mueve frente a lo suyo normal">{mov}</Chip>
                      </>
                    ) : <span className="text-xs text-texto-3">sin lectura todavía</span>}
                  </span>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] items-center gap-2">
                  <label className="text-xs text-texto-2" htmlFor={"veto-" + s}>El bot, con {base(s)}:</label>
                  <select id={"veto-" + s} disabled={poner.isPending} value={pide ? "cerrar" : v?.modo ?? "normal"} onChange={(ev) => elegir(s, ev.target.value)}
                    className={cx(CASILLA, "px-2", (v || pide) && "border-aviso/60 text-aviso")}>
                    <option value="normal">Normal</option>
                    <option value="congelar">{VETOS.congelar.nombre}</option>
                    <option value="cubrir">{VETOS.cubrir.nombre}</option>
                    <option value="cerrar">{VETOS.cerrar.nombre}</option>
                  </select>
                </div>
                {pide && (
                  <div className="grid gap-2 rounded-lg border border-baja-marca/30 bg-baja-marca/10 p-3 text-xs" role="alert">
                    <span>«Fuera» vende {base(s)} ahora {horas ? `y no vuelve a entrar en ${horas} horas` : "y no vuelve a entrar hasta que la pongas en «Normal»"}. ¿Seguro?</span>
                    <div className="grid grid-cols-2 gap-2">
                      <BotonT variante="peligro" onClick={() => { setPorConfirmar(null); poner.mutate({ simbolo: s, modo: "cerrar", horas }); }}>Sí, vender {base(s)}</BotonT>
                      <BotonT onClick={() => setPorConfirmar(null)}>Cancelar</BotonT>
                    </div>
                  </div>
                )}
                {v && !pide && (
                  <p className="text-[11px] text-aviso">
                    {VETOS[v.modo]?.nombre ?? v.modo} desde {cuando(v.desde_utc)} · {valido(v.hasta_ms) ? `vuelve a «Normal» ${hastaCuando(v.hasta_ms)}` : "hasta que la pongas en «Normal»"}
                  </p>
                )}
                {poner.variables?.simbolo === s && <Resultado m={poner} />}
                <div className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)] items-center gap-3">
                  <LargoCorto alElegir={(lado) => alOperar(s, lado)} />
                  <InterruptorFila marcado={callada} disabled={prefs.isPending} alCambiar={(x) => silenciar(s, x)}>Silenciar avisos</InterruptorFila>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="grid gap-1 border-t border-borde px-4 py-3 text-xs leading-relaxed text-texto-3 lg:border-t-0">
          <Resultado m={prefs} />
          <p><span className="font-semibold text-texto-2">Normal:</span> el bot decide solo, como siempre.</p>
          {(Object.keys(VETOS) as ModoVeto[]).map((k) => (
            <p key={k}><span className="font-semibold text-texto-2">{VETOS[k].nombre}:</span> {VETOS[k].texto}</p>
          ))}
          <p><span className="font-semibold text-texto-2">Largo / Corto:</span> te llevan a «Operar» con esa moneda puesta (tu cuenta manual, no la del bot).</p>
          <p><span className="font-semibold text-texto-2">Silenciar avisos:</span> el asistente sigue mirándola, pero no te avisa.</p>
        </div>
      </Panel>
    </div>
  );
}
