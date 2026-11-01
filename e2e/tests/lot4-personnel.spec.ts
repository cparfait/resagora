/**
 * Lot 4 — personnel et application mobile des gardiens : écrans du planificateur (PER-02 à PER-07, IMP-02), puis
 * parcours hors ligne d'un gardien (MOB-01, MOB-02, MOB-05, MOB-07) : connexion, mode avion, pointage mis en file,
 * réouverture sans réseau, retour du réseau et envoi unique.
 */
import { expect, test, type Browser, type Page } from "@playwright/test";
import { BACKOFFICE, MOBILE, connecterAvecTotp, motDePasseDemo, sansViolationAxe } from "./outils";

/** Code de déverrouillage choisi par le gardien de recette (propre à l'application, distinct du mot de passe). */
const CODE = "582047";

test("PER-02 PER-03 PER-07 IMP-02 REF-04 @a11y les écrans du planificateur sont accessibles", async ({ page }) => {
  await connecterAvecTotp(page, "planif.recette");
  for (const [chemin, titre] of [
    ["/personnel/vacations", "Planning du personnel"],
    ["/personnel/presence", "Présence par site"],
    ["/personnel/agents", "Agents d'équipement et gardiens"],
    ["/personnel/trames", "Trames hebdomadaires"],
    ["/personnel/absences", "Absences"],
    ["/personnel/compteurs", "Compteurs d'heures"],
    ["/personnel/incidents", "Incidents"],
    ["/personnel/saisies", "Saisies du terrain"],
  ]) {
    await page.goto(`${BACKOFFICE}${chemin}`);
    await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();
    await expect(page.getByText("Chargement en cours…")).toHaveCount(0);
    await sansViolationAxe(page, `l'écran ${chemin}`);
  }
  await page.goto(`${BACKOFFICE}/personnel/agents`);
  await expect(page.getByRole("cell", { name: "DEMO0001" })).toBeVisible();
  const agents = (await (await page.request.get(`${BACKOFFICE}/api/gestion/personnel/agents?taille=50`)).json()) as { results: { id: number; identifiant_ad: string }[] };
  const gardien = agents.results.find((a) => a.identifiant_ad === "gardien01");
  expect(gardien).toBeDefined();
  const du = new Date().toISOString().slice(0, 10);
  const au = new Date(Date.now() + 13 * 86_400_000).toISOString().slice(0, 10);
  const pdf = await page.request.get(`${BACKOFFICE}/api/gestion/personnel/vacations/planning-pdf?agent=${gardien?.id}&du=${du}&au=${au}`);
  expect(pdf.status()).toBe(200);
  expect((await pdf.body()).subarray(0, 5).toString()).toBe("%PDF-");
});

/** SEC-10 : un nouveau téléphone au-delà de deux appareils (ou après un retrait) attend l'autorisation du planificateur. */
async function autoriserAppareilsEnAttente(browser: Browser): Promise<void> {
  const contexte = await browser.newContext({ ignoreHTTPSErrors: true });
  const planif = await contexte.newPage();
  await connecterAvecTotp(planif, "planif.recette");
  const liste = (await (await planif.request.get(`${BACKOFFICE}/api/gestion/personnel/appareils?taille=200`)).json()) as {
    results: { id: number; a_autoriser: boolean; revoque_le: string | null }[];
  };
  const csrf = (await contexte.cookies()).find((c) => c.name.includes("csrf"))?.value ?? "";
  for (const appareil of liste.results.filter((a) => a.a_autoriser && !a.revoque_le)) {
    const reponse = await planif.request.post(`${BACKOFFICE}/api/gestion/personnel/appareils/${appareil.id}/autoriser`, { headers: { "X-CSRFToken": csrf, Origin: BACKOFFICE, Referer: `${BACKOFFICE}/` } });
    expect(reponse.status()).toBe(200);
  }
  await contexte.close();
}

async function seConnecter(page: Page): Promise<void> {
  await page.getByLabel("Identifiant").fill("gardien01");
  await page.getByLabel("Mot de passe").fill(motDePasseDemo());
  await page.getByRole("button", { name: "Se connecter" }).click();
}

test("MOB-01 MOB-02 MOB-05 SEC-10 @a11y un gardien pointe hors ligne, rouvre l'application sans réseau puis synchronise", async ({ page, context, browser }) => {
  await page.goto(MOBILE);
  const changer = page.getByRole("button", { name: /Changer de compte/ });
  if (await changer.isVisible().catch(() => false)) await changer.click();
  await seConnecter(page);
  const choix = page.getByRole("heading", { level: 1, name: "Choisissez votre code" });
  const refus = page.getByRole("alert").filter({ hasText: "appareil non autorisé" });
  await expect(choix.or(refus)).toBeVisible();
  if (await refus.isVisible()) {
    // Nouveau navigateur de recette = nouvel appareil : le planificateur l'autorise, puis le gardien se reconnecte.
    await autoriserAppareilsEnAttente(browser);
    await seConnecter(page);
  }
  await expect(choix).toBeVisible();
  await sansViolationAxe(page, "le choix du code de déverrouillage");
  await page.getByLabel("Code de déverrouillage", { exact: true }).fill(CODE);
  await page.getByLabel("Confirmez le code").fill(CODE);
  await page.getByRole("button", { name: "Enregistrer le code" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour .* — mes vacations/ })).toBeVisible();
  await expect(page.getByText(/^Connecté — 0 saisie en attente/)).toBeVisible();
  await sansViolationAxe(page, "le planning du gardien");
  // Le service worker est installé : la coquille de l'application est en cache.
  await page.waitForFunction(() => navigator.serviceWorker.controller !== null);

  await context.setOffline(true);
  await page.getByRole("button", { name: /Pointer mon arrivée/ }).first().click();
  await expect(page.getByText(/Hors ligne — 1 saisie en attente/)).toBeVisible();

  // Mode avion : l'application se rouvre et se déverrouille avec le mot de passe, sans réseau (MOB-01, MOB-07).
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Déverrouiller l'application" })).toBeVisible();
  await expect(page.getByText(/1 saisie pas encore transmise/)).toBeVisible();
  await sansViolationAxe(page, "le déverrouillage hors ligne");
  await page.getByLabel("Code de déverrouillage", { exact: true }).fill(CODE);
  await page.getByRole("button", { name: "Déverrouiller" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /mes vacations/ })).toBeVisible();
  await expect(page.getByText(/Hors ligne — 1 saisie en attente/)).toBeVisible();

  // Retour du réseau : la saisie part une fois, la file se vide (MOB-05).
  await context.setOffline(false);
  await page.getByRole("button", { name: "Synchroniser" }).click();
  await expect(page.getByText(/Connecté — 0 saisie en attente/)).toBeVisible();
  await page.getByRole("button", { name: "Se déconnecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Connexion des gardiens" })).toBeVisible();
});
