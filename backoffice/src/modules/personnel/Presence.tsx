/** REF-04, PER-02 : présence d'un agent réglée par site et par salle. Tous les sites n'ont pas besoin d'une présence :
 * seules les salles où elle est requise font naître des besoins de gardiennage à partir de leurs réservations. Changer
 * le réglage fait recalculer par le serveur les besoins à venir du site ; les vacations devenues inutiles passent
 * « à revoir » et l'agent est prévenu (RG-09). Modification réservée aux gestionnaires du référentiel. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router";
import { ErreurApi, requete, type Page as PageApi } from "../../api/http";
import type { Espace } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Chargement, Erreur } from "../../ui/Etats";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";

function Interrupteur({ espace, modifiable, enCours, onBasculer }: { espace: Espace; modifiable: boolean; enCours: boolean; onBasculer: (requis: boolean) => void }) {
  const requis = Boolean(espace.gardiennage_requis);
  return (
    <label className={`inline-flex shrink-0 items-center gap-3 text-[0.85rem] font-medium text-encre ${modifiable ? "cursor-pointer" : ""}`}>
      <span>
        Présence d'un agent <span className="sr-only">— {espace.nom}</span>
      </span>
      <input type="checkbox" role="switch" aria-checked={requis} className="peer sr-only" checked={requis} disabled={!modifiable || enCours} onChange={(e) => onBasculer(e.target.checked)} />
      <span
        aria-hidden="true"
        className="relative h-6 w-11 shrink-0 rounded-full bg-contour-champ/50 transition-colors peer-checked:bg-vert peer-focus-visible:outline-[3px] peer-focus-visible:outline-offset-3 peer-focus-visible:outline-vert-profond peer-focus-visible:outline-solid peer-disabled:opacity-60 after:absolute after:top-0.5 after:left-0.5 after:size-5 after:rounded-full after:bg-blanc after:shadow-carte after:transition-transform peer-checked:after:translate-x-5"
      />
      <span aria-hidden="true" className="w-[5.5rem] text-encre-douce">
        {requis ? "Requise" : "Non requise"}
      </span>
    </label>
  );
}

export default function Presence() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const modifiable = peut("gerer_referentiel");
  const espaces = useQuery({
    queryKey: ["presence-espaces"],
    queryFn: async () => (await requete<PageApi<Espace>>("GET", "/api/gestion/referentiel/espaces?actif=true&taille=500")).results,
  });
  const basculer = useMutation({
    mutationFn: ({ espace, requis }: { espace: Espace; requis: boolean }) => requete<Espace>("PATCH", `/api/gestion/referentiel/espaces/${espace.id}`, { gardiennage_requis: requis }),
    onSuccess: async (_, { espace, requis }) => {
      annoncer(
        requis
          ? `Présence requise dans ${espace.nom} : les besoins à venir sont calculés.`
          : `Plus de présence requise dans ${espace.nom} : les besoins à venir sont retirés et les vacations concernées passent « à revoir ».`,
      );
      for (const cle of ["presence-espaces", "espaces-gardiennes", "besoins", "vacations", "a-traiter"]) await client.invalidateQueries({ queryKey: [cle] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Réglage impossible.", "erreur"),
  });

  const parSite = new Map<string, Espace[]>();
  for (const e of (espaces.data ?? []).toSorted((a, b) => a.nom.localeCompare(b.nom, "fr"))) parSite.set(e.site_nom, [...(parSite.get(e.site_nom) ?? []), e]);
  const sites = [...parSite.entries()].toSorted(([a], [b]) => a.localeCompare(b, "fr"));
  const requises = (espaces.data ?? []).filter((e) => e.gardiennage_requis);
  const sitesCouverts = sites.filter(([, liste]) => liste.some((e) => e.gardiennage_requis)).length;

  return (
    <Page
      titre="Présence par site"
      description="Choisissez les salles où un agent doit être présent pendant les réservations. Les autres salles fonctionnent sans gardien : elles ne créent aucun besoin dans le planning du personnel."
    >
      {espaces.isPending ? <Chargement /> : null}
      {espaces.isError ? <Erreur erreur={espaces.error} reessayer={() => void espaces.refetch()} /> : null}
      {espaces.data ? (
        <>
          <p className="mt-0 mb-2">
            <strong>
              {requises.length} salle{requises.length > 1 ? "s" : ""} sur {espaces.data.length}
            </strong>{" "}
            demande{requises.length > 1 ? "nt" : ""} une présence, sur {sitesCouverts} site{sitesCouverts > 1 ? "s" : ""} sur {sites.length}.
          </p>
          <p className="mt-0 mb-5 text-petit text-encre-douce">
            {modifiable
              ? "Le changement s'applique aux réservations à venir : les besoins sont recalculés, et un agent déjà prévu sur une salle qui n'en a plus besoin est prévenu."
              : "Vous pouvez consulter ces réglages ; seul un gestionnaire du référentiel peut les modifier."}{" "}
            Les temps d'ouverture et de fermeture se règlent dans <Link to="/referentiel/espaces">Sites et espaces</Link>.
          </p>
          <div className="grid gap-4 xl:grid-cols-2">
            {sites.map(([site, liste]) => {
              const nombre = liste.filter((e) => e.gardiennage_requis).length;
              const id = `site-${liste[0]?.site ?? site}`;
              return (
                <section key={site} aria-labelledby={id} className="rounded-lg bg-carte p-5 shadow-carte">
                  <header className="flex flex-wrap items-start justify-between gap-3">
                    <h2 id={id} className="m-0 text-base font-semibold text-encre">
                      {site}
                    </h2>
                    <Badge libelle={nombre ? `${nombre} salle${nombre > 1 ? "s" : ""} à couvrir` : "Sans présence"} ton={nombre ? "info" : "neutre"} />
                  </header>
                  <ul className="m-0 mt-2 list-none divide-y divide-filet p-0">
                    {liste.map((e) => (
                      <li key={e.id} className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 py-3">
                        <div className="min-w-0">
                          <p className="m-0 font-medium text-encre">{e.nom}</p>
                          <p className="m-0 text-[0.8rem] text-encre-douce">
                            {e.famille_libelle}
                            {e.capacite ? ` · ${e.capacite} personnes` : ""}
                            {e.gardiennage_requis ? ` · ouverture ${e.temps_ouverture_min ?? 15} min avant, fermeture ${e.temps_fermeture_min ?? 15} min après` : ""}
                          </p>
                        </div>
                        <Interrupteur espace={e} modifiable={modifiable} enCours={basculer.isPending && basculer.variables?.espace.id === e.id} onBasculer={(requis) => basculer.mutate({ espace: e, requis })} />
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        </>
      ) : null}
    </Page>
  );
}
