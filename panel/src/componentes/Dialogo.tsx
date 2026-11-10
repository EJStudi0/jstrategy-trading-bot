// Confirmaciones con el <dialog> del navegador: accesible, con foco atrapado y sin estilos inyectados.
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from "react";
import { Boton } from "./ui";

interface Pregunta {
  titulo: string;
  texto: ReactNode;
  si?: string;
  peligro?: boolean;
}

const Contexto = createContext<(p: Pregunta) => Promise<boolean>>(async () => false);
export const useConfirmar = () => useContext(Contexto);

export function ProveedorDeConfirmacion({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [pregunta, setPregunta] = useState<Pregunta | null>(null);
  const resolver = useRef<(v: boolean) => void>(() => {});

  const confirmar = useCallback((p: Pregunta) => {
    setPregunta(p);
    return new Promise<boolean>((r) => {
      resolver.current = r;
      requestAnimationFrame(() => ref.current?.showModal());
    });
  }, []);

  const cerrar = (v: boolean) => {
    ref.current?.close();
    resolver.current(v);
  };

  return (
    <Contexto.Provider value={confirmar}>
      {children}
      <dialog
        ref={ref}
        onCancel={(e) => { e.preventDefault(); cerrar(false); }}
        aria-labelledby="dialogo-titulo"
        className="panel m-auto w-[min(440px,calc(100vw-32px))] p-0 text-texto backdrop:bg-black/60 open:entra"
      >
        {pregunta && (
          <div className="p-5">
            <h2 id="dialogo-titulo" className="text-base font-semibold tracking-tight">{pregunta.titulo}</h2>
            <div className="mt-2 text-sm leading-relaxed text-texto-2">{pregunta.texto}</div>
            <div className="mt-5 flex flex-wrap justify-end gap-2">
              <Boton onClick={() => cerrar(false)}>Cancelar</Boton>
              <Boton variante={pregunta.peligro ? "peligro" : "primario"} onClick={() => cerrar(true)} autoFocus>
                {pregunta.si ?? "Sí"}
              </Boton>
            </div>
          </div>
        )}
      </dialog>
    </Contexto.Provider>
  );
}
