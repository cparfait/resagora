/** Accueil de l'agent : identité, rôles et périmètres effectifs (RG-14), raccourcis vers ses écrans. */
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { requete, type Page as PageApi } from "../../api/http";
import type { Site } from "../../api/types";
import { useSession } from "../../auth/session";
import { MODULES } from "../../cadre/modules";
import { Page } from "../../ui/Page";

export default function Accueil() {
  const { moi, peut } = useSession();
  const sites = useQuery({ queryKey: ["options", "sites"], queryFn: () => requete<PageApi<Site>>("GET", "/api/gestion/referentiel/sites?taille=500") });
  const nomSite = (id: number) => sites.data?.results.find((s) => s.id === id)?.nom ?? `site n° ${id}`;
  const raccourcis = MODULES.filter((m) => m.chemin !== "/" && !m.masque && peut(m.action)).slice(0, 8);

  return (
    <Page titre={`Bonjour ${moi?.nom_affiche ?? ""}`} description="Vos habilitations et vos écrans.">
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
