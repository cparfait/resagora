/**
 * Gabarit des pages (RGAA 9 et 12) : lien d'évitement, en-tête, navigation principale, contenu, pied de
 * page avec l'état d'accessibilité ; à chaque changement de page, le focus est placé sur le titre (TitrePage).
 * Charte (DESIGN.md) : en-tête blanc au logotype de la Ville, élément actif souligné d'anis, contenu centré sur
 * 1 280 px sur fond gris, pied de page vert profond.
 */
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import { requete } from "./api/http";
import type { Declaration } from "./api/types";
import { useSession } from "./session";
import { classesBouton } from "./ui/Bouton";
import { cn } from "./ui/cn";
import { classesAlerte } from "./ui/Elements";

const LIEN = ({ isActive }: { isActive: boolean }) =>
  cn(
    "inline-flex min-h-11 items-center border-b-4 border-transparent px-1 font-semibold text-encre no-underline hover:text-vert",
    isActive && "border-anis text-vert",
  );

function Navigation() {
  const { connecte, contact, deconnecter } = useSession();
  const naviguer = useNavigate();
  return (
    <nav aria-label="Navigation principale">
      <ul className="m-0 flex list-none flex-wrap items-center gap-x-5 gap-y-1 p-0">
        <li>
          <NavLink to="/" end className={LIEN}>
            Accueil
          </NavLink>
        </li>
        <li>
          <NavLink to="/equipements" className={LIEN}>Équipements</NavLink>
        </li>
        <li>
          <NavLink to="/disponibilites" className={LIEN}>Disponibilités</NavLink>
        </li>
        {connecte ? (
          <>
            <li>
              <NavLink to="/espace" end className={LIEN}>
                Mon espace
              </NavLink>
            </li>
            <li>
              <NavLink to="/espace/dossiers" className={LIEN}>Mes demandes</NavLink>
            </li>
            <li>
              <NavLink to="/espace/factures" className={LIEN}>Mes factures</NavLink>
            </li>
            <li>
              <NavLink to="/espace/compte" className={LIEN}>Mon compte{contact ? ` (${contact.prenom})` : ""}</NavLink>
            </li>
            <li>
              <button type="button" className={classesBouton("lien", "min-h-11 font-semibold")} onClick={() => void deconnecter().then(() => naviguer("/"))}>
                Se déconnecter
              </button>
            </li>
          </>
        ) : (
          <>
            <li>
              <NavLink to="/connexion" className={({ isActive }) => classesBouton(isActive ? "principal" : "secondaire", "uppercase tracking-wide")}>
                Se connecter
              </NavLink>
            </li>
            <li>
              <NavLink to="/inscription" className={LIEN}>
                Créer un compte
              </NavLink>
            </li>
          </>
        )}
      </ul>
    </nav>
  );
}

export function Cadre({ children }: { children: ReactNode }) {
  const { expiree } = useSession();
  const declaration = useQuery({ queryKey: ["accessibilite"], queryFn: () => requete<Declaration>("GET", "/api/portail/accessibilite"), staleTime: 3_600_000 });
  return (
    <>
      <a href="#contenu" className="sr-only z-50 bg-vert-profond px-4 py-3 text-blanc focus:not-sr-only focus:fixed focus:top-4 focus:left-4">
        Aller au contenu
      </a>
      <header className="border-b border-filet bg-carte" role="banner">
        <div className="mx-auto flex max-w-(--container-contenu) flex-wrap items-center justify-between gap-4 px-4 py-3">
          <Link to="/" className="flex flex-col leading-tight no-underline">
            <span className="text-surtitre font-semibold tracking-[0.12em] text-vert uppercase">Ville de</span>
            <span className="text-2xl font-extrabold text-vert">Châtillon</span>
            <span className="text-petit text-encre-douce">Équipements sportifs et associatifs</span>
          </Link>
          <Navigation />
        </div>
      </header>
      <main id="contenu" tabIndex={-1} className="mx-auto min-h-[60vh] max-w-(--container-contenu) px-4 pt-8 pb-12 focus:outline-none">
        {expiree ? (
          <div className={classesAlerte("attention")} role="status">
            <p>
              Votre session a expiré. <Link to="/connexion">Reconnectez-vous</Link> pour continuer.
            </p>
          </div>
        ) : null}
        {children}
      </main>
      <footer className="bg-vert-profond px-4 py-8 text-blanc" role="contentinfo">
        <ul className="mx-auto mt-0 mb-4 flex max-w-(--container-contenu) list-none flex-wrap gap-x-6 gap-y-2 p-0 [&_a]:inline-flex [&_a]:min-h-11 [&_a]:items-center [&_a]:text-blanc [&_a:hover]:text-anis-clair">
          <li>
            <Link to="/accessibilite">Accessibilité : {declaration.data?.etat ?? "non conforme"}</Link>
          </li>
          <li>
            <Link to="/donnees-personnelles">Données personnelles</Link>
          </li>
          <li>
            <Link to="/mentions-legales">Mentions légales</Link>
          </li>
          <li>
            <Link to="/plan-du-site">Plan du site</Link>
          </li>
        </ul>
        <p className="mx-auto my-0 max-w-(--container-contenu) text-vert-clair">Ville de Châtillon — service des équipements sportifs et associatifs</p>
      </footer>
    </>
  );
}
