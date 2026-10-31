/** Outils communs des parcours : URLs de recette, comptes fictifs de l'annuaire de test, TOTP, axe-core. */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const BACKOFFICE = process.env.BACKOFFICE_URL ?? "https://localhost";
export const PORTAIL = process.env.PORTAIL_URL ?? "https://equipements.chatillon.test:9443";
export const MAILPIT = process.env.MAILPIT_URL ?? "http://127.0.0.1:58025";
export const SIMULATEURS = process.env.SIMULATEURS_URL ?? "http://127.0.0.1:53010";

/** Jeton d'API partagé avec le simulateur DocuSeal de recette (deploy/dev/secrets, ignoré par Git). */
export function jetonSimulateur(): string {
  return readFileSync(resolve(import.meta.dirname, "../../deploy/dev/secrets/simulateur_docuseal_api_jeton"), "utf8").trim();
}

/** Dernier lien reçu par courriel par `destinataire` (Mailpit), par exemple « /confirmation#jeton=… ». */
export async function lienRecu(page: Page, destinataire: string, chemin: string, motif?: string, depuis?: Date): Promise<string> {
  for (let essai = 0; essai < 40; essai++) {
    const liste = (await (await page.request.get(`${MAILPIT}/api/v1/search?query=${encodeURIComponent(`to:"${destinataire}"`)}`)).json()) as {
      messages: { ID: string; Created: string }[];
    };
    for (const message of liste.messages ?? []) {
      if (depuis && new Date(message.Created) < depuis) continue;
      const detail = (await (await page.request.get(`${MAILPIT}/api/v1/message/${message.ID}`)).json()) as { Text: string };
      const trouve = new RegExp(motif ?? String.raw`https?://\S+/${chemin}#jeton=[\w-]+`).exec(detail.Text);
      if (trouve) return trouve[0];
    }
    await page.waitForTimeout(500);
  }
  throw new Error(`Aucun lien « ${chemin} » reçu par ${destinataire}`);
}
/** Signataire de la Ville (paramètre signature.elu_courriel, valeur livrée). */
export const ELU_COURRIEL = process.env.ELU_COURRIEL ?? "elu.sports@chatillon.test";
export const MOBILE = process.env.MOBILE_URL ?? "https://gardiens.chatillon.local";

/** Mot de passe des comptes fictifs, généré par `make secrets` (deploy/dev/secrets, ignoré par Git). */
export function motDePasseDemo(): string {
  return readFileSync(resolve(import.meta.dirname, "../../deploy/dev/secrets/mdp_agents_demo"), "utf8").trim();
}

const BASE32 = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567";

/** Code TOTP (RFC 6238, SHA-1, 30 s, 6 chiffres) calculé à partir de la clé affichée à l'enrôlement. */
export function codeTotp(graine: string, decalage = 0): string {
  let bits = "";
  for (const caractere of graine.replace(/=+$/, "").toUpperCase()) bits += BASE32.indexOf(caractere).toString(2).padStart(5, "0");
  const octets = Buffer.from(bits.match(/.{8}/g)?.map((b) => Number.parseInt(b, 2)) ?? []);
  const compteur = Buffer.alloc(8);
  compteur.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30_000) + decalage));
  const hmac = createHmac("sha1", octets).update(compteur).digest();
  const position = (hmac.at(-1) ?? 0) & 0x0f;
  const valeur = (hmac.readUInt32BE(position) & 0x7fffffff) % 1_000_000;
  return valeur.toString().padStart(6, "0");
}

export async function sansViolationAxe(page: Page, contexte: string): Promise<void> {
  const resultats = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]).analyze();
  const violations = resultats.violations.map((v) => `${v.id} (${v.impact}) : ${v.nodes.map((n) => n.target.join(" ")).join(", ")}`);
  expect(violations, `Violations axe-core sur ${contexte}`).toEqual([]);
}

export async function connecterAgent(page: Page, identifiant: string): Promise<void> {
  await page.goto(BACKOFFICE);
  await page.getByLabel("Identifiant").fill(identifiant);
  await page.getByLabel(/Mot de passe/).fill(motDePasseDemo());
  await page.getByRole("button", { name: "Se connecter" }).click();
}

const ETAT = resolve(import.meta.dirname, "../.etat");

/** Connexion d'un compte à double authentification : enrôlement au premier passage (clé conservée hors Git dans
 * e2e/.etat), code TOTP ensuite. */
export async function connecterAvecTotp(page: Page, identifiant: string): Promise<void> {
  const { existsSync, mkdirSync, writeFileSync } = await import("node:fs");
  const fichier = resolve(ETAT, `totp-${identifiant}.txt`);
  await connecterAgent(page, identifiant);
  const titre = page.getByRole("heading", { level: 1 });
  await expect(titre).toHaveText(/deux étapes/);
  let graine: string;
  if ((await titre.textContent())?.includes("Activer")) {
    graine = ((await page.locator(".connexion__graine").textContent()) ?? "").replace(/\s/g, "");
    mkdirSync(ETAT, { recursive: true });
    writeFileSync(fichier, graine, "utf8");
  } else {
    if (!existsSync(fichier)) throw new Error(`Clé TOTP de ${identifiant} inconnue : faites réinitialiser la double authentification.`);
    graine = readFileSync(fichier, "utf8").trim();
  }
  // Un code TOTP ne sert qu'une fois (anti-rejeu) : une seconde connexion dans la même fenêtre attend le suivant.
  if (DERNIER_CODE.get(identifiant) === codeTotp(graine)) await page.waitForTimeout(30_500 - (Date.now() % 30_000));
  const code = codeTotp(graine);
  DERNIER_CODE.set(identifiant, code);
  await page.getByLabel(/Code à 6 chiffres/).fill(code);
  await page.getByRole("button", { name: "Valider le code" }).click();
  await expect(page.getByRole("heading", { level: 1, name: /Bonjour/ })).toBeVisible();
}

const DERNIER_CODE = new Map<string, string>();
