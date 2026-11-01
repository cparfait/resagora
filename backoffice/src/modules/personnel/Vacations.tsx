/** PER-02 à PER-06, IMP-02, DSH-02 : planning du personnel par semaine. Vue d'ensemble « par agent » (qui est où,
 * heures de chaque agent) ou « par site » (sites où une présence est requise, besoins non couverts), liste « par
 * jour » ; un clic sur un agent ouvre son planning modifiable. Affectation guidée par les règles de temps de travail
 * (forçage motivé et tracé), annulation, planning imprimé. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import type { Espace } from "../../api/types";
import { useSession } from "../../auth/session";
import { Avatar } from "../../ui/Avatar";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { ajouterJours, debutSemaine, heure, isoJour, jourLong } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";
import { TYPES_VACATION } from "./Personnel";
import { dureeLisible, nomAgent, PLAFOND_HEBDO_MINUTES, STATUTS_VACATION, type AbsenceAgent, type AgentPlanning, type Besoin, type Vacation } from "./vacation";
import { ChiffresSemaine, minutesParAgent, TableauAgents, TableauSites } from "./VueEnsemble";

interface Candidat {
  agent: number;
  nom: string;
  minutes_semaine: number;
  prefere: boolean;
  conforme: boolean;
  violations: { code: string; message: string }[];
}

type Vue = "agents" | "sites" | "jours";
const VUES: { valeur: Vue; libelle: string }[] = [
  { valeur: "agents", libelle: "Par agent" },
  { valeur: "sites", libelle: "Par site" },
  { valeur: "jours", libelle: "Par jour" },
];

type Action = { type: "voir" | "affecter" | "annuler" | "modifier"; vacation: Vacation } | { type: "creer" } | null;

const versLocal = (iso: string) => {
  const d = new Date(iso);
  const deux = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${deux(d.getMonth() + 1)}-${deux(d.getDate())}T${deux(d.getHours())}:${deux(d.getMinutes())}`;
};

function Affectation({ vacation, onTermine }: { vacation: Vacation; onTermine: () => void }) {
  const { annoncer } = useNotifications();
  const client = useQueryClient();
  const [choisi, setChoisi] = useState<string>("");
  const [forcer, setForcer] = useState(false);
  const [motif, setMotif] = useState("");
  const candidats = useQuery({
    queryKey: ["candidats", vacation.id],
    queryFn: () => requete<Candidat[]>("GET", `/api/gestion/personnel/vacations/${vacation.id}/candidats`),
  });
  const affecter = useMutation({
    mutationFn: () => requete<Vacation>("POST", `/api/gestion/personnel/vacations/${vacation.id}/affecter`, { agent: choisi ? Number(choisi) : null, forcer, motif }),
    onSuccess: async () => {
      annoncer(choisi ? "Agent affecté." : "Vacation remise à pourvoir.");
      await client.invalidateQueries({ queryKey: ["vacations"] });
      await client.invalidateQueries({ queryKey: ["besoins"] });
      onTermine();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Affectation impossible.", "erreur"),
  });
  const candidat = candidats.data?.find((c) => String(c.agent) === choisi);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        affecter.mutate();
      }}
    >
      <p>
        {jourLong(vacation.debut)}, {heure(vacation.debut)} – {heure(vacation.fin)} — {vacation.site_nom}
      </p>
      {candidats.isPending ? <Chargement /> : null}
      {candidats.isError ? <Erreur erreur={candidats.error} /> : null}
      {candidats.data ? (
        <fieldset>
          <legend>Agents proposés (habilités, disponibles, dans l'ordre de préférence)</legend>
          {candidats.data.length === 0 ? <p>Aucun agent habilité et disponible sur ce créneau.</p> : null}
          {candidats.data.map((c) => (
            <div key={c.agent} className="choix">
              <label>
                <input type="radio" name="candidat" value={c.agent} checked={choisi === String(c.agent)} onChange={(e) => setChoisi(e.target.value)} /> {c.nom} — {Math.round(c.minutes_semaine / 6) / 10} h cette semaine
                {c.prefere ? " — site habituel" : ""}
              </label>{" "}
              {c.conforme ? <Badge libelle="Conforme" ton="succes" /> : <Badge libelle="Hors règles" ton="danger" />}
              {c.violations.length ? (
                <ul className="aide">
                  {c.violations.map((v) => (
                    <li key={v.code + v.message}>{v.message}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ))}
          {vacation.agent ? (
            <label className="choix">
              <input type="radio" name="candidat" value="" checked={choisi === ""} onChange={() => setChoisi("")} /> Retirer l'agent (vacation à pourvoir)
            </label>
          ) : null}
        </fieldset>
      ) : null}
      {candidat && !candidat.conforme ? (
        <>
          <CaseACocher libelle="Forcer l'affectation malgré les règles de temps de travail" checked={forcer} onChange={(e) => setForcer(e.target.checked)} />
          {forcer ? <ChampZone libelle="Motif du forçage (tracé au journal)" obligatoire value={motif} onChange={(e) => setMotif(e.target.value)} /> : null}
        </>
      ) : null}
      <div className="actions">
        <Bouton type="submit" enCours={affecter.isPending} disabled={!choisi && !vacation.agent}>
          Valider l'affectation
        </Bouton>
        <Bouton variante="secondaire" onClick={onTermine}>
          Annuler
        </Bouton>
      </div>
    </form>
  );
}

/** Horaires, site, agent, statut et alertes d'une vacation (carte de la liste par jour et fiche ouverte au clic). */
function DetailVacation({ v, avecSite }: { v: Vacation; avecSite: boolean }) {
  return (
    <>
      <p>
        <strong>
          {heure(v.debut)} – {heure(v.fin)}
        </strong>{" "}
        {avecSite ? `${v.site_nom} — ` : ""}
        {v.agent_nom || "Aucun agent"} <Badge libelle={STATUTS_VACATION[v.statut]?.libelle ?? v.statut} ton={STATUTS_VACATION[v.statut]?.ton ?? "neutre"} />
        {v.type !== "normale" ? <Badge libelle={TYPES_VACATION.find((t) => t.valeur === v.type)?.libelle ?? v.type} ton="info" /> : null}
        {v.forcee ? <Badge libelle="Forcée" ton="attention" /> : null}
      </p>
      {v.violations.length ? (
        <ul className="aide">
          {v.violations.map((x) => (
            <li key={x.code + x.message}>{x.message}</li>
          ))}
        </ul>
      ) : null}
      {v.forcee ? <p className="aide">Motif du forçage : {v.motif_forcage}</p> : null}
      {v.signalement ? <p className="aide">{v.signalement}</p> : null}
      {v.arrivee_reelle ? (
        <p className="aide">
          Pointé : {heure(v.arrivee_reelle)}
          {v.depart_reel ? ` – ${heure(v.depart_reel)}` : ""}
        </p>
      ) : null}
    </>
  );
}

function ActionsVacation({ v, onAction }: { v: Vacation; onAction: (type: "affecter" | "modifier" | "annuler", v: Vacation) => void }) {
  const precision = ` — ${jourLong(v.debut)} ${heure(v.debut)}`;
  return (
    <div className="actions">
      <Bouton variante="lien" onClick={() => onAction("affecter", v)}>
        {v.agent ? "Changer d'agent" : "Affecter un agent"}
        <span className="sr-only">{precision}</span>
      </Bouton>
      <Bouton variante="lien" onClick={() => onAction("modifier", v)}>
        Modifier les horaires<span className="sr-only">{precision}</span>
      </Bouton>
      <Bouton variante="lien" onClick={() => onAction("annuler", v)}>
        Annuler<span className="sr-only"> la vacation{precision}</span>
      </Bouton>
    </div>
  );
}

export default function Vacations() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const lecture = peut("lire_personnel");
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const [parametres] = useSearchParams();
  // DSH-02, DSH-06 : depuis le tableau de bord, les besoins non couverts des N prochains jours (comme le compteur).
  const horizon = Number(parametres.get("besoins_jours") ?? 0);
  const [maintenant] = useState(() => new Date());
  const [site, setSite] = useState(() => parametres.get("site") ?? "");
  // PER-05 : planning d'un agent (toutes ses vacations, tous sites), depuis la vue d'ensemble, la liste des agents ou ce filtre.
  const [agent, setAgent] = useState(() => parametres.get("agent") ?? "");
  const [vue, setVue] = useState<Vue>(() => (horizon > 0 ? "sites" : "agents"));
  const [semaine, setSemaine] = useState(() => debutSemaine(new Date()));
  const [action, setAction] = useState<Action>(null);
  const [saisie, setSaisie] = useState({ motif: "", debut: "", fin: "", type: "normale", site: "" });
  const fin = ajouterJours(semaine, 7);
  const periode = { debut__gte: semaine.toISOString(), debut__lt: fin.toISOString(), taille: 500 };
  // Le planning d'un agent couvre tous ses sites ; sinon le filtre de site s'applique.
  const filtres = agent ? { ...periode, agent } : { ...periode, site: site || undefined };
  const vacations = useQuery({
    queryKey: ["vacations", filtres],
    queryFn: async () => (await requete<PageApi<Vacation>>("GET", construireChemin("/api/gestion/personnel/vacations", filtres))).results,
    enabled: lecture,
  });
  const besoins = useQuery({
    queryKey: ["besoins", filtres, horizon],
    queryFn: async () =>
      (
        await requete<PageApi<Besoin>>(
          "GET",
          construireChemin(
            "/api/gestion/personnel/besoins",
            horizon > 0 ? { site: site || undefined, statut: "a_couvrir", debut__gte: maintenant.toISOString(), debut__lt: ajouterJours(maintenant, horizon).toISOString(), taille: 500 } : { ...periode, site: site || undefined, statut: "a_couvrir" },
          ),
        )
      ).results,
    enabled: lecture,
  });
  const agents = useQuery({
    queryKey: ["agents-planning"],
    queryFn: async () => (await requete<PageApi<AgentPlanning>>("GET", "/api/gestion/personnel/agents?actif=true&taille=500")).results,
    enabled: lecture,
  });
  const absences = useQuery({
    queryKey: ["absences-planning"],
    queryFn: async () => (await requete<PageApi<AbsenceAgent>>("GET", "/api/gestion/personnel/absences?taille=500")).results,
    enabled: lecture,
  });
  // REF-04 : salles où une présence est requise (les autres sites n'apparaissent pas dans la vue par site).
  const espacesCouverts = useQuery({
    queryKey: ["espaces-gardiennes"],
    queryFn: async () => (await requete<PageApi<Espace>>("GET", "/api/gestion/referentiel/espaces?gardiennage_requis=true&actif=true&taille=500")).results,
    enabled: lecture,
  });
  const operation = useMutation({
    mutationFn: ({ methode, url, corps }: { methode: string; url: string; corps?: unknown }) => requete<unknown>(methode, url, corps),
    onSuccess: async () => {
      annoncer("Planning mis à jour.");
      setAction(null);
      await client.invalidateQueries({ queryKey: ["vacations"] });
      await client.invalidateQueries({ queryKey: ["besoins"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });
  if (!lecture) return <DroitsInsuffisants />;
  const ecriture = peut("planifier_personnel");
  const jours = Array.from({ length: 7 }, (_, i) => ajouterJours(semaine, i));
  const parJour = (jour: Date) => (vacations.data ?? []).filter((v) => isoJour(new Date(v.debut)) === isoJour(jour));
  const listeAgents = agents.data ?? [];
  const agentsAffiches = site ? listeAgents.filter((a) => a.sites.includes(Number(site))) : listeAgents;
  const agentChoisi = agent ? listeAgents.find((a) => String(a.id) === agent) : undefined;
  const nomChoisi = agentChoisi ? nomAgent(agentChoisi) : (vacations.data?.find((v) => String(v.agent) === agent)?.agent_nom ?? "Agent");
  const minutesChoisi = agent ? (minutesParAgent(vacations.data ?? []).get(Number(agent)) ?? 0) : 0;
  const sallesParSite = new Map<number, number>();
  for (const e of espacesCouverts.data ?? []) sallesParSite.set(e.site, (sallesParSite.get(e.site) ?? 0) + 1);
  const sitesAffiches = sites
    .map((s) => ({ id: Number(s.valeur), nom: s.libelle, salles: sallesParSite.get(Number(s.valeur)) ?? 0 }))
    .filter((s) => (!site || String(s.id) === site) && (s.salles > 0 || (vacations.data ?? []).some((v) => v.site === s.id && v.statut !== "annulee")));
  const sitesSansPresence = sites.filter((s) => !sallesParSite.has(Number(s.valeur)));

  const ouvrir = (type: "affecter" | "modifier" | "annuler", v: Vacation) => {
    setSaisie({ motif: "", debut: type === "modifier" ? versLocal(v.debut) : "", fin: type === "modifier" ? versLocal(v.fin) : "", type: v.type, site: String(v.site) });
    setAction({ type, vacation: v });
  };
  const creerPourBesoin = (b: Besoin) => operation.mutate({ methode: "POST", url: `/api/gestion/personnel/besoins/${b.id}/vacation` });
  const valider = () => {
    if (!action) return;
    if (action.type === "annuler") operation.mutate({ methode: "POST", url: `/api/gestion/personnel/vacations/${action.vacation.id}/annuler`, corps: { motif: saisie.motif } });
    if (action.type === "modifier")
      operation.mutate({ methode: "PATCH", url: `/api/gestion/personnel/vacations/${action.vacation.id}`, corps: { debut: new Date(saisie.debut).toISOString(), fin: new Date(saisie.fin).toISOString(), type: saisie.type } });
    if (action.type === "creer")
      operation.mutate({ methode: "POST", url: "/api/gestion/personnel/vacations", corps: { site: Number(saisie.site || site), debut: new Date(saisie.debut).toISOString(), fin: new Date(saisie.fin).toISOString(), type: saisie.type } });
  };
  const chargement = vacations.isPending || agents.isPending;
  const erreur = vacations.error ?? agents.error;

  const listeParJour = (avecSite: boolean) =>
    jours.map((jour) => (
      <section key={isoJour(jour)} aria-label={jourLong(jour)} className="planning-jour">
        <h3>{jourLong(jour)}</h3>
        {parJour(jour).length === 0 ? <p className="aide">Aucune vacation.</p> : null}
        <ul className="liste-cartes">
          {parJour(jour).map((v) => (
            <li key={v.id} className="carte">
              <DetailVacation v={v} avecSite={avecSite} />
              {ecriture && v.statut !== "annulee" ? <ActionsVacation v={v} onAction={ouvrir} /> : null}
            </li>
          ))}
        </ul>
      </section>
    ));

  return (
    <Page
      titre="Planning du personnel"
      description="Qui est où, et combien d'heures chacun fait dans la semaine. Les besoins naissent des réservations des salles où une présence est requise ; les règles de temps de travail sont contrôlées à chaque affectation."
      actions={
        <>
          {ecriture ? (
            <Bouton
              onClick={() => {
                setSaisie({ motif: "", debut: "", fin: "", type: "normale", site });
                setAction({ type: "creer" });
              }}
            >
              Nouvelle vacation
            </Bouton>
          ) : null}
          <Bouton
            variante="secondaire"
            disabled={!site && !agent}
            title={site || agent ? undefined : "Choisissez d'abord un site ou un agent"}
            onClick={() =>
              void telecharger(
                construireChemin("/api/gestion/personnel/vacations/planning-pdf", { ...(agent ? { agent } : { site }), du: isoJour(semaine), au: isoJour(ajouterJours(semaine, 6)) }),
                agent ? "planning-agent.pdf" : "planning-site.pdf",
              )
            }
          >
            {agent ? "Imprimer son planning" : "Imprimer le planning du site"}
          </Bouton>
        </>
      }
    >
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Site" videLibelle="Tous mes sites" options={sites} value={site} onChange={(e) => setSite(e.target.value)} />
        <ChampSelection libelle="Agent" videLibelle="Tous les agents" options={listeAgents.map((a) => ({ valeur: String(a.id), libelle: nomAgent(a) }))} value={agent} onChange={(e) => setAgent(e.target.value)} />
        <div className="actions">
          <Bouton variante="secondaire" onClick={() => setSemaine(ajouterJours(semaine, -7))}>
            Semaine précédente
          </Bouton>
          <Bouton variante="secondaire" onClick={() => setSemaine(debutSemaine(new Date()))}>
            Cette semaine
          </Bouton>
          <Bouton variante="secondaire" onClick={() => setSemaine(ajouterJours(semaine, 7))}>
            Semaine suivante
          </Bouton>
        </div>
      </form>
      <h2>Semaine du {jourLong(semaine)}</h2>
      {chargement ? <Chargement /> : null}
      {erreur ? <Erreur erreur={erreur} /> : null}
      {!chargement && !erreur && agent ? (
        <>
          <div className="mb-6 flex flex-wrap items-center justify-between gap-4 rounded-lg bg-carte p-5 shadow-carte">
            <div className="flex items-center gap-3">
              <Avatar nom={nomChoisi} className="size-12 text-sm" />
              <div>
                <p className="m-0 text-base font-semibold text-encre">Planning de {nomChoisi}</p>
                <p className="m-0 text-[0.85rem] text-encre-douce">
                  {dureeLisible(minutesChoisi)} planifiées cette semaine{agentChoisi ? ` sur ${dureeLisible(agentChoisi.duree_hebdo_minutes)} de référence` : ""}
                </p>
              </div>
              {minutesChoisi > PLAFOND_HEBDO_MINUTES ? <Badge libelle="Plus de 48 h" ton="danger" /> : null}
            </div>
            <Bouton variante="secondaire" icone={<ArrowLeft aria-hidden="true" size={18} strokeWidth={1.8} />} onClick={() => setAgent("")}>
              Retour à la vue d'ensemble
            </Bouton>
          </div>
          {listeParJour(true)}
        </>
      ) : null}
      {!chargement && !erreur && !agent ? (
        <>
          <ChiffresSemaine vacations={vacations.data ?? []} agents={agentsAffiches.length} />
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="segments" role="group" aria-label="Affichage du planning">
              {VUES.map((v) => (
                <button key={v.valeur} type="button" className={`segment${vue === v.valeur ? " segment--actif" : ""}`} aria-pressed={vue === v.valeur} onClick={() => setVue(v.valeur)}>
                  {v.libelle}
                </button>
              ))}
            </div>
            {vue === "agents" ? <p className="m-0 text-[0.85rem] text-encre-douce">Cliquez sur un agent pour voir et modifier son planning, sur une vacation pour l'ouvrir.</p> : null}
          </div>
          {besoins.data && besoins.data.length > 0 && vue === "agents" ? (
            <div className="encart encart--alerte flex flex-wrap items-center justify-between gap-3">
              <p className="m-0">
                <strong>
                  {besoins.data.length} besoin{besoins.data.length > 1 ? "s" : ""} non couvert{besoins.data.length > 1 ? "s" : ""}
                </strong>{" "}
                {horizon > 0 ? `dans les ${horizon} prochains jours` : "cette semaine"} : des réservations sans agent prévu.
              </p>
              <Bouton variante="secondaire" icone={null} onClick={() => setVue("sites")}>
                Les voir par site
              </Bouton>
            </div>
          ) : null}
          {besoins.data && besoins.data.length > 0 && vue === "jours" ? (
            <section aria-labelledby="titre-besoins" className="encart encart--alerte">
              <h3 id="titre-besoins">
                Besoins non couverts{horizon > 0 ? ` des ${horizon} prochains jours` : " de la semaine"} ({besoins.data.length})
              </h3>
              <ul>
                {besoins.data.map((b) => (
                  <li key={b.id}>
                    {jourLong(b.debut)}, {heure(b.debut)} – {heure(b.fin)} — {b.site_nom}{" "}
                    {ecriture ? (
                      <Bouton variante="lien" onClick={() => creerPourBesoin(b)}>
                        Créer la vacation<span className="sr-only"> du {jourLong(b.debut)} {heure(b.debut)}</span>
                      </Bouton>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          {vue === "agents" ? (
            <TableauAgents jours={jours} agents={agentsAffiches} vacations={vacations.data ?? []} absences={absences.data ?? []} onAgent={(id) => setAgent(String(id))} onVacation={(v) => setAction({ type: "voir", vacation: v })}
              onToutVoir={() => setVue("sites")}
            />
          ) : null}
          {vue === "sites" ? (
            <>
              {horizon > 0 && besoins.data?.length ? (
                <p className="encart encart--alerte">
                  {besoins.data.length} besoin{besoins.data.length > 1 ? "s" : ""} non couvert{besoins.data.length > 1 ? "s" : ""} dans les {horizon} prochains jours : ils apparaissent semaine par semaine ci-dessous.
                </p>
              ) : null}
              <TableauSites
                jours={jours}
                sites={sitesAffiches}
                vacations={vacations.data ?? []}
                besoins={horizon > 0 ? (besoins.data ?? []).filter((b) => new Date(b.debut) >= semaine && new Date(b.debut) < fin) : (besoins.data ?? [])}
                onVacation={(v) => setAction({ type: "voir", vacation: v })}
                onBesoin={ecriture ? creerPourBesoin : undefined}
              />
              {sitesSansPresence.length ? (
                <p className="mt-3 text-[0.85rem] text-encre-douce">
                  Sans présence requise : {sitesSansPresence.map((s) => s.libelle).join(", ")}. <Link to="/personnel/presence">Régler la présence par salle</Link>
                </p>
              ) : null}
            </>
          ) : null}
          {vue === "jours" ? listeParJour(!site) : null}
        </>
      ) : null}
      <Dialogue ouvert={action?.type === "voir"} titre="Vacation" onFermer={() => setAction(null)}>
        {action?.type === "voir" ? (
          <>
            <p className="mt-0 font-semibold">{jourLong(action.vacation.debut)}</p>
            <DetailVacation v={action.vacation} avecSite />
            {ecriture && action.vacation.statut !== "annulee" ? <ActionsVacation v={action.vacation} onAction={ouvrir} /> : null}
            {action.vacation.agent ? (
              <p className="mb-0">
                <Bouton variante="lien" onClick={() => {
                  setAgent(String(action.vacation.agent));
                  setAction(null);
                }}>
                  Voir tout le planning de {action.vacation.agent_nom}
                </Bouton>
              </p>
            ) : null}
          </>
        ) : null}
      </Dialogue>
      <Dialogue ouvert={action?.type === "affecter"} titre="Affecter un agent" onFermer={() => setAction(null)} large>
        {action?.type === "affecter" ? <Affectation vacation={action.vacation} onTermine={() => setAction(null)} /> : null}
      </Dialogue>
      <Dialogue
        ouvert={action?.type === "annuler" || action?.type === "modifier" || action?.type === "creer"}
        titre={action?.type === "annuler" ? "Annuler la vacation" : action?.type === "creer" ? "Nouvelle vacation" : "Modifier la vacation"}
        onFermer={() => setAction(null)}
      >
        <form
          onSubmit={(e) => {
            e.preventDefault();
            valider();
          }}
        >
          {action?.type === "annuler" ? (
            <ChampZone libelle="Motif" obligatoire value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
          ) : (
            <>
              {action?.type === "creer" ? <ChampSelection libelle="Site" obligatoire options={sites} value={saisie.site} onChange={(e) => setSaisie({ ...saisie, site: e.target.value })} /> : null}
              <ChampTexte libelle="Début" type="datetime-local" obligatoire value={saisie.debut} onChange={(e) => setSaisie({ ...saisie, debut: e.target.value })} />
              <ChampTexte libelle="Fin" type="datetime-local" obligatoire value={saisie.fin} onChange={(e) => setSaisie({ ...saisie, fin: e.target.value })} />
              <ChampSelection libelle="Type" obligatoire options={TYPES_VACATION} value={saisie.type} onChange={(e) => setSaisie({ ...saisie, type: e.target.value })} />
            </>
          )}
          <div className="actions">
            <Bouton type="submit" enCours={operation.isPending}>
              Valider
            </Bouton>
            <Bouton variante="secondaire" onClick={() => setAction(null)}>
              Fermer
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </Page>
  );
}
