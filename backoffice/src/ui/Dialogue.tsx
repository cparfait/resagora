/** Fenêtre modale native (<dialog>) : focus piégé par le navigateur, Échap pour fermer, titre annoncé. Charte :
 * carte plate à angles droits (aucune ombre), bouton de fermeture rond de 44 px libellé. */
import { X } from "lucide-react";
import { useEffect, useId, useRef, type ReactNode } from "react";
import { cn } from "./cn";

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
      className={cn("m-auto max-h-[90vh] rounded-2xl border-0 bg-carte p-0 text-encre shadow-flottant backdrop:bg-encre/50", large ? "w-[min(60rem,95vw)]" : "w-[min(36rem,95vw)]")}
      aria-labelledby={idTitre}
      onCancel={(evenement) => {
        evenement.preventDefault();
        onFermer();
      }}
    >
      {ouvert ? (
        <>
          <div className="sticky top-0 flex items-center justify-between gap-4 border-b border-filet bg-carte px-6 py-4">
            <h2 id={idTitre} className="m-0 text-h3 text-encre">
              {titre}
            </h2>
            <button
              type="button"
              className="inline-flex size-11 shrink-0 cursor-pointer items-center justify-center rounded-full border border-filet bg-carte text-encre hover:border-encre"
              onClick={onFermer}
              aria-label="Fermer la fenêtre"
            >
              <X aria-hidden="true" size={20} strokeWidth={1.8} />
            </button>
          </div>
          <div className="px-6 pt-4 pb-6">{children}</div>
        </>
      ) : null}
    </dialog>
  );
}
