import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { SinAcceso, fragmento, hayToken, olvidarToken, ponerToken } from "./api";
import { ProveedorDeConfirmacion } from "./componentes/Dialogo";
import { useAsistente, useCentinela, useCurva, useCurvaCentinela, useEstado, useGanancias, useGrafica, useMercado, useOperaciones } from "./hooks/datos";
import { haceCuanto } from "./lib/formato";
import { ponerPref, usePrefs, type Prefs } from "./lib/prefs";
import { useTemaEfectivo } from "./lib/tema";
import { ZONA } from "./lib/tiempo";
import { Acceso } from "./marco/Acceso";
import { Marca } from "./marco/Marca";
import { Avisos, Cinta, Encabezado, NavInferior, VISTAS, useAhora } from "./marco/Marco";
import { Asistente } from "./vistas/Asistente";
import { Centinela } from "./vistas/Centinela";
import { Ganancias } from "./vistas/Ganancias";
import { Mando } from "./vistas/Mando";
import { Mercado } from "./vistas/Mercado";
import { Resumen } from "./vistas/Resumen";

// Un enlace con #vista=… o #tema=… abre ahí (el token del fragmento ya lo recogió api.ts).
const vistaInicial = fragmento.get("vista");
if (VISTAS.some((v) => v.id === vistaInicial)) ponerPref("vista", vistaInicial as Prefs["vista"]);
const temaInicial = fragmento.get("tema");
if (temaInicial === "auto" || temaInicial === "oscuro" || temaInicial === "claro") ponerPref("tema", temaInicial);

export function App() {
  const [prefs, poner] = usePrefs();
  const tema = useTemaEfectivo(prefs.tema);
  const [conToken, setConToken] = useState(hayToken());
  const [errorAcceso, setErrorAcceso] = useState<string>();
  const qc = useQueryClient();

  const estado = useEstado(conToken);
  const ganancias = useGanancias(conToken);
  const curva = useCurva(prefs.horas, conToken && prefs.vista === "resumen");
  const mercado = useMercado(conToken);
  const operaciones = useOperaciones(conToken && prefs.vista === "mercado");
  const grafica = useGrafica(prefs.moneda, conToken && prefs.vista === "mercado");
  const centinela = useCentinela(conToken);
  const curvaCentinela = useCurvaCentinela(prefs.horas, conToken && prefs.vista === "centinela");
  const asistente = useAsistente(conToken);
  const ahora = useAhora(5000);

  // Un 401 en cualquier petición devuelve a la pantalla del token.
  const errores = [estado.error, ganancias.error, curva.error, mercado.error, operaciones.error, grafica.error, centinela.error, asistente.error];
  const sinAcceso = errores.find((x) => x instanceof SinAcceso) as SinAcceso | undefined;
  useEffect(() => {
    if (sinAcceso) {
      setConToken(false);
      setErrorAcceso(sinAcceso.motivo === "incorrecto" ? "El token no es correcto." : undefined);
      qc.clear();
    }
  }, [sinAcceso, qc]);

  if (!conToken) {
    return <Acceso error={errorAcceso} alEntrar={(t) => { ponerToken(t); setErrorAcceso(undefined); setConToken(true); }} />;
  }
  const e = estado.data;
  const irA = (v: Prefs["vista"]) => { poner("vista", v); window.scrollTo({ top: 0 }); };
  const verMoneda = (s: string) => { poner("moneda", s); irA("mercado"); };
  const contadores = { asistente: asistente.data?.sin_ver ?? 0 };
  const sinConexion = estado.isError && !(estado.error instanceof SinAcceso);

  return (
    <ProveedorDeConfirmacion>
      <div className="min-h-dvh pb-[calc(4.5rem+env(safe-area-inset-bottom))] lg:pb-0">
        <Encabezado e={e} sinConexion={sinConexion} vista={prefs.vista} alIr={irA} tema={prefs.tema} alTema={(t) => poner("tema", t)} contadores={contadores} />
        <Cinta e={e} m={mercado.data} alElegir={verMoneda} />
        <main className="mx-auto grid max-w-[1680px] gap-3 px-3 py-3 sm:gap-4 sm:px-5 sm:py-5">
          {!e ? (
            <div className="grid min-h-[60vh] place-items-center">
              <div className="grid justify-items-center gap-3 text-sm text-texto-3">
                <span className="animate-pulse"><Marca grande /></span>
                {sinConexion ? "No llego al bot. Sigo intentándolo…" : "Cargando…"}
              </div>
            </div>
          ) : (
            <>
              <Avisos e={e} />
              <div key={prefs.vista} className="entra">
                {prefs.vista === "resumen" && (
                  <Resumen e={e} g={ganancias.data} curva={curva.data} m={mercado.data} prefs={prefs} poner={poner} tema={tema} alElegirMoneda={verMoneda} />
                )}
                {prefs.vista === "ganancias" && <Ganancias e={e} g={ganancias.data} prefs={prefs} poner={poner} tema={tema} />}
                {prefs.vista === "mercado" && (
                  <Mercado e={e} m={mercado.data} g={grafica.data} ops={operaciones.data} prefs={prefs} poner={poner} tema={tema} />
                )}
                {prefs.vista === "centinela" && (
                  <Centinela c={centinela.data} curva={curvaCentinela.data} prefs={prefs} poner={poner} tema={tema} />
                )}
                {prefs.vista === "asistente" && <Asistente a={asistente.data} e={e} />}
                {prefs.vista === "mando" && (
                  <Mando e={e} alIr={irA} prefs={prefs} poner={poner} alOlvidar={() => { olvidarToken(); qc.clear(); setConToken(false); }} />
                )}
              </div>
            </>
          )}
          <footer className="flex flex-wrap items-center justify-between gap-x-6 gap-y-1 border-t border-borde pt-3 text-[11px] text-texto-3">
            <span>{estado.dataUpdatedAt ? "Actualizado " + haceCuanto(ahora - estado.dataUpdatedAt) : "—"} · horas de tu zona ({ZONA})</span>
            <span>
              Simulación: dinero ficticio, mercado real · Gráficas:{" "}
              <a href="https://www.tradingview.com/" target="_blank" rel="noopener noreferrer" className="underline decoration-borde-2 underline-offset-2 hover:text-texto-2">
                TradingView Lightweight Charts™
              </a>{" "}
              Copyright © 2025 TradingView, Inc.
            </span>
          </footer>
        </main>
        <NavInferior vista={prefs.vista} alIr={irA} contadores={contadores} />
      </div>
    </ProveedorDeConfirmacion>
  );
}
