import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { afficher, profil, simulerApi } from "../../test/outils";
import { Saisies } from "./Personnel";
import Presence from "./Presence";
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

const AGENTS = [
  { id: 11, prenom: "Camille", nom: "Martin", sites: [1], duree_hebdo_minutes: 35 * 60 },
  { id: 12, prenom: "Lou", nom: "Bernard", sites: [1], duree_hebdo_minutes: 35 * 60 },
];
const SITES = [
  { id: 1, nom: "Complexe du Parc" },
  { id: 2, nom: "Salle Gabriel Péri" },
];
const page = (results: unknown[]) => ({ json: { count: results.length, next: null, previous: null, results } });

/** Agents, absences, sites et salles où une présence est requise (seul le Complexe du Parc en demande une). */
function referentielPersonnel(url: string) {
  if (url.startsWith("/api/gestion/personnel/agents")) return page(AGENTS);
  if (url.startsWith("/api/gestion/personnel/absences")) return page([{ id: 1, agent: 12, debut: a(3, 0), fin: a(4, 0), nature: "conge" }]);
  if (url.startsWith("/api/gestion/referentiel/sites")) return page(SITES);
  if (url.startsWith("/api/gestion/referentiel/espaces")) return page([{ id: 1, nom: "Gymnase A", site: 1, site_nom: "Complexe du Parc", gardiennage_requis: true }]);
  if (url.startsWith("/api/gestion/personnel/besoins")) return page([]);
  return undefined;
}

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
      return referentielPersonnel(url);
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    expect(await screen.findByText("1 besoin non couvert")).toBeInTheDocument();
    // Vue d'ensemble : la vacation sans agent est sur la ligne « À pourvoir » ; un clic l'ouvre avec ses actions.
    await utilisateur.click(await screen.findByRole("button", { name: /^17:00–22:00 ?Complexe du Parc/ }));
    await utilisateur.click(within(await screen.findByRole("dialog", { name: "Vacation" })).getByRole("button", { name: /Affecter un agent/ }));
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

  it("PER-05 : le planning d'un agent s'ouvre filtré sur ses vacations (lien « Voir son planning »)", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/")) return { json: { count: 0, next: null, previous: null, results: [] } };
      return undefined;
    });
    afficher(<Vacations />, "/personnel/vacations?agent=4");
    await waitFor(() => expect(appels.some((appel) => appel.url.startsWith("/api/gestion/personnel/vacations?") && appel.url.includes("agent=4"))).toBe(true));
    expect(await screen.findByLabelText("Agent")).toBeInTheDocument();
  });

  it("PER-07 la vue par agent montre qui est où, les absences et les heures de chacun", async () => {
    const vacations = [
      { ...VACATION, id: 1, agent: 11, agent_nom: "Camille Martin", statut: "planifiee", debut: a(0, 17), fin: a(0, 22), duree_minutes: 300 },
      { ...VACATION, id: 2, agent: 11, agent_nom: "Camille Martin", statut: "a_revoir", debut: a(2, 8), fin: a(2, 12), duree_minutes: 240 },
      VACATION,
    ];
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations")) return page(vacations);
      return referentielPersonnel(url);
    });
    afficher(<Vacations />);
    const camille = await screen.findByRole("row", { name: /Camille Martin/ });
    expect(within(camille).getByText("9 h")).toBeInTheDocument();
    expect(within(camille).getByText("sur 35 h")).toBeInTheDocument();
    expect(within(camille).getByRole("button", { name: /^08:00–12:00 ?Complexe du Parc ?À revoir/ })).toBeInTheDocument();
    const lou = screen.getByRole("row", { name: /Lou Bernard/ });
    expect(within(lou).getByText("0 h")).toBeInTheDocument();
    expect(within(lou).getByText("Congé")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /À pourvoir/ })).toHaveTextContent("5 h");
    expect(screen.getByText("Agents en poste").nextElementSibling).toHaveTextContent("1 / 2");
  });

  it("PER-05 au-delà de 48 h dans la semaine, l'agent est signalé", async () => {
    const longues = Array.from({ length: 5 }, (_, i) => ({ ...VACATION, id: 20 + i, agent: 11, agent_nom: "Camille Martin", statut: "planifiee", debut: a(i, 6), fin: a(i, 16), duree_minutes: 600 }));
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations")) return page(longues);
      return referentielPersonnel(url);
    });
    afficher(<Vacations />);
    const camille = await screen.findByRole("row", { name: /Camille Martin/ });
    expect(within(camille).getByText("50 h")).toBeInTheDocument();
    expect(within(camille).getByText("Plus de 48 h")).toBeInTheDocument();
  });

  it("PER-05 un clic sur un agent ouvre son planning de la semaine, modifiable", async () => {
    const appels = simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel", "planifier_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations"))
        return page(url.includes("agent=11") ? [{ ...VACATION, agent: 11, agent_nom: "Camille Martin", statut: "planifiee" }] : [VACATION]);
      return referentielPersonnel(url);
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    await utilisateur.click(await screen.findByRole("button", { name: /^Camille Martin/ }));
    expect(await screen.findByText("Planning de Camille Martin")).toBeInTheDocument();
    expect(screen.getByText(/5 h planifiées cette semaine sur 35 h de référence/)).toBeInTheDocument();
    expect(appels.some((x) => x.url.startsWith("/api/gestion/personnel/vacations?") && x.url.includes("agent=11"))).toBe(true);
    expect(screen.getByRole("button", { name: /^Modifier les horaires/ })).toBeInTheDocument();
    await utilisateur.click(screen.getByRole("button", { name: "Retour à la vue d'ensemble" }));
    expect(await screen.findByRole("row", { name: /Lou Bernard/ })).toBeInTheDocument();
  });

  it("RG-14 sans droit de planifier, la vacation s'ouvre sans action de modification", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations")) return page([VACATION]);
      return referentielPersonnel(url);
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    await utilisateur.click(await screen.findByRole("button", { name: /^17:00–22:00 ?Complexe du Parc/ }));
    const dialogue = await screen.findByRole("dialog", { name: "Vacation" });
    expect(within(dialogue).queryByRole("button", { name: /Affecter un agent/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nouvelle vacation" })).not.toBeInTheDocument();
  });

  it("PER-02 au-delà de quatre vacations sans agent dans la journée, la case renvoie à la vue par site", async () => {
    const libres = Array.from({ length: 6 }, (_, i) => ({ ...VACATION, id: 30 + i }));
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations")) return page(libres);
      return referentielPersonnel(url);
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    const ligne = await screen.findByRole("row", { name: /À pourvoir/ });
    expect(within(ligne).getAllByRole("button", { name: /^17:00–22:00/ })).toHaveLength(4);
    await utilisateur.click(within(ligne).getByRole("button", { name: /^\+ 2 autres/ }));
    expect(screen.getByRole("button", { name: "Par site" })).toHaveAttribute("aria-pressed", "true");
  });

  it("REF-04 la vue par site ne montre que les sites où une présence est requise", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel"]) };
      if (url.startsWith("/api/gestion/personnel/vacations")) return page([VACATION]);
      return referentielPersonnel(url);
    });
    const utilisateur = userEvent.setup();
    afficher(<Vacations />);
    await utilisateur.click(await screen.findByRole("button", { name: "Par site" }));
    const tableau = screen.getByRole("table", { name: /Présence par site/ });
    expect(within(tableau).getByRole("rowheader", { name: /Complexe du Parc/ })).toHaveTextContent("1 salle à couvrir");
    expect(within(tableau).queryByText("Salle Gabriel Péri")).not.toBeInTheDocument();
    expect(screen.getByText(/Sans présence requise : Salle Gabriel Péri/)).toBeInTheDocument();
  });
});

describe("REF-04 présence par site", () => {
  const ESPACES = [
    { id: 1, nom: "Gymnase A", site: 1, site_nom: "Complexe du Parc", famille_libelle: "Gymnase", capacite: 200, gardiennage_requis: true, temps_ouverture_min: 15, temps_fermeture_min: 15 },
    { id: 2, nom: "Dojo", site: 1, site_nom: "Complexe du Parc", famille_libelle: "Salle de sport", capacite: 40, gardiennage_requis: false },
    { id: 3, nom: "Salle polyvalente", site: 2, site_nom: "Salle Gabriel Péri", famille_libelle: "Salle municipale", gardiennage_requis: false },
  ];

  it("REF-04 le gestionnaire du référentiel règle la présence salle par salle", async () => {
    const appels = simulerApi((methode, url, corps) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel", "lire_referentiel", "gerer_referentiel"]) };
      if (methode === "PATCH") return { json: { ...ESPACES[1], ...(corps as object) } };
      if (url.startsWith("/api/gestion/referentiel/espaces")) return page(ESPACES);
      return undefined;
    });
    const utilisateur = userEvent.setup();
    afficher(<Presence />);
    expect(await screen.findByText("1 salle sur 3")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Salle Gabriel Péri" })).toHaveTextContent("Sans présence");
    expect(screen.getByRole("switch", { name: /Présence d'un agent — Gymnase A/ })).toBeChecked();
    await utilisateur.click(screen.getByRole("switch", { name: /Présence d'un agent — Dojo/ }));
    await waitFor(() => expect(appels.some((x) => x.methode === "PATCH" && x.url === "/api/gestion/referentiel/espaces/2")).toBe(true));
    expect(appels.find((x) => x.methode === "PATCH")?.corps).toEqual({ gardiennage_requis: true });
  });

  it("RG-14 sans droit sur le référentiel, les réglages sont en lecture seule", async () => {
    simulerApi((_m, url) => {
      if (url.startsWith("/api/gestion/moi")) return { json: profil(["lire_personnel", "lire_referentiel"]) };
      if (url.startsWith("/api/gestion/referentiel/espaces")) return page(ESPACES);
      return undefined;
    });
    afficher(<Presence />);
    expect(await screen.findByRole("switch", { name: /Présence d'un agent — Dojo/ })).toBeDisabled();
    expect(screen.getByText(/seul un gestionnaire du référentiel peut les modifier/)).toBeInTheDocument();
  });
});
