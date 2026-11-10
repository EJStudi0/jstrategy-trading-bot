// Lo que se pide al bot y cada cuánto. TanStack Query guarda lo último que llegó: al refrescar,
// la pantalla se queda como estaba hasta que llega lo nuevo (sin parpadeos ni esqueletos).
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "../api";
import { ZONA } from "../lib/tiempo";
import type { Estado, Ganancias, Grafica, Mando, Mercado, Operacion, PuntoCurva } from "../tipos";

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

function useRefrescarTodo() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries();
}

/** Cambiar el modo. Salir a USDT lo pide el servidor dos veces (la segunda con su código). */
export function usePonerMando() {
  const refrescar = useRefrescarTodo();
  return useMutation({
    mutationFn: async (mando: Mando) => {
      let r = await api<{ confirmar?: string; mando?: Mando }>("/api/mando", { mando });
      if (r.confirmar) r = await api("/api/mando", { mando, confirmacion: r.confirmar });
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
