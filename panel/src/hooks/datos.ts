// Lo que se pide al bot y cada cuánto. TanStack Query guarda lo último que llegó: al refrescar,
// la pantalla se queda como estaba hasta que llega lo nuevo (sin parpadeos ni esqueletos).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ZONA } from "../lib/tiempo";
import type { Asistente, Centinela, Estado, Ganancias, Grafica, Mando, Mercado, ModoVeto, Operacion, OrdenManual, PuntoCurva } from "../tipos";

const S = 1000;

export const useEstado = (activo: boolean) =>
  useQuery({ queryKey: ["estado"], queryFn: () => api<Estado>("/api/estado"), refetchInterval: 15 * S, enabled: activo });

export const useGanancias = (activo: boolean) =>
  useQuery({
    queryKey: ["ganancias", ZONA],
    queryFn: () => api<Ganancias>("/api/ganancias?zona=" + encodeURIComponent(ZONA)),
    refetchInterval: 15 * S,
    enabled: activo,
  });

export const useCurva = (horas: number, activo: boolean) =>
  useQuery({
    queryKey: ["curva", horas],
    queryFn: () => api<PuntoCurva[]>("/api/patrimonio?horas=" + horas),
    refetchInterval: 5 * 60 * S,
    placeholderData: keepPreviousData,
    enabled: activo,
  });

export const useMercado = (activo: boolean) =>
  useQuery({ queryKey: ["mercado"], queryFn: () => api<Mercado>("/api/mercado"), refetchInterval: 5 * 60 * S, enabled: activo });

export const useOperaciones = (activo: boolean) =>
  useQuery({ queryKey: ["operaciones"], queryFn: () => api<Operacion[]>("/api/operaciones?n=300"), refetchInterval: 60 * S, enabled: activo });

export const useGrafica = (simbolo: string, activo: boolean) =>
  useQuery({
    queryKey: ["grafica", simbolo],
    queryFn: () => api<Grafica>("/api/grafica?simbolo=" + encodeURIComponent(simbolo)),
    refetchInterval: 5 * 60 * S,
    placeholderData: keepPreviousData,
    enabled: activo,
  });

export const useCentinela = (activo: boolean) =>
  useQuery({ queryKey: ["centinela"], queryFn: () => api<Centinela>("/api/centinela"), refetchInterval: 30 * S, enabled: activo });

export const useCurvaCentinela = (horas: number, activo: boolean) =>
  useQuery({
    queryKey: ["centinela-curva", horas],
    queryFn: () => api<PuntoCurva[]>("/api/centinela/patrimonio?horas=" + horas),
    refetchInterval: 5 * 60 * S,
    placeholderData: keepPreviousData,
    enabled: activo,
  });

function useRefrescarTodo() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

/** Cambiar el modo; con `horas`, la pausa o el «cubrir todo» caducan solos. Salir a USDT lo pide el servidor dos veces (la segunda con su código). */
export function usePonerMando() {
  const refrescar = useRefrescarTodo();
  return useMutation({
    mutationFn: async ({ mando, horas = 0 }: { mando: Mando; horas?: number }) => {
      let r = await api<{ confirmar?: string; mando?: Mando }>("/api/mando", { mando, horas });
      if (r.confirmar) r = await api("/api/mando", { mando, horas, confirmacion: r.confirmar });
      return r;
    },
    onSettled: refrescar,
  });
}

export function useCambiarAjustes() {
  const refrescar = useRefrescarTodo();
  return useMutation({
    mutationFn: (ajustes: Record<string, number>) => api<{ ajustes: Record<string, number> }>("/api/ajustes", ajustes),
    onSettled: refrescar,
  });
}

/** Encender o apagar Centinela. Apagado no vende: deja de operar y conserva lo que tenga. */
export function usePonerCentinela() {
  const refrescar = useRefrescarTodo();
  return useMutation({
    mutationFn: (encendido: boolean) => api<{ encendido: boolean }>("/api/centinela/interruptor", { encendido }),
    onSettled: refrescar,
  });
}

// ── Asistente ────────────────────────────────────────────────────────────────

export const useAsistente = (activo: boolean) =>
  useQuery({ queryKey: ["asistente"], queryFn: () => api<Asistente>("/api/asistente"), refetchInterval: 15 * S, enabled: activo });

/** Una acción del asistente (abrir, cerrar, mover, veto). Al acabar se vuelve a pedir todo. */
function useAccionAsistente<T>(accion: string) {
  const refrescar = useRefrescarTodo();
  return useMutation({ mutationFn: (cuerpo: T) => api<unknown>("/api/asistente/" + accion, cuerpo), onSettled: refrescar });
}

export const useAbrirManual = () => useAccionAsistente<OrdenManual>("abrir");
export const useCerrarManual = () => useAccionAsistente<{ id: number; parte?: number }>("cerrar");
/** Stop y objetivo van siempre los dos: el que llegue vacío (null) se quita. */
export const useMoverManual = () => useAccionAsistente<{ id: number; stop: number | null; objetivo: number | null }>("mover");
/** `modo` null quita el veto; `horas` 0 = sin caducidad. */
export const usePonerVeto = () => useAccionAsistente<{ simbolo: string; modo: ModoVeto | null; horas?: number }>("veto");

/** Marca los avisos como vistos; solo hace falta refrescar el asistente (el contador de la pestaña). */
export function useMarcarVistas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api<{ ok: boolean }>("/api/asistente/vistas", {}),
    onSettled: () => qc.invalidateQueries({ queryKey: ["asistente"] }),
  });
}
