/**
 * Stockage local chiffré (MOB-07) : IndexedDB, AES-GCM 256 bits, clé dérivée d'un code de déverrouillage propre à
 * l'application (PBKDF2, 600 000 itérations), jamais du mot de passe de l'annuaire : un téléphone volé ne permet pas
 * de casser hors ligne le mot de passe Windows de l'agent (D-047). La clé n'est jamais conservée ; 10 codes faux
 * effacent l'appareil. Après 7 jours sans synchronisation, le planning embarqué (données des usagers) est effacé ;
 * les saisies non transmises restent chiffrées jusqu'à leur envoi (MOB-08, D-052).
 */
import { openDB, type DBSchema, type IDBPDatabase } from "idb";

const ITERATIONS = 600_000;
const VERIFICATION = "coffre-des-gardiens";
export const ESSAIS_MAX = 10;
export const LONGUEUR_CODE_MIN = 6;

interface Chiffre {
  iv: Uint8Array<ArrayBuffer>;
  donnees: ArrayBuffer;
}

interface Base extends DBSchema {
  meta: { key: string; value: unknown };
  paquet: { key: string; value: Chiffre };
  file: { key: string; value: { uuid: string; cree_le: number; contenu: Chiffre } };
  photos: { key: string; value: { uuid: string; contenu: Chiffre; type: string } };
  appareil: { key: string; value: string };
}

export interface Meta {
  sel: Uint8Array<ArrayBuffer>;
  verificateur: Chiffre;
  jeton: Chiffre;
  derniere_synchronisation: number | null;
  identifiant: string;
  cree_le: number;
  essais_restants: number;
  planning_efface_le: number | null;
  purge_jours: number;
}

let base: Promise<IDBPDatabase<Base>> | null = null;

export function ouvrir(): Promise<IDBPDatabase<Base>> {
  base ??= openDB<Base>("gardiens", 2, {
    upgrade(db, ancienne) {
      if (ancienne < 1) {
        db.createObjectStore("meta");
        db.createObjectStore("paquet");
        db.createObjectStore("file", { keyPath: "uuid" });
        db.createObjectStore("photos", { keyPath: "uuid" });
      }
      if (ancienne < 2) db.createObjectStore("appareil");
    },
  });
  return base;
}

/** Identifiant aléatoire de l'appareil, tiré une fois et conservé même au changement de compte (SEC-10). */
export async function identifiantAppareil(): Promise<string> {
  const db = await ouvrir();
  const existant = await db.get("appareil", "identifiant");
  if (existant) return existant;
  const nouveau = crypto.randomUUID();
  await db.put("appareil", nouveau, "identifiant");
  return nouveau;
}

const encodeur = new TextEncoder();
const decodeur = new TextDecoder();

async function deriver(code: string, sel: Uint8Array<ArrayBuffer>): Promise<CryptoKey> {
  const materiau = await crypto.subtle.importKey("raw", encodeur.encode(code), "PBKDF2", false, ["deriveKey"]);
  return crypto.subtle.deriveKey(
    { name: "PBKDF2", salt: sel, iterations: ITERATIONS, hash: "SHA-256" },
    materiau,
    { name: "AES-GCM", length: 256 },
    false,
    ["encrypt", "decrypt"],
  );
}

export async function chiffrer(cle: CryptoKey, donnees: ArrayBuffer | Uint8Array<ArrayBuffer>): Promise<Chiffre> {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  return { iv, donnees: await crypto.subtle.encrypt({ name: "AES-GCM", iv }, cle, donnees) };
}

export async function dechiffrer(cle: CryptoKey, chiffre: Chiffre): Promise<ArrayBuffer> {
  return crypto.subtle.decrypt({ name: "AES-GCM", iv: chiffre.iv }, cle, chiffre.donnees);
}

async function chiffrerJson(cle: CryptoKey, valeur: unknown): Promise<Chiffre> {
  return chiffrer(cle, encodeur.encode(JSON.stringify(valeur)));
}

async function dechiffrerJson<T>(cle: CryptoKey, chiffre: Chiffre): Promise<T> {
  return JSON.parse(decodeur.decode(await dechiffrer(cle, chiffre))) as T;
}

export async function lireMeta(): Promise<Meta | undefined> {
  return (await (await ouvrir()).get("meta", "coffre")) as Meta | undefined;
}

async function ecrireMeta(meta: Meta): Promise<void> {
  await (await ouvrir()).put("meta", meta, "coffre");
}

export class CodeInvalide extends Error {}

/** Code de déverrouillage : au moins 6 chiffres, pas une suite triviale. */
export function verifierCode(code: string): string | null {
  if (!new RegExp(`^\\d{${LONGUEUR_CODE_MIN},12}$`).test(code)) return `Le code compte de ${LONGUEUR_CODE_MIN} à 12 chiffres.`;
  if (/^(\d)\1+$/.test(code) || "0123456789012".includes(code) || "9876543210987".includes(code)) return "Ce code est trop simple.";
  return null;
}

/** Première connexion sur l'appareil : crée le coffre et y range le jeton de session (chiffré). */
export async function creerCoffre(code: string, identifiant: string, jeton: string, maintenant = Date.now()): Promise<CryptoKey> {
  const probleme = verifierCode(code);
  if (probleme) throw new CodeInvalide(probleme);
  await effacerTout();
  const sel = crypto.getRandomValues(new Uint8Array(16));
  const cle = await deriver(code, sel);
  await ecrireMeta({
    sel,
    verificateur: await chiffrerJson(cle, VERIFICATION),
    jeton: await chiffrerJson(cle, jeton),
    derniere_synchronisation: null,
    identifiant,
    cree_le: maintenant,
    essais_restants: ESSAIS_MAX,
    planning_efface_le: null,
    purge_jours: 7,
  });
  return cle;
}

export class CodeIncorrect extends Error {
  constructor(
    message: string,
    readonly essaisRestants: number,
    readonly efface = false,
  ) {
    super(message);
  }
}

/** Déverrouillage hors ligne : la clé dérivée doit déchiffrer le vérificateur ; 10 échecs effacent l'appareil. */
export async function deverrouiller(code: string): Promise<{ cle: CryptoKey; jeton: string; meta: Meta }> {
  const meta = await lireMeta();
  if (!meta) throw new CodeIncorrect("Aucune donnée sur cet appareil : connectez-vous.", 0, true);
  const cle = await deriver(code, meta.sel);
  let valide = false;
  try {
    valide = (await dechiffrerJson<string>(cle, meta.verificateur)) === VERIFICATION;
  } catch {
    valide = false;
  }
  if (!valide) {
    const restants = (meta.essais_restants ?? ESSAIS_MAX) - 1;
    if (restants <= 0) {
      await effacerTout();
      throw new CodeIncorrect("Code incorrect : trop d'essais, les données de l'appareil ont été effacées.", 0, true);
    }
    await ecrireMeta({ ...meta, essais_restants: restants });
    throw new CodeIncorrect(`Code incorrect. Il reste ${restants} essai${restants > 1 ? "s" : ""} avant l'effacement de l'appareil.`, restants);
  }
  if (meta.essais_restants !== ESSAIS_MAX) await ecrireMeta({ ...meta, essais_restants: ESSAIS_MAX });
  return { cle, jeton: await dechiffrerJson<string>(cle, meta.jeton), meta };
}

/** Changement du code : tout le contenu est rechiffré avec la nouvelle clé, file d'envoi et photos comprises. */
export async function rechiffrer(ancienne: CryptoKey, code: string, jeton: string): Promise<CryptoKey> {
  const probleme = verifierCode(code);
  if (probleme) throw new CodeInvalide(probleme);
  const db = await ouvrir();
  const meta = await lireMeta();
  if (!meta) throw new CodeIncorrect("Aucune donnée sur cet appareil : connectez-vous.", 0, true);
  const sel = crypto.getRandomValues(new Uint8Array(16));
  const cle = await deriver(code, sel);
  const recoder = async (chiffre: Chiffre) => chiffrer(cle, await dechiffrer(ancienne, chiffre));
  const paquet = await db.get("paquet", "courant");
  const file = await Promise.all((await db.getAll("file")).map(async (e) => ({ ...e, contenu: await recoder(e.contenu) })));
  const photos = await Promise.all((await db.getAll("photos")).map(async (p) => ({ ...p, contenu: await recoder(p.contenu) })));
  const nouvelle: Meta = { ...meta, sel, verificateur: await chiffrerJson(cle, VERIFICATION), jeton: await chiffrerJson(cle, jeton) };
  const nouveauPaquet = paquet ? await recoder(paquet) : null;
  // Écriture en une seule transaction : aucune donnée ne reste chiffrée avec l'ancienne clé.
  const tx = db.transaction(["meta", "paquet", "file", "photos"], "readwrite");
  await Promise.all([
    tx.objectStore("meta").put(nouvelle, "coffre"),
    ...(nouveauPaquet ? [tx.objectStore("paquet").put(nouveauPaquet, "courant")] : []),
    ...file.map((e) => tx.objectStore("file").put(e)),
    ...photos.map((p) => tx.objectStore("photos").put(p)),
    tx.done,
  ]);
  return cle;
}

/** Session renouvelée (mot de passe de l'annuaire ressaisi) : seul le jeton change, le code reste le même. */
export async function remplacerJeton(cle: CryptoKey, jeton: string): Promise<void> {
  const meta = await lireMeta();
  if (!meta) return;
  await ecrireMeta({ ...meta, jeton: await chiffrerJson(cle, jeton) });
}

export async function marquerSynchronisation(instant: number, purgeJours?: number): Promise<void> {
  const meta = await lireMeta();
  if (meta) await ecrireMeta({ ...meta, derniere_synchronisation: instant, planning_efface_le: null, purge_jours: purgeJours ?? meta.purge_jours ?? 7 });
}

export async function enregistrerPaquet<T>(cle: CryptoKey, paquet: T): Promise<void> {
  await (await ouvrir()).put("paquet", await chiffrerJson(cle, paquet), "courant");
}

export async function lirePaquet<T>(cle: CryptoKey): Promise<T | null> {
  const chiffre = await (await ouvrir()).get("paquet", "courant");
  return chiffre ? dechiffrerJson<T>(cle, chiffre) : null;
}

export interface Saisie {
  uuid: string;
  type: "pointage" | "etat_des_lieux" | "incident";
  horodatage: string;
  donnees: Record<string, unknown>;
  photos?: string[];
}

/** File d'envoi persistante (MOB-05) : l'application peut être fermée sans perte. */
export async function ajouterSaisie(cle: CryptoKey, saisie: Saisie): Promise<void> {
  await (await ouvrir()).put("file", { uuid: saisie.uuid, cree_le: Date.now(), contenu: await chiffrerJson(cle, saisie) });
}

export async function listerSaisies(cle: CryptoKey): Promise<Saisie[]> {
  const elements = await (await ouvrir()).getAll("file");
  elements.sort((a, b) => a.cree_le - b.cree_le);
  return Promise.all(elements.map((e) => dechiffrerJson<Saisie>(cle, e.contenu)));
}

export async function compterSaisies(): Promise<number> {
  return (await ouvrir()).count("file");
}

export async function retirerSaisie(uuid: string): Promise<void> {
  await (await ouvrir()).delete("file", uuid);
}

export async function ajouterPhoto(cle: CryptoKey, uuid: string, contenu: Blob): Promise<void> {
  await (await ouvrir()).put("photos", { uuid, type: contenu.type || "image/jpeg", contenu: await chiffrer(cle, await contenu.arrayBuffer()) });
}

export async function lirePhoto(cle: CryptoKey, uuid: string): Promise<Blob | null> {
  const photo = await (await ouvrir()).get("photos", uuid);
  return photo ? new Blob([await dechiffrer(cle, photo.contenu)], { type: photo.type }) : null;
}

export async function retirerPhoto(uuid: string): Promise<void> {
  await (await ouvrir()).delete("photos", uuid);
}

/** Déconnexion ou changement de compte : tout est effacé, sauf l'identifiant de l'appareil. */
export async function effacerTout(): Promise<void> {
  const db = await ouvrir();
  await Promise.all([db.clear("meta"), db.clear("paquet"), db.clear("file"), db.clear("photos")]);
}

/**
 * MOB-08 : au-delà de `purgeJours` sans synchronisation (ou depuis la création du coffre s'il n'a jamais été
 * synchronisé), le planning embarqué est effacé. Les saisies non transmises sont gardées, chiffrées, pour partir au
 * retour du réseau. Vérifiée à l'ouverture, avant même le déverrouillage. Renvoie vrai si un effacement a eu lieu.
 */
export async function purgerSiPerime(maintenant: number, purgeJours?: number): Promise<boolean> {
  const meta = await lireMeta();
  if (!meta || meta.planning_efface_le) return false;
  const jours = purgeJours ?? meta.purge_jours ?? 7;
  const reference = meta.derniere_synchronisation ?? meta.cree_le;
  if (maintenant - reference <= jours * 86_400_000) return false;
  const db = await ouvrir();
  await db.clear("paquet");
  await ecrireMeta({ ...meta, planning_efface_le: maintenant });
  return true;
}
