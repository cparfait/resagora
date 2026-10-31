/** Fenêtre modale native (<dialog>) : focus piégé par le navigateur, Échap pour fermer, titre annoncé. */
import { useEffect, useId, useRef, type ReactNode } from "react";

interface Proprietes {
  ouvert: boolean;
  titre: string;
  onFermer: () => void;
  children: ReactNode;
  large?: boolean;
}

export function Dialogue({ ouvert, titre, onFermer, children, large = false }: Proprietes) {
  const reference = useRef<HTMLDialogElement>(null);
  const idTitre = useId();

  useEffect(() => {
    const dialogue = reference.current;
    if (!dialogue) return;
    if (ouvert && !dialogue.open) {
      if (typeof dialogue.showModal === "function") dialogue.showModal();
      else dialogue.setAttribute("open", "");
    }
    if (!ouvert && dialogue.open) {
      if (typeof dialogue.close === "function") dialogue.close();
      else dialogue.removeAttribute("open");
    }
  }, [ouvert]);

  return (
    <dialog
      ref={reference}
      className={`dialogue${large ? " dialogue--large" : ""}`}
      aria-labelledby={idTitre}
      onCancel={(evenement) => {
        evenement.preventDefault();
        onFermer();
      }}
    >
      {ouvert ? (
        <>
          <div className="dialogue__entete">
            <h2 id={idTitre}>{titre}</h2>
            <button type="button" className="dialogue__fermer" onClick={onFermer} aria-label="Fermer la fenêtre">
              ×
            </button>
          </div>
          <div className="dialogue__corps">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
