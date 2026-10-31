import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ErreurApi } from "../api/http";
import { Badge } from "./Badge";
import { Bouton } from "./Bouton";
import { CaseACocher, ChampSelection, ChampTexte } from "./Champ";
import { Dialogue } from "./Dialogue";
import { Chargement, Erreur, Vide } from "./Etats";
import { Tableau } from "./Tableau";

describe("Composants accessibles du back-office", () => {
  it("relie le libellé, l'aide et l'erreur au champ", () => {
    render(<ChampTexte libelle="Nom" aide="Nom usuel" erreur="Ce champ est obligatoire." obligatoire value="" onChange={() => undefined} />);
    const champ = screen.getByLabelText(/Nom/);
    expect(champ).toHaveAttribute("aria-invalid", "true");
    expect(champ).toHaveAccessibleDescription(/Nom usuel.*Ce champ est obligatoire/);
    expect(screen.getByText("(obligatoire)")).toBeInTheDocument();
  });

  it("propose une option vide et les options d'une liste", () => {
    render(<ChampSelection libelle="Site" options={[{ valeur: "1", libelle: "Stade" }]} value="" onChange={() => undefined} />);
    expect(screen.getByRole("combobox", { name: "Site" })).toHaveDisplayValue("— Choisir —");
    expect(screen.getByRole("option", { name: "Stade" })).toBeInTheDocument();
  });

  it("case à cocher libellée", async () => {
    const changement = vi.fn();
    render(<CaseACocher libelle="Actif" checked={false} onChange={changement} />);
    await userEvent.click(screen.getByRole("checkbox", { name: "Actif" }));
    expect(changement).toHaveBeenCalled();
  });

  it("le bouton annonce un traitement en cours", () => {
    render(<Bouton enCours>Enregistrer</Bouton>);
    expect(screen.getByRole("button")).toHaveAttribute("aria-busy", "true");
    expect(screen.getByRole("button")).toBeDisabled();
  });

  it("un statut porte un libellé, pas seulement une couleur", () => {
    render(<Badge libelle="Validée" ton="succes" />);
    expect(screen.getByText("Validée")).toBeInTheDocument();
  });

  it("les états chargement, vide et erreur sont annoncés", () => {
    const { rerender } = render(<Chargement />);
    expect(screen.getByRole("status")).toHaveTextContent("Chargement en cours");
    rerender(<Vide message="Aucune demande." />);
    expect(screen.getByText("Aucune demande.")).toBeInTheDocument();
    const reessayer = vi.fn();
    rerender(<Erreur erreur={new ErreurApi(500, "erreur", "Service indisponible.")} reessayer={reessayer} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Service indisponible.");
  });

  it("RG-14 une erreur 403 affiche « droits insuffisants »", () => {
    render(<Erreur erreur={new ErreurApi(403, "permission_denied", "Vous n'avez pas les droits pour cette action.")} />);
    expect(screen.getByRole("alert")).toHaveTextContent("contactez l'administrateur fonctionnel");
  });

  it("le tableau trie au clavier et annonce le sens du tri", async () => {
    render(
      <Tableau
        legende="Sites"
        colonnes={[{ cle: "nom", titre: "Nom", rendu: (l: { nom: string }) => l.nom, valeurTri: (l) => l.nom }]}
        lignes={[{ nom: "Stade" }, { nom: "Arène" }]}
        cleLigne={(l) => l.nom}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: /Nom/ }));
    expect(screen.getByRole("columnheader")).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("cell").map((c) => c.textContent)).toEqual(["Arène", "Stade"]);
  });

  it("le tableau vide l'indique en clair", () => {
    render(<Tableau legende="Sites" colonnes={[{ cle: "nom", titre: "Nom", rendu: () => "" }]} lignes={[]} cleLigne={() => 1} messageVide="Rien." />);
    expect(screen.getByText("Rien.")).toBeInTheDocument();
  });

  it("le dialogue porte un titre et se ferme", async () => {
    const fermer = vi.fn();
    render(
      <Dialogue ouvert titre="Ajouter un site" onFermer={fermer}>
        <p>Contenu</p>
      </Dialogue>,
    );
    expect(screen.getByRole("heading", { name: "Ajouter un site" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Fermer la fenêtre" }));
    expect(fermer).toHaveBeenCalled();
  });
});
