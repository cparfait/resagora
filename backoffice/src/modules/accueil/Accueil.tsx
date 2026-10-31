/** DSH-01 à DSH-03, DSH-05, DSH-06 : « que dois-je traiter aujourd'hui ? » — compteurs du jour et alertes, calculés
 * par l'API dans le périmètre de l'agent ; chaque compteur ouvre la liste filtrée qu'il résume. Rôles et périmètres. */
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { requete, type Page as PageApi } from "../../api/http";
import type { Site } from "../../api/types";
import { useSession } from "../../auth/session";
import { MODULES } from "../../cadre/modules";
import { Chargement, Erreur } from "../../ui/Etats";
import { Page } from "../../ui/Page";

export interface Compteur {
  code: string;
  libelle: string;
  nombre: number;
  lien: string;
  groupe: "a_traiter" | "alertes";
  gravite: "info" | "attention" | "danger";
}

function Compteurs({ code, titre, compteurs, vide }: { code: string; titre: string; compteurs: Compteur[]; vide: string }) {
  const actifs = compteurs.filter((c) => c.nombre > 0);
  return (
    <section aria-labelledby={`titre-${code}`}>
      <h2 id={`titre-${code}`}>{titre}</h2>
      {actifs.length === 0 ? <p>{vide}</p> : null}
      <ul className="compteurs">
        {actifs.map((c) => (
          <li key={c.code} className={`compteur compteur--${c.gravite}`}>
            <Link to={c.lien}>
              <span className="compteur__nombre">{c.nombre}</span>
              <span className="compteur__libelle">{c.libelle}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function Accueil() {
  const { moi, peut } = useSession();
  const sites = useQuery({ queryKey: ["options", "sites"], queryFn: () => requete<PageApi<Site>>("GET", "/api/gestion/referentiel/sites?taille=500") });
  const tableau = useQuery({
    queryKey: ["a-traiter"],
    queryFn: () => requete<{ compteurs: Compteur[] }>("GET", "/api/gestion/pilotage/a-traiter"),
    refetchInterval: 5 * 60_000,
  });
  const nomSite = (id: number) => sites.data?.results.find((s) => s.id === id)?.nom ?? `site n° ${id}`;
  const raccourcis = MODULES.filter((m) => m.chemin !== "/" && !m.masque && peut(m.action)).slice(0, 8);
  const compteurs = tableau.data?.compteurs ?? [];

  return (
    <Page titre={`Bonjour ${moi?.nom_affiche ?? ""}`} description="Ce qui vous attend aujourd'hui, dans votre périmètre.">
      {tableau.isPending ? <Chargement /> : null}
      {tableau.isError ? <Erreur erreur={tableau.error} /> : null}
      {tableau.data ? (
        <>
          <Compteurs code="a-traiter" titre="À traiter aujourd'hui" compteurs={compteurs.filter((c) => c.groupe === "a_traiter")} vide="Rien en attente : tout est à jour." />
          <Compteurs code="alertes" titre="Alertes" compteurs={compteurs.filter((c) => c.groupe === "alertes")} vide="Aucune alerte." />
        </>
      ) : null}
      <h2>Vos rôles</h2>
      <ul className="liste-cartes">
        {moi?.habilitations.map((h) => (
          <li key={`${h.role}-${h.perimetre}`} className="carte">
            <h3>{h.role_libelle}</h3>
            <p>
              Périmètre : <strong>{h.perimetre}</strong>
              {h.tous_sites ? " (tous les sites)" : ` — ${h.sites.map(nomSite).join(", ")}`}
            </p>
            <p className="carte__detail">{h.actions.length} actions autorisées</p>
          </li>
        ))}
      </ul>
      {raccourcis.length ? (
        <>
          <h2>Accès rapides</h2>
          <ul className="raccourcis">
            {raccourcis.map((m) => (
              <li key={m.chemin}>
                <Link to={m.chemin}>{m.libelle}</Link>
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </Page>
  );
}
