// Tema efectivo (auto sigue al sistema) y colores concretos para las gráficas, que no entienden var().
import { useEffect, useState } from "react";
import type { Prefs } from "./prefs";

const oscuroDelSistema = () => window.matchMedia("(prefers-color-scheme: dark)").matches;

export function useTemaEfectivo(tema: Prefs["tema"]): "oscuro" | "claro" {
  const [sistema, setSistema] = useState(oscuroDelSistema());
  useEffect(() => {
    const m = window.matchMedia("(prefers-color-scheme: dark)");
    const f = () => setSistema(m.matches);
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, []);
  const efectivo = tema === "auto" ? (sistema ? "oscuro" : "claro") : tema;
  useEffect(() => {
    document.documentElement.dataset.tema = efectivo;
    document.querySelector('meta[name="theme-color"]')?.setAttribute("content", efectivo === "oscuro" ? "#07090d" : "#f3f5f9");
  }, [efectivo]);
  return efectivo;
}

export interface Colores {
  fondo: string; panel: string; borde: string; rejilla: string; texto: string; texto2: string; texto3: string;
  acento: string; acento2: string; sube: string; baja: string; subeMarca: string; bajaMarca: string; aviso: string;
  serie1: string; serie2: string; serie3: string; serie4: string;
}

export function colores(): Colores {
  const s = getComputedStyle(document.documentElement);
  const v = (n: string) => s.getPropertyValue(n).trim();
  return {
    fondo: v("--c-fondo"), panel: v("--c-panel"), borde: v("--c-borde"), rejilla: v("--c-rejilla"), texto: v("--c-texto"),
    texto2: v("--c-texto-2"), texto3: v("--c-texto-3"), acento: v("--c-acento"), acento2: v("--c-acento-2"),
    sube: v("--c-sube"), baja: v("--c-baja"), subeMarca: v("--c-sube-marca"), bajaMarca: v("--c-baja-marca"),
    aviso: v("--c-aviso"), serie1: v("--c-serie-1"), serie2: v("--c-serie-2"), serie3: v("--c-serie-3"), serie4: v("--c-serie-4"),
  };
}

/** "#rrggbb" + opacidad → "rgba(...)", para rellenos de área. */
export function conAlfa(hex: string, a: number): string {
  const h = hex.replace("#", "");
  const n = parseInt(h.length === 3 ? h.split("").map((c) => c + c).join("") : h, 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}
