/**
 * Lot 3 — finances : simulation publique du tarif (TAR-11, CAU-01) et écrans financiers du back-office accessibles
 * (TAR-01, TAR-05, TAR-10, CAU-06). Le devis accepté en ligne et la facture sont dans le parcours du lot 2.
 */
import { expect, test } from "@playwright/test";
import { BACKOFFICE, PORTAIL, connecterAgent, sansViolationAxe } from "./outils";

function samediProchain(): string {
  const jour = new Date(Date.now() + 14 * 86_400_000);
  while (jour.getDay() !== 6) jour.setDate(jour.getDate() + 1);
  return jour.toISOString().slice(0, 10);
}

test("TAR-11 CAU-01 @a11y le tarif d'une salle des fêtes s'estime en ligne, caution comprise", async ({ page }) => {
  await page.goto(`${PORTAIL}/equipements`);
  await page.getByLabel("Nom ou activité").fill("salle polyvalente");
  await page.getByRole("link", { name: "Salle polyvalente - Espace Maison Blanche" }).click();
  await expect(page.getByRole("heading", { level: 2, name: "Estimer le tarif" })).toBeVisible();
  await page.getByLabel(/^Date/).fill(samediProchain());
  await page.getByLabel(/Heure de début/).fill("14:00");
  await page.getByLabel(/Heure de fin/).fill("18:00");
  await page.getByLabel(/Vous êtes/).selectOption({ label: "Particulier" });
  await page.getByRole("button", { name: "Estimer" }).click();
  await expect(page.getByText(/Total estimé/)).toBeVisible();
  await expect(page.getByText(/Caution demandée : 1\s?000,00/)).toBeVisible();
  await sansViolationAxe(page, "la simulation de tarif");
});

test("TAR-01 TAR-05 TAR-10 CAU-06 @a11y les écrans financiers du back-office sont accessibles", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  for (const [chemin, titre] of [
    ["/finances/grilles", "Grilles tarifaires"],
    ["/finances/tarifs", "Tarifs"],
    ["/finances/reductions", "Gratuités et réductions"],
    ["/finances/pieces", "Devis, factures et avoirs"],
    ["/finances/retards", "Factures en retard"],
    ["/finances/cautions", "Cautions"],
  ]) {
    await page.goto(`${BACKOFFICE}${chemin}`);
    await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();
    await expect(page.getByText("Chargement en cours…")).toHaveCount(0);
    await sansViolationAxe(page, `l'écran ${chemin}`);
  }
  await page.goto(`${BACKOFFICE}/finances/pieces`);
  await expect(page.getByRole("cell", { name: /^F\d{4}-\d{5}$/ }).first()).toBeVisible();
});
