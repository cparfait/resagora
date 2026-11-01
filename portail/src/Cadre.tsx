/**
 * Gabarit des pages (RGAA 9 et 12) : lien d'évitement, en-tête, navigation principale, contenu, pied de
 * page avec l'état d'accessibilité ; à chaque changement de page, le focus est placé sur le titre (TitrePage).
 */
import { classesAlerte } from "./ui/Elements";
import { classesBouton } from "./ui/Bouton";
import { useQuery } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import { requete } from "./api/http";
import type { Declaration } from "./api/types";
import { useSession } from "./session";

function Navigation() {
  const { connecte, contact, deconnecter } = useSession();
  const naviguer = useNavigate();
  return (
    <nav aria-label="Navigation principale" className="navigation">
      <ul>
        <li>
          <NavLink to="/" end>
            Accueil
          </NavLink>
        </li>
        <li>
          <NavLink to="/equipements">Équipements</NavLink>
        </li>
        <li>
          <NavLink to="/disponibilites">Disponibilités</NavLink>
        </li>
        {connecte ? (
          <>
            <li>
              <NavLink to="/espace" end>
                Mon espace
              </NavLink>
            </li>
            <li>
              <NavLink to="/espace/dossiers">Mes demandes</NavLink>
            </li>
            <li>
              <NavLink to="/espace/factures">Mes factures</NavLink>
            </li>
            <li>
              <NavLink to="/espace/compte">Mon compte{contact ? ` (${contact.prenom})` : ""}</NavLink>
            </li>
            <li>
              <button type="button" className={classesBouton("lien")} onClick={() => void deconnecter().then(() => naviguer("/"))}>
                Se déconnecter
              </button>
            </li>
          </>
        ) : (
          <>
            <li>
              <NavLink to="/connexion">Se connecter</NavLink>
            </li>
            <li>
              <NavLink to="/inscription">Créer un compte</NavLink>
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
      <a href="#contenu" className="evitement">
        Aller au contenu
      </a>
      <header className="entete" role="banner">
        <div className="entete__interieur">
          <Link to="/" className="entete__marque">
            <span className="entete__ville">Ville de Châtillon</span>
            <span className="entete__service">Équipements sportifs et associatifs</span>
          </Link>
          <Navigation />
        </div>
      </header>
      <main id="contenu" tabIndex={-1} className="contenu">
        {expiree ? (
          <div className={classesAlerte("attention")} role="status">
            <p>
              Votre session a expiré. <Link to="/connexion">Reconnectez-vous</Link> pour continuer.
            </p>
          </div>
        ) : null}
        {children}
      </main>
      <footer className="pied" role="contentinfo">
        <ul>
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
        <p>Ville de Châtillon — service des équipements sportifs et associatifs</p>
      </footer>
    </>
  );
}
