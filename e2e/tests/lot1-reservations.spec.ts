/** Lot 1 — parcours agent : planning (PLA-01), nouvelle demande avec aperçu (PLA-04), validation (PLA-06), usagers (USR-01). */
import { expect, test } from "@playwright/test";
import { connecterAgent, sansViolationAxe } from "./outils";

/** Créneau propre à chaque exécution (mardi à jeudi matin, hors vacances zone C et jours fériés) : le parcours est rejouable. */
function creneauDeRecette(): { date: string; debut: string; fin: string } {
  const semaines = ["2027-01-05", "2027-01-12", "2027-01-19", "2027-01-26", "2027-02-02", "2027-02-23", "2027-03-02", "2027-03-09", "2027-03-16", "2027-03-23", "2027-03-30"];
  const candidats = semaines.flatMap((mardi) => [0, 1, 2].flatMap((j) => [8, 9, 10, 11].map((h) => ({ mardi, j, h }))));
  const choix = candidats[Math.floor(Date.now() / 60_000) % candidats.length]!;
  const jour = new Date(`${choix.mardi}T12:00:00Z`);
  jour.setUTCDate(jour.getUTCDate() + choix.j);
  const deux = (n: number) => String(n).padStart(2, "0");
  return { date: jour.toISOString().slice(0, 10), debut: `${deux(choix.h)}:00`, fin: `${deux(choix.h)}:45` };
}

test.describe("Lot 1 — réservations", () => {
  test.beforeEach(async ({ page }) => {
    await connecterAgent(page, "gest.ville");
    await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
  });

  test("PLA-01 @a11y les six vues du planning sont accessibles", async ({ page }) => {
    await page.getByRole("navigation", { name: "Navigation principale" }).getByRole("link", { name: "Planning", exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Planning" })).toBeVisible();
    for (const vue of ["Semaine", "Jour", "Mois", "Chronologie par espace", "Multi-sites", "Liste"]) {
      await page.getByRole("button", { name: vue, exact: true }).click();
      await expect(page.getByRole("button", { name: vue, exact: true })).toHaveAttribute("aria-pressed", "true");
      await sansViolationAxe(page, `la vue ${vue} du planning`);
    }
    await page.getByRole("button", { name: "Liste", exact: true }).click();
    await page.getByRole("button", { name: "Période suivante" }).click();
    await expect(page.getByText(/séances? sur la période/)).toBeVisible();
  });

  test("PLA-04 PLA-06 @a11y saisir une demande, vérifier les disponibilités, enregistrer puis valider", async ({ page }) => {
    await page.goto("/reservations/nouvelle");
    await expect(page.getByRole("heading", { level: 1, name: "Nouvelle demande" })).toBeVisible();
    await sansViolationAxe(page, "la saisie d'une demande");
    await page.getByLabel("Rechercher un usager").fill("Atelier");
    await page.getByLabel(/^Usager/).selectOption({ index: 1 });
    await page.getByLabel(/^Type de réservation/).selectOption({ label: "Réservation ponctuelle" });
    await page.getByLabel(/^Objet/).fill("Tournoi de fin d'année");
    await page.getByLabel(/^Espace/).selectOption({ label: "Espace Maison Blanche — Salle de réunion du 1er étage - Espace Maison Blanche" });
    const creneau = creneauDeRecette();
    await page.getByLabel(/^Date de début/).fill(creneau.date);
    await page.getByLabel(/^Heure de début/).fill(creneau.debut);
    await page.getByLabel(/^Heure de fin/).fill(creneau.fin);
    await page.getByRole("button", { name: "Vérifier les disponibilités" }).click();
    await expect(page.getByRole("heading", { name: /Aperçu : 1 séance/ })).toBeVisible();
    await expect(page.getByText("Aucun conflit avec les réservations validées.")).toBeVisible();
    await page.getByRole("button", { name: "Enregistrer la demande" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /Dossier D\d{4}-\d{5}/ })).toBeVisible();
    await sansViolationAxe(page, "la fiche du dossier");
    await page.getByRole("button", { name: "Valider", exact: true }).click();
    await expect(page.getByText("Réservation : Validée.")).toBeVisible();
  });

  test("USR-01 @a11y consulter la fiche d'une association", async ({ page }) => {
    await page.goto("/usagers");
    await expect(page.getByRole("heading", { level: 1, name: "Usagers" })).toBeVisible();
    await sansViolationAxe(page, "la liste des usagers");
    await page.getByRole("button", { name: /Ouvrir la fiche de/ }).first().click();
    await expect(page.getByRole("heading", { level: 2, name: "Contacts" })).toBeVisible();
    await expect(page.getByRole("heading", { level: 2, name: "Pièces justificatives" })).toBeVisible();
    await sansViolationAxe(page, "la fiche usager");
  });
});
