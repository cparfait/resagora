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

// Capacité horaire de référence de la vue multi-sites (taux d'occupation) : inchangée.
const HEURE_MIN = 7;
const HEURE_MAX = 24;
const PAS_MINUTES = 15;

/** Plage horaire de la vue semaine : 8 h – 22 h, élargie aux séances affichées. La grille occupe la hauteur
 * disponible de la fenêtre (planning sans défilement, DESIGN.md) : positions et hauteurs en pourcentage. */
interface Plage {
  min: number;
  max: number;
}

export function plageHoraire(seances: SeancePlanning[]): Plage {
  let min = 8;
  let max = 22;
  for (const s of seances) {
    const debut = new Date(s.debut);
    const fin = new Date(s.fin);
    min = Math.min(min, Math.floor(minutesDuJour(debut) / 60));
    max = Math.max(max, memeJour(debut, fin) ? Math.ceil(minutesDuJour(fin) / 60) : 24);
  }
  return { min: Math.max(0, min), max: Math.min(24, max) };
}

function classeSeance(s: SeancePlanning, coloration: Coloration): string {
  const motif = STATUTS[s.statut]?.motif ?? "plein";
  const couleur = coloration === "statut" ? `statut-${s.statut}` : (COULEURS_TYPE[s.type_usager] ?? "type-autre");
  return `seance ${couleur} motif-${motif}${s.signalement ? " seance--signalee" : ""}`;
}

/** Complément lu par les lecteurs d'écran : le nom accessible commence par le texte visible (RGAA 7.1, WCAG 2.5.3). */
function complementSeance(s: SeancePlanning): string {
  return `, ${s.espace_nom}, ${jourLong(s.debut)}, ${STATUTS[s.statut]?.libelle ?? s.statut}${s.signalement ? `, à traiter : ${s.signalement}` : ""}`;
}

function Pastille({
  seance,
  coloration,
  onOuvrir,
  style,
  glissable,
  carte = false,
}: {
  seance: SeancePlanning;
  coloration: Coloration;
  onOuvrir: (s: SeancePlanning) => void;
  style?: CSSProperties;
  glissable: boolean;
  /** Carte dans le flux (chronologie) : horaire, usager et statut en clair, au lieu d'un bloc positionné. */
  carte?: boolean;
}) {
  const glisser = (e: DragEvent<HTMLButtonElement>) => {
    e.dataTransfer.setData("text/plain", String(seance.id));
    e.dataTransfer.effectAllowed = "move";
  };
  return (
    <button type="button" className={cn(classeSeance(seance, coloration), carte && "seance--carte")} style={style} draggable={glissable} onDragStart={glisser} onClick={() => onOuvrir(seance)}>
      <span className="seance__heure">
        {heure(seance.debut)}–{heure(seance.fin)}
      </span>
      <span className="seance__titre">{seance.usager}</span>
      <span className="sr-only">{complementSeance(seance)}</span>
      {carte ? (
        <span aria-hidden="true" className="seance__statut">
          {STATUTS[seance.statut]?.libelle ?? seance.statut}
        </span>
      ) : null}
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

function instantDepuisPosition(jour: Date, plage: Plage, e: DragEvent<HTMLDivElement>): Date {
  const zone = e.currentTarget.getBoundingClientRect();
  const portee = (plage.max - plage.min) * 60;
  const minutes = Math.max(0, Math.round((((e.clientY - zone.top) / zone.height) * portee) / PAS_MINUTES) * PAS_MINUTES);
  const r = new Date(jour);
  r.setHours(plage.min, 0, 0, 0);
  r.setMinutes(r.getMinutes() + minutes);
  return r;
}

function Graduations({ plage }: { plage: Plage }) {
  return (
    <div className="grille__heures" aria-hidden="true">
      <div className="grille__heures-espace" />
      <div className="grille__heures-liste">
        {Array.from({ length: plage.max - plage.min }, (_, i) => (
          <div key={i} className="grille__heure">
            {plage.min + i} h
          </div>
        ))}
      </div>
    </div>
  );
}

function Lignes({ plage }: { plage: Plage }) {
  return (
    <div className="grille__lignes" aria-hidden="true">
      {Array.from({ length: plage.max - plage.min }, (_, i) => (
        <div key={i} />
      ))}
    </div>
  );
}

/** Séances simultanées d'un même jour côte à côte : chaque groupe de séances qui se chevauchent est réparti en
 * sous-colonnes (partition gloutonne), une séance isolée garde toute la largeur. */
function couloirs(seances: SeancePlanning[]): Map<number, { rang: number; nombre: number }> {
  const places = new Map<number, { rang: number; nombre: number }>();
  let groupe: { id: number; rang: number }[] = [];
  let fins: number[] = [];
  let finGroupe = -Infinity;
  const clore = () => {
    for (const { id, rang } of groupe) places.set(id, { rang, nombre: Math.max(1, fins.length) });
    groupe = [];
    fins = [];
  };
  for (const s of seances.toSorted((a, b) => new Date(a.debut).getTime() - new Date(b.debut).getTime())) {
    const debut = new Date(s.debut).getTime();
    const fin = new Date(s.fin).getTime();
    if (debut >= finGroupe) clore();
    const libre = fins.findIndex((f) => f <= debut);
    const rang = libre === -1 ? fins.length : libre;
    fins[rang] = fin;
    groupe.push({ id: s.id, rang });
    finGroupe = groupe.length === 1 ? fin : Math.max(finGroupe, fin);
  }
  clore();
  return places;
}

function positionVerticale(s: SeancePlanning, plage: Plage, rang = 0, nombre = 1): CSSProperties {
  const debut = new Date(s.debut);
  const fin = new Date(s.fin);
  const portee = (plage.max - plage.min) * 60;
  const haut = ((minutesDuJour(debut) - plage.min * 60) / portee) * 100;
  const duree = Math.max(PAS_MINUTES, (fin.getTime() - debut.getTime()) / 60000);
  return {
    top: `${Math.max(0, haut)}%`,
    height: `${(duree / portee) * 100}%`,
    left: `calc(${(100 * rang) / nombre}% + 1px)`,
    width: `calc(${100 / nombre}% - 2px)`,
    right: "auto",
  };
}

export function VueSemaine({ seances, debut, coloration, onOuvrir, onDeposer, jours = 7 }: Commun & { jours?: number }) {
  const colonnes = Array.from({ length: jours }, (_, i) => ajouterJours(debut, i));
  const plage = plageHoraire(seances);
  return (
    // Zone qui peut défiler horizontalement sur petit écran : focalisable pour défiler au clavier (WCAG 2.1.1).
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="grille" role="group" tabIndex={0} aria-label={`Planning du ${jourLong(colonnes[0] ?? debut)}${jours > 1 ? ` au ${jourLong(colonnes[colonnes.length - 1] ?? debut)}` : ""}`}>
      <Graduations plage={plage} />
      {colonnes.map((jour) => {
        const duJour = seances.filter((s) => memeJour(new Date(s.debut), jour));
        const places = couloirs(duJour);
        return (
          <div key={isoJour(jour)} className="grille__colonne">
            <div className="grille__entete">{jourCourt(jour)}</div>
            <div className="grille__corps" {...zoneDepot(onDeposer, seances, (e) => ({ debut: instantDepuisPosition(jour, plage, e) }))}>
              <Lignes plage={plage} />
              {duJour.map((s) => (
                <Pastille key={s.id} seance={s} coloration={coloration} onOuvrir={onOuvrir} style={positionVerticale(s, plage, places.get(s.id)?.rang, places.get(s.id)?.nombre)} glissable={Boolean(onDeposer)} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}

/** Initiales d'un espace pour la vignette de la chronologie (« Gymnase Gabriel Péri » → « GP »). */
function initialesEspace(nom: string): string {
  const mots = nom.split(/[\s-]+/).filter((mot) => /^[A-ZÀ-Ý0-9]/u.test(mot));
  return (mots.length > 1 ? mots.slice(-2) : mots).map((mot) => mot[0]).join("") || "?";
}

/** Chronologie par espace façon Mariloo : une ligne par espace (vignette, nom, capacité), une colonne par jour,
 * les séances du jour en cartes empilées. Déposer une carte dans une autre case garde son horaire et change le jour
 * et l'espace (contrôle serveur avant déplacement, PLA-02). */
export function VueChronologie({ seances, debut, coloration, onOuvrir, onDeposer, espaces, jours = 7 }: Commun & { espaces: Espace[]; jours?: number }) {
  const colonnes = Array.from({ length: jours }, (_, i) => ajouterJours(debut, i));
  const gabarit: CSSProperties = { gridTemplateColumns: `minmax(11rem, 14rem) repeat(${jours}, minmax(7.5rem, 1fr))` };
  return (
    // Zone qui défile horizontalement : focalisable pour défiler au clavier (WCAG 2.1.1, règle axe scrollable-region-focusable).
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="chronologie" role="group" aria-label="Chronologie par espace" tabIndex={0}>
      <div className="chronologie__ligne chronologie__ligne--entete" style={gabarit}>
        <div className="chronologie__espace">Espace</div>
        {colonnes.map((j) => (
          <div key={isoJour(j)} className="chronologie__jour">
            {jourCourt(j)}
          </div>
        ))}
      </div>
      {espaces.map((espace) => {
        const lignes = seances.filter((s) => s.espace === espace.id);
        return (
          <div key={espace.id} className="chronologie__ligne" style={gabarit}>
            <div className="chronologie__espace">
              <span aria-hidden="true" className="chronologie__vignette">
                {initialesEspace(espace.nom)}
              </span>
              <span className="chronologie__identite">
                <span className="chronologie__nom">{espace.nom}</span>
                {espace.capacite ? <span className="chronologie__capacite">{espace.capacite} personnes</span> : null}
              </span>
            </div>
            {colonnes.map((jour) => {
              const duJour = lignes.filter((s) => memeJour(new Date(s.debut), jour)).toSorted((a, b) => a.debut.localeCompare(b.debut));
              return (
                <div
                  key={isoJour(jour)}
                  className="chronologie__case"
                  {...zoneDepot(onDeposer, seances, (e) => {
                    const deplacee = seances.find((s) => String(s.id) === e.dataTransfer.getData("text/plain"));
                    if (!deplacee) return null;
                    const origine = new Date(deplacee.debut);
                    const r = new Date(jour);
                    r.setHours(origine.getHours(), origine.getMinutes(), 0, 0);
                    return { espace: espace.id, debut: r };
                  })}
                >
                  {duJour.map((s) => (
                    <Pastille key={s.id} seance={s} coloration={coloration} onOuvrir={onOuvrir} glissable={Boolean(onDeposer)} carte />
                  ))}
                </div>
              );
            })}
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
              <td colSpan={7} className="p-8 text-center text-encre-douce">
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
