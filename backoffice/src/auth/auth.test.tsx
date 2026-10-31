import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { App } from "../App";
import { Cadre } from "../cadre/Cadre";
import { afficher, profil, simulerApi } from "../test/outils";
import { peutAvec } from "./session";

describe("SEC-02 / SEC-03 connexion des agents", () => {
  it("SEC-02 sans session, l'écran de connexion est affiché", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { statut: 401, json: { code: "not_authenticated" } } : { statut: 204 }));
    afficher(<App />);
    expect(await screen.findByRole("heading", { name: "Connexion" })).toBeInTheDocument();
    expect(screen.getByLabelText(/Identifiant/)).toHaveAttribute("autocomplete", "username");
  });

  it("SEC-02 identifiants refusés : message du serveur affiché", async () => {
    simulerApi((m, url) => {
      if (url.endsWith("/moi")) return { statut: 401, json: {} };
      if (m === "POST" && url.endsWith("/auth/connexion")) return { statut: 400, json: { code: "identifiants_invalides", message: "Identifiant ou mot de passe incorrect." } };
      return { statut: 204 };
    });
    afficher(<App />);
    await userEvent.type(await screen.findByLabelText(/Identifiant/), "agent");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "faux");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Identifiant ou mot de passe incorrect.");
  });

  it("SEC-03 un rôle sensible passe par l'étape du code TOTP", async () => {
    const appels = simulerApi((m, url) => {
      if (url.endsWith("/moi")) return { statut: 401, json: {} };
      if (m === "POST" && url.endsWith("/auth/connexion")) return { json: { etape: "code_totp" } };
      if (m === "POST" && url.endsWith("/auth/totp")) return { statut: 400, json: { code: "code_invalide", message: "Code incorrect ou expiré." } };
      return { statut: 204 };
    });
    afficher(<App />);
    await userEvent.type(await screen.findByLabelText(/Identifiant/), "regie");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("heading", { name: "Vérification en deux étapes" })).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText(/Code à 6 chiffres/), "123456");
    await userEvent.click(screen.getByRole("button", { name: "Valider le code" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Code incorrect");
    expect(appels.find((a) => a.url.endsWith("/auth/totp"))?.corps).toEqual({ code: "123456" });
  });

  it("SEC-03 l'enrôlement affiche le code QR décrit", async () => {
    simulerApi((m, url) => {
      if (url.endsWith("/moi")) return { statut: 401, json: {} };
      if (m === "POST" && url.endsWith("/auth/connexion")) return { json: { etape: "enrolement_totp" } };
      if (url.endsWith("/auth/totp/enrolement")) return { json: { uri: "otpauth://totp/x", qr_svg: "<svg></svg>", graine: "ABCDEF" } };
      return { statut: 204 };
    });
    afficher(<App />);
    await userEvent.type(await screen.findByLabelText(/Identifiant/), "admin");
    await userEvent.type(screen.getByLabelText(/Mot de passe/), "secret");
    await userEvent.click(screen.getByRole("button", { name: "Se connecter" }));
    expect(await screen.findByRole("img", { name: /Code QR/ })).toBeInTheDocument();
    expect(screen.getByText("ABCDEF")).toBeInTheDocument();
  });
});

describe("RG-14 droits dans l'interface", () => {
  it("RG-14 peut() respecte rôle × périmètre et la double authentification", () => {
    const moi = profil(["lire_referentiel", "gerer_referentiel"]);
    expect(peutAvec(moi, "gerer_referentiel", 1)).toBe(true);
    expect(peutAvec(moi, "gerer_referentiel", 2)).toBe(false);
    expect(peutAvec(moi, "administrer")).toBe(false);
    expect(peutAvec({ ...moi, double_authentification_exigee: true }, "lire_referentiel")).toBe(false);
    expect(peutAvec(null, "lire_referentiel")).toBe(false);
  });

  it("RG-14 la navigation n'affiche que les écrans autorisés", async () => {
    simulerApi((_m, url) => (url.endsWith("/moi") ? { json: profil(["lire_referentiel"]) } : { json: { count: 0, results: [] } }));
    afficher(<Cadre />);
    await waitFor(() => expect(screen.getByRole("link", { name: "Sites" })).toBeInTheDocument());
    expect(screen.queryByRole("link", { name: "Journal d'audit" })).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Rôles" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Aller au contenu" })).toHaveAttribute("href", "#contenu");
  });
});
