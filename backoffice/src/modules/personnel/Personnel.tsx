/** PER-01 à PER-09, IMP-02, MOB-06, SEC-10 : agents et habilitations, trames, absences, compteurs et export paie,
 * incidents, appareils mobiles, saisies reçues du terrain. Les règles (temps de travail, périmètre) sont dans l'API. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { dateHeure, dateSimple, isoJour, ajouterJours, debutMois } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

type Ligne = Record<string, unknown> & { id: number };

export const NATURES_ABSENCE = [
  { valeur: "conge", libelle: "Congé" },
  { valeur: "maladie", libelle: "Arrêt maladie" },
  { valeur: "formation", libelle: "Formation" },
  { valeur: "autre", libelle: "Autre absence" },
];
export const NATURES_INCIDENT = [
  { valeur: "degradation", libelle: "Dégradation" },
  { valeur: "comportement", libelle: "Comportement" },
  { valeur: "accident", libelle: "Accident ou blessure" },
  { valeur: "technique", libelle: "Problème technique" },
  { valeur: "absence_usager", libelle: "Usager absent" },
  { valeur: "autre", libelle: "Autre" },
];
export const GRAVITES = [
  { valeur: "mineur", libelle: "Mineur" },
  { valeur: "majeur", libelle: "Majeur" },
  { valeur: "securite", libelle: "Sécurité des personnes" },
];
export const TYPES_VACATION = [
  { valeur: "normale", libelle: "Normale" },
  { valeur: "supplementaire", libelle: "Heures supplémentaires" },
  { valeur: "astreinte", libelle: "Astreinte" },
];
const JOURS = ["Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche"].map((libelle, i) => ({ valeur: String(i), libelle }));
const libelleDe = (options: { valeur: string; libelle: string }[], valeur: unknown) => options.find((o) => o.valeur === String(valeur))?.libelle ?? String(valeur ?? "");

function useAgents(actif: boolean) {
  return useOptions("agents-personnel", "/api/gestion/personnel/agents", (a) => `${String(a.nom)} ${String(a.prenom)} (${String(a.matricule)})`, actif);
}

function useSites(actif: boolean) {
  return useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), actif);
}

/** Lien d'abonnement iCal : affiché une seule fois, l'ancien est révoqué (PER-08). */
function ActionsAgent({ agent }: { agent: Ligne }) {
  const { peut } = useSession();
  const { annoncer } = useNotifications();
  const [lien, setLien] = useState<string | null>(null);
  const emettre = useMutation({
    mutationFn: () => requete<{ url: string }>("POST", `/api/gestion/personnel/agents/${agent.id}/ical`),
    onSuccess: (r) => setLien(r.url),
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Lien impossible à créer.", "erreur"),
  });
  const revoquer = useMutation({
    mutationFn: () => requete<{ revoques: number }>("POST", `/api/gestion/personnel/agents/${agent.id}/revoquer-ical`),
    onSuccess: (r) => annoncer(r.revoques ? "Abonnement iCal révoqué." : "Aucun abonnement actif."),
  });
  const nom = `${String(agent.prenom)} ${String(agent.nom)}`;
  const voir = (
    <Link to={`/personnel/vacations?agent=${agent.id}`}>
      Voir son planning<span className="sr-only"> : {nom}</span>
    </Link>
  );
  if (!peut("planifier_personnel")) return voir;
  return (
    <>
      {voir}
      <Bouton variante="lien" onClick={() => emettre.mutate()} enCours={emettre.isPending}>
        Lien iCal<span className="sr-only"> de {nom}</span>
      </Bouton>
      <Bouton variante="lien" onClick={() => revoquer.mutate()}>
        Révoquer l'iCal<span className="sr-only"> de {nom}</span>
      </Bouton>
      <Bouton
        variante="lien"
        onClick={() => {
          const du = new Date();
          void telecharger(construireChemin("/api/gestion/personnel/vacations/planning-pdf", { agent: agent.id, du: isoJour(du), au: isoJour(ajouterJours(du, 27)) }), `planning-${String(agent.matricule)}.pdf`);
        }}
      >
        Planning PDF<span className="sr-only"> de {nom}</span>
      </Bouton>
      <Dialogue ouvert={lien !== null} titre={`Abonnement iCal — ${nom}`} onFermer={() => setLien(null)}>
        <p>Transmettez ce lien à l'agent : il ne sera plus affiché. Le lien précédent ne fonctionne plus.</p>
        <p className="aide">
          Dans Outlook : Calendrier → Ajouter un calendrier → S'abonner à partir du web, puis coller l'adresse. Le planning se met à jour tout seul (environ toutes les heures).
        </p>
        <ChampTexte libelle="Adresse d'abonnement" readOnly value={lien ?? ""} onFocus={(e) => e.currentTarget.select()} />
        <Bouton onClick={() => setLien(null)}>Fermer</Bouton>
      </Dialogue>
    </>
  );
}

export function Agents() {
  const { peut } = useSession();
  const lecture = peut("lire_personnel");
  const sites = useSites(lecture);
  return (
    <EcranRessource<Ligne>
      titre="Agents d'équipement et gardiens"
      description="Fiches des agents, sites d'affectation et habilitations. L'identifiant de l'annuaire rattache la fiche au compte utilisé dans l'application mobile."
      chemin="/api/gestion/personnel/agents"
      cleRequete="agents-personnel"
      actionLecture="lire_personnel"
      actionEcriture="gerer_agents"
      libelleObjet="Agent"
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (a) => `${String(a.nom)} ${String(a.prenom)}`, valeurTri: (a) => String(a.nom) },
        { cle: "matricule", titre: "Matricule", rendu: (a) => String(a.matricule) },
        { cle: "sites", titre: "Sites", rendu: (a) => (a.sites_noms as string[]).join(", ") },
        {
          cle: "habilitations",
          titre: "Habilitations",
          rendu: (a) => (
            <span className="badges">
              {(a.habilitations as { id: number; type_libelle: string; valide: boolean; valide_jusqu_au: string | null }[]).map((h) => (
                <Badge key={h.id} libelle={`${h.type_libelle}${h.valide_jusqu_au ? ` (${dateSimple(h.valide_jusqu_au)})` : ""}`} ton={h.valide ? "succes" : "danger"} />
              ))}
            </span>
          ),
        },
        { cle: "compte", titre: "Compte mobile", rendu: (a) => (a.utilisateur ? <Badge libelle="Rattaché" ton="succes" /> : <Badge libelle={a.identifiant_ad ? "En attente de connexion" : "Aucun"} ton="attention" />) },
        { cle: "actif", titre: "État", rendu: (a) => (a.actif ? "Actif" : <Badge libelle="Inactif" ton="attention" />) },
      ]}
      champs={[
        { nom: "matricule", libelle: "Matricule", type: "texte", obligatoire: true },
        { nom: "prenom", libelle: "Prénom", type: "texte", obligatoire: true },
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "identifiant_ad", libelle: "Identifiant de l'annuaire", type: "texte", aide: "Identifiant Windows de l'agent (ex. jdupont)." },
        { nom: "courriel", libelle: "Courriel professionnel", type: "courriel" },
        { nom: "telephone", libelle: "Téléphone professionnel", type: "texte" },
        { nom: "sites", libelle: "Sites d'affectation possibles", type: "multiple", obligatoire: true, options: sites },
        { nom: "site_prefere", libelle: "Site habituel", type: "selection", options: sites },
        { nom: "duree_hebdo_minutes", libelle: "Durée hebdomadaire de référence (minutes)", type: "nombre", aide: "35 h = 2 100 minutes." },
        { nom: "actif", libelle: "Agent actif", type: "booleen" },
      ]}
      valeursInitiales={{ actif: true, duree_hebdo_minutes: 2100 }}
      filtres={[
        { nom: "sites", libelle: "Site", options: sites },
        { nom: "actif", libelle: "État", options: [{ valeur: "true", libelle: "Actifs" }, { valeur: "false", libelle: "Inactifs" }] },
      ]}
      actionsLigne={(a) => <ActionsAgent agent={a} />}
    />
  );
}

export function Habilitations() {
  const { peut } = useSession();
  const lecture = peut("lire_personnel");
  const agents = useAgents(lecture);
  const types = useOptions("types-habilitation", "/api/gestion/personnel/types-habilitation", (t) => String(t.libelle), lecture);
  return (
    <>
      <EcranRessource<Ligne>
        titre="Habilitations des agents"
        description="SSIAP, PSC1… Une habilitation expirée exclut l'agent des propositions d'affectation sur les espaces qui l'exigent (PER-01)."
        chemin="/api/gestion/personnel/habilitations"
        cleRequete="habilitations-agents"
        actionLecture="lire_personnel"
        actionEcriture="gerer_agents"
        libelleObjet="Habilitation"
        suppression
        colonnes={[
          { cle: "agent", titre: "Agent", rendu: (h) => libelleDe(agents, h.agent) },
          { cle: "type", titre: "Habilitation", rendu: (h) => String(h.type_libelle) },
          { cle: "obtenue", titre: "Obtenue le", rendu: (h) => (h.obtenue_le ? dateSimple(String(h.obtenue_le)) : "—") },
          { cle: "validite", titre: "Valide jusqu'au", rendu: (h) => (h.valide_jusqu_au ? dateSimple(String(h.valide_jusqu_au)) : "Sans limite"), valeurTri: (h) => String(h.valide_jusqu_au ?? "9999") },
          { cle: "etat", titre: "État", rendu: (h) => <Badge libelle={h.valide ? "Valide" : "Expirée"} ton={h.valide ? "succes" : "danger"} /> },
        ]}
        champs={[
          { nom: "agent", libelle: "Agent", type: "selection", obligatoire: true, options: agents },
          { nom: "type", libelle: "Habilitation", type: "selection", obligatoire: true, options: types },
          { nom: "obtenue_le", libelle: "Obtenue le", type: "date" },
          { nom: "valide_jusqu_au", libelle: "Valide jusqu'au", type: "date" },
        ]}
        filtres={[
          { nom: "agent", libelle: "Agent", options: agents },
          { nom: "type", libelle: "Habilitation", options: types },
        ]}
      />
      <EcranRessource<Ligne>
        titre="Types d'habilitation"
        chemin="/api/gestion/personnel/types-habilitation"
        cleRequete="types-habilitation"
        actionLecture="lire_personnel"
        actionEcriture="gerer_agents"
        libelleObjet="Type d'habilitation"
        colonnes={[
          { cle: "code", titre: "Code", rendu: (t) => String(t.code) },
          { cle: "libelle", titre: "Libellé", rendu: (t) => String(t.libelle) },
          { cle: "exigee", titre: "Exigée pour le gardiennage", rendu: (t) => (t.exigee_pour_gardiennage ? "Oui" : "Non") },
        ]}
        champs={[
          { nom: "code", libelle: "Code", type: "texte", obligatoire: true, enCreationSeulement: true },
          { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
          { nom: "exigee_pour_gardiennage", libelle: "Exigée pour tout gardiennage", type: "booleen" },
        ]}
      />
    </>
  );
}

function AppliquerTrame({ trame }: { trame: Ligne }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const appliquer = useMutation({
    mutationFn: () => requete<{ creees: number; conflits: string[] }>("POST", `/api/gestion/personnel/trames/${trame.id}/appliquer`),
    onSuccess: async (r) => {
      annoncer(`Trame appliquée : ${r.creees} vacation(s) créée(s).${r.conflits.length ? ` Laissées à pourvoir (agent déjà affecté) : ${r.conflits.join(" ; ")}` : ""}`);
      await client.invalidateQueries({ queryKey: ["trames"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Application impossible.", "erreur"),
  });
  if (!peut("planifier_personnel")) return null;
  return (
    <Bouton variante="lien" onClick={() => appliquer.mutate()} enCours={appliquer.isPending}>
      Appliquer sur la saison<span className="sr-only"> : {String(trame.nom)}</span>
    </Bouton>
  );
}

export function Trames() {
  const { peut } = useSession();
  const lecture = peut("lire_personnel");
  const sites = useSites(lecture);
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom), lecture);
  const trames = useOptions("trames", "/api/gestion/personnel/trames", (t) => `${String(t.nom)} — ${String(t.site_nom)}`, lecture);
  const agents = useAgents(lecture);
  return (
    <>
      <EcranRessource<Ligne>
        titre="Trames hebdomadaires"
        description="Semaine type d'un site pour une saison ; l'appliquer crée les vacations de toute la saison, hors fermetures (PER-03)."
        chemin="/api/gestion/personnel/trames"
        cleRequete="trames"
        actionLecture="lire_personnel"
        actionEcriture="planifier_personnel"
        libelleObjet="Trame"
        colonnes={[
          { cle: "nom", titre: "Trame", rendu: (t) => String(t.nom) },
          { cle: "site", titre: "Site", rendu: (t) => String(t.site_nom) },
          { cle: "saison", titre: "Saison", rendu: (t) => String(t.saison_nom) },
          { cle: "lignes", titre: "Créneaux", rendu: (t) => String((t.lignes as unknown[]).length) },
          { cle: "appliquee", titre: "Appliquée", rendu: (t) => (t.appliquee_le ? dateHeure(String(t.appliquee_le)) : "Jamais") },
        ]}
        champs={[
          { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
          { nom: "site", libelle: "Site", type: "selection", obligatoire: true, options: sites },
          { nom: "saison", libelle: "Saison", type: "selection", obligatoire: true, options: saisons },
        ]}
        filtres={[
          { nom: "site", libelle: "Site", options: sites },
          { nom: "saison", libelle: "Saison", options: saisons },
        ]}
        actionsLigne={(t) => <AppliquerTrame trame={t} />}
      />
      <EcranRessource<Ligne>
        titre="Créneaux des trames"
        chemin="/api/gestion/personnel/lignes-trame"
        cleRequete="lignes-trame"
        actionLecture="lire_personnel"
        actionEcriture="planifier_personnel"
        libelleObjet="Créneau"
        suppression
        colonnes={[
          { cle: "trame", titre: "Trame", rendu: (l) => libelleDe(trames, l.trame) },
          { cle: "jour", titre: "Jour", rendu: (l) => libelleDe(JOURS, l.jour), valeurTri: (l) => Number(l.jour) },
          { cle: "horaires", titre: "Horaires", rendu: (l) => `${String(l.heure_debut).slice(0, 5)} – ${String(l.heure_fin).slice(0, 5)}` },
          { cle: "agent", titre: "Agent", rendu: (l) => String(l.agent_nom || "À pourvoir") },
          { cle: "type", titre: "Type", rendu: (l) => libelleDe(TYPES_VACATION, l.type) },
        ]}
        champs={[
          { nom: "trame", libelle: "Trame", type: "selection", obligatoire: true, options: trames },
          { nom: "jour", libelle: "Jour", type: "selection", obligatoire: true, options: JOURS },
          { nom: "heure_debut", libelle: "Début", type: "heure", obligatoire: true },
          { nom: "heure_fin", libelle: "Fin", type: "heure", obligatoire: true },
          { nom: "agent", libelle: "Agent habituel", type: "selection", options: agents },
          { nom: "type", libelle: "Type", type: "selection", obligatoire: true, options: TYPES_VACATION },
        ]}
        valeursInitiales={{ type: "normale" }}
        filtres={[{ nom: "trame", libelle: "Trame", options: trames }]}
      />
    </>
  );
}

export function Absences() {
  const { peut } = useSession();
  const agents = useAgents(peut("lire_personnel"));
  return (
    <EcranRessource<Ligne>
      titre="Absences"
      description="Une absence libère les vacations de l'agent sur la période : elles redeviennent à pourvoir et un remplaçant est proposé (PER-06)."
      chemin="/api/gestion/personnel/absences"
      cleRequete="absences"
      actionLecture="lire_personnel"
      actionEcriture="planifier_personnel"
      libelleObjet="Absence"
      colonnes={[
        { cle: "agent", titre: "Agent", rendu: (a) => String(a.agent_nom) },
        { cle: "nature", titre: "Nature", rendu: (a) => libelleDe(NATURES_ABSENCE, a.nature) },
        { cle: "debut", titre: "Du", rendu: (a) => dateHeure(String(a.debut)), valeurTri: (a) => String(a.debut) },
        { cle: "fin", titre: "Au", rendu: (a) => dateHeure(String(a.fin)) },
        { cle: "commentaire", titre: "Commentaire", rendu: (a) => String(a.commentaire) },
      ]}
      champs={[
        { nom: "agent", libelle: "Agent", type: "selection", obligatoire: true, options: agents },
        { nom: "nature", libelle: "Nature", type: "selection", obligatoire: true, options: NATURES_ABSENCE },
        { nom: "debut", libelle: "Début", type: "dateheure", obligatoire: true },
        { nom: "fin", libelle: "Fin", type: "dateheure", obligatoire: true },
        { nom: "commentaire", libelle: "Commentaire", type: "zone" },
      ]}
      filtres={[
        { nom: "agent", libelle: "Agent", options: agents },
        { nom: "nature", libelle: "Nature", options: NATURES_ABSENCE },
      ]}
    />
  );
}

interface LigneCompteur {
  agent: number;
  nom: string;
  planifiees: number;
  realisees: number;
  supplementaires: number;
  nuit: number;
  dimanches_feries: number;
  astreintes: number;
  depassements?: number;
}

const heures = (minutes: number) => `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, "0")}`;

export function Compteurs() {
  const { peut } = useSession();
  const [periode, setPeriode] = useState(() => {
    const debut = debutMois(new Date());
    return { du: isoJour(debut), au: isoJour(ajouterJours(new Date(debut.getFullYear(), debut.getMonth() + 1, 1), -1)) };
  });
  const compteurs = useQuery({
    queryKey: ["compteurs", periode],
    queryFn: () => requete<LigneCompteur[]>("GET", construireChemin("/api/gestion/personnel/compteurs", periode)),
    enabled: peut("lire_personnel"),
  });
  if (!peut("lire_personnel")) return <DroitsInsuffisants />;
  return (
    <Page
      titre="Compteurs d'heures"
      description="Heures planifiées et réalisées (pointages du mobile), supplémentaires, de nuit (21 h – 6 h), dimanches et jours fériés, astreintes (PER-07)."
      actions={
        <Bouton variante="secondaire" onClick={() => void telecharger(construireChemin("/api/gestion/personnel/compteurs", { ...periode, export: "csv" }), `compteurs-${periode.du}.csv`)}>
          Exporter pour la paie (tableur)
        </Bouton>
      }
    >
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampTexte libelle="Du" type="date" value={periode.du} onChange={(e) => setPeriode({ ...periode, du: e.target.value })} />
        <ChampTexte libelle="Au" type="date" value={periode.au} onChange={(e) => setPeriode({ ...periode, au: e.target.value })} />
      </form>
      {compteurs.isPending ? <Chargement /> : null}
      {compteurs.isError ? <Erreur erreur={compteurs.error} /> : null}
      {compteurs.data ? (
        <Tableau<LigneCompteur>
          legende="Compteurs d'heures par agent"
          lignes={compteurs.data}
          cleLigne={(l) => l.agent}
          messageVide="Aucun agent dans votre périmètre."
          colonnes={[
            { cle: "nom", titre: "Agent", rendu: (l) => l.nom, valeurTri: (l) => l.nom },
            { cle: "planifiees", titre: "Planifiées", rendu: (l) => heures(l.planifiees), valeurTri: (l) => l.planifiees },
            { cle: "realisees", titre: "Réalisées", rendu: (l) => heures(l.realisees), valeurTri: (l) => l.realisees },
            { cle: "supplementaires", titre: "Supplémentaires", rendu: (l) => heures(l.supplementaires), valeurTri: (l) => l.supplementaires },
            { cle: "nuit", titre: "Nuit", rendu: (l) => heures(l.nuit) },
            { cle: "dimanches", titre: "Dimanches et fériés", rendu: (l) => heures(l.dimanches_feries) },
            { cle: "astreintes", titre: "Astreintes", rendu: (l) => heures(l.astreintes) },
          ]}
        />
      ) : null}
    </Page>
  );
}

export function Incidents() {
  const { peut } = useSession();
  const sites = useSites(peut("lire_personnel"));
  return (
    <EcranRessource<Ligne>
      titre="Incidents"
      description="Incidents signalés par les gardiens (application mobile) ou saisis ici, rattachés à la séance et à l'usager (PER-09)."
      chemin="/api/gestion/personnel/incidents"
      cleRequete="incidents"
      actionLecture="lire_personnel"
      actionEcriture="planifier_personnel"
      libelleObjet="Incident"
      colonnes={[
        { cle: "constate", titre: "Constaté le", rendu: (i) => dateHeure(String(i.constate_le)), valeurTri: (i) => String(i.constate_le) },
        { cle: "lieu", titre: "Lieu", rendu: (i) => [i.site_nom, i.espace_nom].filter(Boolean).join(" — ") },
        { cle: "usager", titre: "Usager", rendu: (i) => String(i.usager_nom || "—") },
        { cle: "nature", titre: "Nature", rendu: (i) => libelleDe(NATURES_INCIDENT, i.nature) },
        { cle: "gravite", titre: "Gravité", rendu: (i) => <Badge libelle={libelleDe(GRAVITES, i.gravite)} ton={i.gravite === "mineur" ? "info" : "danger"} /> },
        { cle: "description", titre: "Description", rendu: (i) => String(i.description) },
        { cle: "source", titre: "Source", rendu: (i) => (i.source === "mobile" ? `Mobile (${String(i.signale_par_nom)})` : String(i.signale_par_nom || "Back-office")) },
        { cle: "traite", titre: "Suite", rendu: (i) => (i.traite ? <Badge libelle="Traité" ton="succes" /> : <Badge libelle="À traiter" ton="attention" />) },
      ]}
      champs={[
        { nom: "site", libelle: "Site", type: "selection", obligatoire: true, options: sites, enCreationSeulement: true },
        { nom: "nature", libelle: "Nature", type: "selection", obligatoire: true, options: NATURES_INCIDENT, enCreationSeulement: true },
        { nom: "gravite", libelle: "Gravité", type: "selection", obligatoire: true, options: GRAVITES, enCreationSeulement: true },
        { nom: "constate_le", libelle: "Constaté le", type: "dateheure", obligatoire: true, enCreationSeulement: true },
        { nom: "description", libelle: "Description", type: "zone", obligatoire: true, enCreationSeulement: true },
        { nom: "traite", libelle: "Incident traité", type: "booleen" },
        { nom: "suite_donnee", libelle: "Suite donnée", type: "zone" },
      ]}
      valeursInitiales={{ gravite: "mineur" }}
      filtres={[
        { nom: "site", libelle: "Site", options: sites },
        { nom: "traite", libelle: "Suite", options: [{ valeur: "false", libelle: "À traiter" }, { valeur: "true", libelle: "Traités" }] },
        { nom: "gravite", libelle: "Gravité", options: GRAVITES },
      ]}
    />
  );
}

function RetirerAppareil({ appareil }: { appareil: Ligne }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const operation = useMutation({
    mutationFn: (action: "retirer" | "autoriser") => requete<Ligne>("POST", `/api/gestion/personnel/appareils/${appareil.id}/${action}`),
    onSuccess: async (_r, action) => {
      annoncer(action === "retirer" ? "Appareil retiré : ses sessions sont coupées." : "Appareil autorisé : l'agent peut se connecter.");
      await client.invalidateQueries({ queryKey: ["appareils"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });
  if (!peut("gerer_appareils")) return null;
  if (appareil.a_autoriser && !appareil.revoque_le)
    return (
      <Bouton variante="lien" onClick={() => operation.mutate("autoriser")} enCours={operation.isPending}>
        Autoriser cet appareil<span className="sr-only"> : {String(appareil.libelle)}</span>
      </Bouton>
    );
  if (!appareil.actif) return null;
  return (
    <Bouton variante="lien" onClick={() => operation.mutate("retirer")} enCours={operation.isPending}>
      Retirer (perte, vol)<span className="sr-only"> : {String(appareil.libelle)}</span>
    </Bouton>
  );
}

export function Appareils() {
  const { peut } = useSession();
  const agents = useAgents(peut("lire_personnel"));
  return (
    <EcranRessource<Ligne>
      titre="Appareils mobiles"
      description="Smartphones des gardiens. Retirer un appareil coupe immédiatement ses sessions ; après un retrait, le nouvel appareil de l'agent attend votre autorisation. En accès par Internet (option B), l'empreinte du certificat d'appareil est exigée (SEC-10)."
      chemin="/api/gestion/personnel/appareils"
      cleRequete="appareils"
      actionLecture="lire_personnel"
      actionEcriture="gerer_appareils"
      libelleObjet="Appareil"
      colonnes={[
        { cle: "agent", titre: "Agent", rendu: (a) => String(a.agent_nom) },
        { cle: "libelle", titre: "Appareil", rendu: (a) => String(a.libelle) },
        { cle: "certificat", titre: "Certificat", rendu: (a) => (a.empreinte_certificat ? `${String(a.empreinte_certificat).slice(0, 16)}…` : "—") },
        { cle: "synchro", titre: "Dernière synchronisation", rendu: (a) => (a.derniere_synchronisation ? dateHeure(String(a.derniere_synchronisation)) : "Jamais") },
        {
          cle: "etat",
          titre: "État",
          rendu: (a) =>
            a.actif ? (
              <Badge libelle="Actif" ton="succes" />
            ) : a.a_autoriser && !a.revoque_le ? (
              <Badge libelle="À autoriser (nouvel appareil)" ton="attention" />
            ) : (
              <Badge libelle={`Retiré le ${a.revoque_le ? dateSimple(String(a.revoque_le)) : ""}`} ton="danger" />
            ),
        },
      ]}
      champs={[
        { nom: "agent", libelle: "Agent", type: "selection", obligatoire: true, options: agents },
        { nom: "libelle", libelle: "Désignation de l'appareil", type: "texte", obligatoire: true },
        { nom: "certificat", libelle: "Certificat d'appareil (PEM, option B)", type: "zone", aide: "Collez le certificat délivré par l'autorité interne." },
      ]}
      filtres={[
        { nom: "agent", libelle: "Agent", options: agents },
        { nom: "actif", libelle: "État", options: [{ valeur: "true", libelle: "Actifs" }, { valeur: "false", libelle: "Retirés" }] },
      ]}
      actionsLigne={(a) => <RetirerAppareil appareil={a} />}
    />
  );
}

interface Saisie {
  id: number;
  agent_nom: string;
  type: string;
  horodatage_appareil: string;
  statut: string;
  message: string;
  recue_le: string;
  donnees: Record<string, unknown>;
  traitee_par?: number | null;
}
const STATUTS_SAISIE: Record<string, { libelle: string; ton: "succes" | "attention" | "danger" }> = {
  acceptee: { libelle: "Acceptée", ton: "succes" },
  conflit: { libelle: "Conflit à examiner", ton: "attention" },
  rejetee: { libelle: "Rejetée", ton: "danger" },
};
const TYPES_SAISIE: Record<string, string> = { pointage: "Pointage", etat_des_lieux: "État des lieux", incident: "Incident" };

export function Saisies() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [parametres] = useSearchParams();
  const [statut, setStatut] = useState(() => parametres.get("statut") ?? "conflit");
  const saisies = useQuery({
    queryKey: ["saisies-mobiles", statut],
    queryFn: async () => (await requete<PageApi<Saisie>>("GET", construireChemin("/api/gestion/personnel/saisies", { statut, taille: 200 }))).results,
    enabled: peut("lire_personnel"),
  });
  const examiner = useMutation({
    mutationFn: (id: number) => requete<Saisie>("POST", `/api/gestion/personnel/saisies/${id}/examinee`),
    onSuccess: async () => {
      annoncer("Saisie marquée comme examinée.");
      await client.invalidateQueries({ queryKey: ["saisies-mobiles"] });
    },
  });
  if (!peut("lire_personnel")) return <DroitsInsuffisants />;
  return (
    <Page titre="Saisies du terrain" description="Saisies reçues de l'application mobile. Une saisie sur une séance annulée ou modifiée entre-temps est conservée et signalée ici (MOB-06).">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <div className="champ">
          <label htmlFor="statut-saisie">État</label>
          <select id="statut-saisie" value={statut} onChange={(e) => setStatut(e.target.value)}>
            <option value="">Toutes</option>
            {Object.entries(STATUTS_SAISIE).map(([valeur, s]) => (
              <option key={valeur} value={valeur}>
                {s.libelle}
              </option>
            ))}
          </select>
        </div>
      </form>
      {saisies.isPending ? <Chargement /> : null}
      {saisies.isError ? <Erreur erreur={saisies.error} /> : null}
      {saisies.data ? (
        <Tableau<Saisie>
          legende="Saisies reçues du terrain"
          lignes={saisies.data}
          cleLigne={(s) => s.id}
          messageVide="Aucune saisie."
          colonnes={[
            { cle: "horodatage", titre: "Saisie le (appareil)", rendu: (s) => dateHeure(s.horodatage_appareil), valeurTri: (s) => s.horodatage_appareil },
            { cle: "recue", titre: "Reçue le", rendu: (s) => dateHeure(s.recue_le) },
            { cle: "agent", titre: "Agent", rendu: (s) => s.agent_nom },
            { cle: "type", titre: "Type", rendu: (s) => TYPES_SAISIE[s.type] ?? s.type },
            { cle: "statut", titre: "État", rendu: (s) => <Badge libelle={STATUTS_SAISIE[s.statut]?.libelle ?? s.statut} ton={STATUTS_SAISIE[s.statut]?.ton ?? "attention"} /> },
            { cle: "message", titre: "Signalement", rendu: (s) => s.message || "—" },
          ]}
          actions={(s) =>
            s.statut !== "acceptee" && peut("planifier_personnel") ? (
              <Bouton variante="lien" onClick={() => examiner.mutate(s.id)}>
                Marquer examinée<span className="sr-only"> : saisie de {s.agent_nom} du {dateHeure(s.horodatage_appareil)}</span>
              </Bouton>
            ) : null
          }
        />
      ) : null}
    </Page>
  );
}
