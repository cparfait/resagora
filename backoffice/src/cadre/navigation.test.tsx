import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../test/outils";
import { Cadre } from "./Cadre";
import { MODULES } from "./modules";
import { RUBRIQUES, rubriqueDe } from "./navigation";

describe("Menu du back-office (rubriques, sur le modèle de CityResa)", () => {
  it("chaque écran du registre appartient à une rubrique, une seule fois", () => {
    const ecrans = MODULES.filter((m) => !m.masque).map((m) => m.chemin);
    for (const chemin of ecrans) expect(rubriqueDe(chemin), chemin).toBeDefined();
    const ranges = RUBRIQUES.flatMap((r) => r.chemins);
    expect(new Set(ranges).size).toBe(ranges.length);
    for (const chemin of ranges) expect(ecrans, chemin).toContain(chemin);
    expect(rubriqueDe("/reservations/dossiers/42")?.libelle).toBe("Réservations");
    expect(RUBRIQUES.filter((r) => r.section === "general").length).toBeLessThanOrEqual(13);
  });

  it("RG-14 DSH-06 rubriques permises, pastille « à traiter », onglets de la rubrique courante", async () => {
    simulerApi((_m, url) => {
      if (url.endsWith("/moi")) return { json: profil(["lire_referentiel", "lire_reservation", "creer_reservation"]) };
      if (url.startsWith("/api/gestion/pilotage/a-traiter"))
        return { json: { compteurs: [{ code: "demandes", libelle: "Demandes à instruire", nombre: 21, lien: "/reservations/dossiers?statut=demande", groupe: "a_traiter", gravite: "attention" }] } };
      return { json: { count: 0, results: [] } };
    });
    afficher(<Cadre />, "/reservations/campagnes");
    const menu = await screen.findByRole("navigation", { name: "Navigation principale" });
    const reservations = await within(menu).findByRole("link", { name: /^Réservations\s*, 21 à traiter$/ });
    expect(reservations).toHaveAttribute("href", "/reservations/dossiers");
    expect(reservations).toHaveAttribute("aria-current", "page");
    expect(within(menu).getByRole("link", { name: "Planning" })).toHaveAttribute("href", "/reservations/planning");
    expect(within(menu).queryByRole("link", { name: /Finances|Journal d'audit/ })).not.toBeInTheDocument();
    expect(within(menu).queryByText("Administration")).not.toBeInTheDocument();
    const onglets = screen.getByRole("navigation", { name: "Écrans de la rubrique Réservations" });
    expect(within(onglets).getAllByRole("link").map((l) => l.textContent)).toEqual(["Dossiers", "Nouvelle demande", "Campagnes annuelles"]);
    expect(within(onglets).getByRole("link", { name: "Campagnes annuelles" })).toHaveAttribute("aria-current", "page");
    await waitFor(() => expect(screen.getAllByRole("link", { name: "Nouvelle demande" })[0]).toHaveAttribute("href", "/reservations/nouvelle"));
  });
});
