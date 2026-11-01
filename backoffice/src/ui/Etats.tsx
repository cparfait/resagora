/** États d'un écran : chargement (squelette), vide (message + action), erreur (réessayer), droits insuffisants.
 * Charte : cartes plates, squelette fixe (aucune animation automatique), icônes au trait. */
import { Lock, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { ErreurApi } from "../api/http";
import { Bouton } from "./Bouton";

const CARTE = "border border-filet bg-carte p-6";

export function Chargement({ libelle = "Chargement en cours…", lignes = 4 }: { libelle?: string; lignes?: number }) {
  return (
    <div className={CARTE} role="status" aria-live="polite">
      <span className="sr-only">{libelle}</span>
      {Array.from({ length: lignes }, (_, i) => (
        <div key={i} className="my-2.5 h-5 bg-fond" aria-hidden="true" />
      ))}
    </div>
  );
}

export function Vide({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className={CARTE}>
      <p className="mt-0">{message}</p>
      {action}
    </div>
  );
}

export function Erreur({ erreur, reessayer }: { erreur: unknown; reessayer?: () => void }) {
  if (erreur instanceof ErreurApi && erreur.statut === 403) return <DroitsInsuffisants message={erreur.message} />;
  const message = erreur instanceof ErreurApi ? erreur.message : "Une erreur inattendue est survenue.";
  return (
    <div className="border border-danger bg-danger-fond p-6" role="alert">
      <p className="mt-0 flex items-start gap-2">
        <TriangleAlert aria-hidden="true" size={20} strokeWidth={1.8} className="mt-0.5 shrink-0 text-danger" />
        <span>{message}</span>
      </p>
      {reessayer ? (
        <Bouton variante="secondaire" onClick={reessayer}>
          Réessayer
        </Bouton>
      ) : null}
    </div>
  );
}

export function DroitsInsuffisants({ message = "Vous n'avez pas les droits pour accéder à cet écran." }: { message?: string }) {
  return (
    <div className="border border-attention bg-attention-fond p-6" role="alert">
      <p className="mt-0 flex items-start gap-2">
        <Lock aria-hidden="true" size={20} strokeWidth={1.8} className="mt-0.5 shrink-0 text-attention" />
        <span>{message}</span>
      </p>
      <p className="mb-0">Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur fonctionnel.</p>
    </div>
  );
}
