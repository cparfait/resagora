import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import PaiementsEnLigne from "./PaiementsEnLigne";

const EN_COURS = {
  id: 5,
  facture: "F2026-00012",
  usager_nom: "Comité des fêtes",
  mode: "regie",
  refdet: "F2026-00012",
  montant: 16000,
  statut: "redirigee",
  statut_libelle: "En cours sur PayFiP",
  numauto: "",
  paye_le: null,
  trop_percu: 0,
  controle: "",
  controle_libelle: "—",
  rembourse_le: null,
  erreur: "",
  motif_cloture: "",
  cree_le: "2026-11-12T09:00:00Z",
  verifiee_le: null,
};

describe("Paiements en ligne", () => {
  it("TAR-07 : la régie relit un paiement resté en cours auprès de PayFiP", async () => {
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_finances", "encaisser"]) };
      if (methode === "POST") return { json: { ...EN_COURS, statut: "payee", statut_libelle: "Payée", numauto: "654321" } };
      if (url.startsWith("/api/gestion/finances/paiements-en-ligne")) return { json: { count: 1, next: null, previous: null, results: [EN_COURS] } };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<PaiementsEnLigne />);
    const tableau = await screen.findByRole("table");
    expect(within(tableau).getByText("En cours sur PayFiP")).toBeInTheDocument();
    await utilisateur.click(within(tableau).getByRole("button", { name: /Vérifier auprès de PayFiP/ }));
    await waitFor(() => expect(appels.some((a) => a.methode === "POST" && a.url === "/api/gestion/finances/paiements-en-ligne/5/verifier")).toBe(true));
    expect(await screen.findByText(/Enregistré : Payée/)).toBeInTheDocument();
  });

  it("TAR-07 : sans le droit d'encaisser, ni vérification ni rapprochement", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_finances"]) };
      if (url.startsWith("/api/gestion/finances/paiements-en-ligne")) return { json: { count: 1, next: null, previous: null, results: [EN_COURS] } };
      return undefined;
    });
    afficher(<PaiementsEnLigne />);
    expect(await screen.findByText("En cours sur PayFiP")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Vérifier auprès de PayFiP/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rapprocher maintenant" })).not.toBeInTheDocument();
  });

  it("TAR-07 : un trop-perçu se rembourse et la trace en est envoyée à l'API", async () => {
    const tropPercu = { ...EN_COURS, id: 7, statut: "payee", statut_libelle: "Payée", trop_percu: 16000, controle: "trop_percu", controle_libelle: "Trop-perçu à rembourser" };
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_finances", "encaisser"]) };
      if (methode === "POST") return { json: { ...tropPercu, rembourse_le: "2026-11-20" } };
      if (url.startsWith("/api/gestion/finances/paiements-en-ligne")) return { json: { count: 1, next: null, previous: null, results: [tropPercu] } };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<PaiementsEnLigne />);
    expect(await screen.findByText(/Trop-perçu à rembourser : 160,00/)).toBeInTheDocument();
    await utilisateur.click(screen.getByRole("button", { name: /Enregistrer le remboursement/ }));
    const dialogue = await screen.findByRole("dialog", { name: "Remboursement d'un trop-perçu" });
    await utilisateur.type(within(dialogue).getByLabelText(/Référence/), "MANDAT 42");
    await utilisateur.click(within(dialogue).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(appels.some((a) => a.url === "/api/gestion/finances/paiements-en-ligne/7/rembourser")).toBe(true));
    expect(appels.find((a) => a.url.endsWith("/rembourser"))?.corps).toMatchObject({ reference: "MANDAT 42", par: "ville" });
  });
});
