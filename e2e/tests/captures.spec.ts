/** Refonte graphique (DESIGN.md) : captures de trois écrans par application, à 320 et 1280 px. Désactivé par défaut :
 * CAPTURES=avant|apres npx playwright test captures. Images dans e2e/.etat/captures/<phase>/ (ignoré par Git). Mesure
 * aussi le défilement vertical (planning sans défilement) et le débordement horizontal. */
import { test, type Page } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { BACKOFFICE, connecterAgent, PORTAIL } from "./outils";

const PHASE = process.env.CAPTURES ?? "";
const DOSSIER = resolve(import.meta.dirname, "../.etat/captures", PHASE);
const LARGEURS = [
  { nom: "320", largeur: 320, hauteur: 720 },
  { nom: "1280", largeur: 1280, hauteur: 720 },
];
const BACKOFFICE_ECRANS = [
  ["accueil", "/"],
  ["planning", "/reservations/planning"],
  ["dossiers", "/reservations/dossiers"],
];
const PORTAIL_ECRANS = [
  ["accueil", "/"],
  ["equipements", "/equipements"],
  ["connexion", "/connexion"],
];

test.skip(!PHASE, "Captures de la refonte : CAPTURES=avant|apres");

async function capturer(page: Page, application: string, ecrans: string[][], base: string, mesures: string[]) {
  for (const { nom, largeur, hauteur } of LARGEURS) {
    await page.setViewportSize({ width: largeur, height: hauteur });
    for (const [ecran, chemin] of ecrans) {
      await page.goto(`${base}${chemin}`);
      await page.waitForLoadState("networkidle");
      if (ecran === "planning") {
        // Semaine de la Toussaint vide dans le jeu de démonstration : la suivante montre des séances.
        await page.getByRole("button", { name: "Période suivante" }).click();
        await page.getByRole("group", { name: /^Planning du/ }).waitFor();
      }
      await page.screenshot({ path: resolve(DOSSIER, `${application}-${ecran}-${nom}.png`), fullPage: true });
      const { defilement, horizontal } = await page.evaluate(() => ({
        defilement: document.documentElement.scrollHeight - window.innerHeight,
        horizontal: document.documentElement.scrollWidth - window.innerWidth,
      }));
      mesures.push(`${application}\t${ecran}\t${nom}\tdéfilement vertical ${defilement} px\tdébordement horizontal ${horizontal} px`);
    }
  }
}

test("captures du back-office et du portail", async ({ page }) => {
  test.setTimeout(600_000);
  mkdirSync(DOSSIER, { recursive: true });
  const mesures: string[] = [];
  await capturer(page, "portail", PORTAIL_ECRANS, PORTAIL, mesures);
  await connecterAgent(page, "gest.ville");
  // La page de connexion a aussi un titre de niveau 1 : on attend la navigation de l'application connectée.
  await page.getByRole("navigation", { name: "Navigation principale" }).waitFor();
  await capturer(page, "backoffice", BACKOFFICE_ECRANS, BACKOFFICE, mesures);
  writeFileSync(resolve(DOSSIER, "mesures.tsv"), `${mesures.join("\n")}\n`, "utf8");
});
