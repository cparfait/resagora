/** En-tête d'écran : titre de document unique, un seul h1 suivi du filet anis de la charte, actions principales. */
import { useEffect, type ReactNode } from "react";

export function Page({ titre, description, actions, children }: { titre: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    document.title = `${titre} — Gestion des équipements — Ville de Châtillon`;
  }, [titre]);
  return (
    <section className="page" aria-labelledby="titre-page">
      <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1
            id="titre-page"
            tabIndex={-1}
            className="m-0 text-h1 text-encre after:mt-2 after:block after:h-1 after:w-10 after:bg-anis after:content-[''] focus:outline-none"
          >
            {titre}
          </h1>
          {description ? <p className="mt-3 mb-0 max-w-[70ch] text-encre-douce">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
