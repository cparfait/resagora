/** Tableau de bord façon Mariloo : chiffres-clés et deux graphiques sobres (guide de visualisation du projet).
 * - Occupation par espace : grandeur à comparer → barres horizontales triées, une seule teinte (vert de la charte),
 *   valeur au bout de la barre.
 * - Répartition des heures par type d'usager : part du tout → une barre empilée à 100 %, palette catégorielle validée
 *   (validate_palette.js : 4 premiers emplacements, toutes vérifications passées ; contraste < 3:1 de l'aqua et du
 *   jaune compensé par les étiquettes et le tableau), couleur attachée au type, jamais au rang.
 * Les info-bulles complètent sans rien cacher : chaque valeur est aussi dans l'étiquette ou dans le tableau des données. */
import { useState, type ReactNode } from "react";
import { Tableau } from "../../ui/Tableau";

export interface LigneOccupation {
  espace: number;
  espace_nom: string;
  site_nom: string;
  premier_niveau: boolean;
  minutes_reservees: number;
  minutes_ouverture: number;
  taux: number;
}
export interface Part {
  cle: string;
  libelle: string;
  minutes: number;
  part: number;
}

// Ordre fixe des types d'usagers → emplacements de la palette catégorielle (la couleur suit le type).
const COULEURS_TYPES: Record<string, string> = {
  association: "var(--color-serie-1)",
  entreprise: "var(--color-serie-2)",
  particulier: "var(--color-serie-3)",
  service_municipal: "var(--color-serie-4)",
  ecole: "var(--color-serie-5)",
  autre_collectivite: "var(--color-serie-6)",
};
const COULEUR_AUTRE = "var(--color-serie-7)";

export const heures = (minutes: number) => `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(minutes / 60)} h`;
export const pourcent = (centiemes: number) => `${new Intl.NumberFormat("fr-FR", { maximumFractionDigits: 0 }).format(centiemes / 100)} %`;

export function CarteGraphique({ titre, sousTitre, children, donnees }: { titre: string; sousTitre: string; children: ReactNode; donnees: ReactNode }) {
  return (
    <section className="rounded-lg bg-carte p-5 shadow-carte" aria-label={titre}>
      <h2 className="m-0 text-base font-semibold text-encre">{titre}</h2>
      <p className="mt-0.5 mb-4 text-[0.85rem] text-encre-douce">{sousTitre}</p>
      {children}
      <details className="mt-4 text-petit">
        <summary className="inline-flex min-h-11 cursor-pointer items-center font-medium text-vert">Voir les données</summary>
        {donnees}
      </details>
    </section>
  );
}

function InfoBulle({ texte }: { texte: string }) {
  return (
    <span role="tooltip" className="pointer-events-none absolute -top-9 left-1/2 z-10 -translate-x-1/2 rounded-md bg-encre px-2.5 py-1 text-[0.8rem] font-semibold whitespace-nowrap text-blanc shadow-flottant">
      {texte}
    </span>
  );
}

export function BarresOccupation({ lignes }: { lignes: LigneOccupation[] }) {
  const [survol, setSurvol] = useState<number | null>(null);
  const triees = lignes.toSorted((a, b) => b.taux - a.taux).slice(0, 8);
  return (
    <ul className="m-0 flex list-none flex-col gap-2.5 p-0" aria-hidden="true">
      {triees.map((l) => (
        <li key={l.espace} className="grid grid-cols-[minmax(0,13rem)_minmax(0,1fr)_3rem] items-center gap-3 text-[0.85rem]">
          <span className="truncate text-encre" title={l.espace_nom}>
            {l.espace_nom}
          </span>
          <span className="relative h-3.5 rounded-r-[4px] bg-fond" onPointerEnter={() => setSurvol(l.espace)} onPointerLeave={() => setSurvol(null)}>
            <span className="block h-full rounded-r-[4px] bg-vert transition-[filter] hover:brightness-125" style={{ width: `${Math.min(100, l.taux / 100)}%` }} />
            {survol === l.espace ? <InfoBulle texte={`${heures(l.minutes_reservees)} sur ${heures(l.minutes_ouverture)} d'ouverture`} /> : null}
          </span>
          <span className="text-right font-semibold text-encre tabular-nums">{pourcent(l.taux)}</span>
        </li>
      ))}
    </ul>
  );
}

export function TableauOccupation({ lignes }: { lignes: LigneOccupation[] }) {
  return (
    <Tableau<LigneOccupation>
      legende="Occupation par espace"
      lignes={lignes.toSorted((a, b) => b.taux - a.taux)}
      cleLigne={(l) => l.espace}
      colonnes={[
        { cle: "espace", titre: "Espace", rendu: (l) => l.espace_nom },
        { cle: "site", titre: "Site", rendu: (l) => l.site_nom },
        { cle: "reservees", titre: "Heures réservées", rendu: (l) => heures(l.minutes_reservees) },
        { cle: "ouverture", titre: "Heures d'ouverture", rendu: (l) => heures(l.minutes_ouverture) },
        { cle: "taux", titre: "Taux", rendu: (l) => pourcent(l.taux) },
      ]}
    />
  );
}

export function BarreRepartition({ parts }: { parts: Part[] }) {
  const [survol, setSurvol] = useState<string | null>(null);
  const visibles = parts.filter((p) => p.minutes > 0);
  return (
    <div aria-hidden="true">
      <div className="flex h-4 gap-[2px]">
        {visibles.map((p, rang) => (
          <span
            key={p.cle}
            className={`relative h-full ${rang === 0 ? "rounded-l-[4px]" : ""} ${rang === visibles.length - 1 ? "rounded-r-[4px]" : ""}`}
            style={{ width: `${p.part / 100}%`, background: COULEURS_TYPES[p.cle] ?? COULEUR_AUTRE }}
            onPointerEnter={() => setSurvol(p.cle)}
            onPointerLeave={() => setSurvol(null)}
          >
            {survol === p.cle ? <InfoBulle texte={`${p.libelle} : ${heures(p.minutes)} (${pourcent(p.part)})`} /> : null}
          </span>
        ))}
      </div>
      <ul className="mt-4 mb-0 grid list-none grid-cols-2 gap-x-4 gap-y-2 p-0 text-[0.85rem]">
        {visibles.map((p) => (
          <li key={p.cle} className="flex items-center gap-2">
            <span className="size-3 shrink-0 rounded-[3px]" style={{ background: COULEURS_TYPES[p.cle] ?? COULEUR_AUTRE }} />
            <span className="text-encre">{p.libelle}</span>
            <span className="ml-auto font-semibold text-encre tabular-nums">{pourcent(p.part)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function TableauRepartition({ parts }: { parts: Part[] }) {
  return (
    <Tableau<Part>
      legende="Répartition des heures par type d'usager"
      lignes={parts}
      cleLigne={(p) => p.cle}
      colonnes={[
        { cle: "type", titre: "Type d'usager", rendu: (p) => p.libelle },
        { cle: "heures", titre: "Heures", rendu: (p) => heures(p.minutes) },
        { cle: "part", titre: "Part", rendu: (p) => pourcent(p.part) },
      ]}
    />
  );
}
