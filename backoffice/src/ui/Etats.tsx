/** États d'un écran : chargement (squelette), vide (message + action), erreur (réessayer), droits insuffisants. */
import type { ReactNode } from "react";
import { ErreurApi } from "../api/http";
import { Bouton } from "./Bouton";

export function Chargement({ libelle = "Chargement en cours…", lignes = 4 }: { libelle?: string; lignes?: number }) {
  return (
    <div className="etat etat--chargement" role="status" aria-live="polite">
      <span className="visuellement-masque">{libelle}</span>
      {Array.from({ length: lignes }, (_, i) => (
        <div key={i} className="squelette" aria-hidden="true" />
      ))}
    </div>
  );
}

export function Vide({ message, action }: { message: string; action?: ReactNode }) {
  return (
    <div className="etat etat--vide">
      <p>{message}</p>
      {action}
    </div>
  );
}

export function Erreur({ erreur, reessayer }: { erreur: unknown; reessayer?: () => void }) {
  if (erreur instanceof ErreurApi && erreur.statut === 403) return <DroitsInsuffisants message={erreur.message} />;
  const message = erreur instanceof ErreurApi ? erreur.message : "Une erreur inattendue est survenue.";
  return (
    <div className="etat etat--erreur" role="alert">
      <p>
        <span aria-hidden="true">⚠ </span>
        {message}
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
    <div className="etat etat--droits" role="alert">
      <p>
        <span aria-hidden="true">🔒 </span>
        {message}
      </p>
      <p>Si vous pensez qu'il s'agit d'une erreur, contactez l'administrateur fonctionnel.</p>
    </div>
  );
}
