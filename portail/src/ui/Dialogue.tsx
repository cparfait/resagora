import { useEffect, useId, useRef, type ReactNode } from "react";
import { classesBouton } from "./Bouton";

/** Fenêtre modale native (<dialog>) : focus piégé par le navigateur, fermeture par Échap, titre associé. Charte :
 * carte plate à angles droits, sans ombre. */
export function Dialogue({ ouvert, titre, onFermer, children }: { ouvert: boolean; titre: string; onFermer: () => void; children: ReactNode }) {
  const reference = useRef<HTMLDialogElement>(null);
  const identifiant = useId();
  useEffect(() => {
    const dialogue = reference.current;
    if (!dialogue) return;
    if (ouvert && !dialogue.open) dialogue.showModal();
    if (!ouvert && dialogue.open) dialogue.close();
  }, [ouvert]);
  return (
    <dialog
      ref={reference}
      className="m-auto w-[min(40rem,95vw)] max-w-[95vw] border-2 border-vert bg-carte px-6 pt-4 pb-6 text-encre backdrop:bg-encre/60"
      aria-labelledby={identifiant}
      onClose={onFermer}
      onCancel={onFermer}
    >
      {ouvert ? (
        <>
          <div className="flex items-baseline justify-between gap-4">
            <h2 id={identifiant} className="text-h3 text-encre">
              {titre}
            </h2>
            <button type="button" className={classesBouton("lien")} onClick={onFermer}>
              Fermer<span className="sr-only"> la fenêtre « {titre} »</span>
            </button>
          </div>
          {children}
        </>
      ) : null}
    </dialog>
  );
}
