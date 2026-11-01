/** PER-02, PER-05, PER-07, DSH-02 : vue d'ensemble de la semaine du planning du personnel.
 * - « Par agent » : qui est où (site et horaires de chaque vacation, absences) et heures planifiées de la semaine,
 *   comparées à la durée de référence de l'agent ; un clic sur l'agent ouvre son planning modifiable.
 * - « Par site » : les sites où une présence est requise (réglée par salle, REF-04), leurs vacations (agent ou « à
 *   pourvoir ») et les besoins encore non couverts.
 * Vrais tableaux HTML (en-têtes de ligne et de colonne lus par les lecteurs d'écran) ; la couleur double un texte. */
import { Building2, CalendarClock, CircleAlert, Clock, Users } from "lucide-react";
import type { ReactNode } from "react";
import { Avatar } from "../../ui/Avatar";
import { Badge } from "../../ui/Badge";
import { Chiffre } from "../../ui/Chiffre";
import { cn } from "../../ui/cn";
import { heure, isoJour, jourCourt, jourLong } from "../../ui/metier";
import { NATURES_ABSENCE } from "./Personnel";
import { dureeLisible, nomAgent, PLAFOND_HEBDO_MINUTES, STATUTS_VACATION, type AbsenceAgent, type AgentPlanning, type Besoin, type Vacation } from "./vacation";

const TONS: Record<string, string> = {
  planifiee: "border-vert bg-vert-pale",
  a_revoir: "border-attention bg-attention-fond",
  a_pourvoir: "border-danger bg-danger-fond",
};

const enCours = (vacations: Vacation[]) => vacations.filter((v) => v.statut !== "annulee");
const leJour = (instant: string, jour: Date) => isoJour(new Date(instant)) === isoJour(jour);
const somme = (vacations: Vacation[]) => vacations.reduce((total, v) => total + v.duree_minutes, 0);

/** Minutes planifiées par agent sur les vacations affichées (hors annulées). */
export function minutesParAgent(vacations: Vacation[]): Map<number, number> {
  const minutes = new Map<number, number>();
  for (const v of enCours(vacations)) if (v.agent !== null) minutes.set(v.agent, (minutes.get(v.agent) ?? 0) + v.duree_minutes);
  return minutes;
}

export function ChiffresSemaine({ vacations, agents }: { vacations: Vacation[]; agents: number }) {
  const actives = enCours(vacations);
  const affectees = actives.filter((v) => v.agent !== null);
  const aPourvoir = actives.filter((v) => v.agent === null);
  const aRevoir = actives.filter((v) => v.statut === "a_revoir");
  return (
    <div className="mb-6 grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
      <Chiffre icone={Users} libelle="Agents en poste" valeur={`${minutesParAgent(vacations).size} / ${agents}`} detail="avec au moins une vacation" />
      <Chiffre icone={Clock} libelle="Heures planifiées" valeur={dureeLisible(somme(affectees))} detail={`${affectees.length} vacation${affectees.length > 1 ? "s" : ""} affectée${affectees.length > 1 ? "s" : ""}`} />
      <Chiffre icone={CircleAlert} libelle="Vacations à pourvoir" valeur={String(aPourvoir.length)} detail={`${dureeLisible(somme(aPourvoir))} sans agent`} />
      <Chiffre icone={CalendarClock} libelle="Vacations à revoir" valeur={String(aRevoir.length)} detail="réservations modifiées depuis" />
    </div>
  );
}

function Pastille({ vacation, libelle, complement, onOuvrir }: { vacation: Vacation; libelle: string; complement: string; onOuvrir: (v: Vacation) => void }) {
  return (
    <button
      type="button"
      onClick={() => onOuvrir(vacation)}
      className={cn(
        "flex w-full min-w-0 cursor-pointer flex-col items-start gap-0.5 rounded-md border-0 border-l-[3px] border-solid px-2 py-1.5 text-left font-sans text-[0.78rem] leading-tight text-encre transition-[filter] hover:brightness-95",
        TONS[vacation.statut] ?? TONS.planifiee,
      )}
    >
      <span className="font-semibold tabular-nums">
        {heure(vacation.debut)}–{heure(vacation.fin)}
      </span>
      <span className="max-w-full truncate" title={libelle}>
        {libelle}
      </span>
      {vacation.statut !== "planifiee" ? <span className="text-[0.72rem] font-semibold">{STATUTS_VACATION[vacation.statut]?.libelle ?? vacation.statut}</span> : null}
      <span className="sr-only">{complement}</span>
    </button>
  );
}

function Heures({ minutes, reference }: { minutes: number; reference: number }) {
  const depasse = minutes > PLAFOND_HEBDO_MINUTES;
  return (
    <div>
      <p className="m-0 flex flex-wrap items-baseline justify-between gap-x-2">
        <span className="text-base font-semibold text-encre tabular-nums">{dureeLisible(minutes)}</span>
        <span className="text-[0.75rem] text-encre-douce">sur {dureeLisible(reference)}</span>
      </p>
      <span aria-hidden="true" className="mt-1.5 block h-1.5 rounded-full bg-fond">
        <span className={cn("block h-full rounded-full", depasse ? "bg-danger" : "bg-vert")} style={{ width: `${Math.min(100, reference ? (minutes / reference) * 100 : 0)}%` }} />
      </span>
      {depasse ? (
        <span className="mt-1.5 inline-block">
          <Badge libelle="Plus de 48 h" ton="danger" />
        </span>
      ) : null}
    </div>
  );
}

function Grille({ legende, premiere, derniere, jours, children }: { legende: string; premiere: string; derniere: string; jours: Date[]; children: ReactNode }) {
  return (
    // Zone qui défile horizontalement sur petit écran : focalisable pour défiler au clavier (WCAG 2.1.1).
    // oxlint-disable-next-line jsx-a11y/no-noninteractive-tabindex
    <div className="overflow-x-auto rounded-lg bg-carte shadow-carte" role="region" aria-label={legende} tabIndex={0}>
      <table className="w-full min-w-[58rem] table-fixed border-collapse text-petit">
        <caption className="sr-only">{legende}</caption>
        <colgroup>
          <col className="w-[12.5rem]" />
          {jours.map((j) => (
            <col key={isoJour(j)} />
          ))}
          <col className="w-[8.5rem]" />
        </colgroup>
        <thead>
          <tr className="text-[0.8rem] text-encre-douce">
            <th scope="col" className="px-3 py-3 text-left font-semibold">
              {premiere}
            </th>
            {jours.map((j) => (
              <th key={isoJour(j)} scope="col" className="px-2 py-3 text-center font-semibold capitalize">
                {jourCourt(j)}
              </th>
            ))}
            <th scope="col" className="px-3 py-3 text-left font-semibold">
              {derniere}
            </th>
          </tr>
        </thead>
        <tbody>{children}</tbody>
      </table>
    </div>
  );
}

// Au-delà, la case « À pourvoir » renvoie à la vue par site, qui les range par lieu.
const MAX_A_POURVOIR = 4;
const CELLULE = "border-t border-l border-filet p-1.5 align-top";
const ENTETE_LIGNE = "border-t border-filet p-2 text-left align-top font-normal";
// En-tête de ligne avec vignette : l'icône décorative est posée à gauche, le texte reste enfant direct de la cellule.
const ENTETE_ICONE = "relative min-h-[3.75rem] py-3 pr-2 pl-[3.75rem]";

export function TableauAgents({
  jours,
  agents,
  vacations,
  absences,
  onAgent,
  onVacation,
  onToutVoir,
}: {
  jours: Date[];
  agents: AgentPlanning[];
  vacations: Vacation[];
  absences: AbsenceAgent[];
  onAgent: (agent: number) => void;
  onVacation: (v: Vacation) => void;
  /** Vacations sans agent au-delà de quatre dans la journée : ouvrir la vue par site. */
  onToutVoir: () => void;
}) {
  const actives = enCours(vacations);
  const minutes = minutesParAgent(vacations);
  // Agents affichés + agents d'une vacation de la semaine absents de la liste (inactifs depuis, autre périmètre).
  const lignes = [
    ...agents.map((a) => ({ id: a.id, nom: nomAgent(a), reference: a.duree_hebdo_minutes })),
    ...[...new Map(actives.filter((v) => v.agent !== null && !agents.some((a) => a.id === v.agent)).map((v) => [v.agent as number, v.agent_nom])).entries()].map(([id, nom]) => ({ id, nom, reference: 35 * 60 })),
  ].toSorted((a, b) => a.nom.localeCompare(b.nom, "fr"));
  const sansAgent = actives.filter((v) => v.agent === null);
  const absent = (agent: number, jour: Date) => {
    const debut = new Date(jour).getTime();
    const fin = debut + 86_400_000;
    return absences.find((a) => a.agent === agent && new Date(a.debut).getTime() < fin && new Date(a.fin).getTime() > debut);
  };
  return (
    <Grille legende="Qui est où : vacations de la semaine par agent" premiere="Agent" derniere="Heures de la semaine" jours={jours}>
      {lignes.map((l) => (
        <tr key={l.id}>
          <th scope="row" className={ENTETE_LIGNE}>
            <button type="button" onClick={() => onAgent(l.id)} className="group flex w-full cursor-pointer items-center gap-3 rounded-md border-0 bg-transparent p-1 text-left font-sans hover:bg-vert-pale">
              <Avatar nom={l.nom} />
              <span className="flex min-w-0 flex-col">
                <span className="font-semibold text-encre group-hover:underline">{l.nom}</span>
                <span className="sr-only">, voir et modifier son planning</span>
              </span>
            </button>
          </th>
          {jours.map((jour) => {
            const absence = absent(l.id, jour);
            return (
              <td key={isoJour(jour)} className={CELLULE}>
                <div className="flex flex-col gap-1">
                  {absence ? <span className="rounded-md bg-fond px-2 py-1.5 text-[0.78rem] font-semibold text-encre-douce">{NATURES_ABSENCE.find((n) => n.valeur === absence.nature)?.libelle ?? "Absent"}</span> : null}
                  {actives
                    .filter((v) => v.agent === l.id && leJour(v.debut, jour))
                    .map((v) => (
                      <Pastille key={v.id} vacation={v} libelle={v.site_nom} complement={`, ${l.nom}, ${jourLong(v.debut)}`} onOuvrir={onVacation} />
                    ))}
                </div>
              </td>
            );
          })}
          <td className={CELLULE}>
            <Heures minutes={minutes.get(l.id) ?? 0} reference={l.reference} />
          </td>
        </tr>
      ))}
      {sansAgent.length ? (
        <tr className="bg-danger-fond/40">
          <th scope="row" className={cn(ENTETE_LIGNE, ENTETE_ICONE)}>
            <span aria-hidden="true" className="absolute top-3 left-3 inline-flex size-9 items-center justify-center rounded-full bg-danger-fond text-danger">
              <CircleAlert size={18} strokeWidth={1.8} />
            </span>
            <span className="block font-semibold text-encre">À pourvoir</span>
            <span className="block text-[0.75rem] text-encre-douce">Vacations sans agent</span>
          </th>
          {jours.map((jour) => {
            const duJour = sansAgent.filter((v) => leJour(v.debut, jour));
            const autres = duJour.length - MAX_A_POURVOIR;
            return (
              <td key={isoJour(jour)} className={CELLULE}>
                <div className="flex flex-col gap-1">
                  {duJour.slice(0, MAX_A_POURVOIR).map((v) => (
                    <Pastille key={v.id} vacation={v} libelle={v.site_nom} complement={`, sans agent, ${jourLong(v.debut)}`} onOuvrir={onVacation} />
                  ))}
                  {autres > 0 ? (
                    <button type="button" onClick={onToutVoir} className="cursor-pointer rounded-md border border-dashed border-danger bg-carte px-2 py-1.5 text-left font-sans text-[0.78rem] font-semibold text-encre hover:bg-danger-fond">
                      + {autres} autre{autres > 1 ? "s" : ""}
                      <span className="sr-only"> vacation{autres > 1 ? "s" : ""} sans agent le {jourLong(jour)}, voir par site</span>
                    </button>
                  ) : null}
                </div>
              </td>
            );
          })}
          <td className={CELLULE}>
            <span className="text-base font-semibold text-encre tabular-nums">{dureeLisible(somme(sansAgent))}</span>
          </td>
        </tr>
      ) : null}
    </Grille>
  );
}

export function TableauSites({
  jours,
  sites,
  vacations,
  besoins,
  onVacation,
  onBesoin,
}: {
  jours: Date[];
  /** Sites à afficher, avec le nombre de salles où une présence est requise. */
  sites: { id: number; nom: string; salles: number }[];
  vacations: Vacation[];
  besoins: Besoin[];
  onVacation: (v: Vacation) => void;
  /** Créer la vacation d'un besoin non couvert ; absent sans le droit de planifier. */
  onBesoin?: (b: Besoin) => void;
}) {
  const actives = enCours(vacations);
  return (
    <Grille legende="Présence par site : vacations et besoins non couverts de la semaine" premiere="Site" derniere="Présence prévue" jours={jours}>
      {sites.map((s) => {
        const duSite = actives.filter((v) => v.site === s.id);
        const sansAgent = duSite.filter((v) => v.agent === null);
        return (
          <tr key={s.id}>
            <th scope="row" className={cn(ENTETE_LIGNE, ENTETE_ICONE)}>
              <span aria-hidden="true" className="absolute top-3 left-3 inline-flex size-9 items-center justify-center rounded-md bg-vert-pale text-vert">
                <Building2 size={18} strokeWidth={1.8} />
              </span>
              <span className="block font-semibold text-encre">{s.nom}</span>
              <span className="block text-[0.75rem] text-encre-douce">{s.salles ? `${s.salles} salle${s.salles > 1 ? "s" : ""} à couvrir` : "Aucune salle à couvrir"}</span>
            </th>
            {jours.map((jour) => (
              <td key={isoJour(jour)} className={CELLULE}>
                <div className="flex flex-col gap-1">
                  {duSite
                    .filter((v) => leJour(v.debut, jour))
                    .map((v) => (
                      <Pastille key={v.id} vacation={v} libelle={v.agent_nom || "Sans agent"} complement={`, ${s.nom}, ${jourLong(v.debut)}`} onOuvrir={onVacation} />
                    ))}
                  {besoins
                    .filter((b) => b.site === s.id && leJour(b.debut, jour))
                    .map((b) => {
                      const contenu = (
                        <>
                          <span className="font-semibold tabular-nums">
                            {heure(b.debut)}–{heure(b.fin)}
                          </span>
                          <span className="text-[0.72rem] font-semibold text-danger">Non couvert</span>
                        </>
                      );
                      const classes = "flex w-full flex-col items-start gap-0.5 rounded-md border border-dashed border-danger bg-carte px-2 py-1.5 text-left font-sans text-[0.78rem] leading-tight text-encre";
                      return onBesoin ? (
                        <button key={`b${b.id}`} type="button" className={cn(classes, "cursor-pointer hover:bg-danger-fond")} onClick={() => onBesoin(b)}>
                          {contenu}
                          <span className="text-[0.72rem] text-vert underline">Créer la vacation</span>
                          <span className="sr-only">
                            , {s.nom}, {jourLong(b.debut)}
                          </span>
                        </button>
                      ) : (
                        <span key={`b${b.id}`} className={classes}>
                          {contenu}
                        </span>
                      );
                    })}
                </div>
              </td>
            ))}
            <td className={CELLULE}>
              <span className="block text-base font-semibold text-encre tabular-nums">{dureeLisible(somme(duSite))}</span>
              {sansAgent.length ? <span className="text-[0.75rem] text-danger">dont {dureeLisible(somme(sansAgent))} sans agent</span> : null}
            </td>
          </tr>
        );
      })}
    </Grille>
  );
}
