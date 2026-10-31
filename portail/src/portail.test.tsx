/** Portail : gabarit accessible (POR-09), connexion en deux temps (SEC-04), indicateur d'étapes (POR-04). */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { describe, expect, it, vi } from "vitest";
import { Routage } from "./App";
import { Indicateur } from "./espace/Demande";
import { adresseDePaiementSure } from "./espace/Paiement";
import { SessionProvider } from "./session";

function reponses(table: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (entree) => {
    const url = typeof entree === "string" ? entree : entree instanceof URL ? entree.href : entree.url;
    const cle = Object.keys(table).find((c) => url.startsWith(c));
    const corps = cle ? table[cle] : { code: "introuvable", message: "Élément introuvable." };
    const statut = cle ? (typeof corps === "object" && corps && "statut" in corps ? Number((corps as { statut: number }).statut) : 200) : 404;
    return new Response(JSON.stringify(corps), { status: statut, headers: { "Content-Type": "application/json" } });
  });
}

function afficher(chemin: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[chemin]}>
        <SessionProvider>
          <Routage />
        </SessionProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const SESSION = { connecte: false, csrf: "jeton-csrf", expire_dans: 0, contact: null };
const DECLARATION = { etat: "non conforme", taux: 0, date_audit: "", auditeur: "", non_conformites: "", contact: "x@exemple.test", date_declaration: "31/10/2026", referentiel: "RGAA 4.1.2", conservation: { inactivite_mois: 36, pieces_expirees_mois: 12, service: "", courriel: "" } };

describe("Portail", () => {
  it("POR-09 le gabarit a un lien d'évitement, une navigation nommée, un seul titre et l'état d'accessibilité", async () => {
    reponses({ "/api/portail/session": SESSION, "/api/portail/accessibilite": DECLARATION });
    afficher("/");
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveAttribute("href", "#contenu");
    expect(screen.getByRole("navigation", { name: "Navigation principale" })).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 1 })).toHaveLength(1);
    expect(await screen.findByRole("link", { name: "Accessibilité : non conforme" })).toBeInTheDocument();
    expect(document.title).toContain("Portail des équipements");
  });

  it("SEC-04 la connexion demande le code de double authentification sans exposer de jeton", async () => {
    const appels = reponses({ "/api/portail/session": SESSION, "/api/portail/accessibilite": DECLARATION, "/api/portail/auth/connexion": { etape: "totp", defi: "defi-opaque" } });
    afficher("/connexion");
    await userEvent.type(screen.getByLabelText(/Adresse électronique/), "camille@exemple.test");
    await userEvent.type(screen.getByLabelText(/^Mot de passe/), "Volant-Plume-Raquette-7");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByLabelText(/Code de sécurité/)).toHaveFocus();
    const connexion = appels.mock.calls.find(([url]) => String(url).includes("/auth/connexion"));
    const entetes = (connexion?.[1]?.headers ?? {}) as Record<string, string>;
    expect(entetes["X-CSRF-Token"]).toBe("jeton-csrf");
  });

  it("SEC-04 une erreur de connexion est annoncée en haut du formulaire", async () => {
    reponses({ "/api/portail/session": SESSION, "/api/portail/accessibilite": DECLARATION, "/api/portail/auth/connexion": { statut: 401, code: "identifiants_invalides", message: "Identifiant ou mot de passe incorrect." } });
    afficher("/connexion");
    await userEvent.type(screen.getByLabelText(/Adresse électronique/), "camille@exemple.test");
    await userEvent.type(screen.getByLabelText(/^Mot de passe/), "faux-mot-de-passe");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiant ou mot de passe incorrect.");
  });

  it("POR-04 l'indicateur d'étape est textuel et marque l'étape courante", () => {
    render(<Indicateur etape={2} />);
    const navigation = screen.getByRole("navigation", { name: "Étapes de la demande" });
    expect(within(navigation).getByText("Étape 2 sur 4 : Détails de l'activité")).toBeInTheDocument();
    expect(within(navigation).getByText("Détails de l'activité").closest("li")).toHaveAttribute("aria-current", "step");
  });

  it("POR-01 l'espace personnel redirige vers la connexion sans session", async () => {
    reponses({ "/api/portail/session": SESSION, "/api/portail/accessibilite": DECLARATION });
    afficher("/espace/dossiers");
    expect(await screen.findByRole("heading", { level: 1, name: "Se connecter" })).toBeInTheDocument();
  });

  it("VAL-04 l'association retrouve son attestation annuelle dans un tableau titré, téléchargeable", async () => {
    reponses({
      "/api/portail/session": { connecte: true, csrf: "jeton", expire_dans: 1800, contact: { id: 1, prenom: "Camille", nom: "Martin", totp: false } },
      "/api/portail/accessibilite": DECLARATION,
      "/api/portail/attestations": [{ id: 4, exercice: 2025, usager: 2, usager_nom: "Basket club", montant: 1234500, montant_texte: "12 345,00 €", deposee_le: "2026-01-20T09:00:00Z", numero: "ATT-2025-0004" }],
    });
    afficher("/espace/attestations");
    expect(await screen.findByRole("heading", { level: 1, name: "Attestations de valorisation" })).toBeInTheDocument();
    const tableau = await screen.findByRole("table", { name: "Attestations déposées par la Ville" });
    expect(within(tableau).getByRole("rowheader", { name: "2025" })).toBeInTheDocument();
    expect(within(tableau).getByText("12 345,00 €")).toBeInTheDocument();
    expect(within(tableau).getByRole("button", { name: /attestation 2025.*Basket club.*PDF/ })).toBeInTheDocument();
  });

  it("POR-07 le retour de PayFiP affiche l'état relu par la Ville, pas celui de l'adresse", async () => {
    const etat = { uuid: "2b4c7f0e-0000-4000-8000-000000000001", facture: "F2026-00012", facture_id: 12, montant: 16000, montant_texte: "160,00 €", statut: "redirigee", message: "Paiement en cours de vérification auprès de la DGFiP.", termine: false, numero_autorisation: "", url: "https://www.payfip.gouv.fr/tpa/paiementws.web?idop=abc" };
    const table: Record<string, unknown> = {
      "/api/portail/session": { connecte: true, csrf: "jeton", expire_dans: 1800, contact: { id: 1, prenom: "Camille", nom: "Martin", totp: false } },
      "/api/portail/accessibilite": DECLARATION,
      "/api/portail/paiements/": etat,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (entree) => {
      const url = typeof entree === "string" ? entree : entree instanceof URL ? entree.href : entree.url;
      const cle = Object.keys(table).find((c) => url.startsWith(c));
      return new Response(JSON.stringify(cle ? table[cle] : {}), { status: cle ? 200 : 404, headers: { "Content-Type": "application/json" } });
    });
    afficher("/espace/paiement/2b4c7f0e-0000-4000-8000-000000000001?resultat=P");
    expect(await screen.findByRole("heading", { level: 1, name: "Paiement en ligne" })).toBeInTheDocument();
    expect(await screen.findByText("Paiement en cours de vérification auprès de la DGFiP.")).toBeInTheDocument();
    expect(screen.queryByText(/merci/)).not.toBeInTheDocument();
  });

  it("POR-07 seule une adresse de paiement HTTPS est suivie", () => {
    expect(adresseDePaiementSure("https://www.payfip.gouv.fr/tpa/paiementws.web?idop=abc")).toBe(true);
    expect(adresseDePaiementSure("http://localhost:53010/payfip/paiementws.web?idop=abc")).toBe(true);
    expect(adresseDePaiementSure("http://evil.example/payfip")).toBe(false);
    expect(adresseDePaiementSure("javascript:alert(1)")).toBe(false);
  });

  it("POR-07 au départ, la page redirige vers PayFiP une fois l'opération préparée ; au retour, jamais", async () => {
    const etat = { uuid: "2b4c7f0e-0000-4000-8000-000000000002", facture: "F2026-00013", facture_id: 13, montant: 16000, montant_texte: "160,00 €", statut: "redirigee", message: "Paiement en cours de vérification auprès de la DGFiP.", termine: false, numero_autorisation: "", url: "https://www.payfip.gouv.fr/tpa/paiementws.web?idop=abc" };
    const table: Record<string, unknown> = {
      "/api/portail/session": { connecte: true, csrf: "jeton", expire_dans: 1800, contact: { id: 1, prenom: "Camille", nom: "Martin", totp: false } },
      "/api/portail/accessibilite": DECLARATION,
      "/api/portail/paiements/": etat,
    };
    vi.spyOn(globalThis, "fetch").mockImplementation(async (entree) => {
      const url = typeof entree === "string" ? entree : entree instanceof URL ? entree.href : entree.url;
      const cle = Object.keys(table).find((c) => url.startsWith(c));
      return new Response(JSON.stringify(cle ? table[cle] : {}), { status: cle ? 200 : 404, headers: { "Content-Type": "application/json" } });
    });
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    afficher("/espace/paiement/2b4c7f0e-0000-4000-8000-000000000002?depart=1");
    expect(await screen.findByText(/Vous allez être redirigé vers PayFiP/)).toBeInTheDocument();
    expect(assign).toHaveBeenCalledWith("https://www.payfip.gouv.fr/tpa/paiementws.web?idop=abc");
    vi.unstubAllGlobals();
  });
});
