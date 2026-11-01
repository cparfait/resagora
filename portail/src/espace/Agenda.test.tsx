import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgendaStructure } from "./Agenda";

const URL_ABONNEMENT = `https://portail.test/api/portail/agenda/${"x".repeat(43)}.ics`;

function serveur() {
  let actif = false;
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (entree, options) => {
    const url = typeof entree === "string" ? entree : entree instanceof URL ? entree.href : entree.url;
    const methode = options?.method ?? "GET";
    const repondre = (corps: unknown, status = 200) => new Response(JSON.stringify(corps), { status, headers: { "Content-Type": "application/json" } });
    if (url.startsWith("/api/portail/session")) return repondre({ connecte: true, csrf: "csrf", expire_dans: 600, contact: null });
    const etat = () => ({ actif, cree_le: actif ? "2026-11-01T10:00:00Z" : null, expire_le: actif ? "2027-11-01T10:00:00Z" : null, dernier_acces: null });
    if (methode === "POST") {
      actif = true;
      return repondre({ ...etat(), url: URL_ABONNEMENT }, 201);
    }
    if (methode === "DELETE") {
      actif = false;
      return new Response(null, { status: 204 });
    }
    return repondre(etat());
  });
}

function afficher() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AgendaStructure usager={3} />
    </QueryClientProvider>,
  );
}

afterEach(() => vi.restoreAllMocks());

describe("Agenda des séances d'une structure", () => {
  it("POR-05 crée un lien d'abonnement montré une seule fois, puis le désactive", async () => {
    const appels = serveur();
    afficher();
    expect(screen.getByRole("heading", { level: 2, name: "Agenda des séances" })).toBeInTheDocument();
    await userEvent.click(await screen.findByRole("button", { name: "Créer un lien d'abonnement" }));
    const champ = await screen.findByLabelText("Lien d'abonnement");
    expect(champ).toHaveValue(URL_ABONNEMENT);
    expect(champ).toHaveAttribute("readonly");
    expect(screen.getByRole("status")).toHaveTextContent("il ne sera plus affiché");
    expect(await screen.findByText(/valable jusqu'au 1 novembre 2027/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Désactiver le lien" }));
    expect(await screen.findByRole("button", { name: "Créer un lien d'abonnement" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Lien d'abonnement")).not.toBeInTheDocument();
    const ecritures = appels.mock.calls.filter(([, o]) => o?.method === "POST" || o?.method === "DELETE");
    expect(ecritures.map(([u, o]) => `${o?.method} ${String(u)}`)).toEqual(["POST /api/portail/usagers/3/agenda", "DELETE /api/portail/usagers/3/agenda"]);
  });
});
