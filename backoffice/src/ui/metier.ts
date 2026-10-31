/** Libellés, tons et formats métier communs (statuts, types d'usagers, dates en heure de Paris). */
import type { Ton } from "./Badge";

export const STATUTS: Record<string, { libelle: string; ton: Ton; motif: string }> = {
  demande: { libelle: "Demande", ton: "info", motif: "hachure-legere" },
  en_instruction: { libelle: "En instruction", ton: "info", motif: "hachure-legere" },
  option: { libelle: "Option", ton: "attention", motif: "pointille" },
  validee: { libelle: "Validée", ton: "succes", motif: "plein" },
  confirmee: { libelle: "Confirmée", ton: "succes", motif: "plein" },
  realisee: { libelle: "Réalisée", ton: "neutre", motif: "plein" },
  cloturee: { libelle: "Clôturée", ton: "neutre", motif: "plein" },
  refusee: { libelle: "Refusée", ton: "danger", motif: "barre" },
  annulee: { libelle: "Annulée", ton: "danger", motif: "barre" },
};

export const TYPES_USAGER: Record<string, string> = {
  association: "Association",
  ecole: "École",
  entreprise: "Entreprise ou CSE",
  particulier: "Particulier",
  service_municipal: "Service municipal",
  autre_collectivite: "Autre collectivité",
};

export const COULEURS_TYPE: Record<string, string> = {
  association: "type-association",
  ecole: "type-ecole",
  entreprise: "type-entreprise",
  particulier: "type-particulier",
  service_municipal: "type-ville",
  autre_collectivite: "type-autre",
};

export const ZONE = "Europe/Paris";
const formatJour = new Intl.DateTimeFormat("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: ZONE });
const formatJourCourt = new Intl.DateTimeFormat("fr-FR", { weekday: "short", day: "numeric", month: "short", timeZone: ZONE });
const formatHeure = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: ZONE });
const formatDateHeure = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeStyle: "short", timeZone: ZONE });
const formatDate = new Intl.DateTimeFormat("fr-FR", { dateStyle: "medium", timeZone: ZONE });

export const jourLong = (d: Date | string) => formatJour.format(new Date(d));
export const jourCourt = (d: Date | string) => formatJourCourt.format(new Date(d));
export const heure = (d: Date | string) => formatHeure.format(new Date(d));
export const dateHeure = (d: Date | string) => formatDateHeure.format(new Date(d));
export const dateSimple = (d: Date | string) => formatDate.format(new Date(d));

/** Date du jour au format AAAA-MM-JJ (heure locale du poste). */
export function isoJour(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function ajouterJours(d: Date, jours: number): Date {
  const r = new Date(d);
  r.setDate(r.getDate() + jours);
  return r;
}

export function debutSemaine(d: Date): Date {
  const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const decalage = (r.getDay() + 6) % 7;
  r.setDate(r.getDate() - decalage);
  return r;
}

export function debutMois(d: Date): Date {
  return new Date(d.getFullYear(), d.getMonth(), 1);
}

export function memeJour(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Minutes depuis minuit (heure locale) d'un instant. */
export function minutesDuJour(d: Date): number {
  return d.getHours() * 60 + d.getMinutes();
}

export function euros(centimes: number): string {
  return new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(centimes / 100);
}
