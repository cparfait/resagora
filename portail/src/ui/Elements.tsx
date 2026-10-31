/** Éléments communs du portail : titre de page, états de chargement et d'erreur, alertes, formats. */
import { useEffect, useRef, type ReactNode } from "react";
import { messageErreur } from "../api/http";

const SUFFIXE = "Portail des équipements — Ville de Châtillon";
let premierAffichage = true;

/** Titre de document unique (RGAA 8.6) et unique h1 de la page ; le focus va au titre à chaque navigation. */
export function TitrePage({ titre, sousTitre, children }: { titre: string; sousTitre?: string; children?: ReactNode }) {
  const titreRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    document.title = `${titre}${sousTitre ? ` — ${sousTitre}` : ""} — ${SUFFIXE}`;
  }, [titre, sousTitre]);
  useEffect(() => {
    // Au premier affichage, le focus reste au début du document (lien d'évitement) ; ensuite il suit la navigation.
    if (premierAffichage) {
      premierAffichage = false;
      return;
    }
    window.scrollTo(0, 0);
    titreRef.current?.focus();
  }, []);
  return (
    <div className="entete-page">
      <h1 tabIndex={-1} id="titre-page" ref={titreRef}>
        {titre}
      </h1>
      {children}
    </div>
  );
}

export function Chargement({ texte = "Chargement en cours…" }: { texte?: string }) {
  return (
    <p className="chargement" role="status" aria-live="polite">
      {texte}
    </p>
  );
}

export function ErreurChargement({ erreur, reessayer }: { erreur: unknown; reessayer?: () => void }) {
  return (
    <div className="alerte alerte--erreur" role="alert">
      <p>{messageErreur(erreur, "Les informations n'ont pas pu être chargées.")}</p>
      {reessayer ? (
        <button type="button" className="bouton bouton--secondaire" onClick={reessayer}>
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

export function Alerte({ ton = "info", titre, children }: { ton?: "info" | "succes" | "attention" | "erreur"; titre?: string; children: ReactNode }) {
  return (
    <div className={`alerte alerte--${ton}`} role={ton === "erreur" ? "alert" : "status"}>
      {titre ? <p className="alerte__titre">{titre}</p> : null}
      {children}
    </div>
  );
}

export function Etiquette({ texte, ton = "neutre" }: { texte: string; ton?: "neutre" | "info" | "succes" | "attention" | "danger" }) {
  return <span className={`etiquette etiquette--${ton}`}>{texte}</span>;
}

const PARIS = "Europe/Paris";

export function date(valeur: string | null | undefined): string {
  if (!valeur) return "";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "long", timeZone: PARIS }).format(new Date(valeur.length === 10 ? `${valeur}T12:00:00` : valeur));
}

export function dateHeure(valeur: string | null | undefined): string {
  if (!valeur) return "";
  return new Intl.DateTimeFormat("fr-FR", { dateStyle: "full", timeStyle: "short", timeZone: PARIS }).format(new Date(valeur));
}

export function heure(valeur: string): string {
  return new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: PARIS }).format(new Date(valeur)).replace(":", " h ");
}

export function taille(octets: number): string {
  return octets >= 1024 * 1024 ? `${(octets / 1024 / 1024).toFixed(1).replace(".", ",")} Mo` : `${Math.max(1, Math.round(octets / 1024))} ko`;
}

export const TONS_STATUT: Record<string, "neutre" | "info" | "succes" | "attention" | "danger"> = {
  brouillon: "neutre",
  demande: "info",
  en_instruction: "info",
  option: "attention",
  validee: "succes",
  confirmee: "succes",
  realisee: "neutre",
  cloturee: "neutre",
  refusee: "danger",
  annulee: "neutre",
};
