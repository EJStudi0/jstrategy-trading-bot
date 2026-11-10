/// <reference types="vitest/config" />
import { createHash } from "node:crypto";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";

const RAIZ = fileURLToPath(new URL(".", import.meta.url));
// Lo que define la página. tests/test_panel.py calcula la misma huella y falla si la compilación de
// bot/panel_estatico/ no corresponde a estas fuentes (alguien cambió el panel y no lo compiló).
const FUENTES = ["index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json", "src", "public"];

function ficheros(ruta: string): string[] {
  if (statSync(ruta).isDirectory()) return readdirSync(ruta).flatMap((n) => ficheros(join(ruta, n)));
  return [ruta];
}

export function huellaDeFuentes(): string {
  const todos = FUENTES.flatMap((f) => ficheros(join(RAIZ, f)))
    .map((r) => relative(RAIZ, r).split(sep).join("/"))
    .sort();
  const h = createHash("sha256");
  for (const r of todos) {
    h.update(r + "\n" + createHash("sha256").update(readFileSync(join(RAIZ, r))).digest("hex") + "\n");
  }
  return h.digest("hex");
}

function huella(): Plugin {
  return {
    name: "huella-de-fuentes",
    apply: "build",
    generateBundle() {
      this.emitFile({ type: "asset", fileName: "huella.json", source: JSON.stringify({ fuentes: huellaDeFuentes() }) + "\n" });
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), huella()],
  build: {
    outDir: "../bot/panel_estatico",
    emptyOutDir: true,
    assetsInlineLimit: 0,      // nada en línea: la política de contenido no deja data: ni estilos en línea
    target: "es2022",
    chunkSizeWarningLimit: 1200,
  },
  server: { port: 5173, proxy: { "/api": "http://127.0.0.1:8790" } },
  test: { include: ["src/**/*.test.ts"] },
});
