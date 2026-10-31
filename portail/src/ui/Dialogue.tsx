import { useEffect, useId, useRef, type ReactNode } from "react";

/** Fenêtre modale native (<dialog>) : focus piégé par le navigateur, fermeture par Échap, titre associé. */
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
    <dialog ref={reference} className="dialogue" aria-labelledby={identifiant} onClose={onFermer} onCancel={onFermer}>
      {ouvert ? (
        <>
          <div className="dialogue__entete">
            <h2 id={identifiant}>{titre}</h2>
            <button type="button" className="bouton bouton--lien" onClick={onFermer}>
              Fermer<span className="visuellement-masque"> la fenêtre « {titre} »</span>
            </button>
          </div>
          {children}
        </>
      ) : null}
    </dialog>
  );
}
