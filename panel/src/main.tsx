import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./estilos.css";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { SinAcceso } from "./api";
import { App } from "./App";

const cliente = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (veces, error) => !(error instanceof SinAcceso) && veces < 2,
      refetchOnWindowFocus: true,
      staleTime: 5000,
    },
  },
});

createRoot(document.getElementById("raiz")!).render(
  <StrictMode>
    <QueryClientProvider client={cliente}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
);
