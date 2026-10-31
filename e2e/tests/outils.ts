/** Outils communs des parcours : URLs de recette, comptes fictifs de l'annuaire de test, TOTP, axe-core. */
import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";
import { createHmac } from "node:crypto";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

export const BACKOFFICE = process.env.BACKOFFICE_URL ?? "https://localhost";
export const PORTAIL = process.env.PORTAIL_URL ?? "https://equipements.chatillon.test:8443";
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
