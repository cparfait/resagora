/** Refonte graphique (DESIGN.md) : parcours clavier des gabarits — lien d'évitement visible au focus, focus visible
 * (anneau vert profond de 3 px), menu du back-office sur petit écran (aria-expanded), planning sans défilement. */
import { expect, test, type Page } from "@playwright/test";
import { BACKOFFICE, connecterAgent, PORTAIL, sansViolationAxe } from "./outils";

async function anneauDeFocus(page: Page): Promise<string> {
  return page.evaluate(() => {
    const style = getComputedStyle(document.activeElement as Element);
    return `${style.outlineStyle} ${style.outlineWidth}`;
  });
}

test("POR-09 @a11y portail : lien d'évitement au clavier puis focus visible sur la navigation", async ({ page }) => {
  await page.goto(PORTAIL);
  await page.keyboard.press("Tab");
  const evitement = page.getByRole("link", { name: "Aller au contenu" });
  await expect(evitement).toBeFocused();
  await expect(evitement).toBeInViewport();
  expect(await anneauDeFocus(page)).toBe("solid 3px");
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: /Ville de Châtillon/ })).toBeFocused();
  expect(await anneauDeFocus(page)).toBe("solid 3px");
  await page.keyboard.press("Shift+Tab");
  await expect(evitement).toBeFocused();
});

test("PLA-01 @a11y back-office : menu au clavier sur petit écran et planning sans défilement en 1280 × 720", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 720 });
  await connecterAgent(page, "gest.ville");
  const menu = page.getByRole("button", { name: "Menu" });
  await expect(menu).toHaveAttribute("aria-expanded", "false");
  await expect(page.getByRole("navigation", { name: "Navigation principale" })).toBeHidden();
  await menu.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveAttribute("aria-expanded", "true");
  const navigation = page.getByRole("navigation", { name: "Navigation principale" });
  await expect(navigation).toBeVisible();
  await sansViolationAxe(page, "le menu ouvert sur petit écran");
  await navigation.getByRole("link", { name: "Planning", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Planning" })).toBeFocused();
  await expect(menu).toHaveAttribute("aria-expanded", "false");

  await page.setViewportSize({ width: 1280, height: 720 });
  await page.getByRole("button", { name: "Période suivante" }).click();
  await expect(page.getByRole("group", { name: /^Planning du/ })).toBeVisible();
  const defilement = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  expect(defilement, "le planning de la semaine tient dans la fenêtre").toBeLessThanOrEqual(0);
  const filtres = page.getByRole("button", { name: /^Filtres/ });
  await filtres.focus();
  await page.keyboard.press("Enter");
  await expect(filtres).toHaveAttribute("aria-expanded", "true");
  await expect(page.getByRole("search", { name: "Filtrer le planning" })).toBeVisible();
  await sansViolationAxe(page, "le planning avec les filtres ouverts");
});
