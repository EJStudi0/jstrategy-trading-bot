import { describe, expect, it } from "vitest";
import { cifra, claveDia, cuentaAtras, dinero, duracion, fechaLocal, pct, pctFraccion, precio, signoDe } from "./formato";
import { alDia, aniosParaDoblar, diasDelAnio } from "./niveles";

describe("cifras", () => {
  it("usa coma decimal, punto de miles y el menos tipográfico", () => {
    expect(cifra(4963.04)).toBe("4.963,04");
    expect(cifra(-6.75, 2)).toBe("\u22126,75");
    expect(cifra(0.3, 2, true)).toBe("+0,30");
    expect(cifra(-0.001, 2, true)).toBe("0,00");
    expect(cifra(null)).toBe("—");
  });
  it("dinero, porcentajes y precios", () => {
    expect(dinero(1.07, { signo: true })).toBe("+1,07 $");
    expect(pctFraccion(0.123, 1)).toBe("12,3 %");
    expect(pct(-8.7, 1)).toBe("−8,7 %");
    expect(precio(74016.4)).toBe("74.016");
    expect(precio(0.17764)).toBe("0,1776");
    expect(precio(86.02)).toBe("86,02");
  });
  it("el signo ignora los céntimos de ruido", () => {
    expect(signoDe(0.004)).toBe("");
    expect(signoDe(0.31)).toBe("sube");
    expect(signoDe(-2)).toBe("baja");
  });
});

describe("fechas", () => {
  it("la fecha de un día es su medianoche local", () => {
    const f = fechaLocal("2026-11-10");
    expect(f.getDate()).toBe(10);
    expect(f.getHours()).toBe(0);
    expect(claveDia(f)).toBe("2026-11-10");
  });
  it("duraciones y cuenta atrás", () => {
    expect(duracion(45_000)).toBe("45 s");
    expect(duracion(3 * 3600e3 + 12 * 60e3)).toBe("3 h 12 min");
    expect(cuentaAtras(2 * 3600e3 + 41 * 60e3 + 7e3)).toBe("02:41:07");
  });
});

describe("lo medido en dólares", () => {
  it("un 8,2 % al año con 4.963 $ son algo más de un dólar al día", () => {
    expect(alDia(8.2, 4963)).toBeCloseTo(1.0717, 3);
  });
  it("el último año medido acaba en su fecha", () => {
    expect(diasDelAnio("2024", "2026-11-09")).toBe(366);
    expect(diasDelAnio("2026", "2026-11-09")).toBe(312);
  });
  it("al 8 % el dinero se dobla en unos 9 años", () => {
    expect(aniosParaDoblar(8.2)).toBeCloseTo(8.8, 1);
  });
});
