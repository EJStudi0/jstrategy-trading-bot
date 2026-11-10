// Un mes en semanas de lunes a domingo. Cada día lleva su cifra escrita; el color (verde gana, rojo
// pierde, más intenso cuanto más) solo acompaña.
import { cx } from "../componentes/ui";
import { cifra, claveDia, diaSemana, dinero, signoDe } from "../lib/formato";
import type { Dia } from "../tipos";

const CABECERA = ["L", "M", "X", "J", "V", "S", "D"];

export function Calendario({ anio, mes, porDia, hoy, primerDia, elegido, alElegir }: {
  anio: number; mes: number; porDia: Map<string, Dia>; hoy: string; primerDia: string; elegido: string;
  alElegir: (clave: string) => void;
}) {
  const primero = new Date(anio, mes, 1);
  const hueco = (primero.getDay() + 6) % 7;
  const diasMes = new Date(anio, mes + 1, 0).getDate();
  let maximo = 0;
  for (let d = 1; d <= diasMes; d++) {
    const r = porDia.get(claveDia(new Date(anio, mes, d)));
    if (r) maximo = Math.max(maximo, Math.abs(r.ganancia));
  }
  const celdas = [];
  for (let i = 0; i < hueco; i++) celdas.push(<span key={"h" + i} />);
  for (let d = 1; d <= diasMes; d++) {
    const fecha = new Date(anio, mes, d);
    const clave = claveDia(fecha);
    const r = porDia.get(clave);
    const s = r ? signoDe(r.ganancia) : "";
    const futuro = clave > hoy;
    const antes = clave < primerDia;
    const fuerza = r && maximo > 0 ? 0.12 + 0.4 * Math.sqrt(Math.abs(r.ganancia) / maximo) : 0;
    const fondo = s === "sube" ? `rgb(16 185 129 / ${fuerza})` : s === "baja" ? `rgb(244 63 94 / ${fuerza})` : undefined;
    celdas.push(
      <button
        key={clave}
        type="button"
        disabled={futuro || (antes && !r)}
        onClick={() => alElegir(clave)}
        aria-pressed={clave === elegido}
        aria-label={`${diaSemana(fecha)}: ${r ? dinero(r.ganancia, { signo: true }) : futuro ? "aún no ha llegado" : "sin datos"}`}
        style={fondo ? { background: fondo } : undefined}
        className={cx(
          "group relative flex min-h-12 flex-col justify-between rounded-md border p-1.5 text-left transition sm:min-h-16 sm:p-2",
          r ? "border-transparent" : "border-dashed border-borde",
          !r && !futuro && "bg-panel-2/40",
          (futuro || antes) && !r && "opacity-40",
          clave === hoy && "ring-1 ring-acento",
          clave === elegido && "ring-2 ring-texto",
          !futuro && "hover:brightness-125",
        )}
      >
        <span className="num text-[10px] text-texto-3 sm:text-[11px]">{d}</span>
        {r && (
          <span className="num truncate text-[10.5px] font-semibold text-texto sm:text-xs">
            {cifra(r.ganancia, Math.abs(r.ganancia) >= 100 ? 0 : Math.abs(r.ganancia) >= 10 ? 1 : 2, true)}
          </span>
        )}
      </button>,
    );
  }
  return (
    <div className="grid grid-cols-7 gap-1 sm:gap-1.5" role="grid">
      {CABECERA.map((c) => <span key={c} className="pb-1 text-center text-[11px] font-semibold text-texto-3">{c}</span>)}
      {celdas}
    </div>
  );
}
