import { describe, expect, it } from "vitest";
import {
  distanciaPct, etiquetaMovimiento, fraseMando, gananciaDeObjetivo, hastaCuando, importante, leerNumero, objetivoPorMultiplo,
  precioParaCasilla, riesgoDeStop, stopPara, stopPorPct,
} from "./asistente";

describe("asistente", () => {
  it("pone nombre al movimiento de una moneda", () => {
    expect(etiquetaMovimiento(0.79)).toBe("tranquilo");
    expect(etiquetaMovimiento(0.8)).toBe("normal");
    expect(etiquetaMovimiento(1.29)).toBe("normal");
    expect(etiquetaMovimiento(1.3)).toBe("movido");
    expect(etiquetaMovimiento(null)).toBe("—");
  });
  it("calcula lo que se pierde si salta el stop", () => {
    // Largo de 200 USDT a 100 con stop en 95: pierde el 5 % → 10 USDT, el 1 % de una cuenta de 1.000.
    const largo = riesgoDeStop(1, 100, 95, 200, 1000);
    expect(largo?.usdt).toBeCloseTo(10);
    expect(largo?.pct).toBeCloseTo(1);
    // Corto: el stop va por encima.
    expect(riesgoDeStop(-1, 100, 102, 500, 1000)?.usdt).toBeCloseTo(10);
    // Stop del lado equivocado, o sin precio: no se enseña nada.
    expect(riesgoDeStop(1, 100, 105, 200, 1000)).toBeNull();
    expect(riesgoDeStop(-1, 100, 95, 200, 1000)).toBeNull();
    expect(riesgoDeStop(1, null, 95, 200, 1000)).toBeNull();
    expect(riesgoDeStop(1, 100, 95, 200, null)?.pct).toBeNull();
  });
  it("lee números con coma o con punto y rellena casillas con coma", () => {
    expect(leerNumero("")).toBeNull();
    expect(leerNumero(" 250 ")).toBe(250);
    expect(leerNumero("0,1776")).toBeCloseTo(0.1776);
    expect(leerNumero("74016.5")).toBe(74016.5);
    expect(leerNumero("74.016,5")).toBe(74016.5);
    expect(leerNumero("abc")).toBeNaN();
    expect(leerNumero("-5")).toBeNaN();
    expect(precioParaCasilla(74016.44)).toBe("74016,4");
    expect(precioParaCasilla(0.177641)).toBe("0,17764");
    expect(leerNumero(precioParaCasilla(86.019)!)).toBeCloseTo(86.02);
  });
  it("el stop sugerido solo sirve para su lado", () => {
    expect(stopPara({ precio: 100, stop: 96 }, 1)).toBe(96);
    expect(stopPara({ precio: 100, stop: 96 }, -1)).toBeNull();
    expect(stopPara({ precio: 100, stop: null }, 1)).toBeNull();
  });
  it("pone el stop a un tanto por ciento, del lado que toca", () => {
    expect(stopPorPct(1, 100, 2)).toBeCloseTo(98);
    expect(stopPorPct(-1, 100, 2)).toBeCloseTo(102);
    expect(stopPorPct(1, null, 2)).toBeNull();
    expect(stopPorPct(1, 100, 0)).toBeNull();
  });
  it("pone el objetivo a un múltiplo del riesgo", () => {
    expect(objetivoPorMultiplo(1, 100, 98, 2)).toBeCloseTo(104);
    expect(objetivoPorMultiplo(-1, 100, 103, 1)).toBeCloseTo(97);
    expect(objetivoPorMultiplo(1, 100, 102, 2)).toBeNull();   // stop del lado equivocado
    expect(objetivoPorMultiplo(1, 100, null, 2)).toBeNull();
    // Con ese objetivo se gana justo el múltiplo de lo que se arriesga.
    const riesgo = riesgoDeStop(1, 100, 98, 500, 1000)!.usdt;
    expect(gananciaDeObjetivo(1, 100, objetivoPorMultiplo(1, 100, 98, 3), 500)).toBeCloseTo(3 * riesgo);
    expect(gananciaDeObjetivo(1, 100, 95, 500)).toBeNull();
  });
  it("mide lo que falta hasta un nivel", () => {
    expect(distanciaPct(100, 101.5)).toBeCloseTo(1.5);
    expect(distanciaPct(100, 90)).toBeCloseTo(-10);
    expect(distanciaPct(null, 90)).toBeNull();
    expect(distanciaPct(0, 90)).toBeNull();
  });
  it("resume el estado del bot y deja fuera lo silenciado", () => {
    const ahora = new Date(2026, 10, 11, 10, 0).getTime();
    expect(fraseMando("auto", null, ahora)).toBe("Automático");
    expect(fraseMando("pausa", new Date(2026, 10, 11, 18, 30).getTime(), ahora)).toBe("En pausa hasta las 18:30");
    expect(fraseMando("neutral", new Date(2026, 10, 12, 2, 0).getTime(), ahora)).toBe("Cubierto hasta mañana a las 02:00");
    expect(fraseMando("pausa", null, ahora)).toBe("En pausa");
    expect(fraseMando("fuera", null, ahora)).toBe("Fuera");
    expect(importante({ fuerza: "alta" })).toBe(true);
    expect(importante({ fuerza: "alta", callada: true })).toBe(false);
    expect(importante({ fuerza: "baja" })).toBe(false);
  });
  it("dice cuándo caduca un mando", () => {
    const ahora = new Date(2026, 10, 11, 10, 0).getTime();
    expect(hastaCuando(new Date(2026, 10, 11, 14, 0).getTime(), ahora)).toBe("a las 14:00");
    expect(hastaCuando(new Date(2026, 10, 12, 2, 5).getTime(), ahora)).toBe("mañana a las 02:05");
    expect(hastaCuando(new Date(2026, 10, 14, 9, 0).getTime(), ahora)).toBe("el 14 nov a las 09:00");
  });
});
