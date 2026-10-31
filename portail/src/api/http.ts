/**
 * Accès à l'API du portail, toujours à travers la façade DMZ : cookie de session HttpOnly posé par la
 * façade (jamais de jeton dans le navigateur), jeton CSRF en double soumission, erreurs en français.
 */
export type ErreursChamps = Record<string, string[]>;

export class ErreurApi extends Error {
  readonly statut: number;
  readonly code: string;
  readonly champs: ErreursChamps;
  readonly details: Record<string, unknown>;

  constructor(statut: number, code: string, message: string, champs: ErreursChamps = {}, details: Record<string, unknown> = {}) {
    super(message);
    this.statut = statut;
    this.code = code;
    this.champs = champs;
    this.details = details;
  }
}

const METHODES_SURES = new Set(["GET", "HEAD", "OPTIONS"]);
let jetonCsrf = "";
let surExpiration: (() => void) | null = null;

export function definirCsrf(valeur: string): void {
  jetonCsrf = valeur;
}

export function quandSessionExpire(rappel: () => void): void {
  surExpiration = rappel;
}

function aplatir(brut: unknown, prefixe = ""): ErreursChamps {
  if (!brut || typeof brut !== "object") return {};
  const resultat: ErreursChamps = {};
  for (const [cle, valeur] of Object.entries(brut as Record<string, unknown>)) {
    const nom = prefixe ? `${prefixe}.${cle}` : cle;
    if (Array.isArray(valeur) && valeur.every((v) => typeof v === "string")) resultat[nom] = valeur as string[];
    else if (typeof valeur === "string") resultat[nom] = [valeur];
    else if (valeur && typeof valeur === "object") Object.assign(resultat, aplatir(valeur, nom));
  }
  return resultat;
}

async function erreurDepuis(reponse: Response): Promise<ErreurApi> {
  let corps: Record<string, unknown> = {};
  try {
    corps = (await reponse.json()) as Record<string, unknown>;
  } catch {
    corps = {};
  }
  // Réponse de validation DRF : { champ: ["message"] } sans message général.
  const champs = typeof corps.message === "string" ? aplatir(corps.champs ?? {}) : aplatir(corps);
  const message =
    typeof corps.message === "string"
      ? corps.message
      : reponse.status >= 500
        ? "Le service est momentanément indisponible. Réessayez plus tard."
        : Object.keys(champs).length
          ? "Certains champs sont à corriger."
          : "La demande n'a pas pu aboutir.";
  return new ErreurApi(reponse.status, typeof corps.code === "string" ? corps.code : "erreur", message, champs, (corps.details as Record<string, unknown>) ?? {});
}

async function assurerCsrf(): Promise<void> {
  // Première écriture avant que l'état de session soit connu (lien de confirmation ouvert directement) :
  // la façade pose alors le cookie de double soumission et renvoie le jeton.
  const reponse = await fetch("/api/portail/session", { credentials: "same-origin", headers: { Accept: "application/json" } });
  if (reponse.ok) jetonCsrf = ((await reponse.json()) as { csrf?: string }).csrf ?? "";
}

export async function requete<T>(methode: string, url: string, corps?: unknown, signal?: AbortSignal): Promise<T> {
  if (!METHODES_SURES.has(methode) && !jetonCsrf) await assurerCsrf();
  const entetes: Record<string, string> = { Accept: "application/json" };
  const formulaire = corps instanceof FormData;
  if (corps !== undefined && !formulaire) entetes["Content-Type"] = "application/json";
  if (!METHODES_SURES.has(methode)) entetes["X-CSRF-Token"] = jetonCsrf;
  const reponse = await fetch(url, {
    method: methode,
    headers: entetes,
    credentials: "same-origin",
    body: corps === undefined ? undefined : formulaire ? corps : JSON.stringify(corps),
    signal,
  });
  if (!reponse.ok) {
    const erreur = await erreurDepuis(reponse);
    if (reponse.status === 401 && erreur.code === "session_expiree") surExpiration?.();
    throw erreur;
  }
  if (reponse.status === 204) return undefined as T;
  return (await reponse.json()) as T;
}

export function chemin(base: string, parametres: Record<string, string | number | boolean | undefined | null> = {}): string {
  const recherche = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(parametres)) {
    if (valeur !== undefined && valeur !== null && valeur !== "") recherche.set(cle, String(valeur));
  }
  const texte = recherche.toString();
  return texte ? `${base}?${texte}` : base;
}

/** Téléchargement d'un document (convention, pièce) : le fichier arrive par la façade, en pièce jointe. */
export async function telecharger(url: string, nomParDefaut: string): Promise<void> {
  const reponse = await fetch(url, { credentials: "same-origin" });
  if (!reponse.ok) throw await erreurDepuis(reponse);
  const disposition = reponse.headers.get("Content-Disposition") ?? "";
  const nom = /filename="([^"]+)"/.exec(disposition)?.[1] ?? nomParDefaut;
  const lien = document.createElement("a");
  lien.href = URL.createObjectURL(await reponse.blob());
  lien.download = nom;
  document.body.append(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(lien.href);
}

export function messageErreur(erreur: unknown, repli = "Une erreur est survenue."): string {
  return erreur instanceof ErreurApi ? erreur.message : repli;
}
