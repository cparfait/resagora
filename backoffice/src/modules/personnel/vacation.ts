/** Types et libellés partagés du planning du personnel (vacations, besoins, agents, absences). */

export interface Violation {
  code: string;
  message: string;
  gravite?: string;
}
export interface Vacation {
  id: number;
  site: number;
  site_nom: string;
  agent: number | null;
  agent_nom: string;
  debut: string;
  fin: string;
  duree_minutes: number;
  type: string;
  statut: string;
  violations: Violation[];
  forcee: boolean;
  motif_forcage: string;
  arrivee_reelle: string | null;
  depart_reel: string | null;
  signalement: string;
}
export interface Besoin {
  id: number;
  site: number;
  site_nom: string;
  debut: string;
  fin: string;
  statut: string;
  seances: string[];
}
export interface AgentPlanning {
  id: number;
  prenom: string;
  nom: string;
  sites: number[];
  duree_hebdo_minutes: number;
}
export interface AbsenceAgent {
  id: number;
  agent: number;
  debut: string;
  fin: string;
  nature: string;
}

export const STATUTS_VACATION: Record<string, { libelle: string; ton: "succes" | "attention" | "danger" | "neutre" }> = {
  planifiee: { libelle: "Planifiée", ton: "succes" },
  a_pourvoir: { libelle: "À pourvoir", ton: "danger" },
  a_revoir: { libelle: "À revoir", ton: "attention" },
  annulee: { libelle: "Annulée", ton: "neutre" },
};

/** PER-05 : durée maximale hebdomadaire (décret n° 2000-815). Le serveur la contrôle à chaque affectation ; elle sert
 * ici de repère visuel dans la colonne des heures. */
export const PLAFOND_HEBDO_MINUTES = 48 * 60;

/** 1 950 min → « 32 h 30 » ; 480 min → « 8 h ». */
export function dureeLisible(minutes: number): string {
  const total = Math.round(minutes);
  const h = Math.floor(total / 60);
  const m = total % 60;
  return m ? `${h} h ${String(m).padStart(2, "0")}` : `${h} h`;
}

export const nomAgent = (a: Pick<AgentPlanning, "prenom" | "nom">) => `${a.prenom} ${a.nom}`;
