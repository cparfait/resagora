/**
 * Accès HTTP à l'API de gestion : cookie de session HttpOnly, jeton CSRF Django sur les écritures,
 * erreurs normalisées en français (code, message, erreurs par champ).
 */
import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";

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

export function lireCookie(nom: string): string | undefined {
  return document.cookie
    .split(";")
    .map((morceau) => morceau.trim().split("="))
    .find(([cle]) => cle === nom)?.[1];
}

export function jetonCsrf(): string {
  return lireCookie("__Host-csrf-agent") ?? lireCookie("csrf-agent") ?? "";
}

function aplatirChamps(brut: unknown): ErreursChamps {
  if (!brut || typeof brut !== "object") return {};
  const resultat: ErreursChamps = {};
  for (const [cle, valeur] of Object.entries(brut as Record<string, unknown>)) {
    if (Array.isArray(valeur)) resultat[cle] = valeur.map(String);
    else if (typeof valeur === "string") resultat[cle] = [valeur];
    else if (valeur && typeof valeur === "object") resultat[cle] = Object.values(valeur).flat().map(String);
  }
  return resultat;
}

export async function erreurDepuisReponse(reponse: Response): Promise<ErreurApi> {
  let corps: Record<string, unknown> = {};
  try {
    corps = (await reponse.json()) as Record<string, unknown>;
  } catch {
    corps = {};
  }
  const message =
    typeof corps.message === "string"
      ? corps.message
      : reponse.status >= 500
        ? "Le service est momentanément indisponible. Réessayez plus tard."
        : "La demande n'a pas pu aboutir.";
  return new ErreurApi(
    reponse.status,
    typeof corps.code === "string" ? corps.code : "erreur",
    message,
    aplatirChamps(corps.champs),
    (corps.details as Record<string, unknown>) ?? {},
  );
}

const csrf: Middleware = {
  onRequest({ request }) {
    if (!METHODES_SURES.has(request.method)) request.headers.set("X-CSRFToken", jetonCsrf());
    return request;
  },
};

export const client = createClient<paths>({ baseUrl: "", credentials: "same-origin" });
client.use(csrf);

/** Appel générique (listes, formulaires) : renvoie le JSON ou lève une ErreurApi. */
export async function requete<T>(methode: string, chemin: string, corps?: unknown, signal?: AbortSignal): Promise<T> {
  const entetes: Record<string, string> = { Accept: "application/json" };
  const estFormulaire = corps instanceof FormData;
  if (corps !== undefined && !estFormulaire) entetes["Content-Type"] = "application/json";
  if (!METHODES_SURES.has(methode)) entetes["X-CSRFToken"] = jetonCsrf();
  const reponse = await fetch(chemin, {
    method: methode,
    headers: entetes,
    credentials: "same-origin",
    body: corps === undefined ? undefined : estFormulaire ? corps : JSON.stringify(corps),
    signal,
  });
  if (!reponse.ok) throw await erreurDepuisReponse(reponse);
  if (reponse.status === 204) return undefined as T;
  return (await reponse.json()) as T;
}

/** Téléchargement d'un fichier (export, PDF) via un lien temporaire. */
let signalerEchec: (message: string) => void = () => undefined;

/** Branché par le fournisseur de notifications : un téléchargement refusé ou en échec est annoncé à l'agent. */
export function definirSignalementTelechargement(rappel: (message: string) => void): void {
  signalerEchec = rappel;
}

/** Télécharge un fichier de l'API ; en cas d'échec (droits, document absent, réseau), le message est annoncé. */
export async function telecharger(chemin: string, nomParDefaut: string): Promise<void> {
  let reponse: Response;
  try {
    reponse = await fetch(chemin, { credentials: "same-origin" });
  } catch {
    signalerEchec("Téléchargement impossible : vérifiez la connexion au réseau de la Ville.");
    return;
  }
  if (!reponse.ok) {
    signalerEchec((await erreurDepuisReponse(reponse)).message);
    return;
  }
  const disposition = reponse.headers.get("Content-Disposition") ?? "";
  const nom = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? nomParDefaut;
  const url = URL.createObjectURL(await reponse.blob());
  const lien = document.createElement("a");
  lien.href = url;
  lien.download = nom;
  document.body.append(lien);
  lien.click();
  lien.remove();
  URL.revokeObjectURL(url);
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export function construireChemin(base: string, parametres: Record<string, string | number | boolean | undefined | null>): string {
  const recherche = new URLSearchParams();
  for (const [cle, valeur] of Object.entries(parametres)) {
    if (valeur !== undefined && valeur !== null && valeur !== "") recherche.set(cle, String(valeur));
  }
  const texte = recherche.toString();
  return texte ? `${base}?${texte}` : base;
}
