import { defineConfig, devices } from "@playwright/test";

/**
 * Parcours de bout en bout sur la pile de recette (LAN + DMZ en conteneurs, données de démonstration).
 * BACKOFFICE_URL : proxy LAN ; PORTAIL_URL : proxy DMZ ; MOBILE_URL : application des gardiens.
 */
export default defineConfig({
  testDir: "./tests",
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: process.env.BACKOFFICE_URL ?? "https://localhost",
    ignoreHTTPSErrors: true,
    locale: "fr-FR",
    timezoneId: "Europe/Paris",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Recette sur un poste : les noms publics du portail et de la signature pointent vers le proxy DMZ local.
    launchOptions: { args: ["--host-resolver-rules=MAP equipements.chatillon.test 127.0.0.1, MAP signature.chatillon.test 127.0.0.1"] },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
