/** DSH-01 à DSH-03, DSH-05, DSH-06 : « que dois-je traiter aujourd'hui ? » — compteurs du jour et alertes, calculés
 * par l'API dans le périmètre de l'agent ; chaque compteur ouvre la liste filtrée qu'il résume. Rôles et périmètres. */
import { Link } from "react-router";
import { useQuery } from "@tanstack/react-query";
import { Building2, CalendarCheck, Clock, Gauge, Inbox, TriangleAlert } from "lucide-react";
import { construireChemin, requete, type Page as PageApi } from "../../api/http";
import type { Site } from "../../api/types";
import { useSession } from "../../auth/session";
import { MODULES } from "../../cadre/modules";
import { Chiffre } from "../../ui/Chiffre";
import { Chargement, Erreur } from "../../ui/Etats";
import { isoJour } from "../../ui/metier";
import { Page } from "../../ui/Page";
import { BarreRepartition, BarresOccupation, CarteGraphique, heures, pourcent, TableauOccupation, TableauRepartition, type LigneOccupation, type Part } from "./Graphiques";

export interface Compteur {
  code: string;
  libelle: string;
  nombre: number;
  lien: string;
  groupe: "a_traiter" | "alertes";
  gravite: "info" | "attention" | "danger";
}

const ICONES_GRAVITE = { info: Inbox, attention: Clock, danger: TriangleAlert } as const;
const TEINTES_GRAVITE = { info: "bg-vert-pale text-vert", attention: "bg-attention-fond text-attention", danger: "bg-danger-fond text-danger" } as const;

/** Compteurs « à traiter » et alertes, en liste façon panneau de notifications (DSH-01, DSH-06 : chaque compteur
 * ouvre la liste filtrée qu'il résume). */
function Compteurs({ code, titre, compteurs, vide }: { code: string; titre: string; compteurs: Compteur[]; vide: string }) {
  const actifs = compteurs.filter((c) => c.nombre > 0);
  return (
    // « À traiter aujourd'hui » est le bloc prioritaire de l'écran (un seul par écran, DESIGN.md).
    <section aria-labelledby={`titre-${code}`} className={code === "a-traiter" ? "bloc-prioritaire" : "rounded-lg bg-carte p-5 shadow-carte"}>
      <h2 id={`titre-${code}`} className="mt-0 mb-3 text-base font-semibold">
        {titre}
      </h2>
      {actifs.length === 0 ? <p className="m-0 text-petit text-encre-douce">{vide}</p> : null}
      <ul className="m-0 flex list-none flex-col gap-2 p-0">
        {actifs.map((c) => {
          const Icone = ICONES_GRAVITE[c.gravite] ?? Inbox;
          return (
            <li key={c.code}>
              <Link
                to={c.lien}
                className="flex min-h-14 items-center gap-3 rounded-lg bg-carte px-3 py-2 text-encre no-underline shadow-carte transition-colors hover:text-vert-fonce hover:underline"
              >
                <span aria-hidden="true" className={`inline-flex size-9 shrink-0 items-center justify-center rounded-md ${TEINTES_GRAVITE[c.gravite] ?? TEINTES_GRAVITE.info}`}>
                  <Icone size={18} strokeWidth={1.8} />
                </span>
                <span className="compteur__nombre text-xl font-bold tabular-nums">{c.nombre}</span>
                <span className="compteur__libelle text-petit leading-snug font-medium">{c.libelle}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

/** Carte chiffre-clé façon Mariloo : pastille d'icône teintée, libellé, valeur (guide dataviz : stat tile). */
function bornesDuMois(): { du: string; au: string; libelle: string } {
  const aujourd_hui = new Date();
  const premier = new Date(aujourd_hui.getFullYear(), aujourd_hui.getMonth(), 1);
  const dernier = new Date(aujourd_hui.getFullYear(), aujourd_hui.getMonth() + 1, 0);
  const libelle = new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(premier);
  return { du: isoJour(premier), au: isoJour(dernier), libelle: libelle.charAt(0).toUpperCase() + libelle.slice(1) };
}

export default function Accueil() {
  const { moi, peut } = useSession();
  const sites = useQuery({ queryKey: ["options", "sites"], queryFn: () => requete<PageApi<Site>>("GET", "/api/gestion/referentiel/sites?taille=500") });
  const tableau = useQuery({
    queryKey: ["a-traiter"],
    queryFn: () => requete<{ compteurs: Compteur[] }>("GET", "/api/gestion/pilotage/a-traiter"),
    refetchInterval: 5 * 60_000,
  });
  const mois = bornesDuMois();
  const statistiques = peut("lire_statistiques");
  const occupation = useQuery({
    queryKey: ["accueil-occupation", mois.du],
    queryFn: () => requete<{ espaces: LigneOccupation[] }>("GET", construireChemin("/api/gestion/pilotage/statistiques/occupation", { du: mois.du, au: mois.au })),
    enabled: statistiques,
  });
  const repartition = useQuery({
    queryKey: ["accueil-repartition", mois.du],
    queryFn: () => requete<{ types_usager: Part[] }>("GET", construireChemin("/api/gestion/pilotage/statistiques/repartition", { du: mois.du, au: mois.au })),
    enabled: statistiques,
  });
  const nomSite = (id: number) => sites.data?.results.find((s) => s.id === id)?.nom ?? `site n° ${id}`;
  const raccourcis = MODULES.filter((m) => m.chemin !== "/" && !m.masque && peut(m.action)).slice(0, 8);
  const compteurs = tableau.data?.compteurs ?? [];
  const espaces = (occupation.data?.espaces ?? []).filter((l) => l.premier_niveau);
  const reservees = espaces.reduce((total, l) => total + l.minutes_reservees, 0);
  const ouvertes = espaces.reduce((total, l) => total + l.minutes_ouverture, 0);
  const demandes = compteurs.find((c) => c.code === "demandes")?.nombre ?? 0;

  return (
    <Page titre={`Bonjour ${moi?.nom_affiche ?? ""}`} description="Ce qui vous attend aujourd'hui, dans votre périmètre.">
      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_22rem]">
        <div className="flex min-w-0 flex-col gap-6">
          {statistiques && occupation.data ? (
            <>
              <section aria-label="Chiffres clés du mois" className="grid grid-cols-[repeat(auto-fit,minmax(min(8.5rem,100%),1fr))] gap-4">
                <Chiffre icone={Building2} libelle="Espaces suivis" valeur={String(espaces.length)} detail={mois.libelle} />
                <Chiffre icone={Inbox} libelle="Demandes à instruire" valeur={String(demandes)} detail="Aujourd'hui" />
                <Chiffre icone={CalendarCheck} libelle="Heures réservées" valeur={heures(reservees)} detail={mois.libelle} />
                <Chiffre icone={Gauge} libelle="Taux d'occupation" valeur={ouvertes ? pourcent(Math.round((10000 * reservees) / ouvertes)) : "—"} detail={mois.libelle} />
              </section>
              <div className="grid grid-cols-[repeat(auto-fit,minmax(min(22rem,100%),1fr))] gap-4">
                <CarteGraphique titre="Occupation des espaces" sousTitre={`${mois.libelle} — les 8 espaces les plus occupés`} donnees={<TableauOccupation lignes={espaces} />}>
                  <BarresOccupation lignes={espaces} />
                </CarteGraphique>
                {repartition.data ? (
                  <CarteGraphique titre="Répartition des heures" sousTitre={`${mois.libelle} — par type d'usager`} donnees={<TableauRepartition parts={repartition.data.types_usager} />}>
                    <BarreRepartition parts={repartition.data.types_usager} />
                  </CarteGraphique>
                ) : null}
              </div>
            </>
          ) : null}
          {raccourcis.length ? (
            <section aria-labelledby="titre-raccourcis">
              <h2 id="titre-raccourcis" className="mt-0 mb-3 text-base font-semibold">
                Accès rapides
              </h2>
              <ul className="raccourcis m-0">
                {raccourcis.map((m) => (
                  <li key={m.chemin}>
                    <Link to={m.chemin}>{m.libelle}</Link>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <section aria-labelledby="titre-roles">
            <h2 id="titre-roles" className="mt-0 mb-3 text-base font-semibold">
              Vos rôles
            </h2>
            <ul className="liste-cartes m-0">
              {moi?.habilitations.map((h) => (
                <li key={`${h.role}-${h.perimetre}`} className="carte">
                  <h3 className="text-base">{h.role_libelle}</h3>
                  <p className="text-petit">
                    Périmètre : <strong>{h.perimetre}</strong>
                    {h.tous_sites ? " (tous les sites)" : ` — ${h.sites.map(nomSite).join(", ")}`}
                  </p>
                  <p className="carte__detail text-petit">{h.actions.length} actions autorisées</p>
                </li>
              ))}
            </ul>
          </section>
        </div>
        <aside className="flex flex-col gap-4" aria-label="À traiter et alertes">
          {tableau.isPending ? <Chargement /> : null}
          {tableau.isError ? <Erreur erreur={tableau.error} /> : null}
          {tableau.data ? (
            <>
              <Compteurs code="a-traiter" titre="À traiter aujourd'hui" compteurs={compteurs.filter((c) => c.groupe === "a_traiter")} vide="Rien en attente : tout est à jour." />
              <Compteurs code="alertes" titre="Alertes" compteurs={compteurs.filter((c) => c.groupe === "alertes")} vide="Aucune alerte." />
            </>
          ) : null}
        </aside>
      </div>
    </Page>
  );
}
