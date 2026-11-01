/** Cadre des écrans : lien d'évitement, en-tête, navigation filtrée par les droits, contenu principal. */
import { BASE_BOUTON, CLASSES_BOUTON } from "../ui/Bouton";
import { cn } from "../ui/cn";
import { useQueryClient } from "@tanstack/react-query";
import { Suspense, useEffect, useRef } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { requete } from "../api/http";
import { useSession } from "../auth/session";
import { Chargement } from "../ui/Etats";
import { GROUPES, MODULES } from "./modules";

export function Cadre() {
  const { moi, peut } = useSession();
  const client = useQueryClient();
  const emplacement = useLocation();
  const principal = useRef<HTMLElement>(null);

  // Le focus revient au titre de l'écran à chaque changement de page (navigation au clavier et lecteurs d'écran).
  const chemin = emplacement.pathname;
  useEffect(() => {
    if (chemin) principal.current?.querySelector<HTMLElement>("h1")?.focus();
  }, [chemin]);

  const deconnecter = async () => {
    await requete<void>("POST", "/api/gestion/auth/deconnexion");
    client.clear();
    await client.invalidateQueries({ queryKey: ["moi"] });
  };

  const visibles = MODULES.filter((m) => !m.masque && peut(m.action));

  return (
    <div className="cadre">
      <a className="lien-evitement" href="#contenu">
        Aller au contenu
      </a>
      <header className="cadre__entete">
        <p className="cadre__titre">
          <span className="cadre__logo" aria-hidden="true">
            ▦
          </span>
          Équipements · Ville de Châtillon
        </p>
        <div className="cadre__utilisateur">
          <span>{moi?.nom_affiche}</span>
          <button type="button" className={cn(BASE_BOUTON, CLASSES_BOUTON.secondaire, "border-blanc bg-transparent text-blanc hover:bg-vert-fonce hover:text-blanc")} onClick={() => void deconnecter()}>
            Se déconnecter
          </button>
        </div>
      </header>
      <div className="cadre__corps">
        <nav className="cadre__navigation" aria-label="Navigation principale">
          {GROUPES.map((groupe) => {
            const entrees = visibles.filter((m) => m.groupe === groupe);
            if (!entrees.length) return null;
            return (
              <div key={groupe} className="navigation__groupe">
                <h2 className="navigation__titre">{groupe}</h2>
                <ul>
                  {entrees.map((m) => (
                    <li key={m.chemin}>
                      <NavLink to={m.chemin} end={m.chemin === "/"}>
                        {m.libelle}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <main id="contenu" className="cadre__contenu" ref={principal} tabIndex={-1}>
          <Suspense fallback={<Chargement libelle="Chargement de l'écran…" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
