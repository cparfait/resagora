import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import Accueil from "../accueil/Accueil";
import { Statistiques } from "./Pilotage";
import { Editions, Valorisation } from "./Valorisation";

const vide = { count: 0, next: null, previous: null, results: [] };

describe("Pilotage", () => {
  it("DSH-01, DSH-06 : chaque compteur non nul ouvre la liste filtrée qu'il résume", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_referentiel", "lire_reservation"]) };
      if (url.startsWith("/api/gestion/pilotage/a-traiter"))
        return {
          json: {
            compteurs: [
              { code: "demandes", libelle: "Demandes à instruire", nombre: 4, lien: "/reservations/dossiers?statut=demande,en_instruction", groupe: "a_traiter", gravite: "attention" },
              { code: "conflits", libelle: "Conflits", nombre: 0, lien: "/reservations/planning", groupe: "alertes", gravite: "danger" },
            ],
          },
        };
      if (url.startsWith("/api/gestion/")) return { json: vide };
      return undefined;
    });
    afficher(<Accueil />);
    const lien = await screen.findByRole("link", { name: /4\s*Demandes à instruire/ });
    expect(lien).toHaveAttribute("href", "/reservations/dossiers?statut=demande,en_instruction");
    expect(screen.queryByText("Conflits")).not.toBeInTheDocument();
    expect(screen.getByText("Aucune alerte.")).toBeInTheDocument();
  });

  it("STA-01 : l'occupation s'affiche en tableau et s'exporte en tableur", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_statistiques"]) };
      if (url.startsWith("/api/gestion/pilotage/statistiques/occupation") && url.includes("export=xlsx")) return { json: {} };
      if (url.startsWith("/api/gestion/pilotage/statistiques/occupation"))
        return {
          json: {
            espaces: [],
            sites: [{ site: 1, site_nom: "Complexe du Parc", minutes_reservees: 6000, minutes_ouverture: 12000, taux: 5000 }],
          },
        };
      if (url.startsWith("/api/gestion/pilotage/statistiques/repartition")) return { json: { types_usager: [], activites: [], familles: [] } };
      if (url.startsWith("/api/gestion/")) return { json: vide };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Statistiques />);
    const tableau = await screen.findByRole("table", { name: /Occupation par site/ });
    expect(within(tableau).getByText("Complexe du Parc")).toBeInTheDocument();
    expect(within(tableau).getByText("50 %")).toBeInTheDocument();
    // Sans le droit de lire les finances, la section des recettes n'est pas interrogée.
    expect(appels.some((a) => a.url.includes("statistiques/recettes"))).toBe(false);
    await utilisateur.click(screen.getByRole("button", { name: /Exporter l'occupation/ }));
    await waitFor(() => expect(appels.some((a) => a.url.includes("occupation") && a.url.includes("export=xlsx"))).toBe(true));
  });

  it("STA-01 : sans le droit, l'écran des statistiques est refusé", async () => {
    simulerApi((_m, url) => (url.startsWith("/api/gestion/moi") ? { json: profil(["lire_reservation"]) } : { json: vide }));
    afficher(<Statistiques />);
    expect(await screen.findByText(/pas les droits/)).toBeInTheDocument();
  });

  it("VAL-05 : la synthèse signale le dépassement du seuil de convention et permet d'éditer l'attestation", async () => {
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_valorisation", "calculer_valorisation"]) };
      if (url.startsWith("/api/gestion/valorisation/exercices/3/synthese"))
        return {
          json: {
            seuils: { convention: 2_300_000, compte_rendu: 15_300_000 },
            lignes: [
              { usager: 7, usager_nom: "Basket club", usager_type: "association", valorisation: 41, nature: 2_100_000, numeraire: 500_000, total: 2_600_000, alertes: ["convention"], attestation: null, figee: true },
            ],
          },
        };
      if (methode === "POST" && url.endsWith("/attestation")) return { json: { id: 41 } };
      if (url.startsWith("/api/gestion/valorisation/exercices"))
        return { json: { count: 1, next: null, previous: null, results: [{ id: 3, annee: 2026, statut: "cloture", date_limite_attestations: null, date_limite: "2027-03-31", cloture_le: "2027-01-15T09:00:00Z", cout_personnel: 3200, absences_valorisees: true }] } };
      if (url.startsWith("/api/gestion/")) return { json: vide };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Valorisation />);
    const tableau = await screen.findByRole("table", { name: /Synthèse 2026/ });
    expect(within(tableau).getByText("Convention obligatoire (> 23 000,00 €)")).toBeInTheDocument();
    expect(within(tableau).queryByText(/Compte rendu financier/)).not.toBeInTheDocument();
    await utilisateur.click(within(tableau).getByRole("button", { name: /attestation.*Basket club/ }));
    await waitFor(() => expect(appels.some((a) => a.methode === "POST" && a.url === "/api/gestion/valorisation/valorisations/41/attestation")).toBe(true));
    expect(screen.queryByRole("button", { name: /Clôturer/ })).not.toBeInTheDocument();
  });

  it("IMP-01 : un planning refusé par l'API est annoncé à l'agent au lieu d'échouer en silence", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_reservation"]) };
      if (url.startsWith("/api/gestion/pilotage/planning.pdf")) return { statut: 403, json: { code: "droits_insuffisants", message: "Vous n'avez pas les droits sur ce site." } };
      if (url.startsWith("/api/gestion/referentiel/sites")) return { json: { count: 1, next: null, previous: null, results: [{ id: 2, nom: "Complexe du Parc" }] } };
      if (url.startsWith("/api/gestion/")) return { json: vide };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Editions />);
    const site = await screen.findByLabelText("Site");
    await waitFor(() => expect(within(site).getByRole("option", { name: "Complexe du Parc" })).toBeInTheDocument());
    await utilisateur.selectOptions(site, "2");
    await utilisateur.click(screen.getByRole("button", { name: "Imprimer le planning" }));
    expect(await screen.findByText("Vous n'avez pas les droits sur ce site.")).toBeInTheDocument();
  });
});
