import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import Dossiers from "./Dossiers";

const vide = { count: 0, next: null, previous: null, results: [] };
const DOSSIER = { id: 3, numero: "D2026-00003", objet: "Entraînement", usager: 1, usager_nom: "Association Sportive Châtillonnaise", usager_type: "association", type_reservation_libelle: "Ponctuelle", statut: "demande", nombre_reservations: 1, cree_le: "2026-11-01T09:00:00Z" };

describe("PLA-06 liste des dossiers", () => {
  it("PLA-06 les pilules de statut filtrent la liste côté serveur et « À traiter » porte le compteur", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.endsWith("/moi")) return { json: profil(["lire_reservation"]) };
      if (url.includes("/a-traiter")) return { json: { compteurs: [{ code: "demandes", libelle: "Demandes", nombre: 4, lien: "/reservations/dossiers?statut=demande,en_instruction", groupe: "a_traiter" }] } };
      if (url.includes("/reservations/dossiers")) return { json: { count: 1, next: null, previous: null, results: [DOSSIER] } };
      return { json: vide };
    });
    afficher(<Dossiers />);
    expect(await screen.findByText("Association Sportive Châtillonnaise")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Toutes" })).toHaveAttribute("aria-pressed", "true");
    expect(await screen.findByRole("button", { name: "À traiter 4" })).toHaveAttribute("aria-pressed", "false");
    await userEvent.click(screen.getByRole("button", { name: "Terminées" }));
    expect(screen.getByRole("button", { name: "Terminées" })).toHaveAttribute("aria-pressed", "true");
    await waitFor(() => expect(appels.some((a) => a.url.includes("/reservations/dossiers") && decodeURIComponent(a.url).includes("statut=realisee,cloturee"))).toBe(true));
  });

  it("RG-14 sans droit de lecture, la liste n'est pas affichée", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["administrer"]) } : { json: vide }));
    afficher(<Dossiers />);
    expect(await screen.findByRole("alert")).toHaveTextContent("droits");
    expect(screen.queryByRole("button", { name: "Toutes" })).not.toBeInTheDocument();
  });
});
