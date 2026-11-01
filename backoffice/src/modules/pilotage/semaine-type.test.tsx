import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import SemaineType, { couloirs, type Creneau } from "./SemaineType";

const creneau = (champs: Partial<Creneau>): Creneau => ({
  jour: 1,
  jour_libelle: "Mardi",
  debut: "18:00",
  fin: "20:00",
  espace: 6,
  espace_nom: "Gymnase A",
  occupant: "Club de hand",
  type_usager: "association",
  activite: "Handball",
  statut: "validee",
  provisoire: false,
  frequence: "chaque semaine",
  pendant_vacances: false,
  du: "2026-09-01",
  au: "2027-06-30",
  dossier: "D-2026-0012",
  dossier_id: 12,
  reservation: 40,
  ...champs,
});

const REPONSE = {
  saison: { id: 3, nom: "2026-2027", debut: "2026-09-01", fin: "2027-06-30" },
  jours: ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"],
  creneaux: [creneau({}), creneau({ jour: 3, jour_libelle: "Jeudi", occupant: "Amicale yoga", provisoire: true, statut: "demande", frequence: "une semaine sur 2", dossier_id: 13, reservation: 41 })],
};

describe("Semaine type", () => {
  it("IMP-01 : la semaine type d'un espace s'affiche en grille et en tableau, et s'imprime en calendrier", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_reservation"]) };
      if (url.startsWith("/api/gestion/pilotage/semaine-type.pdf")) return { json: {} };
      if (url.startsWith("/api/gestion/pilotage/semaine-type")) return { json: REPONSE };
      if (url.startsWith("/api/gestion/")) return { json: { count: 0, next: null, previous: null, results: [] } };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<SemaineType />, "/pilotage/semaine-type?espace=6");

    const grille = await screen.findByRole("group", { name: /Semaine type, saison 2026-2027/ });
    expect(within(grille).getByText("Lundi")).toBeInTheDocument();
    expect(within(grille).getByRole("link", { name: /18:00–20:00\s*Club de hand/ })).toHaveAttribute("href", "/reservations/dossiers/12");
    expect(within(grille).getByRole("link", { name: /Amicale yoga.*une semaine sur 2, provisoire/ })).toBeInTheDocument();
    const tableau = screen.getByRole("table", { name: "Créneaux de la semaine type" });
    expect(within(tableau).getByRole("link", { name: "Amicale yoga" })).toHaveAttribute("href", "/reservations/dossiers/13");
    expect(appels.some((a) => a.url.startsWith("/api/gestion/pilotage/semaine-type?") && a.url.includes("espace=6"))).toBe(true);

    await utilisateur.click(screen.getByRole("button", { name: "Imprimer le calendrier" }));
    await waitFor(() => expect(appels.some((a) => a.url.startsWith("/api/gestion/pilotage/semaine-type.pdf") && a.url.includes("mise_en_page=calendrier"))).toBe(true));
  });

  it("IMP-01 : sans le droit de lire les réservations, l'écran est refusé", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      return undefined;
    });
    afficher(<SemaineType />, "/pilotage/semaine-type?espace=6");
    expect(await screen.findByText(/droits/i)).toBeInTheDocument();
    expect(appels.some((a) => a.url.includes("semaine-type"))).toBe(false);
  });

  it("IMP-01 : deux créneaux simultanés le même jour occupent deux sous-colonnes", () => {
    const a = creneau({});
    const b = creneau({ debut: "19:00", fin: "21:00", reservation: 42 });
    const c = creneau({ debut: "20:00", fin: "22:00", reservation: 43 });
    const { rangs, nombre } = couloirs([a, b, c]);
    expect(nombre).toBe(2);
    expect([rangs.get(a), rangs.get(b), rangs.get(c)]).toEqual([0, 1, 0]);
  });
});
