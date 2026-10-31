import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { ErreurApi } from "./api/http";
import { App } from "./App";
import { SessionProvider } from "./session";
import "./styles.css";

const client = new QueryClient({
  defaultOptions: {
    queries: {
      retry: (tentatives, erreur) => !(erreur instanceof ErreurApi && erreur.statut < 500) && tentatives < 2,
      refetchOnWindowFocus: false,
    },
  },
});

const racine = document.getElementById("racine");
if (racine)
  createRoot(racine).render(
    <StrictMode>
      <QueryClientProvider client={client}>
        <SessionProvider>
          <App />
        </SessionProvider>
      </QueryClientProvider>
    </StrictMode>,
  );
