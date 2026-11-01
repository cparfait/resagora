/**
 * Lot 5 — matériel : écrans accessibles (MAT-01, MAT-03 à MAT-05) et prêt depuis la fiche d'un dossier, refusé
 * quand la quantité demandée dépasse la disponibilité (MAT-02, scénario R5-02), accepté sinon.
 */
import { expect, test } from "@playwright/test";
import { BACKOFFICE, connecterAgent, sansViolationAxe } from "./outils";

test("MAT-01 MAT-03 MAT-04 MAT-05 @a11y les écrans du matériel sont accessibles", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  for (const [chemin, titre] of [
    ["/materiel/stocks", "État du stock"],
    ["/materiel/prets", "Prêts de matériel"],
    ["/materiel/controles", "Contrôles et maintenance"],
    ["/materiel/pannes", "Pannes"],
    ["/materiel/mouvements", "Mouvements de stock"],
    ["/materiel/catalogue", "Catalogue du matériel"],
  ]) {
    await page.goto(`${BACKOFFICE}${chemin}`);
    await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();
    await expect(page.getByText("Chargement en cours…")).toHaveCount(0);
    await sansViolationAxe(page, `l'écran ${chemin}`);
  }
  await page.goto(`${BACKOFFICE}/materiel/controles`);
  await expect(page.getByRole("heading", { name: /Contrôles dépassés \(\d+/ })).toBeVisible();
  await page.goto(`${BACKOFFICE}/materiel/pannes`);
  await expect(page.getByRole("cell", { name: /Sonorisation portable/ }).first()).toBeVisible();
});

test("MAT-02 R5-02 un prêt au-delà de la disponibilité est refusé depuis la fiche du dossier", async ({ page }) => {
  await connecterAgent(page, "gest.ville");
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  const prets = (await (await page.request.get(`${BACKOFFICE}/api/gestion/materiel/prets?taille=1&statut=validee`)).json()) as { results: { dossier: number }[] };
  const dossier = prets.results[0]?.dossier;
  expect(dossier).toBeDefined();
  await page.goto(`${BACKOFFICE}/reservations/dossiers/${dossier}`);
  const section = page.getByRole("region", { name: "Matériel" });
  await expect(section).toBeVisible();
  await sansViolationAxe(page, "la fiche du dossier avec son matériel");
  const preter = async (quantite: string) => {
    await section.getByRole("button", { name: "Prêter du matériel" }).click();
    const dialogue = page.getByRole("dialog", { name: "Prêter du matériel" });
    await dialogue.getByLabel(/Réservation/).selectOption({ index: 1 });
    const liste = dialogue.getByLabel(/Matériel du site/);
    await expect(liste.locator("option", { hasText: "Chaises pliantes" })).toHaveCount(1);
    await liste.selectOption((await liste.locator("option", { hasText: "Chaises pliantes" }).getAttribute("value")) ?? "");
    await dialogue.getByLabel(/Quantité/).fill(quantite);
    await dialogue.getByRole("button", { name: "Enregistrer le prêt" }).click();
  };
  await preter("5000");
  await expect(page.getByText(/disponible\(s\) du .* 5000 demandé\(s\)/)).toBeVisible();
  await preter("3");
  await expect(page.getByText(/Prêt de matériel enregistré/)).toBeVisible();
  await expect(section.getByRole("cell", { name: /3 × Chaises pliantes/ }).first()).toBeVisible();
});
