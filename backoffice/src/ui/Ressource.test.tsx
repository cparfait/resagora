import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import Sites from "../modules/referentiel/Sites";
import { afficher, profil, simulerApi } from "../test/outils";

const SITE = { id: 1, code: "stade", nom: "Stade municipal", adresse: "1 rue du Stade", code_postal: "92320", commune: "Châtillon", telephone: "", actif: true };

describe("REF-01 écran générique des ressources (sites)", () => {
  it("REF-01 liste les sites et propose l'ajout si l'agent peut gérer le référentiel", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["lire_referentiel", "gerer_referentiel"]) } : { json: { count: 1, next: null, previous: null, results: [SITE] } }));
    afficher(<Sites />);
    expect(await screen.findByRole("cell", { name: "Stade municipal" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Ajouter site/ })).toBeInTheDocument();
    expect(screen.getByText("1 élément")).toBeInTheDocument();
  });

  it("RG-14 sans droit d'écriture, ni ajout ni modification", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["lire_referentiel"]) } : { json: { count: 1, next: null, previous: null, results: [SITE] } }));
    afficher(<Sites />);
    expect(await screen.findByRole("cell", { name: "Stade municipal" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Ajouter/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Modifier/ })).not.toBeInTheDocument();
  });

  it("RG-14 sans droit de lecture, écran « droits insuffisants »", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["administrer"]) } : undefined));
    afficher(<Sites />);
    expect(await screen.findByRole("alert")).toHaveTextContent("droits");
  });

  it("REF-01 les erreurs du serveur sont affichées sous les champs", async () => {
    simulerApi((m, url) => {
      if (url.endsWith("/moi")) return { json: profil(["lire_referentiel", "gerer_referentiel"]) };
      if (m === "POST") return { statut: 400, json: { code: "validation", message: "Certains champs sont invalides.", champs: { code: ["Ce code existe déjà."] } } };
      return { json: { count: 0, next: null, previous: null, results: [] } };
    });
    afficher(<Sites />);
    await userEvent.click(await screen.findByRole("button", { name: /Ajouter site/ }));
    const dialogue = await screen.findByRole("dialog");
    await userEvent.type(within(dialogue).getByLabelText("Code (obligatoire)"), "stade");
    await userEvent.type(within(dialogue).getByLabelText("Nom (obligatoire)"), "Stade");
    await userEvent.click(within(dialogue).getByRole("button", { name: "Enregistrer" }));
    await waitFor(() => expect(within(dialogue).getByLabelText("Code (obligatoire)")).toHaveAccessibleDescription(/Ce code existe déjà/));
    expect(within(dialogue).getByRole("alert")).toHaveTextContent("Certains champs sont invalides.");
  });

  it("REF-01 état d'erreur avec bouton Réessayer", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["lire_referentiel"]) } : { statut: 500, json: { message: "Service indisponible." } }));
    afficher(<Sites />);
    expect(await screen.findByRole("button", { name: "Réessayer" })).toBeInTheDocument();
  });
});
