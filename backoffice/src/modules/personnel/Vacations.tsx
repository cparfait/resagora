/** PER-02 à PER-06, IMP-02, DSH-02 : planning des vacations d'un site par semaine, besoins non couverts,
 * affectation guidée par les règles de temps de travail (forçage motivé et tracé), annulation, planning imprimé. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useSearchParams } from "react-router";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
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

interface Violation {
  code: string;
  message: string;
  gravite?: string;
}
interface Vacation {
  id: number;
  site: number;
  site_nom: string;
  agent: number | null;
  agent_nom: string;
  debut: string;
  fin: string;
  duree_minutes: number;
  type: string;
  statut: string;
  violations: Violation[];
  forcee: boolean;
  motif_forcage: string;
  arrivee_reelle: string | null;
  depart_reel: string | null;
  signalement: string;
}
interface Besoin {
  id: number;
  site_nom: string;
  debut: string;
  fin: string;
  statut: string;
  seances: { espace: string; usager: string }[] | number[];
}
interface Candidat {
  agent: number;
  nom: string;
  minutes_semaine: number;
  prefere: boolean;
  conforme: boolean;
  violations: Violation[];
}

const STATUTS: Record<string, { libelle: string; ton: "succes" | "attention" | "danger" | "neutre" }> = {
  planifiee: { libelle: "Planifiée", ton: "succes" },
  a_pourvoir: { libelle: "À pourvoir", ton: "danger" },
  a_revoir: { libelle: "À revoir", ton: "attention" },
  annulee: { libelle: "Annulée", ton: "neutre" },
};

type Action = { type: "affecter" | "annuler" | "modifier"; vacation: Vacation } | { type: "creer" } | null;

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

export default function Vacations() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const lecture = peut("lire_personnel");
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const agents = useOptions("agents-personnel", "/api/gestion/personnel/agents?actif=true", (a) => `${String(a.prenom)} ${String(a.nom)}`, lecture);
  const [parametres] = useSearchParams();
  // DSH-02, DSH-06 : depuis le tableau de bord, les besoins non couverts des N prochains jours (comme le compteur).
  const horizon = Number(parametres.get("besoins_jours") ?? 0);
  const [maintenant] = useState(() => new Date());
  const [site, setSite] = useState(() => parametres.get("site") ?? "");
  // PER-05 : planning d'un agent (toutes ses vacations, tous sites), depuis la liste des agents ou ce filtre.
  const [agent, setAgent] = useState(() => parametres.get("agent") ?? "");
  const [semaine, setSemaine] = useState(() => debutSemaine(new Date()));
  const [action, setAction] = useState<Action>(null);
  const [saisie, setSaisie] = useState({ motif: "", debut: "", fin: "", type: "normale", site: "" });
  const fin = ajouterJours(semaine, 7);
  const filtres = { site: site || undefined, agent: agent || undefined, debut__gte: semaine.toISOString(), debut__lt: fin.toISOString(), taille: 500 };
  const vacations = useQuery({
    queryKey: ["vacations", filtres],
    queryFn: async () => (await requete<PageApi<Vacation>>("GET", construireChemin("/api/gestion/personnel/vacations", filtres))).results,
    enabled: lecture,
  });
  const besoins = useQuery({
    queryKey: ["besoins", filtres],
    queryFn: async () =>
      (
        await requete<PageApi<Besoin>>(
          "GET",
          construireChemin(
            "/api/gestion/personnel/besoins",
            horizon > 0 ? { site: site || undefined, statut: "a_couvrir", debut__gte: maintenant.toISOString(), debut__lt: ajouterJours(maintenant, horizon).toISOString(), taille: 500 } : { ...filtres, statut: "a_couvrir" },
          ),
        )
      ).results,
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
  const valider = () => {
    if (!action) return;
    if (action.type === "annuler") operation.mutate({ methode: "POST", url: `/api/gestion/personnel/vacations/${action.vacation.id}/annuler`, corps: { motif: saisie.motif } });
    if (action.type === "modifier")
      operation.mutate({ methode: "PATCH", url: `/api/gestion/personnel/vacations/${action.vacation.id}`, corps: { debut: new Date(saisie.debut).toISOString(), fin: new Date(saisie.fin).toISOString(), type: saisie.type } });
    if (action.type === "creer")
      operation.mutate({ methode: "POST", url: "/api/gestion/personnel/vacations", corps: { site: Number(saisie.site || site), debut: new Date(saisie.debut).toISOString(), fin: new Date(saisie.fin).toISOString(), type: saisie.type } });
  };
  return (
    <Page
      titre="Planning du personnel"
      description="Vacations par site et par semaine. Les besoins naissent des réservations des espaces gardiennés ; les règles de temps de travail sont contrôlées à chaque affectation."
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
            disabled={!site}
            title={site ? undefined : "Choisissez d'abord un site"}
            onClick={() => void telecharger(construireChemin("/api/gestion/personnel/vacations/planning-pdf", { site, du: isoJour(semaine), au: isoJour(ajouterJours(semaine, 6)) }), "planning-site.pdf")}
          >
            Imprimer le planning du site
          </Bouton>
        </>
      }
    >
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Site" videLibelle="Tous mes sites" options={sites} value={site} onChange={(e) => setSite(e.target.value)} />
        <ChampSelection libelle="Agent" videLibelle="Tous les agents" options={agents} value={agent} onChange={(e) => setAgent(e.target.value)} />
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
      {besoins.data && besoins.data.length > 0 ? (
        <section aria-labelledby="titre-besoins" className="encart encart--alerte">
          <h3 id="titre-besoins">
            Besoins non couverts{horizon > 0 ? ` des ${horizon} prochains jours` : " de la semaine"} ({besoins.data.length})
          </h3>
          <ul>
            {besoins.data.map((b) => (
              <li key={b.id}>
                {jourLong(b.debut)}, {heure(b.debut)} – {heure(b.fin)} — {b.site_nom}{" "}
                {ecriture ? (
                  <Bouton variante="lien" onClick={() => operation.mutate({ methode: "POST", url: `/api/gestion/personnel/besoins/${b.id}/vacation` })}>
                    Créer la vacation<span className="sr-only"> du {jourLong(b.debut)} {heure(b.debut)}</span>
                  </Bouton>
                ) : null}
              </li>
            ))}
          </ul>
        </section>
      ) : null}
      {vacations.isPending ? <Chargement /> : null}
      {vacations.isError ? <Erreur erreur={vacations.error} /> : null}
      {vacations.data
        ? jours.map((jour) => (
            <section key={isoJour(jour)} aria-label={jourLong(jour)} className="planning-jour">
              <h3>{jourLong(jour)}</h3>
              {parJour(jour).length === 0 ? <p className="aide">Aucune vacation.</p> : null}
              <ul className="liste-cartes">
                {parJour(jour).map((v) => (
                  <li key={v.id} className="carte">
                    <p>
                      <strong>
                        {heure(v.debut)} – {heure(v.fin)}
                      </strong>{" "}
                      {site ? "" : `${v.site_nom} — `}
                      {v.agent_nom || "Aucun agent"} <Badge libelle={STATUTS[v.statut]?.libelle ?? v.statut} ton={STATUTS[v.statut]?.ton ?? "neutre"} />
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
                    {ecriture && v.statut !== "annulee" ? (
                      <div className="actions">
                        <Bouton variante="lien" onClick={() => setAction({ type: "affecter", vacation: v })}>
                          {v.agent ? "Changer d'agent" : "Affecter un agent"}
                          <span className="sr-only"> — {jourLong(v.debut)} {heure(v.debut)}</span>
                        </Bouton>
                        <Bouton
                          variante="lien"
                          onClick={() => {
                            setSaisie({ motif: "", debut: versLocal(v.debut), fin: versLocal(v.fin), type: v.type, site: String(v.site) });
                            setAction({ type: "modifier", vacation: v });
                          }}
                        >
                          Modifier les horaires<span className="sr-only"> — {jourLong(v.debut)} {heure(v.debut)}</span>
                        </Bouton>
                        <Bouton
                          variante="lien"
                          onClick={() => {
                            setSaisie({ motif: "", debut: "", fin: "", type: v.type, site: "" });
                            setAction({ type: "annuler", vacation: v });
                          }}
                        >
                          Annuler<span className="sr-only"> la vacation — {jourLong(v.debut)} {heure(v.debut)}</span>
                        </Bouton>
                      </div>
                    ) : null}
                  </li>
                ))}
              </ul>
            </section>
          ))
        : null}
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
