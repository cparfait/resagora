import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import type { Espace, SeancePlanning } from "../../../api/types";
import { afficher, profil, simulerApi } from "../../../test/outils";
import Planning from "../Planning";
import { Legende, VueChronologie, VueListe, VueMois, VueSemaine } from "./vues";

const lundi = new Date(2026, 10, 9);
const seance = (id: number, jour: number, h: number, statut = "validee"): SeancePlanning => ({
  id,
  reservation: id,
  dossier: id,
  numero: `D2026-0000${id}`,
  objet: "Entraînement",
  usager: `Club ${id}`,
  type_usager: "association",
  espace: 1,
  espace_nom: "Gymnase",
  site: 1,
  debut: new Date(2026, 10, jour, h).toISOString(),
  fin: new Date(2026, 10, jour, h + 2).toISOString(),
  statut,
  signalement: "",
});

describe("PLA-01 vues du planning", () => {
  it("PLA-01 la vue semaine place les séances par jour avec un nom accessible", () => {
    render(<VueSemaine seances={[seance(1, 10, 18)]} debut={lundi} coloration="statut" onOuvrir={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Club 1, Gymnase, mardi 10 novembre de 18:00 à 20:00, Validée/ })).toBeInTheDocument();
  });

  it("PLA-01 la vue liste est l'alternative accessible", async () => {
    const ouvrir = vi.fn();
    render(<VueListe seances={[seance(1, 10, 18, "option")]} onOuvrir={ouvrir} />);
    expect(screen.getByRole("cell", { name: /Club 1/ })).toBeInTheDocument();
    expect(screen.getByText("Option")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Ouvrir" }));
    expect(ouvrir).toHaveBeenCalled();
  });

  it("PLA-01 la vue mois compte les séances du jour", () => {
    render(<VueMois seances={[seance(1, 10, 18), seance(2, 10, 20)]} debut={lundi} coloration="statut" onOuvrir={vi.fn()} onJour={vi.fn()} />);
    expect(screen.getByRole("button", { name: /mardi 10 novembre \(2 séances\)/ })).toBeInTheDocument();
  });

  it("PLA-01 la chronologie présente une ligne par espace", () => {
    const espaces = [{ id: 1, nom: "Gymnase" }, { id: 2, nom: "Dojo" }] as Espace[];
    render(<VueChronologie seances={[seance(1, 10, 18)]} debut={lundi} espaces={espaces} coloration="type_usager" onOuvrir={vi.fn()} />);
    expect(screen.getByText("Dojo")).toBeInTheDocument();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("PLA-03 la légende suit la coloration choisie", () => {
    const { rerender } = render(<Legende coloration="statut" />);
    expect(screen.getByText("Confirmée")).toBeInTheDocument();
    rerender(<Legende coloration="type_usager" />);
    expect(screen.getByText("Service municipal")).toBeInTheDocument();
  });

  it("PLA-02 déposer une séance déclenche le calcul du nouveau créneau", () => {
    const deposer = vi.fn();
    const s = seance(1, 10, 18);
    const { container } = render(<VueSemaine seances={[s]} debut={lundi} coloration="statut" onOuvrir={vi.fn()} onDeposer={deposer} />);
    const colonnes = container.querySelectorAll(".grille__corps");
    const cible = colonnes[3] as HTMLElement;
    vi.spyOn(cible, "getBoundingClientRect").mockReturnValue({ top: 0, left: 0, width: 100, height: 816, right: 100, bottom: 816, x: 0, y: 0, toJSON: () => ({}) });
    const evenement = new Event("drop", { bubbles: true, cancelable: true });
    Object.assign(evenement, { clientY: 48 * 11, dataTransfer: { getData: () => "1" } });
    fireEvent(cible, evenement);
    expect(deposer).toHaveBeenCalledTimes(1);
    const appel = deposer.mock.calls[0] as [{ debut: Date; fin: Date; espace: number }];
    const { debut, fin, espace } = appel[0];
    expect(debut.getDate()).toBe(12);
    expect(debut.getHours()).toBe(18);
    expect((fin.getTime() - debut.getTime()) / 3600000).toBe(2);
    expect(espace).toBe(1);
  });
});

describe("PLA-02 contrôle serveur avant déplacement", () => {
  it("PLA-02 un créneau occupé est refusé et la séance reste en place", async () => {
    const aujourdhui = new Date();
    const s = { ...seance(7, 10, 18), debut: new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate(), 18).toISOString(), fin: new Date(aujourdhui.getFullYear(), aujourdhui.getMonth(), aujourdhui.getDate(), 20).toISOString() };
    const appels = simulerApi((m, url) => {
      if (url.endsWith("/moi")) return { json: profil(["lire_reservation", "valider_reservation", "lire_referentiel"], { habilitations: [{ role: "gestionnaire", role_libelle: "G", perimetre: "Ville", tous_sites: true, sites: [], actions: ["lire_reservation", "valider_reservation", "lire_referentiel"] }] }) };
      if (url.includes("/planning")) return { json: [s] };
      if (url.includes("/vues")) return { json: [] };
      if (url.includes("/referentiel/espaces")) return { json: { count: 1, next: null, previous: null, results: [{ id: 1, nom: "Gymnase", site: 1, site_nom: "Site A", famille: 1 }] } };
      if (url.includes("controle-deplacement"))
        return { json: { possible: false, hors_horaires: false, fermeture: false, conflits: [{ occurrence: 9, reservation: 9, dossier: "D2026-00009", usager: "Club voisin", espace: "Gymnase", debut: s.debut, fin: s.fin }], alternatives: [] } };
      return { json: { count: 0, next: null, previous: null, results: [] } };
    });
    afficher(<Planning />);
    await userEvent.click(await screen.findByRole("button", { name: /Club 7/ }));
    const dialogue = await screen.findByRole("dialog");
    await userEvent.click(within(dialogue).getByRole("button", { name: "Déplacer…" }));
    await userEvent.click(await screen.findByRole("button", { name: "Vérifier la disponibilité" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Créneau indisponible" })).toBeInTheDocument());
    expect(screen.getByText(/Club voisin/)).toBeInTheDocument();
    expect(appels.some((a) => a.url.endsWith("/deplacer"))).toBe(false);
  });
});
