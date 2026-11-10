import { cx } from "../componentes/ui";

/** El logotipo: un cuadro con degradado y una línea que sube. */
export function Marca({ grande = false }: { grande?: boolean }) {
  return (
    <span className={cx("relative inline-grid shrink-0 place-items-center rounded-[9px] bg-gradient-to-br from-acento to-acento-2 shadow-[0_0_24px_-4px_var(--c-acento)]",
                        grande ? "size-12 rounded-xl" : "size-7")}>
      <svg viewBox="0 0 24 24" className={grande ? "size-7" : "size-4"} fill="none" stroke="white" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M5 16l4.2-4.4 3.4 2.6 5.4-6.8" />
      </svg>
    </span>
  );
}
