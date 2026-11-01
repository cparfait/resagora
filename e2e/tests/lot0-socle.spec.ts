/** Lot 0 — parcours agent : connexion AD (SEC-02), double authentification (SEC-03), droits (RG-14), audit (ADM-05). */
import { expect, test } from "@playwright/test";
import { BACKOFFICE, codeTotp, connecterAgent, sansViolationAxe } from "./outils";

test.describe("Lot 0 — socle", () => {
  test("SEC-02 @a11y page de connexion accessible", async ({ page }) => {
    await page.goto(BACKOFFICE);
    await expect(page.getByRole("heading", { name: "Connexion" })).toBeVisible();
    await sansViolationAxe(page, "la page de connexion");
  });

  test("SEC-02 un mot de passe faux affiche un message neutre", async ({ page }) => {
    await page.goto(BACKOFFICE);
    await page.getByLabel("Identifiant").fill("gest.ville");
    await page.getByLabel(/Mot de passe/).fill("mauvais-mot-de-passe");
    await page.getByRole("button", { name: "Se connecter" }).click();
    await expect(page.getByRole("alert")).toHaveText("Identifiant ou mot de passe incorrect.");
  });

  test("SEC-02 RG-14 @a11y un gestionnaire se connecte par l'annuaire et voit ses écrans", async ({ page }) => {
    await connecterAgent(page, "gest.ville");
    await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
    await expect(page.getByText("Gestionnaire des équipements")).toBeVisible();
    const navigation = page.getByRole("navigation", { name: "Navigation principale" });
    await expect(navigation.getByRole("link", { name: "Sites et espaces", exact: true })).toBeVisible();
    await expect(navigation.getByRole("link", { name: "Journal d'audit" })).toHaveCount(0);
    await sansViolationAxe(page, "l'accueil du gestionnaire");
    await navigation.getByRole("link", { name: "Sites et espaces", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Sites" })).toBeVisible();
    // Les écrans de la rubrique sont proposés en onglets (menu sur le modèle de CityResa).
    const onglets = page.getByRole("navigation", { name: "Écrans de la rubrique Sites et espaces" });
    await expect(onglets.getByRole("link", { name: "Sites", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(onglets.getByRole("link", { name: "Espaces", exact: true })).toBeVisible();
    await sansViolationAxe(page, "la liste des sites");
    const reponse = await page.request.get(`${BACKOFFICE}/api/gestion/audit/journal`);
    expect(reponse.status()).toBe(403);
  });

  test("SEC-03 ADM-05 @a11y l'administrateur active la double authentification puis consulte le journal", async ({ page }) => {
    await connecterAgent(page, "admin.recette");
    const titre = page.getByRole("heading", { level: 1 });
    await expect(titre).toHaveText(/deux étapes/);
    if ((await titre.textContent())?.includes("Activer")) {
      await expect(page.getByRole("img", { name: /Code QR/ })).toBeVisible();
      await sansViolationAxe(page, "l'enrôlement TOTP");
      const graine = (await page.locator(".connexion__graine").textContent()) ?? "";
      await page.getByLabel(/Code à 6 chiffres/).fill(codeTotp(graine));
      await page.getByRole("button", { name: "Valider le code" }).click();
      await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
      await page.getByRole("link", { name: "Journal d'audit" }).click();
      await expect(page.getByRole("heading", { level: 1, name: "Journal d'audit" })).toBeVisible();
      await page.getByRole("button", { name: "Vérifier l'intégrité" }).click();
      await expect(page.getByText(/Chaîne intègre/)).toBeVisible();
      await sansViolationAxe(page, "le journal d'audit");
    } else {
      // Compte déjà enrôlé lors d'une exécution précédente : le code est demandé.
      await expect(page.getByLabel(/Code à 6 chiffres/)).toBeVisible();
    }
  });
});
