/** Faux serveur mobile pour les tests : enregistre les appels et répond comme l'API /api/mobile/*. */
import type { Accuse, Paquet } from "../synchro";

export const PAQUET: Paquet = {
  genere_le: "2026-11-10T08:00:00Z",
  agent: { prenom: "Camille", nom: "Martin" },
  parametres: { alerte_heures: 24, purge_jours: 7 },
  sites: [{ id: 1, nom: "Gymnase des Écoles", adresse: "1 rue de l'Exemple" }],
  vacations: [
    {
      id: 10,
      site: 1,
      site_nom: "Gymnase des Écoles",
      debut: "2026-11-10T16:00:00Z",
      fin: "2026-11-10T20:00:00Z",
      type: "normale",
      statut: "planifiee",
      arrivee_reelle: null,
      depart_reel: null,
      signalement: "",
    },
  ],
  seances: [
    {
      id: 100,
      vacation: 10,
      espace: "Grande salle",
      famille: "gymnase",
      debut: "2026-11-10T17:00:00Z",
      fin: "2026-11-10T19:00:00Z",
      statut: "validee",
      usager: "Club de basket",
      activite: "Basket",
      effectif: 20,
      referent: { nom: "Référent fictif", telephone: "01 00 00 00 00" },
      etat_des_lieux: true,
      materiel: [{ libelle: "Table pliante", quantite: 8, statut: "Validée" }],
    },
  ],
  grilles: { gymnase: ["Sol propre", "Filets en place"], commune: ["Lumières éteintes"] },
};

export interface Appel {
  chemin: string;
  methode: string;
  corps: unknown;
  autorisation: string | null;
}

interface Options {
  enLigne?: () => boolean;
  session?: () => boolean;
  accuse?: (uuid: string) => Accuse;
  totp?: boolean;
}

const MOTS_DE_PASSE = new Set(["Mot-de-passe-1", "Nouveau-mot-de-passe-2"]);

export function fauxServeur(options: Options = {}) {
  const appels: Appel[] = [];
  const json = (donnees: unknown, statut = 200) => new Response(JSON.stringify(donnees), { status: statut, headers: { "Content-Type": "application/json" } });
  const f = async (entree: RequestInfo | URL, init: RequestInit = {}): Promise<Response> => {
    const chemin = typeof entree === "string" ? entree : entree.toString();
    if (options.enLigne && !options.enLigne()) throw new TypeError("Failed to fetch");
    const entetes = new Headers(init.headers);
    const corps = typeof init.body === "string" ? (JSON.parse(init.body) as unknown) : (init.body ?? null);
    appels.push({ chemin, methode: init.method ?? "GET", corps, autorisation: entetes.get("Authorization") });
    if (chemin === "/api/mobile/sante") return json({ statut: "ok" });
    if (chemin === "/api/mobile/auth/connexion") {
      const { mot_de_passe } = corps as { mot_de_passe: string };
      if (!MOTS_DE_PASSE.has(mot_de_passe)) return json({ code: "identifiants_invalides", message: "Identifiant ou mot de passe incorrect." }, 400);
      return options.totp ? json({ etape: "totp", defi: "defi-1" }) : json({ etape: "connecte", jeton: `jeton-${appels.length}` });
    }
    if (chemin === "/api/mobile/auth/totp") return json({ etape: "connecte", jeton: "jeton-totp" });
    if (options.session && !options.session()) return json({ detail: "Session expirée." }, 401);
    if (chemin === "/api/mobile/photos") return json({ uuid: "ok" }, 201);
    if (chemin === "/api/mobile/saisies") {
      const { saisies } = corps as { saisies: { uuid: string }[] };
      return json({ accuses: saisies.map((s) => options.accuse?.(s.uuid) ?? { uuid: s.uuid, statut: "acceptee", message: "" }) });
    }
    if (chemin === "/api/mobile/paquet") return json(PAQUET);
    if (chemin === "/api/mobile/auth/deconnexion") return new Response(null, { status: 204 });
    return json({}, 404);
  };
  return { f: f as typeof fetch, appels };
}
