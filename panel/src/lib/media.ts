import { useEffect, useState } from "react";

/** Si se cumple una consulta de medios (por ejemplo, pantalla ancha), y se actualiza al cambiar. */
export function useMedia(consulta: string): boolean {
  const [si, setSi] = useState(() => window.matchMedia(consulta).matches);
  useEffect(() => {
    const m = window.matchMedia(consulta);
    const f = () => setSi(m.matches);
    f();
    m.addEventListener("change", f);
    return () => m.removeEventListener("change", f);
  }, [consulta]);
  return si;
}
