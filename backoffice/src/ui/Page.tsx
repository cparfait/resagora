/** En-tête d'écran : titre de document unique, un seul h1 sobre (ergonomie Mariloo), actions principales à droite. */
import { useEffect, type ReactNode } from "react";
import { cn } from "./cn";

export function Page({
  titre,
  description,
  actions,
  children,
  className,
}: {
  titre: string;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  useEffect(() => {
    document.title = `${titre} — Gestion des équipements — Ville de Châtillon`;
  }, [titre]);
  return (
    <section className={cn("page", className)} aria-labelledby="titre-page">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 id="titre-page" tabIndex={-1} className="m-0 text-[1.75rem] leading-tight font-semibold text-encre focus:outline-none">
            {titre}
          </h1>
          {description ? <p className="mt-1.5 mb-0 max-w-[75ch] text-petit text-encre-douce">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}
