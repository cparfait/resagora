/**
 * Synchronisation (MOB-05) : santé du réseau, envoi des photos puis des saisies par lots, accusés traités, paquet
 * descendant rafraîchi. Une saisie n'est retirée de la file qu'après l'accusé du serveur (accepté, conflit signalé ou
 * rejet motivé) ; une coupure laisse la file intacte, l'envoi est retenté plus tard.
 */
import { ajouterSaisie, enregistrerPaquet, lirePhoto, listerSaisies, marquerSynchronisation, retirerPhoto, retirerSaisie, type Saisie } from "./coffre";

export interface Seance {
  id: number;
  vacation: number;
  espace: string;
  famille: string;
  debut: string;
  fin: string;
  statut: string;
  usager: string;
  activite: string;
  effectif: number | null;
  referent: { nom: string; telephone: string } | null;
  etat_des_lieux: boolean;
  materiel: { libelle: string; quantite: number; statut: string }[];
}

export interface Vacation {
  id: number;
  site: number;
  site_nom: string;
  debut: string;
  fin: string;
  type: string;
  statut: string;
  arrivee_reelle: string | null;
  depart_reel: string | null;
  signalement: string;
}

export interface Paquet {
  genere_le: string;
  agent: { prenom: string; nom: string };
  parametres: { alerte_heures: number; purge_jours: number };
  sites: { id: number; nom: string; adresse: string }[];
  vacations: Vacation[];
  seances: Seance[];
  grilles: Record<string, string[]>;
}

export interface Accuse {
  uuid: string;
  statut: "acceptee" | "conflit" | "rejetee";
  message: string;
}

export class ReseauIndisponible extends Error {}
export class SessionExpiree extends Error {}

type Fetch = typeof fetch;

async function appeler(f: Fetch, jeton: string, chemin: string, init: RequestInit = {}): Promise<Response> {
  let reponse: Response;
  try {
    reponse = await f(chemin, { ...init, headers: { ...(init.headers as Record<string, string> | undefined), Authorization: `Appareil ${jeton}` }, credentials: "omit" });
  } catch {
    throw new ReseauIndisponible("Réseau indisponible.");
  }
  if (reponse.status === 401) throw new SessionExpiree("Session expirée : reconnectez-vous quand vous aurez du réseau.");
  if (reponse.status >= 500 || reponse.status === 429) throw new ReseauIndisponible("Service momentanément indisponible.");
  return reponse;
}

export async function reseauDisponible(f: Fetch = fetch): Promise<boolean> {
  if (typeof navigator !== "undefined" && navigator.onLine === false) return false;
  try {
    const reponse = await f("/api/mobile/sante", { credentials: "omit", cache: "no-store" });
    return reponse.ok;
  } catch {
    return false;
  }
}

/** Enregistre une saisie terrain dans la file (identifiant généré sur l'appareil, horodatage local). */
export async function saisir(cle: CryptoKey, type: Saisie["type"], donnees: Record<string, unknown>, photos: string[] = []): Promise<Saisie> {
  const saisie: Saisie = { uuid: crypto.randomUUID(), type, horodatage: new Date().toISOString(), donnees, photos };
  await ajouterSaisie(cle, saisie);
  return saisie;
}

export interface Bilan {
  envoyees: number;
  conflits: Accuse[];
  rejets: Accuse[];
  paquet: Paquet | null;
}

const TAILLE_LOT = 50;

export async function synchroniser(cle: CryptoKey, jeton: string, f: Fetch = fetch): Promise<Bilan> {
  if (!(await reseauDisponible(f))) throw new ReseauIndisponible("Hors ligne : les saisies restent sur l'appareil.");
  const bilan: Bilan = { envoyees: 0, conflits: [], rejets: [], paquet: null };
  const saisies = await listerSaisies(cle);
  for (const saisie of saisies) {
    for (const photo of saisie.photos ?? []) {
      const contenu = await lirePhoto(cle, photo);
      if (!contenu) continue;
      const formulaire = new FormData();
      formulaire.append("uuid", photo);
      formulaire.append("fichier", contenu, contenu.type === "image/png" ? "signature.png" : "photo.jpg");
      const reponse = await appeler(f, jeton, "/api/mobile/photos", { method: "POST", body: formulaire });
      if (reponse.status >= 400 && reponse.status < 500) {
        // Refus définitif (format, taille, antivirus) : la photo est écartée, la saisie part quand même.
        await retirerPhoto(photo);
        bilan.rejets.push({ uuid: photo, statut: "rejetee", message: "Une photo a été refusée par le serveur et n'a pas été transmise." });
        continue;
      }
      if (!reponse.ok) throw new ReseauIndisponible("Envoi d'une photo refusé : nouvel essai plus tard.");
    }
  }
  for (let debut = 0; debut < saisies.length; debut += TAILLE_LOT) {
    const lot = saisies.slice(debut, debut + TAILLE_LOT).map(({ photos: _photos, ...saisie }) => saisie);
    const reponse = await appeler(f, jeton, "/api/mobile/saisies", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ saisies: lot }),
    });
    if (!reponse.ok) throw new ReseauIndisponible("Envoi des saisies refusé : nouvel essai plus tard.");
    const { accuses } = (await reponse.json()) as { accuses: Accuse[] };
    for (const accuse of accuses) {
      const saisie = saisies.find((s) => s.uuid === accuse.uuid);
      await retirerSaisie(accuse.uuid);
      for (const photo of saisie?.photos ?? []) await retirerPhoto(photo);
      bilan.envoyees += 1;
      if (accuse.statut === "conflit") bilan.conflits.push(accuse);
      if (accuse.statut === "rejetee") bilan.rejets.push(accuse);
    }
  }
  const reponse = await appeler(f, jeton, "/api/mobile/paquet");
  if (reponse.ok) {
    bilan.paquet = (await reponse.json()) as Paquet;
    await enregistrerPaquet(cle, bilan.paquet);
    await marquerSynchronisation(Date.now(), bilan.paquet.parametres.purge_jours);
  }
  return bilan;
}
