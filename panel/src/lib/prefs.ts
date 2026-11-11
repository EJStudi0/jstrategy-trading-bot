// Preferencias de este aparato (vista, tema, periodos...). Solo comodidad: si el almacenamiento
// falla (modo privado), todo sigue funcionando con los valores por defecto.
import { useCallback, useEffect, useState } from "react";

const CLAVE = "bot_jorge_pref_v2";

export interface Prefs {
  vista: "resumen" | "ganancias" | "mercado" | "centinela" | "asistente" | "mando";
  /** La sub-pestaña del asistente que se miró la última vez. */
  sub: "avisos" | "operar" | "monedas" | "ajustes";
  tema: "auto" | "oscuro" | "claro";
  horas: 24 | 168 | 720 | 0;
  vsBtc: boolean;
  dias: 14 | 30 | 90 | 0;
  moneda: string;
  reloj: string;
  canal: string;
  marcas: boolean;
}

const BASE: Prefs = { vista: "resumen", sub: "avisos", tema: "auto", horas: 168, vsBtc: false, dias: 30, moneda: "BTCUSDT",
                      reloj: "8/32", canal: "20", marcas: true };

const VALIDOS: { [K in keyof Prefs]?: readonly Prefs[K][] } = {
  vista: ["resumen", "ganancias", "mercado", "centinela", "asistente", "mando"],
  sub: ["avisos", "operar", "monedas", "ajustes"],
  tema: ["auto", "oscuro", "claro"],
  horas: [24, 168, 720, 0],
  dias: [14, 30, 90, 0],
};

function leer(): Prefs {
  let guardadas: Partial<Prefs> = {};
  try {
    guardadas = JSON.parse(localStorage.getItem(CLAVE) || "{}") || {};
  } catch {
    /* nada */
  }
  const p = { ...BASE, ...guardadas } as Prefs;
  for (const [k, lista] of Object.entries(VALIDOS) as [keyof Prefs, readonly unknown[]][]) {
    if (!lista.includes(p[k])) (p as unknown as Record<string, unknown>)[k] = BASE[k];
  }
  return p;
}

let actuales = leer();
const oyentes = new Set<(p: Prefs) => void>();

export function ponerPref<K extends keyof Prefs>(k: K, v: Prefs[K]) {
  actuales = { ...actuales, [k]: v };
  try {
    localStorage.setItem(CLAVE, JSON.stringify(actuales));
  } catch {
    /* nada */
  }
  oyentes.forEach((f) => f(actuales));
}

export function usePrefs(): [Prefs, <K extends keyof Prefs>(k: K, v: Prefs[K]) => void] {
  const [p, setP] = useState(actuales);
  useEffect(() => {
    oyentes.add(setP);
    return () => void oyentes.delete(setP);
  }, []);
  const poner = useCallback(<K extends keyof Prefs>(k: K, v: Prefs[K]) => ponerPref(k, v), []);
  return [p, poner];
}
