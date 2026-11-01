/** Cadre des écrans : lien d'évitement, en-tête, navigation filtrée par les droits, contenu principal. Charte
 * (DESIGN.md) : en-tête blanc au logotype de la Ville ; navigation latérale dépliée, libellés visibles, élément actif
 * en vert plein, qui défile seule (la page ne s'allonge pas avec le menu) ; sur petit écran, bouton « Menu ». */
import { useQueryClient } from "@tanstack/react-query";
import { LogOut, Menu, X } from "lucide-react";
import { Suspense, useEffect, useRef, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { requete } from "../api/http";
import { useSession } from "../auth/session";
import { BASE_BOUTON, CLASSES_BOUTON } from "../ui/Bouton";
import { cn } from "../ui/cn";
import { Chargement } from "../ui/Etats";
import { GROUPES, MODULES } from "./modules";

export function Cadre() {
  const { moi, peut } = useSession();
  const client = useQueryClient();
  const emplacement = useLocation();
  const principal = useRef<HTMLElement>(null);
  const [menuOuvert, setMenuOuvert] = useState(false);

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
    <div className="min-h-dvh bg-fond">
      <a
        className="sr-only z-50 bg-vert-profond px-4 py-3 text-blanc focus:not-sr-only focus:fixed focus:top-2 focus:left-2"
        href="#contenu"
      >
        Aller au contenu
      </a>
      <header className="sticky top-0 z-40 flex h-16 items-center justify-between gap-4 border-b border-filet bg-carte px-4 print:hidden lg:px-6">
        <div className="flex items-center gap-3">
          <button
            type="button"
            className={cn(BASE_BOUTON, CLASSES_BOUTON.secondaire, "px-3 lg:hidden")}
            aria-expanded={menuOuvert}
            aria-controls="navigation-principale"
            onClick={() => setMenuOuvert((ouvert) => !ouvert)}
          >
            {menuOuvert ? <X aria-hidden="true" size={20} strokeWidth={1.8} /> : <Menu aria-hidden="true" size={20} strokeWidth={1.8} />}
            Menu
          </button>
          <p className="m-0 flex min-w-0 flex-col leading-tight">
            <span className="text-surtitre font-semibold tracking-[0.12em] text-vert uppercase">Ville de Châtillon</span>
            <span className="text-lg font-bold text-encre">Équipements</span>
          </p>
        </div>
        <div className="flex items-center gap-4">
          <span className="hidden text-petit text-encre-douce sm:inline">{moi?.nom_affiche}</span>
          <button type="button" className={cn(BASE_BOUTON, CLASSES_BOUTON.secondaire, "px-3 sm:px-5")} onClick={() => void deconnecter()}>
            <LogOut aria-hidden="true" size={18} strokeWidth={1.8} />
            <span className="sr-only sm:not-sr-only">Se déconnecter</span>
          </button>
        </div>
      </header>
      <div className="lg:grid lg:grid-cols-[16rem_minmax(0,1fr)]">
        <nav
          id="navigation-principale"
          className={cn(
            "border-b border-filet bg-carte px-3 py-4 print:hidden lg:sticky lg:top-16 lg:block lg:h-[calc(100dvh-4rem)] lg:overflow-y-auto lg:border-r lg:border-b-0",
            menuOuvert ? "block" : "hidden",
          )}
          aria-label="Navigation principale"
        >
          {GROUPES.map((groupe) => {
            const entrees = visibles.filter((m) => m.groupe === groupe);
            if (!entrees.length) return null;
            return (
              <div key={groupe} className="mb-3">
                <h2 className="mx-2 mt-3 mb-1 text-surtitre font-semibold tracking-[0.12em] text-vert uppercase">{groupe}</h2>
                <ul className="m-0 list-none p-0">
                  {entrees.map((m) => (
                    <li key={m.chemin}>
                      <NavLink
                        to={m.chemin}
                        end={m.chemin === "/"}
                        onClick={() => setMenuOuvert(false)}
                        className={({ isActive }) =>
                          cn(
                            "flex min-h-11 items-center px-2 py-1.5 text-petit leading-snug text-encre no-underline hover:bg-info-fond hover:text-vert-fonce",
                            isActive && "bg-vert font-semibold text-blanc hover:bg-vert-fonce hover:text-blanc",
                          )
                        }
                      >
                        {m.libelle}
                      </NavLink>
                    </li>
                  ))}
                </ul>
              </div>
            );
          })}
        </nav>
        <main id="contenu" className="min-w-0 px-4 py-6 focus:outline-none lg:px-8" ref={principal} tabIndex={-1}>
          <Suspense fallback={<Chargement libelle="Chargement de l'écran…" />}>
            <Outlet />
          </Suspense>
        </main>
      </div>
    </div>
  );
}
