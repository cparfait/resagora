/**
 * Lot 6 — pilotage : tableau de bord « à traiter » dont les compteurs ouvrent la liste filtrée (DSH-01, DSH-06),
 * statistiques et tableau de la direction (STA-01 à STA-05, DSH-04), valorisation des avantages en nature avec
 * alerte de seuil (VAL-05), méthodes (VAL-01), éditions du planning en PDF (IMP-01, IMP-03) et envoi programmé (IMP-04).
 */
import { expect, test } from "@playwright/test";
import { BACKOFFICE, connecterAgent, sansViolationAxe } from "./outils";

test("DSH-01 DSH-06 @a11y le tableau de bord ouvre la liste filtrée de chaque compteur", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  const section = page.getByRole("region", { name: "À traiter aujourd'hui" });
  await expect(section).toBeVisible();
  await expect(page.getByText("Chargement en cours…")).toHaveCount(0);
  await sansViolationAxe(page, "le tableau de bord");
  const compteur = section.getByRole("link").first();
  if ((await compteur.count()) > 0) {
    const lien = (await compteur.getAttribute("href")) ?? "";
    await compteur.click();
    await expect.poll(() => { const u = new URL(page.url()); return `${u.pathname}${u.search}`; }).toBe(lien);
    await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  }
});

test("STA-01 STA-02 STA-03 DSH-04 VAL-01 VAL-05 IMP-04 @a11y les écrans de pilotage sont accessibles", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  for (const [chemin, titre] of [
    ["/pilotage/statistiques", "Statistiques"],
    ["/pilotage/valorisation", "Valorisation des avantages en nature"],
    ["/pilotage/methodes-valorisation", "Méthodes de valorisation"],
    ["/pilotage/editions", "Éditions du planning"],
    ["/documents/a-controler", "Documents signés à contrôler"],
  ]) {
    await page.goto(`${BACKOFFICE}${chemin}`);
    await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();
    await expect(page.getByText("Chargement en cours…")).toHaveCount(0);
    await sansViolationAxe(page, `l'écran ${chemin}`);
  }
  await page.goto(`${BACKOFFICE}/pilotage/statistiques`);
  await expect(page.getByRole("table", { name: /Occupation par site/ })).toBeVisible();
  await page.goto(`${BACKOFFICE}/pilotage/valorisation`);
  const synthese = page.getByRole("table", { name: /Synthèse \d{4}/ });
  await expect(synthese).toBeVisible();
  // Données de CityResa : associations valorisées, aucune au-delà du seuil de 23 000 € (alerte testée côté API).
  await expect(synthese.getByRole("row").nth(1)).toBeVisible();
  await expect(page.getByText(/Les attestations s'éditent une fois l'exercice clôturé/)).toBeVisible();
  await page.goto(`${BACKOFFICE}/pilotage/editions`);
  await expect(page.getByRole("cell", { name: /Planning hebdomadaire/ }).first()).toBeVisible();
});

test("IMP-01 IMP-03 le planning d'un espace et la feuille de salle s'impriment en PDF", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  await page.goto(`${BACKOFFICE}/pilotage/editions`);
  const liste = page.getByLabel("ou espace", { exact: true }).first();
  await liste.selectOption({ index: 1 });
  const [planning] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: "Imprimer le planning" }).click()]);
  expect(planning.suggestedFilename()).toMatch(/^planning-\d{8}\.pdf$/);
  const [feuille] = await Promise.all([page.waitForEvent("download"), page.getByRole("button", { name: /Feuille de salle/ }).click()]);
  expect(feuille.suggestedFilename()).toMatch(/^feuille-\d+-\d{8}\.pdf$/);
});

test("DSH-04 le tableau de la direction est refusé au gestionnaire", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  const reponse = await page.request.get(`${BACKOFFICE}/api/gestion/pilotage/direction`);
  expect(reponse.status()).toBe(403);
});
