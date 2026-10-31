/** Outils de test : client de requêtes isolé, session simulée, réponses d'API simulées par chemin. */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import type { Moi } from "../api/types";
import { SessionProvider } from "../auth/session";
import { NotificationsProvider } from "../ui/Notifications";

export type Repondeur = (methode: string, url: string, corps: unknown) => { statut?: number; json?: unknown } | undefined;

export function simulerApi(repondeur: Repondeur) {
  const appels: { methode: string; url: string; corps: unknown }[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (entree, init) => {
    const url = typeof entree === "string" ? entree : entree instanceof URL ? entree.href : entree.url;
    const methode = (init?.method ?? (entree instanceof Request ? entree.method : "GET")).toUpperCase();
    const brut = init?.body ?? (entree instanceof Request && methode !== "GET" ? await entree.clone().text() : undefined);
    const corps = typeof brut === "string" && brut ? JSON.parse(brut) : undefined;
    appels.push({ methode, url, corps });
    const reponse = repondeur(methode, url, corps) ?? { statut: 404, json: { code: "not_found", message: "Élément introuvable." } };
    const statut = reponse.statut ?? 200;
    return new Response(statut === 204 ? null : JSON.stringify(reponse.json ?? {}), { status: statut, headers: { "Content-Type": "application/json" } });
  });
  return appels;
}

export function profil(actions: string[], surcharges: Partial<Moi> = {}): Moi {
  return {
    id: 1,
    identifiant: "agent.test",
    nom_affiche: "Agent Test",
    courriel: "agent.test@exemple.test",
    double_authentification_exigee: false,
    double_authentification_active: false,
    double_authentification_validee: false,
    habilitations: [{ role: "gestionnaire", role_libelle: "Gestionnaire", perimetre: "Site A", tous_sites: false, sites: [1], actions }],
    ...surcharges,
  };
}

export function afficher(element: ReactElement, chemin = "/") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <NotificationsProvider>
        <SessionProvider>
          <MemoryRouter initialEntries={[chemin]}>{element}</MemoryRouter>
        </SessionProvider>
      </NotificationsProvider>
    </QueryClientProvider>,
  );
}
