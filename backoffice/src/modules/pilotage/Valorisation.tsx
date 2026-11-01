/** VAL-01 à VAL-08 : exercices, méthodes par famille, calcul, synthèse avec alertes de seuil, attestations, annexe
 * du compte administratif, import des subventions, simulation en cours d'année, clôture et recalcul tracé. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { construireChemin, ErreurApi, jetonCsrf, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { dateHeure, dateSimple, euros, isoJour } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

interface Exercice {
  id: number;
  annee: number;
  statut: "ouvert" | "cloture";
  date_limite_attestations: string | null;
  date_limite: string;
  cloture_le: string | null;
  cout_personnel: number;
  absences_valorisees: boolean;
}
interface LigneSynthese {
  usager: number;
  usager_nom: string;
  usager_type: string;
  valorisation: number | null;
  nature: number;
  numeraire: number;
  total: number;
  alertes: ("convention" | "compte_rendu")[];
  attestation: "deposee" | "en_signature" | null;
  figee: boolean;
}
interface Synthese {
  seuils: { convention: number; compte_rendu: number };
  lignes: LigneSynthese[];
}
interface Simulation {
  usager_nom: string;
  jusqu_au: string;
  montant_espaces: number;
  montant_materiel: number;
  montant_personnel: number;
  total: number;
  anomalies: string[];
}

const METHODES = [
  { valeur: "tarif_reference", libelle: "Tarif de référence voté" },
  { valeur: "cout_revient", libelle: "Coût de revient horaire" },
  { valeur: "valeur_locative", libelle: "Valeur locative" },
];

export function Valorisation() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const lecture = peut("lire_valorisation");
  const usagers = useOptions("usagers-valorisation", "/api/gestion/usagers?type=association", (u) => String(u.nom), lecture);
  const exercices = useQuery({
    queryKey: ["exercices"],
    queryFn: async () => (await requete<PageApi<Exercice>>("GET", "/api/gestion/valorisation/exercices?taille=50")).results,
    enabled: lecture,
  });
  const [choisi, setChoisi] = useState<string>("");
  const exercice = exercices.data?.find((e) => String(e.id) === choisi) ?? exercices.data?.[0];
  const synthese = useQuery({
    queryKey: ["synthese", exercice?.id],
    queryFn: () => requete<Synthese>("GET", `/api/gestion/valorisation/exercices/${exercice?.id}/synthese`),
    enabled: lecture && exercice !== undefined,
  });
  const [dialogue, setDialogue] = useState<"creer" | "simuler" | "subventions" | "recalcul" | null>(null);
  const [saisie, setSaisie] = useState(() => ({ annee: String(new Date().getFullYear()), usager: "", jusqu_au: isoJour(new Date()), motif: "", valorisation: 0 }));
  const [simulation, setSimulation] = useState<Simulation | null>(null);
  const [fichier, setFichier] = useState<File | null>(null);
  const [rejets, setRejets] = useState<string[] | null>(null);
  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["exercices"] });
    await client.invalidateQueries({ queryKey: ["synthese"] });
  };
  const operation = useMutation({
    mutationFn: ({ url, corps, methode = "POST" }: { url: string; corps?: unknown; methode?: string }) => requete<Record<string, unknown>>(methode, url, corps),
    onSuccess: async (resultat) => {
      const anomalies = Array.isArray(resultat.anomalies) ? (resultat.anomalies as string[]) : [];
      annoncer(anomalies.length ? `Calcul terminé avec ${anomalies.length} anomalie(s) : ${anomalies.slice(0, 3).join(" ; ")}` : "Opération effectuée.", anomalies.length ? "erreur" : "succes");
      setDialogue(null);
      await rafraichir();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });
  const importer = useMutation({
    mutationFn: async (confirmer: boolean) => {
      const formulaire = new FormData();
      if (fichier) formulaire.append("fichier", fichier);
      if (confirmer) formulaire.append("confirmer", "oui");
      const reponse = await fetch(`/api/gestion/valorisation/exercices/${exercice?.id}/subventions`, { method: "POST", body: formulaire, credentials: "same-origin", headers: { "X-CSRFToken": jetonCsrf() } });
      const donnees = (await reponse.json()) as { importees?: number; a_importer?: number; rejets?: string[]; confirmation_requise?: boolean; message?: string };
      if (!reponse.ok) throw new Error(donnees.message ?? "Import impossible.");
      return donnees;
    },
    onSuccess: async (r) => {
      if (r.confirmation_requise) {
        // Rien n'est remplacé tant que l'agent n'a pas vu les lignes rejetées (M6).
        setRejets(r.rejets ?? []);
        return;
      }
      annoncer(`${r.importees ?? 0} subvention(s) importée(s)${r.rejets?.length ? ` ; ${r.rejets.length} ligne(s) écartée(s)` : ""}.`);
      setRejets(null);
      setDialogue(null);
      await rafraichir();
    },
    onError: (e) => annoncer((e as Error).message, "erreur"),
  });
  const seuils = synthese.data?.seuils;
  if (!lecture) return <DroitsInsuffisants />;
  const calcul = peut("calculer_valorisation");
  const ouvert = exercice?.statut === "ouvert";
  return (
    <Page
      titre="Valorisation des avantages en nature"
      description="Concours en nature accordés aux associations (mises à disposition, matériel, personnel) au tarif de référence conservé ; seuils légaux de 23 000 € (convention) et 153 000 € (compte rendu financier)."
      actions={calcul ? <Bouton onClick={() => setDialogue("creer")}>Nouvel exercice</Bouton> : null}
    >
      {exercices.isPending ? <Chargement /> : null}
      {exercices.isError ? <Erreur erreur={exercices.error} /> : null}
      {exercices.data?.length ? (
        <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
          <ChampSelection
            libelle="Exercice"
            options={exercices.data.map((e) => ({ valeur: String(e.id), libelle: `${e.annee}${e.statut === "cloture" ? " (clôturé)" : ""}` }))}
            value={String(exercice?.id ?? "")}
            onChange={(e) => setChoisi(e.target.value)}
          />
        </form>
      ) : exercices.data ? (
        <p>Aucun exercice : créez l'exercice de l'année.</p>
      ) : null}
      {exercice ? (
        <div className="actions">
          {calcul && ouvert ? (
            <Bouton onClick={() => operation.mutate({ url: `/api/gestion/valorisation/exercices/${exercice.id}/calculer`, corps: {} })} enCours={operation.isPending}>
              Calculer tous les bénéficiaires
            </Bouton>
          ) : null}
          {calcul ? (
            <Bouton variante="secondaire" onClick={() => { setSimulation(null); setDialogue("simuler"); }}>
              Simuler en cours d'année
            </Bouton>
          ) : null}
          {calcul && ouvert ? (
            <Bouton variante="secondaire" onClick={() => setDialogue("subventions")}>
              Importer les subventions en numéraire
            </Bouton>
          ) : null}
          <Bouton variante="secondaire" onClick={() => void telecharger(`/api/gestion/valorisation/exercices/${exercice.id}/annexe`, `annexe-concours-${exercice.annee}.csv`)}>
            Annexe du compte administratif (tableur)
          </Bouton>
          {peut("cloturer_valorisation") && ouvert ? (
            <Bouton variante="danger" onClick={() => operation.mutate({ url: `/api/gestion/valorisation/exercices/${exercice.id}/cloturer` })}>
              Clôturer l'exercice {exercice.annee}
            </Bouton>
          ) : null}
        </div>
      ) : null}
      {exercice ? (
        <p className="aide">
          Paramètres de l'exercice : personnel dédié valorisé {euros(exercice.cout_personnel)} de l'heure ; absences non signalées {exercice.absences_valorisees ? "valorisées" : "non valorisées"} ; attestations à déposer
          avant le {dateSimple(exercice.date_limite)}.
        </p>
      ) : null}
      {exercice && exercice.statut === "cloture" ? <p className="alerte">Exercice clôturé le {exercice.cloture_le ? dateHeure(exercice.cloture_le) : ""} : les montants sont figés ; un recalcul passe par la procédure tracée.</p> : null}
      {exercice && exercice.statut === "ouvert" ? <p className="aide">Les attestations s'éditent une fois l'exercice clôturé (montants définitifs). La clôture recalcule chaque bénéficiaire.</p> : null}
      {synthese.data ? (
        <Tableau<LigneSynthese>
          legende={`Synthèse ${exercice?.annee ?? ""}`}
          lignes={synthese.data.lignes}
          cleLigne={(l) => l.usager}
          messageVide="Aucune valorisation calculée."
          colonnes={[
            { cle: "usager", titre: "Bénéficiaire", rendu: (l) => l.usager_nom, valeurTri: (l) => l.usager_nom },
            { cle: "nature", titre: "En nature", rendu: (l) => euros(l.nature), valeurTri: (l) => l.nature },
            { cle: "numeraire", titre: "En numéraire", rendu: (l) => euros(l.numeraire), valeurTri: (l) => l.numeraire },
            { cle: "total", titre: "Total", rendu: (l) => euros(l.total), valeurTri: (l) => l.total },
            {
              cle: "alertes",
              titre: "Seuils",
              rendu: (l) => (
                <span className="badges">
                  {l.alertes.includes("convention") ? <Badge libelle={`Convention obligatoire (> ${euros(seuils?.convention ?? 0)})`} ton="attention" /> : null}
                  {l.alertes.includes("compte_rendu") ? <Badge libelle={`Compte rendu financier (> ${euros(seuils?.compte_rendu ?? 0)})`} ton="danger" /> : null}
                </span>
              ),
            },
            {
              cle: "attestation",
              titre: "Attestation",
              rendu: (l) =>
                l.attestation === "deposee" ? <Badge libelle="Déposée sur le portail" ton="succes" /> : l.attestation === "en_signature" ? <Badge libelle="En signature (élu)" ton="info" /> : "—",
            },
          ]}
          actions={(l) =>
            l.valorisation ? (
              <span className="actions">
                {calcul && ouvert ? (
                  <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/valorisation/exercices/${exercice?.id}/calculer`, corps: { usager: l.usager } })}>
                    Recalculer<span className="visuellement-masque"> : {l.usager_nom}</span>
                  </Bouton>
                ) : null}
                {calcul && l.figee && !l.attestation && l.usager_type === "association" && l.nature > 0 ? (
                  <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/valorisation/valorisations/${l.valorisation}/attestation` })}>
                    Éditer et faire signer l'attestation<span className="visuellement-masque"> : {l.usager_nom}</span>
                  </Bouton>
                ) : null}
                {peut("cloturer_valorisation") && !ouvert ? (
                  <Bouton variante="lien" onClick={() => { setSaisie({ ...saisie, motif: "", valorisation: l.valorisation ?? 0 }); setDialogue("recalcul"); }}>
                    Procédure de recalcul<span className="visuellement-masque"> : {l.usager_nom}</span>
                  </Bouton>
                ) : null}
              </span>
            ) : null
          }
        />
      ) : null}

      <Dialogue ouvert={dialogue === "creer"} titre="Nouvel exercice" onFermer={() => setDialogue(null)}>
        <form onSubmit={(e) => { e.preventDefault(); operation.mutate({ url: "/api/gestion/valorisation/exercices", corps: { annee: Number(saisie.annee) } }); }}>
          <ChampTexte libelle="Année" type="number" obligatoire value={saisie.annee} onChange={(e) => setSaisie({ ...saisie, annee: e.target.value })} />
          <Bouton type="submit" enCours={operation.isPending}>Créer</Bouton>
        </form>
      </Dialogue>
      <Dialogue ouvert={dialogue === "simuler"} titre="Simulation en cours d'année" onFermer={() => setDialogue(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void requete<Simulation>("GET", construireChemin(`/api/gestion/valorisation/exercices/${exercice?.id}/simulation`, { usager: saisie.usager, jusqu_au: saisie.jusqu_au }))
              .then(setSimulation)
              .catch((erreur: unknown) => annoncer(erreur instanceof ErreurApi ? erreur.message : "Simulation impossible.", "erreur"));
          }}
        >
          <ChampSelection libelle="Association" obligatoire options={usagers} value={saisie.usager} onChange={(e) => setSaisie({ ...saisie, usager: e.target.value })} />
          <ChampTexte libelle="Jusqu'au" type="date" obligatoire value={saisie.jusqu_au} onChange={(e) => setSaisie({ ...saisie, jusqu_au: e.target.value })} />
          <Bouton type="submit">Simuler</Bouton>
        </form>
        {simulation ? (
          <div aria-live="polite">
            <p>
              {simulation.usager_nom}, au {simulation.jusqu_au} : <strong>{euros(simulation.total)}</strong> (espaces {euros(simulation.montant_espaces)}, matériel {euros(simulation.montant_materiel)}, personnel {euros(simulation.montant_personnel)}). Rien n'est enregistré.
            </p>
            {simulation.anomalies.length ? <p className="alerte">Tarifs manquants : {simulation.anomalies.join(" ; ")}</p> : null}
          </div>
        ) : null}
      </Dialogue>
      <Dialogue ouvert={dialogue === "subventions"} titre="Importer les subventions en numéraire" onFermer={() => setDialogue(null)}>
        <form onSubmit={(e) => { e.preventDefault(); importer.mutate(false); }}>
          <p className="aide">Fichier CSV séparé par des points-virgules : identifiant (SIRET, RNA ou nom) ; montant en euros ; objet ; délibération. Un nouvel import remplace le précédent.</p>
          <div className="champ">
            <label htmlFor="fichier-subventions">Fichier</label>
            <input id="fichier-subventions" type="file" accept=".csv,text/csv" required onChange={(e) => setFichier(e.target.files?.[0] ?? null)} />
          </div>
          <Bouton type="submit" enCours={importer.isPending}>Importer</Bouton>
        </form>
        {rejets ? (
          <div role="alert" className="alerte">
            <p>
              {rejets.length} ligne(s) ne peuvent pas être importées. Rien n'a encore été remplacé : corrigez le fichier, ou importez les autres lignes en écartant celles-ci.
            </p>
            <ul>
              {rejets.slice(0, 20).map((r) => (
                <li key={r}>{r}</li>
              ))}
            </ul>
            <Bouton variante="danger" onClick={() => importer.mutate(true)} enCours={importer.isPending}>
              Importer sans les lignes écartées
            </Bouton>
          </div>
        ) : null}
      </Dialogue>
      <Dialogue ouvert={dialogue === "recalcul"} titre="Procédure de recalcul d'un exercice clôturé" onFermer={() => setDialogue(null)}>
        <form onSubmit={(e) => { e.preventDefault(); operation.mutate({ url: `/api/gestion/valorisation/valorisations/${saisie.valorisation}/recalculer`, corps: { motif: saisie.motif } }); }}>
          <p>Une nouvelle version figée est créée ; l'ancienne reste consultable. Le motif est tracé au journal d'audit ; une attestation déjà déposée est rééditée et repart en signature.</p>
          <ChampZone libelle="Motif du recalcul" obligatoire value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
          <Bouton type="submit" variante="danger" enCours={operation.isPending}>Recalculer</Bouton>
        </form>
      </Dialogue>
    </Page>
  );
}

export function MethodesValorisation() {
  const { peut } = useSession();
  const lecture = peut("lire_valorisation");
  const exercices = useOptions("exercices", "/api/gestion/valorisation/exercices", (e) => String(e.annee), lecture);
  const familles = useOptions("familles", "/api/gestion/referentiel/familles", (f) => String(f.libelle), lecture);
  return (
    <EcranRessource<Record<string, unknown> & { id: number }>
      titre="Méthodes de valorisation"
      description="Par famille d'espaces et par exercice (VAL-01) : tarif de référence voté (défaut), coût de revient horaire ou valeur locative, fondés sur une délibération. La méthode d'un exercice clôturé ne change plus."
      chemin="/api/gestion/valorisation/methodes"
      cleRequete="methodes-valorisation"
      actionLecture="lire_valorisation"
      actionEcriture="calculer_valorisation"
      libelleObjet="Méthode"
      colonnes={[
        { cle: "exercice", titre: "Exercice", rendu: (m) => exercices.find((e) => e.valeur === String(m.exercice))?.libelle ?? String(m.exercice) },
        { cle: "famille", titre: "Famille", rendu: (m) => String(m.famille_libelle) },
        { cle: "methode", titre: "Méthode", rendu: (m) => METHODES.find((x) => x.valeur === m.methode)?.libelle ?? String(m.methode) },
        { cle: "fondement", titre: "Délibération", rendu: (m) => String(m.deliberation_reference || "—") },
      ]}
      champs={[
        { nom: "exercice", libelle: "Exercice", type: "selection", obligatoire: true, options: exercices },
        { nom: "famille", libelle: "Famille d'espaces", type: "selection", obligatoire: true, options: familles },
        { nom: "methode", libelle: "Méthode", type: "selection", obligatoire: true, options: METHODES },
        { nom: "cout_horaire_centimes", libelle: "Coût de revient d'une heure", type: "euros" },
        { nom: "loyer_m2_annuel_centimes", libelle: "Valeur locative annuelle du m²", type: "euros" },
        { nom: "heures_annuelles_reference", libelle: "Heures d'ouverture annuelles de référence", type: "nombre" },
        { nom: "deliberation_reference", libelle: "Délibération (référence)", type: "texte" },
      ]}
      valeursInitiales={{ methode: "tarif_reference", heures_annuelles_reference: 2000 }}
      filtres={[{ nom: "exercice", libelle: "Exercice", options: exercices }]}
    />
  );
}

export function Editions() {
  const { peut } = useSession();
  const lecture = peut("lire_reservation");
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`, lecture);
  const [saisie, setSaisie] = useState(() => ({ site: "", espace: "", du: isoJour(new Date()), papier: "A4", mise_en_page: "calendrier" }));
  if (!lecture) return <DroitsInsuffisants />;
  const au = (() => {
    const d = new Date(saisie.du);
    d.setDate(d.getDate() + 6);
    return isoJour(d);
  })();
  return (
    <>
      <Page
        titre="Éditions du planning"
        description={
          <>
            Planning hebdomadaire d'un espace ou d'un site (A4 ou A3, noir et blanc, date d'édition, QR code vers la version en ligne), en calendrier ou en liste, et feuille à afficher en salle. Pour les créneaux réguliers de la saison, voir la <Link to="/pilotage/semaine-type">semaine type</Link>.
          </>
        }
      >
        <form className="formulaire" onSubmit={(e) => e.preventDefault()}>
          <ChampSelection libelle="Site" videLibelle="—" options={sites} value={saisie.site} onChange={(e) => setSaisie({ ...saisie, site: e.target.value, espace: "" })} />
          <ChampSelection libelle="ou espace" videLibelle="—" options={espaces} value={saisie.espace} onChange={(e) => setSaisie({ ...saisie, espace: e.target.value, site: "" })} />
          <ChampTexte libelle="Semaine du" type="date" value={saisie.du} onChange={(e) => setSaisie({ ...saisie, du: e.target.value })} />
          <ChampSelection libelle="Format" options={[{ valeur: "A4", libelle: "A4" }, { valeur: "A3", libelle: "A3 (paysage)" }]} value={saisie.papier} onChange={(e) => setSaisie({ ...saisie, papier: e.target.value })} />
          <ChampSelection
            libelle="Mise en page"
            options={[
              { valeur: "calendrier", libelle: "Calendrier (grille de la semaine)" },
              { valeur: "liste", libelle: "Liste par jour" },
            ]}
            value={saisie.mise_en_page}
            onChange={(e) => setSaisie({ ...saisie, mise_en_page: e.target.value })}
          />
          <div className="actions">
            <Bouton
              disabled={!saisie.site && !saisie.espace}
              onClick={() => void telecharger(construireChemin("/api/gestion/pilotage/planning.pdf", { site: saisie.site || undefined, espace: saisie.espace || undefined, du: saisie.du, au, papier: saisie.papier, mise_en_page: saisie.mise_en_page }), "planning.pdf")}
            >
              Imprimer le planning
            </Bouton>
            <Bouton variante="secondaire" disabled={!saisie.espace} onClick={() => void telecharger(construireChemin("/api/gestion/pilotage/feuille-de-salle.pdf", { espace: saisie.espace, jour: saisie.du }), "feuille-de-salle.pdf")}>
              Feuille de salle (espace)
            </Bouton>
          </div>
        </form>
      </Page>
      <EcranRessource<Record<string, unknown> & { id: number }>
        titre="Envois programmés"
        description="Le planning de la semaine suivante part chaque semaine, au jour et à l'heure choisis, en pièce jointe (IMP-04)."
        chemin="/api/gestion/pilotage/envois-planning"
        cleRequete="envois-planning"
        actionLecture="lire_reservation"
        actionEcriture="instruire_reservation"
        libelleObjet="Envoi programmé"
        suppression
        colonnes={[
          { cle: "libelle", titre: "Envoi", rendu: (e) => String(e.libelle) },
          { cle: "cible", titre: "Planning", rendu: (e) => String(e.cible) },
          { cle: "destinataires", titre: "Destinataires", rendu: (e) => (e.destinataires as string[]).join(", ") },
          { cle: "prochain", titre: "Prochain envoi", rendu: (e) => (e.prochain_envoi_le ? dateHeure(String(e.prochain_envoi_le)) : "—") },
        ]}
        champs={[
          { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
          { nom: "site", libelle: "Site", type: "selection", options: sites },
          { nom: "espace", libelle: "ou espace", type: "selection", options: espaces },
          { nom: "destinataires_texte", libelle: "Destinataires (une adresse par ligne)", type: "zone", obligatoire: true },
          { nom: "jour_semaine", libelle: "Jour d'envoi", type: "selection", obligatoire: true, options: ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"].map((j, i) => ({ valeur: String(i), libelle: j })) },
          { nom: "heure", libelle: "Heure", type: "heure", obligatoire: true },
          { nom: "format_papier", libelle: "Format", type: "selection", options: [{ valeur: "A4", libelle: "A4" }, { valeur: "A3", libelle: "A3" }] },
          { nom: "actif", libelle: "Actif", type: "booleen" },
        ]}
        valeursInitiales={{ jour_semaine: 4, heure: "16:00", format_papier: "A4", actif: true }}
      />
    </>
  );
}
