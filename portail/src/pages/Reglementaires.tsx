/** Pages réglementaires : déclaration d'accessibilité (POR-09), données personnelles (USR-06), mentions, plan du site. */
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { requete } from "../api/http";
import type { Declaration } from "../api/types";
import { useSession } from "../session";
import { Chargement, ErreurChargement, TitrePage } from "../ui/Elements";

function useDeclaration() {
  return useQuery({ queryKey: ["accessibilite"], queryFn: () => requete<Declaration>("GET", "/api/portail/accessibilite"), staleTime: 3_600_000 });
}

export function Accessibilite() {
  const declaration = useDeclaration();
  if (declaration.isPending) return <Chargement />;
  if (declaration.isError) return <ErreurChargement erreur={declaration.error} />;
  const d = declaration.data;
  const nonConformites = d.non_conformites.split("\n").filter((l) => l.trim());
  return (
    <>
      <TitrePage titre="Déclaration d'accessibilité" />
      <p>La Ville de Châtillon s'engage à rendre ses services en ligne accessibles, conformément à l'article 47 de la loi n° 2005-102 du 11 février 2005.</p>
      <p>Cette déclaration d'accessibilité s'applique au portail des équipements sportifs et associatifs.</p>
      <h2>État de conformité</h2>
      <p>
        Le portail est <strong>{d.etat}</strong> avec le référentiel général d'amélioration de l'accessibilité ({d.referentiel})
        {d.date_audit ? `, selon l'audit réalisé le ${d.date_audit}${d.auditeur ? ` par ${d.auditeur}` : ""}, avec un taux de conformité de ${d.taux} %.` : " : aucun audit de conformité n'a encore été réalisé."}
      </p>
      <h2>Contenus non accessibles</h2>
      {nonConformites.length ? (
        <ul>
          {nonConformites.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      ) : (
        <p>Aucun contenu non accessible n'est connu à ce jour.</p>
      )}
      <h2>Établissement de cette déclaration</h2>
      <p>Cette déclaration a été établie le {d.date_declaration}. Technologies utilisées : HTML, CSS, JavaScript. Les parcours sont testés avec des outils automatiques (axe-core) et au clavier.</p>
      <h2>Retour d'information et contact</h2>
      <p>
        Si vous n'arrivez pas à accéder à un contenu ou à un service, vous pouvez écrire à <a href={`mailto:${d.contact}`}>{d.contact}</a> pour être orienté vers une alternative accessible ou obtenir le
        contenu sous une autre forme.
      </p>
      <h2>Voies de recours</h2>
      <p>
        Si vous avez signalé un défaut d'accessibilité sans obtenir de réponse satisfaisante, vous pouvez écrire au Défenseur des droits, contacter son délégué dans votre région, ou lui écrire
        gratuitement (Défenseur des droits, Libre réponse 71120, 75342 Paris CEDEX 07).
      </p>
    </>
  );
}

export function DonneesPersonnelles() {
  const declaration = useDeclaration();
  const conservation = declaration.data?.conservation;
  return (
    <>
      <TitrePage titre="Données personnelles" />
      <h2>Responsable du traitement</h2>
      <p>La Ville de Châtillon, représentée par son Maire, est responsable du traitement des données collectées sur ce portail.</p>
      <h2>Finalités et base légale</h2>
      <p>
        Les données servent à gérer les comptes des usagers, instruire les demandes de réservation, établir les conventions, factures et attestations, et informer les usagers des événements qui
        concernent leurs réservations. Le traitement relève de la mission de service public de gestion des équipements municipaux et de l'exécution des conventions conclues.
      </p>
      <h2>Destinataires</h2>
      <p>Seuls les agents habilités de la Ville et, pour les paiements, le comptable public y ont accès. Aucune donnée n'est vendue ni transmise à des fins commerciales.</p>
      <h2>Durées de conservation</h2>
      {conservation ? (
        <ul>
          <li>Comptes et contacts : anonymisés après {conservation.inactivite_mois} mois sans activité ni réservation.</li>
          <li>Pièces justificatives : supprimées {conservation.pieces_expirees_mois} mois après leur date de fin de validité.</li>
          <li>Pièces comptables (factures, titres) : conservées selon les règles de la comptabilité publique.</li>
        </ul>
      ) : (
        <Chargement />
      )}
      <h2>Vos droits</h2>
      <p>
        Vous disposez d'un droit d'accès, de rectification, d'effacement et de limitation. Vous pouvez télécharger vos données depuis « Mon compte », ou écrire au service
        {conservation ? ` (${conservation.courriel})` : ""}. Vous pouvez aussi saisir la Commission nationale de l'informatique et des libertés (CNIL).
      </p>
    </>
  );
}

export function MentionsLegales() {
  return (
    <>
      <TitrePage titre="Mentions légales" />
      <h2>Éditeur</h2>
      <p>Ville de Châtillon (Hauts-de-Seine) — service des équipements sportifs et associatifs. Directeur de la publication : le Maire.</p>
      <h2>Hébergement</h2>
      <p>Le portail est hébergé sur les serveurs de la Ville de Châtillon.</p>
      <h2>Cookies</h2>
      <p>Le portail n'utilise qu'un cookie de session, strictement nécessaire à la connexion, et un cookie de sécurité contre la falsification des formulaires. Aucun cookie de mesure d'audience ni publicitaire n'est déposé.</p>
    </>
  );
}

export function PlanDuSite() {
  const { connecte } = useSession();
  return (
    <>
      <TitrePage titre="Plan du site" />
      <ul>
        <li>
          <Link to="/">Accueil</Link>
        </li>
        <li>
          <Link to="/equipements">Équipements</Link>
        </li>
        <li>
          <Link to="/disponibilites">Disponibilités</Link>
        </li>
        {connecte ? (
          <li>
            <Link to="/espace">Mon espace</Link>
            <ul>
              <li>
                <Link to="/espace/dossiers">Mes demandes</Link>
              </li>
              <li>
                <Link to="/espace/demande">Nouvelle demande</Link>
              </li>
              <li>
                <Link to="/espace/campagnes">Créneaux de la saison</Link>
              </li>
              <li>
                <Link to="/espace/factures">Mes factures</Link>
              </li>
              <li>
                <Link to="/espace/attestations">Attestations de valorisation</Link>
              </li>
              <li>
                <Link to="/espace/compte">Mon compte</Link>
              </li>
            </ul>
          </li>
        ) : (
          <>
            <li>
              <Link to="/connexion">Se connecter</Link>
            </li>
            <li>
              <Link to="/inscription">Créer un compte</Link>
            </li>
            <li>
              <Link to="/mot-de-passe-oublie">Mot de passe oublié</Link>
            </li>
          </>
        )}
        <li>
          <Link to="/accessibilite">Déclaration d'accessibilité</Link>
        </li>
        <li>
          <Link to="/donnees-personnelles">Données personnelles</Link>
        </li>
        <li>
          <Link to="/mentions-legales">Mentions légales</Link>
        </li>
      </ul>
    </>
  );
}

export function PageIntrouvable() {
  return (
    <>
      <TitrePage titre="Page introuvable" />
      <p>
        La page demandée n'existe pas ou a été déplacée. <Link to="/">Revenir à l'accueil</Link> ou consulter le <Link to="/plan-du-site">plan du site</Link>.
      </p>
    </>
  );
}
