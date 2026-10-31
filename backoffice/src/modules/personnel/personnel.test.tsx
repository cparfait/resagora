import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import { Saisies } from "./Personnel";
import Vacations from "./Vacations";

const lundi = new Date();
lundi.setHours(0, 0, 0, 0);
lundi.setDate(lundi.getDate() - ((lundi.getDay() + 6) % 7));
const a = (jour: number, h: number) => new Date(lundi.getFullYear(), lundi.getMonth(), lundi.getDate() + jour, h).toISOString();

const VACATION = {
  id: 7,
  site: 1,
  site_nom: "Complexe du Parc",
  agent: null,
  agent_nom: "",
  debut: a(1, 17),
  fin: a(1, 22),
  duree_minutes: 300,
  type: "normale",
  statut: "a_pourvoir",
  violations: [],
  forcee: false,
  motif_forcage: "",
  arrivee_reelle: null,
  depart_reel: null,
  signalement: "",
};

describe("Planning du personnel", () => {
  it("PER-04, PER-05 : affecter un agent hors règles exige un forçage motivé", async () => {
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel", "planifier_personnel"]) };
      if (url.startsWith("/api/gestion/referentiel/sites")) return { json: { count: 1, results: [{ id: 1, nom: "Complexe du Parc" }] } };
      if (url.startsWith("/api/gestion/personnel/besoins")) return { json: { count: 1, results: [{ id: 3, site_nom: "Complexe du Parc", debut: a(2, 9), fin: a(2, 12), statut: "a_couvrir", seances: [] }] } };
      if (url.startsWith("/api/gestion/personnel/vacations/7/candidats"))
        return { json: [{ agent: 11, nom: "Camille Martin", minutes_semaine: 2280, prefere: true, conforme: false, violations: [{ code: "hebdo_max", message: "Plus de 48 h dans la semaine." }] }] };
      if (methode === "POST" && url === "/api/gestion/personnel/vacations/7/affecter") return { json: { ...VACATION, agent: 11, agent_nom: "Camille Martin", statut: "planifiee", forcee: true } };
      if (url.startsWith("/api/gestion/personnel/vacations")) return { json: { count: 1, results: [VACATION] } };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    expect(await screen.findByRole("heading", { name: /Besoins non couverts \(1\)/ })).toBeInTheDocument();
    await utilisateur.click(await screen.findByRole("button", { name: /Affecter un agent/ }));
    const dialogue = await screen.findByRole("dialog", { name: "Affecter un agent" });
    expect(within(dialogue).getByText("Plus de 48 h dans la semaine.")).toBeInTheDocument();
    await utilisateur.click(within(dialogue).getByRole("radio", { name: /Camille Martin/ }));
    await utilisateur.click(within(dialogue).getByRole("checkbox", { name: /Forcer l'affectation/ }));
    await utilisateur.type(within(dialogue).getByLabelText(/Motif du forçage/), "Remplacement urgent validé par le chef de service");
    await utilisateur.click(within(dialogue).getByRole("button", { name: "Valider l'affectation" }));
    await waitFor(() => expect(appels.some((x) => x.url === "/api/gestion/personnel/vacations/7/affecter")).toBe(true));
    const envoi = appels.find((x) => x.url === "/api/gestion/personnel/vacations/7/affecter");
    expect(envoi?.corps).toEqual({ agent: 11, forcer: true, motif: "Remplacement urgent validé par le chef de service" });
  });

  it("MOB-06 : les saisies en conflit sont listées et peuvent être marquées examinées", async () => {
    const appels = simulerApi((methode, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel", "planifier_personnel"]) };
      if (methode === "POST") return { json: {} };
      if (url.startsWith("/api/gestion/personnel/saisies"))
        return {
          json: {
            count: 1,
            results: [{ id: 5, agent_nom: "Camille Martin", type: "pointage", horodatage_appareil: a(1, 18), statut: "conflit", message: "Séance annulée entre-temps.", recue_le: a(1, 20), donnees: {} }],
          },
        };
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Saisies />);
    expect(await screen.findByText("Séance annulée entre-temps.")).toBeInTheDocument();
    await utilisateur.click(screen.getByRole("button", { name: /Marquer examinée/ }));
    await waitFor(() => expect(appels.some((x) => x.methode === "POST" && x.url === "/api/gestion/personnel/saisies/5/examinee")).toBe(true));
  });

  it("refuse l'accès sans le droit de lecture du personnel", async () => {
    simulerApi((_m, url) => (url.startsWith("/api/gestion/moi") ? { json: profil(["lire_reservation"]) } : undefined));
    afficher(<Vacations />);
    expect(await screen.findByText(/droits/i)).toBeInTheDocument();
  });
});
