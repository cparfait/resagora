import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import Accueil from "./Accueil";

const OCCUPATION = {
  espaces: [
    { espace: 1, espace_nom: "Gymnase les Sablons", site_nom: "Sablons", premier_niveau: true, minutes_reservees: 600, minutes_ouverture: 2400, taux: 2500 },
    { espace: 2, espace_nom: "Dojo Marcel Doret", site_nom: "Doret", premier_niveau: true, minutes_reservees: 1200, minutes_ouverture: 2400, taux: 5000 },
  ],
};
const REPARTITION = { types_usager: [{ cle: "association", libelle: "Associations", minutes: 1500, part: 8333 }, { cle: "entreprise", libelle: "Entreprises", minutes: 300, part: 1667 }] };

describe("Tableau de bord façon Mariloo (DSH-01, STA-01, STA-02)", () => {
  it("chiffres-clés, graphiques et leurs tableaux de données pour qui lit les statistiques", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_referentiel", "lire_statistiques"]) };
      if (url.startsWith("/api/gestion/pilotage/a-traiter"))
        return { json: { compteurs: [{ code: "demandes", libelle: "Demandes à instruire", nombre: 4, lien: "/reservations/dossiers", groupe: "a_traiter", gravite: "attention" }] } };
      if (url.startsWith("/api/gestion/pilotage/statistiques/occupation")) return { json: OCCUPATION };
      if (url.startsWith("/api/gestion/pilotage/statistiques/repartition")) return { json: REPARTITION };
      return { json: { count: 0, results: [] } };
    });
    afficher(<Accueil />);
    const chiffres = await screen.findByRole("region", { name: "Chiffres clés du mois" });
    expect(within(chiffres).getByText("Demandes à instruire").nextElementSibling).toHaveTextContent("4");
    expect(within(chiffres).getByText("Heures réservées").nextElementSibling).toHaveTextContent("30 h");
    expect(within(chiffres).getByText("Taux d'occupation").nextElementSibling).toHaveTextContent("38 %");
    const occupation = screen.getByRole("region", { name: "Occupation des espaces" });
    expect(within(occupation).getByRole("table", { name: "Occupation par espace" })).toBeInTheDocument();
    expect(within(occupation).getAllByRole("row")[1]).toHaveTextContent("Dojo Marcel Doret");
    expect(within(screen.getByRole("region", { name: "Répartition des heures" })).getByRole("table", { name: /Répartition des heures/ })).toHaveTextContent("83 %");
    expect(screen.getByRole("link", { name: /4\s*Demandes à instruire/ })).toHaveAttribute("href", "/reservations/dossiers");
  });

  it("RG-14 sans le droit de lire les statistiques : ni chiffres ni graphiques, les compteurs restent", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_referentiel"]) };
      if (url.startsWith("/api/gestion/pilotage/a-traiter")) return { json: { compteurs: [] } };
      return { json: { count: 0, results: [] } };
    });
    afficher(<Accueil />);
    expect(await screen.findByText("Rien en attente : tout est à jour.")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Chiffres clés du mois" })).not.toBeInTheDocument();
    expect(appels.some((a) => a.url.includes("statistiques"))).toBe(false);
  });
});
