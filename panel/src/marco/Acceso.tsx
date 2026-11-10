import { LockKeyhole } from "lucide-react";
import { useState } from "react";
import { Boton } from "../componentes/ui";
import { Marca } from "./Marca";

export function Acceso({ error, alEntrar }: { error?: string; alEntrar: (token: string) => void }) {
  const [valor, setValor] = useState("");
  return (
    <main className="fondo-rejilla relative grid min-h-dvh place-items-center overflow-hidden px-4">
      <div className="pointer-events-none absolute -top-40 left-1/2 h-96 w-[48rem] -translate-x-1/2 rounded-full bg-acento/15 blur-3xl" />
      <form
        className="panel entra relative w-full max-w-sm p-7"
        onSubmit={(ev) => { ev.preventDefault(); if (valor.trim()) alEntrar(valor.trim()); setValor(""); }}
      >
        <Marca grande />
        <h1 className="mt-5 text-xl font-semibold tracking-tight">Bot Jorge</h1>
        <p className="mt-1 text-sm text-texto-2">Panel de la simulación</p>
        <label htmlFor="token" className="mt-7 mb-1.5 block text-xs font-medium text-texto-2">Token del panel</label>
        <input
          id="token" type="password" autoComplete="current-password" spellCheck={false} required autoFocus
          value={valor} onChange={(ev) => setValor(ev.target.value)}
          className="num h-11 w-full rounded-lg border border-borde-2 bg-fondo px-3 text-sm text-texto outline-none transition focus:border-acento focus:ring-2 focus:ring-acento/30"
        />
        <Boton type="submit" variante="primario" className="mt-4 h-11 w-full">Entrar</Boton>
        {error && <p role="alert" className="mt-3 text-sm text-baja">{error}</p>}
        <p className="mt-6 flex gap-2 text-xs leading-relaxed text-texto-3">
          <LockKeyhole className="mt-0.5 size-3.5 shrink-0" />
          <span>Está en <code className="num text-texto-2">.env</code>, línea <code className="num text-texto-2">JORGE_BOT_PANEL_TOKEN</code>. Se guarda solo en este aparato.</span>
        </p>
      </form>
    </main>
  );
}
