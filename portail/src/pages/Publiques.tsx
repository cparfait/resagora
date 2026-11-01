/** Pages sans compte : accueil, catalogue (POR-03), fiche d'un équipement, disponibilités anonymisées (POR-02). */
import { classesBouton } from "../ui/Bouton";
import { useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { chemin, requete, telecharger } from "../api/http";
import type { Disponibilites, EspacePublic, Famille, Page, Site } from "../api/types";
import { SimulateurTarif } from "../espace/Finances";
import { useSession } from "../session";
import { Bouton } from "../ui/Bouton";
import { Case, Champ, Liste } from "../ui/Champs";
import { Chargement, ErreurChargement, TitrePage, date, heure, taille } from "../ui/Elements";

export function Accueil() {
  const { connecte } = useSession();
  return (
    <>
      <TitrePage titre="Réserver un équipement de la Ville">
        <p className="chapo">Gymnases, dojos, terrains, salles associatives et salle des fêtes : consultez les équipements, leurs disponibilités, et déposez vos demandes en ligne.</p>
      </TitrePage>
      <ul className="tuiles">
        <li className="tuile">
          <h2>Découvrir les équipements</h2>
          <p>Capacité, accessibilité, équipements disponibles et règlements.</p>
          <Link to="/equipements">Voir les équipements</Link>
        </li>
        <li className="tuile">
          <h2>Consulter les disponibilités</h2>
          <p>Les créneaux libres et occupés, semaine par semaine, sans créer de compte.</p>
          <Link to="/disponibilites">Voir les disponibilités</Link>
        </li>
        <li className="tuile">
          <h2>{connecte ? "Mon espace" : "Faire une demande"}</h2>
          <p>
            {connecte
              ? "Suivez vos demandes, vos documents à signer et vos échanges avec la Ville."
              : "Associations, écoles, entreprises et particuliers : créez votre compte, il est validé par la Ville."}
          </p>
          <Link to={connecte ? "/espace" : "/inscription"}>{connecte ? "Accéder à mon espace" : "Créer un compte"}</Link>
        </li>
      </ul>
    </>
  );
}

export function Catalogue() {
  const [filtres, setFiltres] = useState({ recherche: "", famille: "", site: "", capacite_min: "", accessible_pmr: false });
  const sites = useQuery({ queryKey: ["sites"], queryFn: () => requete<Site[]>("GET", "/api/portail/catalogue/sites") });
  const familles = useQuery({ queryKey: ["familles"], queryFn: () => requete<Famille[]>("GET", "/api/portail/catalogue/familles") });
  const espaces = useQuery({
    queryKey: ["espaces", filtres],
    queryFn: () =>
      requete<Page<EspacePublic>>(
        "GET",
        chemin("/api/portail/catalogue/espaces", {
          recherche: filtres.recherche,
          famille: filtres.famille,
          batiment__site: filtres.site,
          capacite_min: filtres.capacite_min,
          accessible_pmr: filtres.accessible_pmr ? "true" : "",
          taille: 100,
        }),
      ),
  });
  return (
    <>
      <TitrePage titre="Les équipements" />
      <form className="filtres" role="search" aria-label="Rechercher un équipement" onSubmit={(e) => e.preventDefault()}>
        <Champ libelle="Nom ou activité" type="search" value={filtres.recherche} onChange={(e) => setFiltres({ ...filtres, recherche: e.target.value })} aide="Par exemple : basket, judo, réunion." />
        <Liste libelle="Type d'équipement" vide="Tous les types" options={(familles.data ?? []).map((f) => ({ valeur: String(f.id), libelle: f.libelle }))} value={filtres.famille} onChange={(e) => setFiltres({ ...filtres, famille: e.target.value })} />
        <Liste libelle="Site" vide="Tous les sites" options={(sites.data ?? []).map((s) => ({ valeur: String(s.id), libelle: s.nom }))} value={filtres.site} onChange={(e) => setFiltres({ ...filtres, site: e.target.value })} />
        <Champ libelle="Nombre de personnes" type="number" min={1} inputMode="numeric" value={filtres.capacite_min} onChange={(e) => setFiltres({ ...filtres, capacite_min: e.target.value })} />
        <Case libelle="Accessible aux personnes à mobilité réduite" checked={filtres.accessible_pmr} onChange={(e) => setFiltres({ ...filtres, accessible_pmr: e.target.checked })} />
      </form>
      {espaces.isPending ? <Chargement /> : null}
      {espaces.isError ? <ErreurChargement erreur={espaces.error} reessayer={() => void espaces.refetch()} /> : null}
      {espaces.data ? (
        <>
          <p role="status" aria-live="polite">
            {espaces.data.count} équipement{espaces.data.count > 1 ? "s" : ""} trouvé{espaces.data.count > 1 ? "s" : ""}
          </p>
          <ul className="cartes">
            {espaces.data.results.map((e) => (
              <li key={e.id} className="carte">
                <h2>
                  <Link to={`/equipements/${e.id}`}>{e.nom}</Link>
                </h2>
                <p>
                  {e.famille_libelle} — {e.site_nom}
                </p>
                <p>
                  {e.capacite} personnes{e.surface_m2 ? `, ${e.surface_m2} m²` : ""}
                  {e.accessible_pmr ? ", accessible aux personnes à mobilité réduite" : ""}
                </p>
                {e.photos[0] ? <img src={e.photos[0].url} alt={e.photos[0].description} loading="lazy" width={320} height={200} /> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </>
  );
}

export function FicheEquipement() {
  const { id } = useParams();
  const { connecte } = useSession();
  const espace = useQuery({ queryKey: ["espace", id], queryFn: () => requete<EspacePublic>("GET", `/api/portail/catalogue/espaces/${id}`) });
  if (espace.isPending) return <Chargement />;
  if (espace.isError) return <ErreurChargement erreur={espace.error} />;
  const e = espace.data;
  return (
    <>
      <TitrePage titre={e.nom}>
        <p className="chapo">
          {e.famille_libelle} — {e.site_nom}
          {e.parent_nom ? ` — partie de ${e.parent_nom}` : ""}
        </p>
      </TitrePage>
      <div className="fiche">
        <section aria-labelledby="titre-caracteristiques">
          <h2 id="titre-caracteristiques">Caractéristiques</h2>
          <dl className="details">
            <dt>Capacité</dt>
            <dd>{e.capacite} personnes</dd>
            {e.surface_m2 ? (
              <>
                <dt>Surface</dt>
                <dd>{e.surface_m2} m²</dd>
              </>
            ) : null}
            <dt>Accessibilité</dt>
            <dd>{e.accessible_pmr ? "Accessible aux personnes à mobilité réduite" : "Accès non adapté aux personnes à mobilité réduite"}</dd>
            <dt>Adresse</dt>
            <dd>{e.adresse}</dd>
            {e.equipements ? (
              <>
                <dt>Équipements</dt>
                <dd>{e.equipements}</dd>
              </>
            ) : null}
            {e.activites ? (
              <>
                <dt>Activités</dt>
                <dd>{e.activites}</dd>
              </>
            ) : null}
          </dl>
          {e.description ? <p>{e.description}</p> : null}
        </section>
        {e.photos.length ? (
          <section aria-labelledby="titre-photos">
            <h2 id="titre-photos">Photos</h2>
            <ul className="photos">
              {e.photos.map((p) => (
                <li key={p.id}>
                  <img src={p.url} alt={p.description} width={480} height={300} loading="lazy" />
                </li>
              ))}
            </ul>
          </section>
        ) : null}
        {e.documents.length ? (
          <section aria-labelledby="titre-documents">
            <h2 id="titre-documents">Documents</h2>
            <ul>
              {e.documents.map((d) => (
                <li key={d.id}>
                  <button type="button" className={classesBouton("lien")} onClick={() => void telecharger(d.url, `${d.titre}.pdf`)}>
                    {d.titre} ({d.nature}, {d.format}, {taille(d.taille)})
                  </button>
                </li>
              ))}
            </ul>
          </section>
        ) : null}
      </div>
      <SimulateurTarif espace={e.id} />
      <p className="actions">
        <Link className={classesBouton("secondaire")} to={`/disponibilites?espace=${e.id}`}>
          Voir les disponibilités
        </Link>
        <Link className={classesBouton("principal")} to={connecte ? `/espace/demande?espace=${e.id}` : "/connexion"}>
          {connecte ? "Faire une demande" : "Se connecter pour faire une demande"}
        </Link>
      </p>
    </>
  );
}

const JOURS_SEMAINE = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];
const ETATS: Record<string, string> = { occupe: "Occupé", demande: "Demandé", ferme: "Fermé" };

function lundiDe(jour: Date): Date {
  const resultat = new Date(jour);
  resultat.setHours(12, 0, 0, 0);
  resultat.setDate(resultat.getDate() - ((resultat.getDay() + 6) % 7));
  return resultat;
}

function iso(jour: Date): string {
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${jour.getFullYear()}-${deux(jour.getMonth() + 1)}-${deux(jour.getDate())}`;
}

export function DisponibilitesPage() {
  const [parametres, setParametres] = useSearchParams();
  const espace = parametres.get("espace") ?? "";
  const [debut, setDebut] = useState(() => lundiDe(new Date()));
  const [vue, setVue] = useState<"grille" | "liste">("grille");
  const espaces = useQuery({ queryKey: ["espaces-tous"], queryFn: () => requete<Page<EspacePublic>>("GET", chemin("/api/portail/catalogue/espaces", { taille: 200 })) });
  const dispo = useQuery({
    queryKey: ["dispo", espace, iso(debut)],
    queryFn: () => requete<Disponibilites>("GET", chemin("/api/portail/disponibilites", { espace, debut: iso(debut), jours: 7 })),
    enabled: Boolean(espace),
  });
  const decaler = (semaines: number) => {
    const suivant = new Date(debut);
    suivant.setDate(suivant.getDate() + 7 * semaines);
    setDebut(suivant);
  };
  const heures = useMemo(() => Array.from({ length: 16 }, (_, i) => i + 8), []);
  const etatA = (jour: string, h: number): string => {
    if (!dispo.data) return "";
    const infos = dispo.data.jours.find((j) => j.jour === jour);
    const debutCase = new Date(`${jour}T${String(h).padStart(2, "0")}:00:00`);
    const finCase = new Date(debutCase.getTime() + 3_600_000);
    const plage = dispo.data.plages.find((p) => new Date(p.debut) < finCase && new Date(p.fin) > debutCase);
    if (plage) return ETATS[plage.etat] ?? "Occupé";
    const ouvert = !infos || infos.horaires.length === 0 || infos.horaires.some((o) => o.debut <= `${String(h).padStart(2, "0")}:00` && o.fin >= `${String(h + 1).padStart(2, "0")}:00`);
    return ouvert ? "Libre" : "Fermé";
  };
  return (
    <>
      <TitrePage titre="Disponibilités" sousTitre={dispo.data?.espace_nom} />
      <p>Les créneaux affichés ne mentionnent jamais les usagers. « Demandé » signale une demande en cours d'examen : le créneau peut encore se libérer.</p>
      <form className="filtres" onSubmit={(e) => e.preventDefault()}>
        <Liste
          libelle="Équipement"
          options={(espaces.data?.results ?? []).map((e) => ({ valeur: String(e.id), libelle: `${e.nom} (${e.site_nom})` }))}
          value={espace}
          onChange={(e) => setParametres(e.target.value ? { espace: e.target.value } : {})}
        />
      </form>
      {espace ? (
        <>
          <div className="barre-semaine">
            <Bouton variante="secondaire" onClick={() => decaler(-1)}>
              Semaine précédente
            </Bouton>
            <p aria-live="polite" className="barre-semaine__titre">
              Semaine du {date(iso(debut))}
            </p>
            <Bouton variante="secondaire" onClick={() => decaler(1)}>
              Semaine suivante
            </Bouton>
            <Bouton variante="lien" onClick={() => setVue(vue === "grille" ? "liste" : "grille")} aria-pressed={vue === "liste"}>
              {vue === "grille" ? "Afficher en liste" : "Afficher la grille"}
            </Bouton>
          </div>
          {dispo.isPending ? <Chargement /> : null}
          {dispo.isError ? <ErreurChargement erreur={dispo.error} /> : null}
          {dispo.data && vue === "grille" ? (
            // Zone qui défile horizontalement sur petit écran : elle doit pouvoir recevoir le focus clavier (axe : scrollable-region-focusable).
            // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
            <div className="defilement-horizontal" tabIndex={0} role="region" aria-label="Grille des disponibilités de la semaine">
              <table className="grille-dispo">
                <caption>
                  Disponibilités de {dispo.data.espace_nom}, semaine du {date(iso(debut))}, par heure
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Heure</th>
                    {dispo.data.jours.map((j, i) => (
                      <th key={j.jour} scope="col">
                        {JOURS_SEMAINE[i]} {date(j.jour)}
                        {j.vacances ? " (vacances)" : ""}
                        {j.ferie ? " (férié)" : ""}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {heures.map((h) => (
                    <tr key={h}>
                      <th scope="row">
                        {h} h – {h + 1} h
                      </th>
                      {dispo.data.jours.map((j) => {
                        const etat = etatA(j.jour, h);
                        return (
                          <td key={j.jour} className={`etat-${etat.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")}`}>
                            {etat}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
          {dispo.data && vue === "liste" ? (
            <ul className="liste-jours">
              {dispo.data.jours.map((j, i) => {
                const duJour = dispo.data.plages.filter((p) => iso(new Date(p.debut)) === j.jour);
                return (
                  <li key={j.jour}>
                    <h2>
                      {JOURS_SEMAINE[i]} {date(j.jour)}
                    </h2>
                    <p>{j.horaires.length ? `Ouvert ${j.horaires.map((o) => `de ${o.debut.replace(":", " h ")} à ${o.fin.replace(":", " h ")}`).join(" et ")}` : "Horaires non précisés"}</p>
                    {duJour.length ? (
                      <ul>
                        {duJour.map((p) => (
                          <li key={`${p.debut}-${p.etat}`}>
                            {ETATS[p.etat]} de {heure(p.debut)} à {heure(p.fin)}
                          </li>
                        ))}
                      </ul>
                    ) : (
                      <p>Aucune occupation : libre aux heures d'ouverture.</p>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : null}
        </>
      ) : (
        <p>Choisissez un équipement pour afficher ses disponibilités.</p>
      )}
    </>
  );
}
