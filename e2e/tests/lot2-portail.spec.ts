/**
 * Lot 2 — parcours usager sur le portail (à travers le proxy DMZ, la façade et le flux mTLS) et parcours agent :
 * pages publiques accessibles (POR-09), inscription et validation (POR-01, SEC-04), demande en quatre étapes
 * (POR-04), suivi et messagerie (POR-05, POR-08), pièces et antivirus (POR-06, SEC-07), signature (POR-10, SIG-01).
 */
import { expect, test, type Page } from "@playwright/test";
import { BACKOFFICE, ELU_COURRIEL, PORTAIL, connecterAgent, lienRecu, sansViolationAxe } from "./outils";

const suffixe = Date.now().toString(36);
const COURRIEL = `e2e-${suffixe}@exemple.test`;
const MOT_DE_PASSE = "Volant-Plume-Raquette-7";
const ASSOCIATION = `Badminton recette ${suffixe}`;
const PDF = Buffer.from("%PDF-1.7\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n");
const EICAR = Buffer.from("X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*");

function dansTroisSemaines(): string {
  const jour = new Date(Date.now() + 21 * 86_400_000);
  while (jour.getDay() !== 3) jour.setDate(jour.getDate() + 1);
  return jour.toISOString().slice(0, 10);
}

async function connecterUsager(page: Page) {
  await page.goto(`${PORTAIL}/connexion`);
  await page.getByLabel(/Adresse électronique/).fill(COURRIEL);
  await page.getByLabel(/^Mot de passe/).fill(MOT_DE_PASSE);
  await page.getByRole("button", { name: "Se connecter" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Mon espace" })).toBeVisible();
}

test.describe("Lot 2 — pages publiques", () => {
  test("POR-09 POR-03 POR-02 @a11y toutes les pages publiques sans violation, lien d'évitement au clavier", async ({ page }) => {
    await page.goto(`${PORTAIL}/`);
    await page.keyboard.press("Tab");
    await expect(page.getByRole("link", { name: "Aller au contenu" })).toBeFocused();
    await sansViolationAxe(page, "l'accueil du portail");
    await page.getByRole("navigation", { name: "Navigation principale" }).getByRole("link", { name: "Équipements" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Les équipements" })).toBeFocused();
    await expect(page.getByText(/équipements? trouvés?/)).toBeVisible();
    await sansViolationAxe(page, "le catalogue");
    await page.getByLabel("Nom ou activité").fill("salle associative");
    await page.getByRole("link", { name: "Salle associative 2" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Salle associative 2" })).toBeVisible();
    await sansViolationAxe(page, "la fiche d'un équipement");
    await page.getByRole("link", { name: "Voir les disponibilités" }).click();
    await expect(page.getByRole("table")).toBeVisible();
    await expect(page.getByRole("table")).not.toContainText("CSE");
    await sansViolationAxe(page, "la grille des disponibilités");
    await page.getByRole("button", { name: "Semaine suivante" }).click();
    await page.getByRole("button", { name: "Afficher en liste" }).click();
    await sansViolationAxe(page, "la liste des disponibilités");
    for (const [chemin, titre] of [
      ["/connexion", "Se connecter"],
      ["/inscription", "Créer un compte"],
      ["/mot-de-passe-oublie", "Mot de passe oublié"],
      ["/accessibilite", "Déclaration d'accessibilité"],
      ["/donnees-personnelles", "Données personnelles"],
      ["/mentions-legales", "Mentions légales"],
      ["/plan-du-site", "Plan du site"],
      ["/page-qui-n-existe-pas", "Page introuvable"],
    ]) {
      await page.goto(`${PORTAIL}${chemin}`);
      await expect(page.getByRole("heading", { level: 1, name: titre })).toBeVisible();
      await expect(page).toHaveTitle(new RegExp(`^${titre.replace("'", ".")}.*Portail des équipements`));
      await sansViolationAxe(page, `la page ${chemin}`);
    }
  });

  test("POR-09 SEC-04 @a11y les erreurs de connexion sont annoncées, sans dire si le compte existe", async ({ page }) => {
    await page.goto(`${PORTAIL}/connexion`);
    await page.getByLabel(/Adresse électronique/).fill(`inconnu-${suffixe}@exemple.test`);
    await page.getByLabel(/^Mot de passe/).fill("Mauvais-Mot-2026");
    await page.getByRole("button", { name: "Se connecter" }).click();
    await expect(page.getByRole("alert")).toContainText("Identifiant ou mot de passe incorrect.");
    await sansViolationAxe(page, "l'erreur de connexion");
  });
});

test.describe.serial("Lot 2 — parcours d'une association", () => {
  let dossier = "";

  test("POR-01 SEC-04 @a11y inscription, confirmation par courriel puis validation par la Ville", async ({ page, browser }) => {
    await page.goto(`${PORTAIL}/inscription`);
    await page.getByLabel(/Nom de la structure/).fill(ASSOCIATION);
    await page.getByLabel(/Adresse du siège/).fill("3 rue de la Recette");
    await page.getByLabel(/Code postal/).fill("92320");
    await page.getByLabel(/^Commune/).fill("Châtillon");
    await page.getByLabel(/^Prénom/).fill("Camille");
    await page.getByLabel(/^Nom \(obligatoire\)/).fill(`Recette ${suffixe}`);
    await page.getByLabel(/Adresse électronique/).fill(COURRIEL);
    await page.getByLabel(/^Mot de passe/).fill(MOT_DE_PASSE);
    await page.getByLabel(/Confirmez le mot de passe/).fill("autre-chose");
    await page.getByLabel(/J'accepte les conditions/).check();
    await page.getByRole("button", { name: "Créer mon compte" }).click();
    await expect(page.getByRole("alert")).toContainText("différents");
    await sansViolationAxe(page, "le formulaire d'inscription en erreur");
    await page.getByLabel(/Confirmez le mot de passe/).fill(MOT_DE_PASSE);
    await page.getByRole("button", { name: "Créer mon compte" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Demande de compte envoyée" })).toBeVisible();
    const lien = await lienRecu(page, COURRIEL, "confirmation");
    await page.goto(lien.replace(/^https?:\/\/[^/]+/, PORTAIL));
    await expect(page.getByText("Votre adresse est confirmée.")).toBeVisible();

    const contexteAgent = await browser.newContext({ ignoreHTTPSErrors: true, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const agent = await contexteAgent.newPage();
    await connecterAgent(agent, "gest.ville");
    await expect(agent.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
    await agent.goto(`${BACKOFFICE}/usagers/comptes`);
    await expect(agent.getByRole("heading", { level: 1, name: "Comptes du portail" })).toBeVisible();
    await sansViolationAxe(agent, "les comptes à valider");
    await agent.getByRole("button", { name: `Valider le compte de Camille Recette ${suffixe}` }).click();
    await agent.getByRole("dialog").getByRole("button", { name: "Valider le compte" }).click();
    await expect(agent.getByRole("status").filter({ hasText: /Actif/ }).first()).toBeVisible();
    await contexteAgent.close();

    await connecterUsager(page);
    await sansViolationAxe(page, "mon espace");
  });

  test("POR-06 SEC-07 @a11y dépôt d'une attestation PDF, fichier de test EICAR refusé", async ({ page }) => {
    await connecterUsager(page);
    await page.getByRole("link", { name: ASSOCIATION }).click();
    await expect(page.getByRole("heading", { level: 1, name: ASSOCIATION })).toBeVisible();
    await sansViolationAxe(page, "la fiche de la structure");
    await page.getByLabel(/Type de pièce/).selectOption({ label: "Attestation d'assurance responsabilité civile" });
    await page.getByLabel(/^Fichier/).setInputFiles({ name: "virus.pdf", mimeType: "application/pdf", buffer: EICAR });
    await page.getByRole("button", { name: "Déposer la pièce" }).click();
    await expect(page.getByRole("alert")).toContainText("contrôle antivirus");
    await page.getByLabel(/Type de pièce/).selectOption({ label: "Attestation d'assurance responsabilité civile" });
    await page.getByLabel(/^Fichier/).setInputFiles({ name: "assurance.pdf", mimeType: "application/pdf", buffer: PDF });
    await page.getByRole("button", { name: "Déposer la pièce" }).click();
    await expect(page.getByRole("status").filter({ hasText: "Pièce déposée" })).toBeVisible();
    await expect(page.getByRole("cell", { name: /En cours de vérification/ }).first()).toBeVisible();
  });

  test("POR-04 POR-05 POR-08 @a11y demande en quatre étapes avec brouillon, envoi, suivi et message", async ({ page }) => {
    await connecterUsager(page);
    await page.getByRole("link", { name: "Nouvelle demande" }).first().click();
    await expect(page.getByText("Étape 1 sur 4 : Espace et dates")).toBeVisible();
    await page.getByLabel(/Type de demande/).selectOption({ label: "Réservation ponctuelle" });
    await page.getByLabel(/^Équipement/).selectOption({ label: "Salle associative 2 — Maison des associations et salle des fêtes (25 pers.)" });
    await page.getByLabel(/^Date/).fill(dansTroisSemaines());
    await page.getByLabel(/Heure de début/).fill("14:00");
    await page.getByLabel(/Heure de fin/).fill("16:00");
    await page.getByRole("button", { name: "Vérifier les disponibilités" }).click();
    await expect(page.locator(".creneau__resume")).toContainText("1 séance");
    await sansViolationAxe(page, "l'étape 1 de la demande");
    await page.getByRole("button", { name: "Continuer vers l'étape 2" }).click();
    await expect(page.getByText("Étape 2 sur 4 : Détails de l'activité")).toBeVisible();
    await page.getByLabel(/Objet de la demande/).fill("Tournoi interne de recette");
    await page.getByLabel(/Nombre de personnes/).fill("30");
    await page.getByRole("button", { name: "Continuer vers l'étape 3" }).click();
    await expect(page.getByText("Étape 3 sur 4 : Pièces justificatives")).toBeVisible();
    dossier = page.url().split("/").pop() ?? "";
    await page.goto(`${PORTAIL}/espace/dossiers`);
    await page.getByRole("link", { name: /^D\d{4}-\d{5}$/ }).first().click();
    await expect(page.getByText("Étape 3 sur 4 : Pièces justificatives")).toBeVisible();
    await sansViolationAxe(page, "l'étape 3 reprise depuis le brouillon");
    await page.getByRole("button", { name: "Continuer vers le récapitulatif" }).click();
    await expect(page.getByText("Étape 4 sur 4 : Récapitulatif et envoi")).toBeVisible();
    await sansViolationAxe(page, "le récapitulatif");
    await page.getByRole("button", { name: "Envoyer ma demande" }).click();
    await expect(page.getByRole("heading", { level: 1, name: /Dossier D\d{4}-\d{5}/ })).toBeVisible();
    await expect(page.getByText("Demande envoyée").first()).toBeVisible();
    await page.getByLabel(/Votre message/).fill("Pourrons-nous arriver à 13 h 45 pour installer les tables ?");
    await page.getByRole("button", { name: "Envoyer le message" }).click();
    await expect(page.locator(".message--usager")).toContainText("13 h 45");
    await sansViolationAxe(page, "le suivi du dossier");
  });

  test("POR-10 SIG-01 SIG-03 @a11y la convention générée par la Ville est signée en ligne, dans l'ordre", async ({ page, browser }) => {
    const contexteAgent = await browser.newContext({ ignoreHTTPSErrors: true, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const agent = await contexteAgent.newPage();
    await connecterAgent(agent, "gest.ville");
    await expect(agent.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
    await agent.goto(`${BACKOFFICE}/reservations/dossiers/${dossier}`);
    await expect(agent.getByRole("heading", { level: 1, name: /Dossier D\d{4}-\d{5}/ })).toBeVisible();
    await agent.getByLabel("Modèle à générer").selectOption({ label: "Convention de mise à disposition" });
    await agent.getByRole("button", { name: "Générer le PDF" }).click();
    await expect(agent.getByRole("cell", { name: /Convention de mise à disposition/ })).toBeVisible();
    await sansViolationAxe(agent, "les documents du dossier");
    await agent.getByRole("button", { name: "Signature électronique" }).click();
    await expect(agent.getByText(/Signature (dépôt en cours|en attente de signature)/)).toBeVisible();
    await contexteAgent.close();

    await connecterUsager(page);
    await page.goto(`${PORTAIL}/espace/dossiers/${dossier}`);
    const signer = page.getByRole("button", { name: /Signer en ligne/ });
    await expect(async () => {
      await page.reload();
      await expect(signer).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 30_000 });
    await sansViolationAxe(page, "le document à signer");
    await signer.click();
    await expect(page.getByRole("heading", { name: /Signature/ })).toBeVisible();
    await page.getByLabel(/je le signe/).check();
    const signatureUsager = new Date(Date.now() - 2_000);
    await page.getByRole("button", { name: "Signer le document" }).click();
    await expect(page.getByText("Votre signature est enregistrée.")).toBeVisible();

    // SIG-01 : dès que l'usager a signé, l'élu reçoit par courriel son lien personnel (aucune lecture du simulateur).
    const lienElu = await lienRecu(page, ELU_COURRIEL, "s", String.raw`https?://\S+/s/[\w-]+`, signatureUsager);
    await page.goto(lienElu);
    await page.getByLabel(/je le signe/).check();
    await page.getByRole("button", { name: "Signer le document" }).click();

    await page.goto(`${PORTAIL}/espace/dossiers/${dossier}`);
    await expect(async () => {
      await page.reload();
      await expect(page.getByText(/Signé électroniquement/)).toBeVisible({ timeout: 2_000 });
    }).toPass({ timeout: 60_000 });
  });

  test("TAR-04 TAR-12 @a11y le devis établi par la Ville est accepté en ligne, la facture indique comment régler", async ({ page, browser }) => {
    const contexteAgent = await browser.newContext({ ignoreHTTPSErrors: true, locale: "fr-FR", timezoneId: "Europe/Paris" });
    const agent = await contexteAgent.newPage();
    await connecterAgent(agent, "gest.ville");
    await expect(agent.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
    await agent.goto(`${BACKOFFICE}/reservations/dossiers/${dossier}`);
    await agent.getByRole("button", { name: "Établir le devis" }).click();
    await expect(agent.getByRole("cell", { name: /^DV\d{4}-\d{5}$/ })).toBeVisible();
    await sansViolationAxe(agent, "les devis et factures du dossier");

    await connecterUsager(page);
    await page.goto(`${PORTAIL}/espace/dossiers/${dossier}`);
    await expect(page.getByRole("heading", { level: 2, name: "Devis et factures" })).toBeVisible();
    await sansViolationAxe(page, "le devis à accepter");
    await page.getByRole("button", { name: /Accepter le devis/ }).click();
    await expect(page.getByText(/accepté\. Le service vous adresse la suite/)).toBeVisible();

    await agent.reload();
    await agent.getByRole("button", { name: "Facturer les séances et frais" }).click();
    await expect(agent.getByRole("cell", { name: /^F\d{4}-\d{5}$/ })).toBeVisible();
    await contexteAgent.close();

    await page.goto(`${PORTAIL}/espace/factures`);
    await expect(page.getByRole("heading", { level: 1, name: "Mes devis, factures et cautions" })).toBeVisible();
    await expect(page.getByText("Référence à indiquer")).toBeVisible();
    await expect(page.getByText(/^FR76/)).toBeVisible();
    await sansViolationAxe(page, "mes factures");
  });
});
