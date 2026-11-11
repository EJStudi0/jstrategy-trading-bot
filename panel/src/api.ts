// Conversación con el bot. El token va SIEMPRE en una cabecera (nunca en cookies ni en la URL):
// un navegador no añade esa cabecera por su cuenta, así que otra página no puede pulsar los botones.

const CLAVE = "bot_jorge_token";

export class SinAcceso extends Error {
  constructor(public motivo: "falta" | "incorrecto") {
    super(motivo === "falta" ? "Falta el token" : "El token no es correcto");
  }
}

function leerInicial(): string | null {
  // Se admite en el fragmento (#token=…, que nunca viaja al servidor), para el ensayo. En la consulta
  // (?token=…) no: viajaría al servidor y quedaría en el historial.
  const frag = new URLSearchParams(location.hash.replace(/^#/, ""));
  const dado = frag.get("token");
  if (dado) {
    guardar(dado);
    return dado;
  }
  try {
    return localStorage.getItem(CLAVE);
  } catch {
    return null;
  }
}

/** Lo que llegó en el fragmento además del token (vista, tema), antes de limpiarlo de la barra. */
export const fragmento = new URLSearchParams(location.hash.replace(/^#/, ""));

function guardar(t: string) {
  try {
    localStorage.setItem(CLAVE, t);
  } catch {
    /* modo privado: vale solo para esta pestaña */
  }
}

let token: string | null = leerInicial();
if (location.hash || location.search) history.replaceState(null, "", location.pathname);

export const hayToken = () => !!token;

export function ponerToken(t: string) {
  token = t.trim();
  guardar(token);
}

export function olvidarToken() {
  token = null;
  try {
    localStorage.removeItem(CLAVE);
  } catch {
    /* nada */
  }
}

export async function api<T>(ruta: string, cuerpo?: unknown): Promise<T> {
  if (!token) throw new SinAcceso("falta");
  const opciones: RequestInit = { headers: { Authorization: "Bearer " + token }, cache: "no-store" };
  if (cuerpo !== undefined) {
    opciones.method = "POST";
    opciones.headers = { ...opciones.headers, "Content-Type": "application/json" };
    opciones.body = JSON.stringify(cuerpo);
  }
  const r = await fetch(ruta, opciones);
  if (r.status === 401) {
    olvidarToken();
    throw new SinAcceso("incorrecto");
  }
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((datos as { detail?: string }).detail || "Error " + r.status);
  return datos as T;
}
