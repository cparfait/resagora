/** STA-01 à STA-05 : statistiques d'occupation, de répartition, de recettes et de personnel, exportables en tableur ;
 * DSH-04 : tableau de bord de la direction. Chaque graphique a son tableau de données (accessibilité). */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, requete, telecharger } from "../../api/http";
import { useSession } from "../../auth/session";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte } from "../../ui/Champ";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { euros, isoJour } from "../../ui/metier";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

interface LigneOccupation {
  espace: number;
  espace_nom: string;
  site: number;
  site_nom: string;
  famille: string;
  minutes_reservees: number;
  minutes_ouverture: number;
  taux: number;
}
interface Occupation {
  espaces: LigneOccupation[];
  sites: { site: number; site_nom: string; minutes_reservees: number; minutes_ouverture: number; taux: number }[];
}
interface Part {
  cle: string;
  libelle: string;
  minutes: number;
  part: number;
}
interface Repartition {
  types_usager: Part[];
  activites: Part[];
  familles: Part[];
}
interface Recettes {
  factures: number;
  emis: number;
  avoirs: number;
  net: number;
  regle: number;
  reste_du: number;
  reductions: number;
  gratuites: number;
  concours_en_nature: number | null;
}
interface Personnel {
  agents: number;
  planifiees: number;
  realisees: number;
  supplementaires: number;
  nuit: number;
  dimanches_feries: number;
  astreintes: number;
}

const heures = (minutes: number) => `${Math.round(minutes / 60).toLocaleString("fr-FR")} h`;
const pourcent = (dixMillieme: number) => `${(dixMillieme / 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

function Barres({ titre, parts }: { titre: string; parts: Part[] }) {
  const max = Math.max(1, ...parts.map((p) => p.minutes));
  return (
    <figure>
      <figcaption>{titre}</figcaption>
      <ul className="barres" aria-hidden="true">
        {parts.slice(0, 10).map((p) => (
          <li key={p.cle}>
            <span>{p.libelle}</span>
            <span className="barres__barre" style={{ width: `${(100 * p.minutes) / max}%` }} />
            <span>{pourcent(p.part)}</span>
          </li>
        ))}
      </ul>
      <Tableau<Part>
        legende={titre}
        lignes={parts}
        cleLigne={(p) => p.cle}
        messageVide="Aucune séance sur la période."
        colonnes={[
          { cle: "libelle", titre: "Catégorie", rendu: (p) => p.libelle },
          { cle: "heures", titre: "Heures", rendu: (p) => heures(p.minutes), valeurTri: (p) => p.minutes },
          { cle: "part", titre: "Part", rendu: (p) => pourcent(p.part), valeurTri: (p) => p.part },
        ]}
      />
    </figure>
  );
}

export function Statistiques() {
  const { peut } = useSession();
  const lecture = peut("lire_statistiques");
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const [periode, setPeriode] = useState(() => {
    const jour = new Date();
    return { du: isoJour(new Date(jour.getFullYear(), 0, 1)), au: isoJour(jour), site: "" };
  });
  const parametres = { du: periode.du, au: periode.au, site: periode.site || undefined };
  const occupation = useQuery({ queryKey: ["stats", "occupation", parametres], queryFn: () => requete<Occupation>("GET", construireChemin("/api/gestion/pilotage/statistiques/occupation", parametres)), enabled: lecture });
  const repartition = useQuery({ queryKey: ["stats", "repartition", parametres], queryFn: () => requete<Repartition>("GET", construireChemin("/api/gestion/pilotage/statistiques/repartition", parametres)), enabled: lecture });
  const recettes = useQuery({ queryKey: ["stats", "recettes", parametres], queryFn: () => requete<Recettes>("GET", construireChemin("/api/gestion/pilotage/statistiques/recettes", parametres)), enabled: peut("lire_finances") });
  const personnel = useQuery({ queryKey: ["stats", "personnel", parametres], queryFn: () => requete<Personnel>("GET", construireChemin("/api/gestion/pilotage/statistiques/personnel", parametres)), enabled: peut("lire_personnel") });
  if (!lecture) return <DroitsInsuffisants />;
  const exporter = (nom: string) => void telecharger(construireChemin(`/api/gestion/pilotage/statistiques/${nom}`, { ...parametres, export: "xlsx" }), `${nom}.xlsx`);
  return (
    <Page titre="Statistiques" description="Occupation des équipements, répartition des usages, recettes, gratuités et heures du personnel, dans votre périmètre.">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampTexte libelle="Du" type="date" value={periode.du} onChange={(e) => setPeriode({ ...periode, du: e.target.value })} />
        <ChampTexte libelle="Au" type="date" value={periode.au} onChange={(e) => setPeriode({ ...periode, au: e.target.value })} />
        <ChampSelection libelle="Site" videLibelle="Tous mes sites" options={sites} value={periode.site} onChange={(e) => setPeriode({ ...periode, site: e.target.value })} />
      </form>

      <section aria-labelledby="titre-occupation">
        <h2 id="titre-occupation">Taux d'occupation</h2>
        <Bouton variante="secondaire" onClick={() => exporter("occupation")}>
          Exporter l'occupation (tableur)
        </Bouton>
        {occupation.isPending ? <Chargement /> : null}
        {occupation.isError ? <Erreur erreur={occupation.error} /> : null}
        {occupation.data ? (
          <>
            <Tableau
              legende="Occupation par site"
              lignes={occupation.data.sites}
              cleLigne={(s) => s.site}
              messageVide="Aucun site."
              colonnes={[
                { cle: "site", titre: "Site", rendu: (s) => s.site_nom },
                { cle: "reservees", titre: "Heures réservées", rendu: (s) => heures(s.minutes_reservees), valeurTri: (s) => s.minutes_reservees },
                { cle: "ouverture", titre: "Heures d'ouverture", rendu: (s) => heures(s.minutes_ouverture) },
                { cle: "taux", titre: "Taux", rendu: (s) => pourcent(s.taux), valeurTri: (s) => s.taux },
              ]}
            />
            <details>
              <summary>Détail par espace ({occupation.data.espaces.length})</summary>
              <Tableau<LigneOccupation>
                legende="Occupation par espace"
                lignes={occupation.data.espaces}
                cleLigne={(l) => l.espace}
                colonnes={[
                  { cle: "espace", titre: "Espace", rendu: (l) => `${l.espace_nom} (${l.site_nom})`, valeurTri: (l) => l.espace_nom },
                  { cle: "famille", titre: "Famille", rendu: (l) => l.famille },
                  { cle: "reservees", titre: "Heures réservées", rendu: (l) => heures(l.minutes_reservees), valeurTri: (l) => l.minutes_reservees },
                  { cle: "taux", titre: "Taux", rendu: (l) => pourcent(l.taux), valeurTri: (l) => l.taux },
                ]}
              />
            </details>
          </>
        ) : null}
      </section>

      <section aria-labelledby="titre-repartition">
        <h2 id="titre-repartition">Répartition des usages</h2>
        <Bouton variante="secondaire" onClick={() => exporter("repartition")}>
          Exporter la répartition (tableur)
        </Bouton>
        {repartition.data ? (
          <div className="grille-deux">
            <Barres titre="Heures par type d'usager" parts={repartition.data.types_usager} />
            <Barres titre="Heures par activité" parts={repartition.data.activites} />
          </div>
        ) : null}
      </section>

      {peut("lire_finances") ? (
        <section aria-labelledby="titre-recettes">
          <h2 id="titre-recettes">Recettes, gratuités et réductions</h2>
          <Bouton variante="secondaire" onClick={() => exporter("recettes")}>
            Exporter les recettes (tableur)
          </Bouton>
          {recettes.data ? (
            <ul className="indicateurs">
              <li className="indicateur">Recettes nettes<span className="indicateur__valeur">{euros(recettes.data.net)}</span><span className="indicateur__evolution">{recettes.data.factures} facture(s), avoirs {euros(recettes.data.avoirs)}</span></li>
              <li className="indicateur">Réglé<span className="indicateur__valeur">{euros(recettes.data.regle)}</span><span className="indicateur__evolution">reste dû {euros(recettes.data.reste_du)}</span></li>
              <li className="indicateur">Réductions accordées<span className="indicateur__valeur">{euros(recettes.data.reductions)}</span><span className="indicateur__evolution">gratuités facturées à 0 € : {euros(recettes.data.gratuites)}</span></li>
              {recettes.data.concours_en_nature !== null ? (
                <li className="indicateur">Concours en nature valorisés (toute la Ville)<span className="indicateur__valeur">{euros(recettes.data.concours_en_nature)}</span><span className="indicateur__evolution">gratuités comprises, selon le dernier calcul</span></li>
              ) : null}
            </ul>
          ) : null}
        </section>
      ) : null}

      {peut("lire_personnel") && personnel.data ? (
        <section aria-labelledby="titre-personnel">
          <h2 id="titre-personnel">Personnel</h2>
          <Bouton variante="secondaire" onClick={() => exporter("personnel")}>
            Exporter les heures du personnel (tableur)
          </Bouton>
          <ul className="indicateurs">
            <li className="indicateur">Heures planifiées<span className="indicateur__valeur">{heures(personnel.data.planifiees)}</span><span className="indicateur__evolution">{personnel.data.agents} agent(s)</span></li>
            <li className="indicateur">Heures réalisées<span className="indicateur__valeur">{heures(personnel.data.realisees)}</span></li>
            <li className="indicateur">Heures supplémentaires<span className="indicateur__valeur">{heures(personnel.data.supplementaires)}</span></li>
            <li className="indicateur">Nuit, dimanches et fériés<span className="indicateur__valeur">{heures(personnel.data.nuit + personnel.data.dimanches_feries)}</span></li>
          </ul>
        </section>
      ) : null}
    </Page>
  );
}

interface Annuel {
  annee: number;
  heures_reservees: number;
  taux_occupation: number;
  usagers_actifs: number;
  recettes_nettes: number;
  concours_en_nature: number | null;
}

function Evolution({ courant, precedent, format }: { courant: number; precedent: number; format: (v: number) => string }) {
  if (!precedent) return <span className="indicateur__evolution">pas de comparaison</span>;
  const ecart = ((courant - precedent) / precedent) * 100;
  return (
    <span className="indicateur__evolution">
      {ecart >= 0 ? "en hausse de" : "en baisse de"} {Math.abs(ecart).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} % (précédent : {format(precedent)})
    </span>
  );
}

const MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"];

export function Direction() {
  const { peut } = useSession();
  const [annee, setAnnee] = useState(() => String(new Date().getFullYear()));
  const tableau = useQuery({
    queryKey: ["direction", annee],
    queryFn: () => requete<{ courant: Annuel; precedent: Annuel; mois: { mois: number; heures: number; recettes_nettes: number | null }[] }>("GET", construireChemin("/api/gestion/pilotage/direction", { annee })),
    enabled: peut("lire_tableau_direction"),
  });
  if (!peut("lire_tableau_direction")) return <DroitsInsuffisants />;
  const max = Math.max(1, ...(tableau.data?.mois ?? []).map((m) => m.heures));
  return (
    <Page titre="Tableau de bord de la direction" description="Occupation, recettes et concours en nature de l'année, comparés à l'année précédente.">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampTexte libelle="Année" type="number" min={2020} value={annee} onChange={(e) => setAnnee(e.target.value)} />
      </form>
      {tableau.isPending ? <Chargement /> : null}
      {tableau.isError ? <Erreur erreur={tableau.error} /> : null}
      {tableau.data ? (
        <>
          <ul className="indicateurs">
            <li className="indicateur">
              Taux d'occupation<span className="indicateur__valeur">{pourcent(tableau.data.courant.taux_occupation)}</span>
              <Evolution courant={tableau.data.courant.taux_occupation} precedent={tableau.data.precedent.taux_occupation} format={pourcent} />
            </li>
            <li className="indicateur">
              Heures réservées<span className="indicateur__valeur">{tableau.data.courant.heures_reservees.toLocaleString("fr-FR")} h</span>
              <Evolution courant={tableau.data.courant.heures_reservees} precedent={tableau.data.precedent.heures_reservees} format={(v) => `${v.toLocaleString("fr-FR")} h`} />
            </li>
            <li className="indicateur">
              Usagers actifs<span className="indicateur__valeur">{tableau.data.courant.usagers_actifs}</span>
              <Evolution courant={tableau.data.courant.usagers_actifs} precedent={tableau.data.precedent.usagers_actifs} format={String} />
            </li>
            <li className="indicateur">
              Recettes nettes<span className="indicateur__valeur">{euros(tableau.data.courant.recettes_nettes)}</span>
              <Evolution courant={tableau.data.courant.recettes_nettes} precedent={tableau.data.precedent.recettes_nettes} format={euros} />
            </li>
            {tableau.data.courant.concours_en_nature !== null ? (
              <li className="indicateur">
                Concours en nature<span className="indicateur__valeur">{euros(tableau.data.courant.concours_en_nature)}</span>
                <Evolution courant={tableau.data.courant.concours_en_nature} precedent={tableau.data.precedent.concours_en_nature ?? 0} format={euros} />
              </li>
            ) : null}
          </ul>
          <figure>
            <figcaption>Heures réservées par mois</figcaption>
            <ul className="barres" aria-hidden="true">
              {tableau.data.mois.map((m) => (
                <li key={m.mois}>
                  <span>{MOIS[m.mois - 1]}</span>
                  <span className="barres__barre" style={{ width: `${(100 * m.heures) / max}%` }} />
                  <span>{m.heures} h</span>
                </li>
              ))}
            </ul>
            <Tableau
              legende="Heures réservées par mois"
              lignes={tableau.data.mois}
              cleLigne={(m) => m.mois}
              colonnes={[
                { cle: "mois", titre: "Mois", rendu: (m) => MOIS[m.mois - 1] ?? String(m.mois) },
                { cle: "heures", titre: "Heures", rendu: (m) => `${m.heures} h`, valeurTri: (m) => m.heures },
                ...(tableau.data.mois.some((m) => m.recettes_nettes !== null)
                  ? [{ cle: "recettes", titre: "Recettes nettes", rendu: (m: { recettes_nettes: number | null }) => euros(m.recettes_nettes ?? 0), valeurTri: (m: { recettes_nettes: number | null }) => m.recettes_nettes ?? 0 }]
                  : []),
              ]}
            />
          </figure>
        </>
      ) : null}
    </Page>
  );
}
