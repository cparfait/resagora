/** MAT-01 à MAT-05 : catalogue, état du stock et mouvements, prêts rattachés aux dossiers, contrôles périodiques et
 * pannes. Les quantités ne changent que par des mouvements tracés ; la disponibilité est calculée par l'API. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { dateHeure, dateSimple, euros, isoJour } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

type Ligne = Record<string, unknown> & { id: number };

const NATURES = [
  { valeur: "mobile", libelle: "Matériel mobile, prêté" },
  { valeur: "fixe", libelle: "Équipement fixe d'un espace" },
  { valeur: "consommable", libelle: "Consommable" },
];
const STATUTS_PRET: Record<string, { libelle: string; ton: "neutre" | "info" | "succes" | "attention" | "danger" }> = {
  demandee: { libelle: "Demandé (portail)", ton: "attention" },
  validee: { libelle: "Validé", ton: "info" },
  sortie: { libelle: "Sorti", ton: "info" },
  rendue: { libelle: "Rendu", ton: "succes" },
  refusee: { libelle: "Refusé", ton: "neutre" },
  annulee: { libelle: "Annulé", ton: "neutre" },
};

function useOperation(cles: string[], message: string) {
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  return useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete<unknown>("POST", url, corps),
    onSuccess: async () => {
      annoncer(message);
      for (const cle of cles) await client.invalidateQueries({ queryKey: [cle] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });
}

/** Valeur de référence et prestation facturée : fixées par le service financier (séparation des tâches). */
function TarifMateriel({ materiel }: { materiel: Ligne }) {
  const { peut } = useSession();
  const [ouvert, setOuvert] = useState(false);
  const [saisie, setSaisie] = useState({ valeur: "", prestation: "" });
  const operation = useOperation(["materiels", "options"], "Tarif du matériel enregistré.");
  if (!peut("gerer_tarifs")) return null;
  return (
    <>
      <Bouton
        variante="lien"
        onClick={() => {
          setSaisie({ valeur: (Number(materiel.valeur_journaliere_centimes) / 100).toFixed(2).replace(".", ","), prestation: String(materiel.prestation_code ?? "") });
          setOuvert(true);
        }}
      >
        Tarif<span className="visuellement-masque"> : {String(materiel.libelle)}</span>
      </Bouton>
      <Dialogue ouvert={ouvert} titre={`Tarif — ${String(materiel.libelle)}`} onFermer={() => setOuvert(false)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            operation.mutate({
              url: `/api/gestion/materiel/catalogue/${materiel.id}/tarif`,
              corps: { valeur_journaliere_centimes: Math.round(Number(saisie.valeur.replace(/\s/g, "").replace(",", ".")) * 100), prestation_code: saisie.prestation.trim() },
            });
            setOuvert(false);
          }}
        >
          <ChampTexte libelle="Valeur de référence d'une journée (€)" obligatoire inputMode="decimal" value={saisie.valeur} onChange={(e) => setSaisie({ ...saisie, valeur: e.target.value })} aide="Sert à valoriser les prêts gratuits (avantages en nature)." />
          <ChampTexte libelle="Code de la prestation facturée (vide si gratuit)" value={saisie.prestation} onChange={(e) => setSaisie({ ...saisie, prestation: e.target.value })} aide="Doit exister dans la grille tarifaire en vigueur." />
          <div className="actions">
            <Bouton type="submit" enCours={operation.isPending}>
              Enregistrer
            </Bouton>
            <Bouton variante="secondaire" onClick={() => setOuvert(false)}>
              Annuler
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </>
  );
}

export function Catalogue() {
  return (
    <EcranRessource<Ligne>
      titre="Catalogue du matériel"
      description="Mobilier, sonorisation, équipements fixes des espaces et consommables. La valeur d'une journée sert à valoriser les prêts gratuits ; la prestation désigne la ligne facturée de la grille tarifaire."
      chemin="/api/gestion/materiel/catalogue"
      cleRequete="materiels"
      actionLecture="lire_materiel"
      actionEcriture="gerer_materiel"
      libelleObjet="Matériel"
      colonnes={[
        { cle: "libelle", titre: "Matériel", rendu: (m) => String(m.libelle), valeurTri: (m) => String(m.libelle) },
        { cle: "nature", titre: "Nature", rendu: (m) => NATURES.find((n) => n.valeur === m.nature)?.libelle ?? String(m.nature) },
        { cle: "valeur", titre: "Valeur d'une journée", rendu: (m) => euros(Number(m.valeur_journaliere_centimes)) },
        { cle: "controle", titre: "Contrôle", rendu: (m) => (m.periodicite_controle_jours ? `tous les ${String(m.periodicite_controle_jours)} jours` : "—") },
        {
          cle: "options",
          titre: "Prêt",
          rendu: (m) => (
            <span className="badges">
              {m.reservable ? <Badge libelle="Réservable" ton="info" /> : <Badge libelle="Non réservable" />}
              {m.propose_portail ? <Badge libelle="Proposé en ligne" ton="succes" /> : null}
              {!m.actif ? <Badge libelle="Inactif" ton="attention" /> : null}
            </span>
          ),
        },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true, enCreationSeulement: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "nature", libelle: "Nature", type: "selection", obligatoire: true, options: NATURES },
        { nom: "description", libelle: "Description", type: "zone" },
        { nom: "unite", libelle: "Unité", type: "texte", obligatoire: true },
        { nom: "reservable", libelle: "Réservable", type: "booleen" },
        { nom: "propose_portail", libelle: "Proposé aux usagers sur le portail", type: "booleen" },
        { nom: "periodicite_controle_jours", libelle: "Périodicité du contrôle (jours)", type: "nombre" },
        { nom: "seuil_alerte", libelle: "Seuil d'alerte (consommables)", type: "nombre" },
        { nom: "actif", libelle: "Actif", type: "booleen" },
      ]}
      valeursInitiales={{ nature: "mobile", unite: "unité", reservable: true, actif: true }}
      filtres={[{ nom: "nature", libelle: "Nature", options: NATURES }]}
      actionsLigne={(m) => <TarifMateriel materiel={m} />}
    />
  );
}

interface LigneStock {
  id: number;
  materiel: number;
  materiel_libelle: string;
  nature: string;
  unite: string;
  site: number;
  site_nom: string;
  espace_nom: string;
  quantite: number;
  hors_service: number;
  sortis: number;
  sur_place: number;
  prets_a_venir: number;
  echeance_controle: string | null;
  sous_seuil: boolean;
}

type ActionStock = { type: "transferer" | "perte" | "inventaire" | "panne" | "controle"; stock: LigneStock } | { type: "entrer" } | null;

const TITRES: Record<string, string> = {
  entrer: "Entrée en stock",
  transferer: "Transférer vers un autre lieu",
  perte: "Déclarer une perte ou un vol",
  inventaire: "Ajuster à l'inventaire",
  panne: "Signaler une panne",
  controle: "Enregistrer un contrôle",
};

export function Stocks() {
  const { peut } = useSession();
  const lecture = peut("lire_materiel");
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`, lecture);
  const materiels = useOptions("materiels", "/api/gestion/materiel/catalogue", (m) => String(m.libelle), lecture);
  const [site, setSite] = useState("");
  const [action, setAction] = useState<ActionStock>(null);
  const [aujourdhui] = useState(() => isoJour(new Date()));
  const vide = { quantite: "1", motif: "", site: "", espace: "", materiel: "", description: "", realise_le: aujourdhui, conforme: true, prestataire: "" };
  const [saisie, setSaisie] = useState(vide);
  const etat = useQuery({
    queryKey: ["stocks", site],
    queryFn: () => requete<LigneStock[]>("GET", construireChemin("/api/gestion/materiel/stocks/etat", { site })),
    enabled: lecture,
  });
  const operation = useOperation(["stocks", "pannes", "controles", "mouvements"], "Stock mis à jour.");
  if (!lecture) return <DroitsInsuffisants />;
  const ecriture = peut("gerer_materiel");
  const ouvrir = (a: ActionStock) => {
    setSaisie(vide);
    setAction(a);
  };
  const valider = () => {
    if (!action) return;
    const quantite = Number(saisie.quantite);
    if (action.type === "entrer")
      operation.mutate({ url: "/api/gestion/materiel/stocks/entrer", corps: { materiel: Number(saisie.materiel), site: Number(saisie.site), espace: saisie.espace ? Number(saisie.espace) : null, quantite, motif: saisie.motif } });
    else {
      const base = `/api/gestion/materiel/stocks/${action.stock.id}`;
      if (action.type === "transferer") operation.mutate({ url: `${base}/transferer`, corps: { site: Number(saisie.site), espace: saisie.espace ? Number(saisie.espace) : null, quantite, motif: saisie.motif } });
      if (action.type === "perte" || action.type === "inventaire") operation.mutate({ url: `${base}/${action.type}`, corps: { quantite, motif: saisie.motif } });
      if (action.type === "panne") operation.mutate({ url: `${base}/panne`, corps: { quantite, description: saisie.description } });
      if (action.type === "controle") operation.mutate({ url: `${base}/controle`, corps: { realise_le: saisie.realise_le, conforme: saisie.conforme, observations: saisie.description, prestataire: saisie.prestataire } });
    }
    setAction(null);
  };
  const champLieu = (
    <>
      <ChampSelection libelle="Site" obligatoire options={sites} value={saisie.site} onChange={(e) => setSaisie({ ...saisie, site: e.target.value })} />
      <ChampSelection libelle="Espace (matériel fixe)" options={espaces} value={saisie.espace} onChange={(e) => setSaisie({ ...saisie, espace: e.target.value })} />
    </>
  );
  return (
    <Page
      titre="État du stock"
      description="Quantités par lieu : sur place, sorties en prêt, hors service, prêts à venir et échéance du contrôle périodique."
      actions={
        <>
          {ecriture ? <Bouton onClick={() => ouvrir({ type: "entrer" })}>Entrée en stock</Bouton> : null}
          <Bouton variante="secondaire" onClick={() => void telecharger(construireChemin("/api/gestion/materiel/stocks/etat", { site, export: "csv" }), "etat-du-stock.csv")}>
            Exporter (tableur)
          </Bouton>
        </>
      }
    >
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Site" videLibelle="Tous mes sites" options={sites} value={site} onChange={(e) => setSite(e.target.value)} />
      </form>
      {etat.isPending ? <Chargement /> : null}
      {etat.isError ? <Erreur erreur={etat.error} /> : null}
      {etat.data ? (
        <Tableau<LigneStock>
          legende="État du stock"
          lignes={etat.data}
          cleLigne={(s) => s.id}
          messageVide="Aucun matériel en stock dans votre périmètre."
          colonnes={[
            { cle: "materiel", titre: "Matériel", rendu: (s) => s.materiel_libelle, valeurTri: (s) => s.materiel_libelle },
            { cle: "lieu", titre: "Lieu", rendu: (s) => [s.site_nom, s.espace_nom].filter(Boolean).join(" — ") },
            { cle: "quantite", titre: "Quantité", rendu: (s) => `${s.quantite} ${s.unite}(s)`, valeurTri: (s) => s.quantite },
            { cle: "sur_place", titre: "Sur place", rendu: (s) => String(s.sur_place) },
            { cle: "sortis", titre: "Sortis", rendu: (s) => String(s.sortis) },
            { cle: "hs", titre: "Hors service", rendu: (s) => (s.hors_service ? <Badge libelle={String(s.hors_service)} ton="danger" /> : "0") },
            { cle: "a_venir", titre: "Prêts à venir", rendu: (s) => String(s.prets_a_venir) },
            {
              cle: "controle",
              titre: "Contrôle attendu",
              rendu: (s) =>
                s.echeance_controle ? (
                  <Badge libelle={dateSimple(s.echeance_controle)} ton={s.echeance_controle <= aujourdhui ? "danger" : "neutre"} />
                ) : (
                  "—"
                ),
            },
            { cle: "seuil", titre: "Alerte", rendu: (s) => (s.sous_seuil ? <Badge libelle="Sous le seuil" ton="attention" /> : "") },
          ]}
          actions={(s) => (
            <span className="actions">
              <Bouton variante="lien" onClick={() => ouvrir({ type: "panne", stock: s })}>
                Panne<span className="visuellement-masque"> : {s.materiel_libelle}, {s.site_nom}</span>
              </Bouton>
              {ecriture ? (
                <>
                  <Bouton variante="lien" onClick={() => ouvrir({ type: "controle", stock: s })}>
                    Contrôle<span className="visuellement-masque"> : {s.materiel_libelle}, {s.site_nom}</span>
                  </Bouton>
                  <Bouton variante="lien" onClick={() => ouvrir({ type: "transferer", stock: s })}>
                    Transférer<span className="visuellement-masque"> : {s.materiel_libelle}, {s.site_nom}</span>
                  </Bouton>
                  <Bouton variante="lien" onClick={() => ouvrir({ type: "perte", stock: s })}>
                    Perte<span className="visuellement-masque"> : {s.materiel_libelle}, {s.site_nom}</span>
                  </Bouton>
                  <Bouton variante="lien" onClick={() => ouvrir({ type: "inventaire", stock: s })}>
                    Inventaire<span className="visuellement-masque"> : {s.materiel_libelle}, {s.site_nom}</span>
                  </Bouton>
                </>
              ) : null}
            </span>
          )}
        />
      ) : null}
      <Dialogue ouvert={action !== null} titre={action ? `${TITRES[action.type]}${"stock" in action ? ` — ${action.stock.materiel_libelle}` : ""}` : ""} onFermer={() => setAction(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            valider();
          }}
        >
          {action?.type === "entrer" ? (
            <>
              <ChampSelection libelle="Matériel" obligatoire options={materiels} value={saisie.materiel} onChange={(e) => setSaisie({ ...saisie, materiel: e.target.value })} />
              {champLieu}
            </>
          ) : null}
          {action?.type === "transferer" ? champLieu : null}
          {action && action.type !== "controle" ? (
            <ChampTexte
              libelle={action.type === "inventaire" ? "Quantité comptée" : "Quantité"}
              type="number"
              min={action.type === "inventaire" ? 0 : 1}
              obligatoire
              value={saisie.quantite}
              onChange={(e) => setSaisie({ ...saisie, quantite: e.target.value })}
            />
          ) : null}
          {action?.type === "controle" ? (
            <>
              <ChampTexte libelle="Réalisé le" type="date" obligatoire value={saisie.realise_le} onChange={(e) => setSaisie({ ...saisie, realise_le: e.target.value })} />
              <CaseACocher libelle="Conforme" checked={saisie.conforme} onChange={(e) => setSaisie({ ...saisie, conforme: e.target.checked })} />
              <ChampTexte libelle="Prestataire" value={saisie.prestataire} onChange={(e) => setSaisie({ ...saisie, prestataire: e.target.value })} />
            </>
          ) : null}
          {action?.type === "panne" || action?.type === "controle" ? (
            <ChampZone
              libelle={action.type === "panne" ? "Description de la panne" : "Observations (obligatoires si non conforme)"}
              obligatoire={action.type === "panne"}
              value={saisie.description}
              onChange={(e) => setSaisie({ ...saisie, description: e.target.value })}
            />
          ) : null}
          {action && ["entrer", "transferer", "perte", "inventaire"].includes(action.type) ? (
            <ChampTexte libelle="Motif" obligatoire={action.type === "perte"} value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
          ) : null}
          <div className="actions">
            <Bouton type="submit" enCours={operation.isPending}>
              Valider
            </Bouton>
            <Bouton variante="secondaire" onClick={() => setAction(null)}>
              Annuler
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </Page>
  );
}

interface Pret {
  id: number;
  dossier: number;
  dossier_numero: string;
  usager_nom: string;
  materiel_libelle: string;
  unite: string;
  site_nom: string;
  quantite: number;
  debut: string;
  fin: string;
  statut: string;
  quantite_sortie: number | null;
  quantite_rendue: number | null;
  manquants: number;
  manquants_regles: boolean;
  origine: string;
  motif: string;
  signalement: string;
}

type ActionPret = { type: "refuser" | "sortir" | "rendre" | "retrouver" | "regler-manquants"; pret: Pret } | null;

function TableauPrets({ prets, titre }: { prets: Pret[]; titre: string }) {
  const { peut } = useSession();
  const operation = useOperation(["prets", "stocks", "mouvements"], "Prêt mis à jour.");
  const [action, setAction] = useState<ActionPret>(null);
  const [saisie, setSaisie] = useState({ quantite: "", motif: "", observations: "", solde: true });
  const ouvrir = (type: NonNullable<ActionPret>["type"], pret: Pret) => {
    const restant = (pret.quantite_sortie ?? pret.quantite) - (pret.quantite_rendue ?? 0);
    setSaisie({ quantite: String(type === "rendre" ? restant : type === "retrouver" ? pret.manquants : pret.quantite), motif: "", observations: "", solde: true });
    setAction({ type, pret });
  };
  const valider = () => {
    if (!action) return;
    const url = `/api/gestion/materiel/prets/${action.pret.id}/${action.type}`;
    if (action.type === "refuser") operation.mutate({ url, corps: { motif: saisie.motif } });
    if (action.type === "regler-manquants") operation.mutate({ url, corps: { decision: saisie.motif } });
    if (action.type === "sortir" || action.type === "retrouver") operation.mutate({ url, corps: { quantite: Number(saisie.quantite) } });
    if (action.type === "rendre") operation.mutate({ url, corps: { quantite: Number(saisie.quantite), observations: saisie.observations, solde: saisie.solde } });
    setAction(null);
  };
  const decrire = (p: Pret) => `${p.quantite} ${p.materiel_libelle}, dossier ${p.dossier_numero}`;
  return (
    <>
      <Tableau<Pret>
        legende={titre}
        lignes={prets}
        cleLigne={(p) => p.id}
        messageVide="Aucun prêt."
        colonnes={[
          { cle: "debut", titre: "Période", rendu: (p) => `${dateHeure(p.debut)} → ${dateHeure(p.fin)}`, valeurTri: (p) => p.debut },
          { cle: "materiel", titre: "Matériel", rendu: (p) => `${p.quantite} × ${p.materiel_libelle}` },
          { cle: "dossier", titre: "Dossier", rendu: (p) => `${p.dossier_numero} — ${p.usager_nom}` },
          { cle: "site", titre: "Site", rendu: (p) => p.site_nom },
          { cle: "statut", titre: "État", rendu: (p) => <Badge libelle={STATUTS_PRET[p.statut]?.libelle ?? p.statut} ton={STATUTS_PRET[p.statut]?.ton ?? "neutre"} /> },
          {
            cle: "suivi",
            titre: "Suivi",
            rendu: (p) =>
              [p.quantite_sortie !== null ? `${p.quantite_sortie} sorti(s)` : "", p.quantite_rendue !== null ? `${p.quantite_rendue} rendu(s)` : "", p.manquants ? `${p.manquants} manquant(s)` : "", p.signalement, p.motif]
                .filter(Boolean)
                .join(" — ") || "—",
          },
        ]}
        actions={(p) => (
          <span className="actions">
            {p.statut === "demandee" && peut("creer_reservation") ? (
              <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/materiel/prets/${p.id}/valider` })}>
                Valider<span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
            {["demandee", "validee"].includes(p.statut) && peut("creer_reservation") ? (
              <Bouton variante="lien" onClick={() => ouvrir("refuser", p)}>
                {p.statut === "demandee" ? "Refuser" : "Annuler"}
                <span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
            {p.statut === "validee" && peut("gerer_materiel") ? (
              <Bouton variante="lien" onClick={() => ouvrir("sortir", p)}>
                Remettre<span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
            {p.statut === "sortie" && peut("gerer_materiel") ? (
              <Bouton variante="lien" onClick={() => ouvrir("rendre", p)}>
                Enregistrer le retour<span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
            {p.manquants > 0 && peut("gerer_materiel") ? (
              <Bouton variante="lien" onClick={() => ouvrir("retrouver", p)}>
                Manquants rapportés<span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
            {p.manquants > 0 && !p.manquants_regles && peut("gerer_materiel") ? (
              <Bouton variante="lien" onClick={() => ouvrir("regler-manquants", p)}>
                Statuer sur les manquants<span className="visuellement-masque"> : {decrire(p)}</span>
              </Bouton>
            ) : null}
          </span>
        )}
      />
      <Dialogue ouvert={action !== null} titre={action ? { refuser: "Refuser ou annuler le prêt", sortir: "Remise du matériel", rendre: "Retour du matériel", retrouver: "Manquants rapportés", "regler-manquants": "Décision sur les manquants" }[action.type] : ""} onFermer={() => setAction(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            valider();
          }}
        >
          {action ? <p>{decrire(action.pret)}</p> : null}
          {action?.type === "refuser" || action?.type === "regler-manquants" ? (
            <ChampZone
              libelle={action.type === "refuser" ? "Motif (communiqué à l'usager)" : "Décision (retenue proposée sur la caution, prise en charge par la Ville…)"}
              obligatoire
              value={saisie.motif}
              onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })}
            />
          ) : (
            <ChampTexte
              libelle={action?.type === "rendre" ? "Quantité rendue" : "Quantité"}
              type="number"
              min={action?.type === "rendre" ? 0 : 1}
              obligatoire
              value={saisie.quantite}
              onChange={(e) => setSaisie({ ...saisie, quantite: e.target.value })}
              aide={action?.type === "rendre" ? "Le non-rendu est retiré du stock et signalé au service (consommé pour un consommable)." : undefined}
            />
          )}
          {action?.type === "rendre" ? (
            <>
              <ChampTexte libelle="Observations" value={saisie.observations} onChange={(e) => setSaisie({ ...saisie, observations: e.target.value })} />
              <CaseACocher libelle="Retour complet : les unités non rendues sont déclarées manquantes" checked={saisie.solde} onChange={(e) => setSaisie({ ...saisie, solde: e.target.checked })} />
            </>
          ) : null}
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
    </>
  );
}

export function Prets() {
  const { peut } = useSession();
  const [statut, setStatut] = useState("demandee,validee,sortie");
  const prets = useQuery({
    queryKey: ["prets", statut],
    queryFn: async () => (await requete<PageApi<Pret>>("GET", construireChemin("/api/gestion/materiel/prets", { statut__in: statut, taille: 300 }))).results,
    enabled: peut("lire_materiel"),
  });
  if (!peut("lire_materiel")) return <DroitsInsuffisants />;
  return (
    <Page titre="Prêts de matériel" description="Demandes du portail à valider, prêts à remettre et retours à enregistrer. Une demande n'immobilise le matériel qu'une fois validée.">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection
          libelle="Prêts"
          options={[
            { valeur: "demandee,validee,sortie", libelle: "En cours" },
            { valeur: "demandee", libelle: "Demandes à valider" },
            { valeur: "sortie", libelle: "Sortis (retour attendu)" },
            { valeur: "rendue,refusee,annulee", libelle: "Terminés" },
          ]}
          value={statut}
          onChange={(e) => setStatut(e.target.value)}
        />
      </form>
      {prets.isPending ? <Chargement /> : null}
      {prets.isError ? <Erreur erreur={prets.error} /> : null}
      {prets.data ? <TableauPrets prets={prets.data} titre="Prêts de matériel" /> : null}
    </Page>
  );
}

/** Matériel du dossier (fiche dossier) : prêts et ajout d'un prêt sur une réservation du dossier. */
export function MaterielDossier({ dossier, reservations }: { dossier: number; reservations: { id: number; espace_nom: string; site: number }[] }) {
  const { peut } = useSession();
  const [ajout, setAjout] = useState(false);
  const [saisie, setSaisie] = useState({ reservation: "", stock: "", quantite: "1", commentaire: "" });
  const prets = useQuery({
    queryKey: ["prets", "dossier", dossier],
    queryFn: async () => (await requete<PageApi<Pret>>("GET", construireChemin("/api/gestion/materiel/prets", { dossier, taille: 100 }))).results,
  });
  const site = reservations.find((r) => String(r.id) === saisie.reservation)?.site;
  const stocks = useQuery({
    queryKey: ["stocks", "site", site],
    queryFn: async () => (await requete<PageApi<LigneStock>>("GET", construireChemin("/api/gestion/materiel/stocks", { site, taille: 200 }))).results,
    enabled: ajout && site !== undefined,
  });
  const operation = useOperation(["prets", "stocks"], "Prêt de matériel enregistré pour les séances à venir.");
  const contenu: ReactNode = prets.data ? <TableauPrets prets={prets.data} titre="Matériel du dossier" /> : null;
  return (
    <section aria-labelledby="titre-materiel" className="carte">
      <h2 id="titre-materiel">Matériel</h2>
      {prets.isPending ? <Chargement /> : null}
      {prets.isError ? <Erreur erreur={prets.error} /> : null}
      {contenu}
      {peut("creer_reservation") && reservations.length ? (
        <Bouton variante="secondaire" onClick={() => setAjout(true)}>
          Prêter du matériel
        </Bouton>
      ) : null}
      <Dialogue ouvert={ajout} titre="Prêter du matériel" onFermer={() => setAjout(false)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            operation.mutate({ url: "/api/gestion/materiel/prets", corps: { dossier, reservation: Number(saisie.reservation), stock: Number(saisie.stock), quantite: Number(saisie.quantite), commentaire: saisie.commentaire } });
            setAjout(false);
          }}
        >
          <ChampSelection libelle="Réservation" obligatoire options={reservations.map((r) => ({ valeur: String(r.id), libelle: r.espace_nom }))} value={saisie.reservation} onChange={(e) => setSaisie({ ...saisie, reservation: e.target.value, stock: "" })} />
          <ChampSelection
            libelle="Matériel du site"
            obligatoire
            options={(stocks.data ?? []).filter((s) => s.nature !== "fixe").map((s) => ({ valeur: String(s.id), libelle: `${s.materiel_libelle} (${s.quantite - s.hors_service} en état)` }))}
            value={saisie.stock}
            onChange={(e) => setSaisie({ ...saisie, stock: e.target.value })}
          />
          <ChampTexte libelle="Quantité" type="number" min={1} obligatoire value={saisie.quantite} onChange={(e) => setSaisie({ ...saisie, quantite: e.target.value })} aide="Un prêt par séance à venir de la réservation ; la disponibilité est vérifiée pour chacune." />
          <ChampTexte libelle="Commentaire" value={saisie.commentaire} onChange={(e) => setSaisie({ ...saisie, commentaire: e.target.value })} />
          <div className="actions">
            <Bouton type="submit" enCours={operation.isPending}>
              Enregistrer le prêt
            </Bouton>
            <Bouton variante="secondaire" onClick={() => setAjout(false)}>
              Annuler
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </section>
  );
}

interface Alertes {
  controles: (LigneStock & { echeance: string })[];
  seuils: LigneStock[];
}

export function Controles() {
  const { peut } = useSession();
  const alertes = useQuery({ queryKey: ["controles", "alertes"], queryFn: () => requete<Alertes>("GET", "/api/gestion/materiel/stocks/alertes"), enabled: peut("lire_materiel") });
  const historique = useQuery({
    queryKey: ["controles"],
    queryFn: async () => (await requete<PageApi<Ligne>>("GET", construireChemin("/api/gestion/materiel/controles", { taille: 100 }))).results,
    enabled: peut("lire_materiel"),
  });
  if (!peut("lire_materiel")) return <DroitsInsuffisants />;
  return (
    <Page titre="Contrôles et maintenance" description="Contrôles périodiques dépassés (buts, paniers, barnums, défibrillateurs…) et consommables sous le seuil ; un contrôle se saisit depuis l'état du stock.">
      {alertes.isPending ? <Chargement /> : null}
      {alertes.isError ? <Erreur erreur={alertes.error} /> : null}
      {alertes.data ? (
        <>
          <h2>Contrôles dépassés ({alertes.data.controles.length})</h2>
          <Tableau<LigneStock & { echeance: string }>
            legende="Contrôles dépassés"
            lignes={alertes.data.controles}
            cleLigne={(s) => s.id}
            messageVide="Aucun contrôle en retard."
            colonnes={[
              { cle: "materiel", titre: "Matériel", rendu: (s) => s.materiel_libelle },
              { cle: "lieu", titre: "Lieu", rendu: (s) => [s.site_nom, s.espace_nom].filter(Boolean).join(" — ") },
              { cle: "echeance", titre: "Attendu le", rendu: (s) => <Badge libelle={dateSimple(s.echeance)} ton="danger" /> },
            ]}
          />
          <h2>Consommables sous le seuil ({alertes.data.seuils.length})</h2>
          <Tableau<LigneStock>
            legende="Consommables sous le seuil"
            lignes={alertes.data.seuils}
            cleLigne={(s) => s.id}
            messageVide="Aucun consommable sous le seuil."
            colonnes={[
              { cle: "materiel", titre: "Consommable", rendu: (s) => s.materiel_libelle },
              { cle: "lieu", titre: "Lieu", rendu: (s) => s.site_nom },
              { cle: "quantite", titre: "En stock", rendu: (s) => String(s.quantite - s.hors_service) },
            ]}
          />
        </>
      ) : null}
      <h2>Historique</h2>
      {historique.data ? (
        <Tableau<Ligne>
          legende="Historique des contrôles"
          lignes={historique.data}
          cleLigne={(c) => c.id}
          messageVide="Aucun contrôle enregistré."
          colonnes={[
            { cle: "date", titre: "Réalisé le", rendu: (c) => dateSimple(String(c.realise_le)), valeurTri: (c) => String(c.realise_le) },
            { cle: "stock", titre: "Matériel", rendu: (c) => String(c.stock_libelle) },
            { cle: "nature", titre: "Nature", rendu: (c) => ({ controle: "Contrôle périodique", maintenance: "Maintenance", reparation: "Réparation" })[String(c.nature)] ?? String(c.nature) },
            { cle: "resultat", titre: "Résultat", rendu: (c) => (c.conforme ? <Badge libelle="Conforme" ton="succes" /> : <Badge libelle="Non conforme" ton="danger" />) },
            { cle: "prochain", titre: "Prochain", rendu: (c) => (c.prochain_le ? dateSimple(String(c.prochain_le)) : "—") },
            { cle: "obs", titre: "Observations", rendu: (c) => String(c.observations || c.prestataire || "—") },
          ]}
        />
      ) : null}
    </Page>
  );
}

export function Pannes() {
  const { peut } = useSession();
  const [statut, setStatut] = useState("ouverte");
  const [resolution, setResolution] = useState<{ panne: Ligne; issue: string; texte: string } | null>(null);
  const pannes = useQuery({
    queryKey: ["pannes", statut],
    queryFn: async () => (await requete<PageApi<Ligne>>("GET", construireChemin("/api/gestion/materiel/pannes", { statut, taille: 200 }))).results,
    enabled: peut("lire_materiel"),
  });
  const operation = useOperation(["pannes", "stocks"], "Panne résolue.");
  if (!peut("lire_materiel")) return <DroitsInsuffisants />;
  return (
    <Page titre="Pannes" description="Le matériel en panne est retiré de la disponibilité : il n'est plus réservable jusqu'à sa réparation (MAT-05).">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection
          libelle="État"
          options={[
            { valeur: "ouverte", libelle: "En panne" },
            { valeur: "reparee", libelle: "Réparées" },
            { valeur: "rebut", libelle: "Mises au rebut" },
          ]}
          value={statut}
          onChange={(e) => setStatut(e.target.value)}
        />
      </form>
      {pannes.isPending ? <Chargement /> : null}
      {pannes.data ? (
        <Tableau<Ligne>
          legende="Pannes"
          lignes={pannes.data}
          cleLigne={(p) => p.id}
          messageVide="Aucune panne."
          colonnes={[
            { cle: "date", titre: "Signalée le", rendu: (p) => dateHeure(String(p.signalee_le)), valeurTri: (p) => String(p.signalee_le) },
            { cle: "stock", titre: "Matériel", rendu: (p) => `${String(p.quantite)} × ${String(p.stock_libelle)}` },
            { cle: "description", titre: "Description", rendu: (p) => String(p.description) },
            { cle: "source", titre: "Origine", rendu: (p) => ({ backoffice: "Signalement", controle: "Contrôle non conforme", incident: "Incident" })[String(p.source)] ?? String(p.source) },
            { cle: "resolution", titre: "Résolution", rendu: (p) => String(p.resolution || "—") },
          ]}
          actions={(p) =>
            p.statut === "ouverte" && peut("gerer_materiel") ? (
              <Bouton variante="lien" onClick={() => setResolution({ panne: p, issue: "reparee", texte: "" })}>
                Résoudre<span className="visuellement-masque"> : {String(p.stock_libelle)}</span>
              </Bouton>
            ) : null
          }
        />
      ) : null}
      <Dialogue ouvert={resolution !== null} titre="Résoudre la panne" onFermer={() => setResolution(null)}>
        {resolution ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              operation.mutate({ url: `/api/gestion/materiel/pannes/${resolution.panne.id}/resoudre`, corps: { issue: resolution.issue, resolution: resolution.texte } });
              setResolution(null);
            }}
          >
            <ChampSelection
              libelle="Issue"
              obligatoire
              options={[
                { valeur: "reparee", libelle: "Réparée : remise en service" },
                { valeur: "rebut", libelle: "Mise au rebut : retirée du stock" },
              ]}
              value={resolution.issue}
              onChange={(e) => setResolution({ ...resolution, issue: e.target.value })}
            />
            <ChampZone libelle="Intervention" value={resolution.texte} onChange={(e) => setResolution({ ...resolution, texte: e.target.value })} />
            <div className="actions">
              <Bouton type="submit">Valider</Bouton>
              <Bouton variante="secondaire" onClick={() => setResolution(null)}>
                Annuler
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </Page>
  );
}

export function Mouvements() {
  const { peut } = useSession();
  const mouvements = useQuery({
    queryKey: ["mouvements"],
    queryFn: async () => (await requete<PageApi<Ligne>>("GET", construireChemin("/api/gestion/materiel/mouvements", { taille: 200 }))).results,
    enabled: peut("lire_materiel"),
  });
  if (!peut("lire_materiel")) return <DroitsInsuffisants />;
  return (
    <Page titre="Mouvements de stock" description="Journal immuable : une erreur se corrige par un mouvement inverse (inventaire, entrée).">
      {mouvements.isPending ? <Chargement /> : null}
      {mouvements.data ? (
        <Tableau<Ligne>
          legende="Mouvements de stock"
          lignes={mouvements.data}
          cleLigne={(m) => m.id}
          messageVide="Aucun mouvement."
          colonnes={[
            { cle: "date", titre: "Date", rendu: (m) => dateHeure(String(m.horodatage)), valeurTri: (m) => String(m.horodatage) },
            { cle: "type", titre: "Mouvement", rendu: (m) => String(m.type_libelle) },
            { cle: "stock", titre: "Matériel et lieu", rendu: (m) => `${String(m.stock_libelle)}${m.destination_libelle ? ` → ${String(m.destination_libelle)}` : ""}` },
            { cle: "quantite", titre: "Quantité", rendu: (m) => String(m.quantite) },
            { cle: "motif", titre: "Motif", rendu: (m) => String(m.motif || "—") },
            { cle: "agent", titre: "Par", rendu: (m) => String(m.acteur_libelle) },
          ]}
        />
      ) : null}
    </Page>
  );
}
