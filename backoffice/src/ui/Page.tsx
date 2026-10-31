/** En-tête d'écran : titre de document unique, un seul h1, actions principales. */
import { useEffect, type ReactNode } from "react";

export function Page({ titre, description, actions, children }: { titre: string; description?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  useEffect(() => {
    document.title = `${titre} — Gestion des équipements — Ville de Châtillon`;
  }, [titre]);
  return (
    <section className="page" aria-labelledby="titre-page">
      <header className="page__entete">
        <div>
          <h1 id="titre-page" tabIndex={-1}>
            {titre}
          </h1>
          {description ? <p className="page__description">{description}</p> : null}
        </div>
        {actions ? <div className="page__actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
