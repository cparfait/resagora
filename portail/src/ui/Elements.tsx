/** Éléments communs du portail : titre de page, états de chargement et d'erreur, alertes, formats. */
import { useEffect, useRef, type ReactNode } from "react";
import { messageErreur } from "../api/http";
import { classesBouton } from "./Bouton";
import { cn } from "./cn";

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
    <div className="mb-6">
      <h1
        tabIndex={-1}
        id="titre-page"
        ref={titreRef}
        className="m-0 text-[1.75rem] leading-tight font-bold text-encre after:mt-2 after:block after:h-1 after:w-10 after:bg-anis after:content-[''] focus:outline-none sm:text-h1"
      >
        {titre}
      </h1>
      {children}
    </div>
  );
}

export function Chargement({ texte = "Chargement en cours…" }: { texte?: string }) {
  return (
    <p className="text-encre-douce" role="status" aria-live="polite">
      {texte}
    </p>
  );
}

export function ErreurChargement({ erreur, reessayer }: { erreur: unknown; reessayer?: () => void }) {
  return (
    <div className={classesAlerte("erreur")} role="alert">
      <p className="mt-0">{messageErreur(erreur, "Les informations n'ont pas pu être chargées.")}</p>
      {reessayer ? (
        <button type="button" className={classesBouton("secondaire")} onClick={reessayer}>
          Réessayer
        </button>
      ) : null}
    </div>
  );
}

type TonAlerte = "info" | "succes" | "attention" | "erreur";

const TONS_ALERTE: Record<TonAlerte, string> = {
  info: "border-l-vert bg-info-fond",
  succes: "border-l-succes bg-succes-fond",
  attention: "border-l-attention bg-attention-fond",
  erreur: "border-l-danger bg-danger-fond",
};

/** Bandeau d'alerte de la charte : fond teinté, filet de 6 px à gauche, texte encre (le message dit le statut). */
export function classesAlerte(ton: TonAlerte = "info"): string {
  return cn("my-4 border-l-[6px] px-4 py-3 text-encre focus:outline-3 focus:outline-offset-3 focus:outline-vert-profond", TONS_ALERTE[ton]);
}

export function Alerte({ ton = "info", titre, children }: { ton?: "info" | "succes" | "attention" | "erreur"; titre?: string; children: ReactNode }) {
  return (
    <div className={classesAlerte(ton)} role={ton === "erreur" ? "alert" : "status"}>
      {titre ? <p className="m-0 mb-1 font-bold">{titre}</p> : null}
      {children}
    </div>
  );
}

const TONS_ETIQUETTE = {
  neutre: "bg-fond text-encre-douce",
  info: "bg-info-fond text-info",
  succes: "bg-succes-fond text-succes",
  attention: "bg-attention-fond text-attention",
  danger: "bg-danger-fond text-danger",
};

/** Pastille de statut : le statut est toujours écrit, la couleur ne fait que le souligner. */
export function Etiquette({ texte, ton = "neutre" }: { texte: string; ton?: "neutre" | "info" | "succes" | "attention" | "danger" }) {
  return <span className={cn("ml-1 inline-flex items-center rounded-full border border-current px-2.5 text-sm font-semibold", TONS_ETIQUETTE[ton])}>{texte}</span>;
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
