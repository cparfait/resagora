/**
 * Vues du planning (PLA-01) : semaine, jour, mois, chronologie par espace, occupation multi-sites, liste.
 * Le glisser-déposer (PLA-02) déclenche un contrôle côté serveur avant tout déplacement ; la vue liste
 * et le bouton « Déplacer… » offrent la même fonction au clavier.
 */
import { BASE_BOUTON, CLASSES_BOUTON } from "../../../ui/Bouton";
import { cn } from "../../../ui/cn";
import type { CSSProperties, DragEvent, KeyboardEvent } from "react";
import type { Espace, SeancePlanning, Site } from "../../../api/types";
import { ajouterJours, COULEURS_TYPE, heure, isoJour, jourCourt, jourLong, memeJour, minutesDuJour, STATUTS, TYPES_USAGER } from "../../../ui/metier";
import { Badge } from "../../../ui/Badge";

export type Mode = "jour" | "semaine" | "mois" | "chronologie" | "multi_sites" | "liste";
export type Coloration = "statut" | "type_usager";

export interface Deplacement {
  seance: SeancePlanning;
  espace: number;
  debut: Date;
  fin: Date;
}

interface Commun {
  seances: SeancePlanning[];
  debut: Date;
  coloration: Coloration;
  onOuvrir: (seance: SeancePlanning) => void;
  onDeposer?: (deplacement: Deplacement) => void;
}

const HEURE_MIN = 7;
const HEURE_MAX = 24;
const PAS_MINUTES = 15;
const HAUTEUR_HEURE = 48;

function classeSeance(s: SeancePlanning, coloration: Coloration): string {
  const motif = STATUTS[s.statut]?.motif ?? "plein";
  const couleur = coloration === "statut" ? `statut-${s.statut}` : (COULEURS_TYPE[s.type_usager] ?? "type-autre");
  return `seance ${couleur} motif-${motif}${s.signalement ? " seance--signalee" : ""}`;
}

/** Complément lu par les lecteurs d'écran : le nom accessible commence par le texte visible (RGAA 7.1, WCAG 2.5.3). */
function complementSeance(s: SeancePlanning): string {
  return `, ${s.espace_nom}, ${jourLong(s.debut)}, ${STATUTS[s.statut]?.libelle ?? s.statut}${s.signalement ? `, à traiter : ${s.signalement}` : ""}`;
}

function Pastille({ seance, coloration, onOuvrir, style, glissable }: { seance: SeancePlanning; coloration: Coloration; onOuvrir: (s: SeancePlanning) => void; style?: CSSProperties; glissable: boolean }) {
  const glisser = (e: DragEvent<HTMLButtonElement>) => {
    e.dataTransfer.setData("text/plain", String(seance.id));
    e.dataTransfer.effectAllowed = "move";
  };
  return (
    <button type="button" className={classeSeance(seance, coloration)} style={style} draggable={glissable} onDragStart={glisser} onClick={() => onOuvrir(seance)}>
      <span className="seance__heure">
        {heure(seance.debut)}–{heure(seance.fin)}
      </span>
      <span className="seance__titre">{seance.usager}</span>
      <span className="sr-only">{complementSeance(seance)}</span>
      {seance.signalement ? <span aria-hidden="true"> ⚠</span> : null}
    </button>
  );
}

function zoneDepot(onDeposer: Commun["onDeposer"], seances: SeancePlanning[], calculer: (e: DragEvent<HTMLDivElement>) => { espace?: number; debut: Date } | null) {
  if (!onDeposer) return {};
  return {
    onDragOver: (e: DragEvent<HTMLDivElement>) => e.preventDefault(),
    onDrop: (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      const seance = seances.find((s) => String(s.id) === e.dataTransfer.getData("text/plain"));
      const cible = calculer(e);
      if (!seance || !cible) return;
      const duree = new Date(seance.fin).getTime() - new Date(seance.debut).getTime();
      onDeposer({ seance, espace: cible.espace ?? seance.espace, debut: cible.debut, fin: new Date(cible.debut.getTime() + duree) });
    },
  };
}

function instantDepuisPosition(jour: Date, e: DragEvent<HTMLDivElement>): Date {
  const zone = e.currentTarget.getBoundingClientRect();
  const minutes = Math.max(0, Math.round(((e.clientY - zone.top) / HAUTEUR_HEURE) * 60 / PAS_MINUTES) * PAS_MINUTES);
  const r = new Date(jour);
  r.setHours(HEURE_MIN, 0, 0, 0);
  r.setMinutes(r.getMinutes() + minutes);
  return r;
}

function Graduations() {
  return (
    <div className="grille__heures" aria-hidden="true">
      {Array.from({ length: HEURE_MAX - HEURE_MIN }, (_, i) => (
        <div key={i} className="grille__heure" style={{ height: HAUTEUR_HEURE }}>
          {HEURE_MIN + i} h
        </div>
      ))}
    </div>
  );
}

function positionVerticale(s: SeancePlanning): CSSProperties {
  const debut = new Date(s.debut);
  const fin = new Date(s.fin);
  const haut = ((minutesDuJour(debut) - HEURE_MIN * 60) / 60) * HAUTEUR_HEURE;
  const duree = Math.max(PAS_MINUTES, (fin.getTime() - debut.getTime()) / 60000);
  return { top: Math.max(0, haut), height: Math.max(18, (duree / 60) * HAUTEUR_HEURE - 2) };
}

export function VueSemaine({ seances, debut, coloration, onOuvrir, onDeposer, jours = 7 }: Commun & { jours?: number }) {
  const colonnes = Array.from({ length: jours }, (_, i) => ajouterJours(debut, i));
  return (
    <div className="grille" role="group" aria-label={`Planning du ${jourLong(colonnes[0] ?? debut)}${jours > 1 ? ` au ${jourLong(colonnes[colonnes.length - 1] ?? debut)}` : ""}`}>
      <Graduations />
      {colonnes.map((jour) => {
        const duJour = seances.filter((s) => memeJour(new Date(s.debut), jour));
        return (
          <div key={isoJour(jour)} className="grille__colonne">
            <div className="grille__entete">{jourCourt(jour)}</div>
            <div className="grille__corps" style={{ height: (HEURE_MAX - HEURE_MIN) * HAUTEUR_HEURE }} {...zoneDepot(onDeposer, seances, (e) => ({ debut: instantDepuisPosition(jour, e) }))}>
              {duJour.map((s) => (
                <Pastille key={s.id} seance={s} coloration={coloration} onOuvrir={onOuvrir} style={positionVerticale(s)} glissable={Boolean(onDeposer)} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function VueChronologie({ seances, debut, coloration, onOuvrir, onDeposer, espaces, jours = 7 }: Commun & { espaces: Espace[]; jours?: number }) {
  const colonnes = Array.from({ length: jours }, (_, i) => ajouterJours(debut, i));
  const largeurJour = 100 / jours;
  return (
    <div className="chronologie" role="group" aria-label="Chronologie par espace">
      <div className="chronologie__ligne chronologie__ligne--entete">
        <div className="chronologie__espace">Espace</div>
        <div className="chronologie__piste">
          {colonnes.map((j) => (
            <div key={isoJour(j)} className="chronologie__jour" style={{ width: `${largeurJour}%` }}>
              {jourCourt(j)}
            </div>
          ))}
        </div>
      </div>
      {espaces.map((espace) => {
        const lignes = seances.filter((s) => s.espace === espace.id);
        return (
          <div key={espace.id} className="chronologie__ligne">
            <div className="chronologie__espace">{espace.nom}</div>
            <div
              className="chronologie__piste"
              {...zoneDepot(onDeposer, seances, (e) => {
                const zone = e.currentTarget.getBoundingClientRect();
                const ratio = (e.clientX - zone.left) / zone.width;
                const minutes = Math.round((ratio * jours * (HEURE_MAX - HEURE_MIN) * 60) / PAS_MINUTES) * PAS_MINUTES;
                const jour = Math.floor(minutes / ((HEURE_MAX - HEURE_MIN) * 60));
                const r = ajouterJours(debut, jour);
                r.setHours(HEURE_MIN, 0, 0, 0);
                r.setMinutes(minutes - jour * (HEURE_MAX - HEURE_MIN) * 60);
                return { espace: espace.id, debut: r };
              })}
            >
              {lignes.map((s) => {
                const d = new Date(s.debut);
                const f = new Date(s.fin);
                const indexJour = Math.floor((new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime() - debut.getTime()) / 86400000);
                const portee = (HEURE_MAX - HEURE_MIN) * 60;
                const gauche = indexJour * largeurJour + (Math.max(0, minutesDuJour(d) - HEURE_MIN * 60) / portee) * largeurJour;
                const largeur = Math.max(0.6, (((f.getTime() - d.getTime()) / 60000) / portee) * largeurJour);
                return <Pastille key={s.id} seance={s} coloration={coloration} onOuvrir={onOuvrir} style={{ left: `${gauche}%`, width: `${largeur}%` }} glissable={Boolean(onDeposer)} />;
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function VueMois({ seances, debut, coloration, onOuvrir, onJour }: Commun & { onJour: (jour: Date) => void }) {
  const premier = new Date(debut.getFullYear(), debut.getMonth(), 1);
  const decalage = (premier.getDay() + 6) % 7;
  const cases = Array.from({ length: 42 }, (_, i) => ajouterJours(premier, i - decalage));
  return (
    <table className="mois">
      <caption className="sr-only">Planning du mois</caption>
      <thead>
        <tr>
          {["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"].map((j) => (
            <th key={j} scope="col">
              {j}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {Array.from({ length: 6 }, (_, semaine) => (
          <tr key={semaine}>
            {cases.slice(semaine * 7, semaine * 7 + 7).map((jour) => {
              const duJour = seances.filter((s) => memeJour(new Date(s.debut), jour));
              return (
                <td key={isoJour(jour)} className={jour.getMonth() !== premier.getMonth() ? "mois__hors" : undefined}>
                  <button type="button" className="mois__numero" onClick={() => onJour(jour)} aria-label={`Voir le ${jourLong(jour)} (${duJour.length} séances)`}>
                    {jour.getDate()}
                  </button>
                  <ul className="mois__seances">
                    {duJour.slice(0, 4).map((s) => (
                      <li key={s.id}>
                        <Pastille seance={s} coloration={coloration} onOuvrir={onOuvrir} glissable={false} />
                      </li>
                    ))}
                    {duJour.length > 4 ? <li className="mois__plus">+ {duJour.length - 4} autres</li> : null}
                  </ul>
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function VueMultiSites({ seances, debut, sites, espaces, jours = 7 }: Pick<Commun, "seances" | "debut"> & { sites: Site[]; espaces: Espace[]; jours?: number }) {
  const colonnes = Array.from({ length: jours }, (_, i) => ajouterJours(debut, i));
  const capaciteJour = (HEURE_MAX - HEURE_MIN) * 60;
  return (
    <table className="tableau multi-sites">
      <caption>Taux d'occupation horaire des espaces par site et par jour ({HEURE_MIN} h – {HEURE_MAX} h)</caption>
      <thead>
        <tr>
          <th scope="col">Site</th>
          {colonnes.map((j) => (
            <th key={isoJour(j)} scope="col">
              {jourCourt(j)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sites.map((site) => {
          const espacesSite = espaces.filter((e) => e.site === site.id && !e.parent);
          return (
            <tr key={site.id}>
              <th scope="row">
                {site.nom} <span className="texte-doux">({espacesSite.length} espaces)</span>
              </th>
              {colonnes.map((jour) => {
                const minutes = seances
                  .filter((s) => s.site === site.id && memeJour(new Date(s.debut), jour) && STATUTS[s.statut]?.motif === "plein")
                  .reduce((total, s) => total + (new Date(s.fin).getTime() - new Date(s.debut).getTime()) / 60000, 0);
                const taux = espacesSite.length ? Math.min(100, Math.round((minutes / (capaciteJour * espacesSite.length)) * 100)) : 0;
                return (
                  <td key={isoJour(jour)}>
                    <span className="jauge" aria-hidden="true">
                      <span className="jauge__remplissage" style={{ width: `${taux}%` }} />
                    </span>
                    {taux} %
                  </td>
                );
              })}
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function VueListe({ seances, onOuvrir }: Pick<Commun, "seances" | "onOuvrir">) {
  const touche = (e: KeyboardEvent<HTMLTableRowElement>, s: SeancePlanning) => {
    if (e.key === "Enter") onOuvrir(s);
  };
  return (
    <div className="tableau-conteneur">
      <table className="tableau">
        <caption className="sr-only">Liste des séances de la période</caption>
        <thead>
          <tr>
            <th scope="col">Date</th>
            <th scope="col">Horaire</th>
            <th scope="col">Espace</th>
            <th scope="col">Usager</th>
            <th scope="col">Type</th>
            <th scope="col">Statut</th>
            <th scope="col">
              <span className="sr-only">Actions</span>
            </th>
          </tr>
        </thead>
        <tbody>
          {seances.length === 0 ? (
            <tr>
              <td colSpan={7} className="tableau__vide">
                Aucune séance sur cette période.
              </td>
            </tr>
          ) : (
            seances.map((s) => (
              <tr key={s.id} onKeyDown={(e) => touche(e, s)}>
                <td>{jourLong(s.debut)}</td>
                <td>
                  {heure(s.debut)} – {heure(s.fin)}
                </td>
                <td>{s.espace_nom}</td>
                <td>
                  {s.usager}
                  <br />
                  <span className="texte-doux">{s.numero}</span>
                </td>
                <td>{TYPES_USAGER[s.type_usager] ?? s.type_usager}</td>
                <td>
                  <Badge libelle={STATUTS[s.statut]?.libelle ?? s.statut} ton={STATUTS[s.statut]?.ton ?? "neutre"} />
                  {s.signalement ? <Badge libelle={`À traiter : ${s.signalement}`} ton="attention" /> : null}
                </td>
                <td>
                  <button type="button" className={cn(BASE_BOUTON, CLASSES_BOUTON.lien)} onClick={() => onOuvrir(s)}>
                    Ouvrir
                  </button>
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export function Legende({ coloration }: { coloration: Coloration }) {
  const entrees = coloration === "statut" ? Object.entries(STATUTS).map(([cle, v]) => [`statut-${cle} motif-${v.motif}`, v.libelle]) : Object.entries(TYPES_USAGER).map(([cle, v]) => [COULEURS_TYPE[cle] ?? "", v]);
  return (
    <ul className="legende" aria-label="Légende des couleurs">
      {entrees.map(([classe, libelle]) => (
        <li key={libelle}>
          <span className={`legende__pastille ${classe}`} aria-hidden="true" />
          {libelle}
        </li>
      ))}
    </ul>
  );
}
