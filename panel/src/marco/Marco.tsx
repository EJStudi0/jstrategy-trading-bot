// El marco: cabecera con el estado del bot, cinta de precios y, en el móvil, la barra de abajo.
import { Bitcoin, ChartCandlestick, ChartColumn, Clock, LayoutDashboard, Moon, SlidersHorizontal, Sun, SunMoon, TriangleAlert } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { Chip, PuntoEstado, cx } from "../componentes/ui";
import { MiniLinea } from "../componentes/piezas";
import { base } from "../lib/derivados";
import { cuando, cuentaAtras, horaSegundos, pctFraccion, precio, signoDe, valido } from "../lib/formato";
import type { Prefs } from "../lib/prefs";
import type { Estado, Mercado } from "../tipos";
import { Marca } from "./Marca";

export const VISTAS: { id: Prefs["vista"]; nombre: string; icono: ReactNode }[] = [
  { id: "resumen", nombre: "Resumen", icono: <LayoutDashboard /> },
  { id: "ganancias", nombre: "Ganancias", icono: <ChartColumn /> },
  { id: "mercado", nombre: "Mercado", icono: <ChartCandlestick /> },
  { id: "centinela", nombre: "Centinela", icono: <Bitcoin /> },
  { id: "mando", nombre: "Mando", icono: <SlidersHorizontal /> },
];

export function useAhora(cada = 1000) {
  const [ahora, setAhora] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setAhora(Date.now()), cada);
    return () => clearInterval(t);
  }, [cada]);
  return ahora;
}

const SALUD = { ok: "Datos al día", viejo: "Datos con retraso", ciego: "Sin datos del mercado", arrancando: "Arrancando" };

export function Encabezado({ e, sinConexion, vista, alIr, tema, alTema }: {
  e: Estado | undefined; sinConexion: boolean; vista: Prefs["vista"]; alIr: (v: Prefs["vista"]) => void;
  tema: Prefs["tema"]; alTema: (t: Prefs["tema"]) => void;
}) {
  const ahora = useAhora();
  const prox = e?.proxima_decision_utc ? Date.parse(e.proxima_decision_utc) : null;
  const falta = prox ? prox - ahora : null;
  const estado = sinConexion ? "error" : e?.salud.estado ?? "arrancando";
  const siguienteTema: Record<Prefs["tema"], Prefs["tema"]> = { auto: "oscuro", oscuro: "claro", claro: "auto" };
  const IconoTema = tema === "oscuro" ? Moon : tema === "claro" ? Sun : SunMoon;
  return (
    <header className="sticky top-0 z-30 border-b border-borde bg-fondo/80 pt-[env(safe-area-inset-top)] backdrop-blur-xl">
      <div className="mx-auto flex h-14 max-w-[1680px] items-center gap-3 px-3 sm:px-5">
        <div className="flex items-center gap-2.5">
          <Marca />
          <span className="text-[15px] font-semibold tracking-tight whitespace-nowrap">Bot Jorge</span>
          <Chip tono="acento" className="hidden sm:inline-flex">SIMULACIÓN</Chip>
        </div>
        <nav className="ml-4 hidden h-full items-stretch gap-1 lg:flex" aria-label="Secciones">
          {VISTAS.map((v) => (
            <button key={v.id} type="button" onClick={() => alIr(v.id)} aria-current={vista === v.id ? "page" : undefined}
              className={cx("relative flex items-center gap-2 px-3 text-[13px] font-medium text-texto-3 transition-colors hover:text-texto [&>svg]:size-4",
                            vista === v.id && "text-texto")}>
              {v.icono}{v.nombre}
              {vista === v.id && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-gradient-to-r from-acento to-acento-2" />}
            </button>
          ))}
        </nav>
        <div className="ml-auto flex items-center gap-2">
          <span className="hidden items-center gap-2 rounded-lg border border-borde bg-panel px-2.5 py-1.5 text-xs text-texto-2 sm:flex" role="status">
            <PuntoEstado estado={estado} />
            {sinConexion ? "Sin conexión con el bot" : SALUD[e?.salud.estado ?? "arrancando"]}
            {!sinConexion && e?.salud.mercado && <span className="text-texto-3">· {e.salud.mercado}</span>}
          </span>
          <span className="flex items-center gap-2 rounded-lg border border-borde bg-panel px-2.5 py-1.5 text-xs text-texto-2" title="Próxima decisión del bot">
            <span className="sm:hidden"><PuntoEstado estado={estado} /></span>
            <Clock className="size-3.5 text-acento" />
            <span className="hidden text-texto-3 md:inline">Próxima decisión</span>
            <span className="num font-semibold text-texto">{falta === null ? "—" : falta > 0 ? cuentaAtras(falta) : "ahora"}</span>
          </span>
          <span className="num hidden rounded-lg border border-borde bg-panel px-2.5 py-1.5 text-xs text-texto-2 xl:inline">{horaSegundos(ahora)}</span>
          <button type="button" onClick={() => alTema(siguienteTema[tema])} title={`Tema: ${tema}`} aria-label={`Tema: ${tema}. Cambiar.`}
            className="grid size-8 place-items-center rounded-lg border border-borde bg-panel text-texto-2 hover:text-texto">
            <IconoTema className="size-4" />
          </button>
        </div>
      </div>
    </header>
  );
}

/** Cinta de precios: las diez monedas con su cambio de la semana. Tocar una lleva a su gráfica. */
export function Cinta({ e, m, alElegir }: { e: Estado | undefined; m: Mercado | undefined; alElegir: (s: string) => void }) {
  if (!e) return <div className="h-11 border-b border-borde" />;
  const porSimbolo = new Map((m?.monedas ?? []).map((x) => [x.simbolo, x]));
  return (
    <div className="border-b border-borde bg-panel/60">
      <div className="barra-desliza mx-auto flex h-11 max-w-[1680px] items-center gap-1 overflow-x-auto px-3 sm:px-5">
        {e.monedas.map((mo) => {
          const serie = porSimbolo.get(mo.simbolo)?.c ?? [];
          const cambio = serie.length && valido(mo.precio) ? mo.precio / serie[0] - 1 : null;
          const s = signoDe(cambio, 0.0005);
          return (
            <button key={mo.simbolo} type="button" onClick={() => alElegir(mo.simbolo)}
              className="flex shrink-0 items-center gap-2 rounded-md px-2.5 py-1 text-xs transition-colors hover:bg-panel-2">
              <span className="font-semibold text-texto">{base(mo.simbolo)}</span>
              <span className="num text-texto-2">{precio(mo.precio)}</span>
              <span className={cx("num", s === "sube" ? "text-sube" : s === "baja" ? "text-baja" : "text-texto-3")}>
                {valido(cambio) ? pctFraccion(cambio, 1, true) : ""}
              </span>
              <MiniLinea valores={[...serie, ...(valido(mo.precio) ? [mo.precio] : [])]} ancho={44} alto={16} signo={s} />
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function NavInferior({ vista, alIr }: { vista: Prefs["vista"]; alIr: (v: Prefs["vista"]) => void }) {
  return (
    <nav aria-label="Secciones"
      className="fixed inset-x-0 bottom-0 z-30 grid grid-cols-5 border-t border-borde bg-fondo/85 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden">
      {VISTAS.map((v) => (
        <button key={v.id} type="button" onClick={() => alIr(v.id)} aria-current={vista === v.id ? "page" : undefined}
          className={cx("relative flex h-15 flex-col items-center justify-center gap-1 text-[11px] font-medium text-texto-3 [&>svg]:size-5",
                        vista === v.id && "text-acento")}>
          {vista === v.id && <span className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-gradient-to-r from-acento to-acento-2" />}
          {v.icono}{v.nombre}
        </button>
      ))}
    </nav>
  );
}

export function Avisos({ e }: { e: Estado | undefined }) {
  if (!e?.avisos?.length) return null;
  return (
    <div className="grid gap-2">
      {[...e.avisos].reverse().map((a) => (
        <p key={a.utc + a.texto} className="flex items-center gap-3 rounded-lg border border-aviso/30 bg-aviso/10 px-3.5 py-2.5 text-[13px]">
          <TriangleAlert className="size-4 shrink-0 text-aviso" />
          <span className="flex-1">{a.texto}</span>
          <time className="num shrink-0 text-xs text-texto-3">{cuando(a.utc)}</time>
        </p>
      ))}
    </div>
  );
}

