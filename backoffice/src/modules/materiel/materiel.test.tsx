import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import { Prets, Stocks } from "./Materiel";

const PRET = {
  id: 9,
  dossier: 3,
  dossier_numero: "D2026-00003",
  usager_nom: "Comité des fêtes",
  materiel_libelle: "Table pliante",
  unite: "table",
  site_nom: "Maison des associations",
  quantite: 20,
  debut: "2026-11-14T13:00:00Z",
  fin: "2026-11-14T22:00:00Z",
  statut: "sortie",
  quantite_sortie: 20,
  quantite_rendue: null,
  manquants: 0,
  origine: "backoffice",
  motif: "",
  signalement: "",
};

describe("Matériel", () => {
  it("MAT-03 : le retour de 18 tables sur 20 est transmis à l'API", async () => {
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_materiel", "gerer_materiel", "creer_reservation"]) };
      if (methode === "POST") return { json: { ...PRET, statut: "rendue", quantite_rendue: 18, manquants: 2 } };
      if (url.startsWith("/api/gestion/materiel/prets")) return { json: { count: 1, results: [PRET] } };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Prets />);
    await utilisateur.click(await screen.findByRole("button", { name: /Enregistrer le retour/ }));
    const dialogue = await screen.findByRole("dialog", { name: "Retour du matériel" });
    const champ = within(dialogue).getByLabelText(/Quantité rendue/);
    await utilisateur.clear(champ);
    await utilisateur.type(champ, "18");
    await utilisateur.click(within(dialogue).getByRole("button", { name: "Valider" }));
    await waitFor(() => expect(appels.some((a) => a.url === "/api/gestion/materiel/prets/9/rendre")).toBe(true));
    expect(appels.find((a) => a.url === "/api/gestion/materiel/prets/9/rendre")?.corps).toEqual({ quantite: 18, observations: "", solde: true });
  });

  it("MAT-04 : un contrôle dépassé est signalé dans l'état du stock", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_materiel"]) };
      if (url.startsWith("/api/gestion/materiel/stocks/etat"))
        return {
          json: [
            { id: 1, materiel: 1, materiel_libelle: "But de handball", nature: "fixe", unite: "paire", site: 1, site_nom: "Complexe du Parc", espace_nom: "Gymnase A", quantite: 2, hors_service: 0, sortis: 0, sur_place: 2, prets_a_venir: 0, echeance_controle: "2025-01-01", sous_seuil: false },
          ],
        };
      if (url.startsWith("/api/gestion/")) return { json: { count: 0, results: [] } };
      return undefined;
    });
    afficher(<Stocks />);
    expect(await screen.findByText("But de handball")).toBeInTheDocument();
    expect(screen.getByText(/1 janv. 2025/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Entrée en stock" })).not.toBeInTheDocument();
  });
});
