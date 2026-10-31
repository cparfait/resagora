/** TAR-04 à TAR-13 : devis, factures, acomptes et avoirs ; retards ; export des titres vers Ciril ; import de
 * l'état des encaissements. Les montants viennent de l'API (centimes) ; aucune règle n'est recalculée ici. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { dateHeure, dateSimple, euros } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

export interface Piece {
  id: number;
  nature: string;
  numero: string | null;
  dossier: number;
  dossier_numero: string;
  usager_nom: string;
  origine_numero: string;
  objet: string;
  statut: string;
  emise_le: string | null;
  echeance: string | null;
  validite: string | null;
  total_reference: number;
  total_du: number;
  acompte_deduit: number;
  montant_regle: number;
  reste_du: number;
  montant_avoirs: number;
  lignes: { id: number; rang: number; libelle: string; montant_du: number }[];
  reference_virement: string;
  titre_numero: string;
  document: number | null;
}

export const NATURES: Record<string, string> = { devis: "Devis", acompte: "Facture d'acompte", facture: "Facture", avoir: "Avoir" };
export const STATUTS_PIECE: Record<string, { libelle: string; ton: "neutre" | "info" | "succes" | "attention" | "danger" }> = {
  emis: { libelle: "Émis, à accepter", ton: "info" },
  accepte: { libelle: "Accepté", ton: "succes" },
  refuse: { libelle: "Refusé", ton: "neutre" },
  expire: { libelle: "Expiré", ton: "neutre" },
  remplace: { libelle: "Remplacé par un nouveau devis", ton: "neutre" },
  a_titrer: { libelle: "À titrer", ton: "attention" },
  titre_emis: { libelle: "Titre émis", ton: "info" },
  solde_partiel: { libelle: "Partiellement soldée", ton: "attention" },
  solde: { libelle: "Soldée", ton: "succes" },
  en_recouvrement: { libelle: "En recouvrement", ton: "danger" },
  annulee: { libelle: "Annulée par avoir", ton: "neutre" },
};

type Action = { type: "avoir" | "pointer" | "titre"; piece: Piece } | null;

function erreurTexte(e: unknown): string {
  return e instanceof ErreurApi ? e.message : "Opération impossible.";
}

/** Tableau des pièces avec leurs actions (accepter, avoir, pointer, numéro de titre). */
export function TableauPieces({ pieces, legende, rafraichir }: { pieces: Piece[]; legende: string; rafraichir: () => Promise<void> }) {
  const { peut } = useSession();
  const { annoncer } = useNotifications();
  const [action, setAction] = useState<Action>(null);
  const [saisie, setSaisie] = useState({ motif: "", montant: "", date: "", reference: "", titre: "" });
  const [lignesAvoir, setLignesAvoir] = useState<number[]>([]);
  const operation = useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete<Piece>("POST", url, corps),
    onSuccess: async (p) => {
      annoncer(`${NATURES[p.nature] ?? "Pièce"} ${p.numero ?? ""} : ${STATUTS_PIECE[p.statut]?.libelle ?? p.statut}.`);
      setAction(null);
      setSaisie({ motif: "", montant: "", date: "", reference: "", titre: "" });
      await rafraichir();
    },
    onError: (e) => annoncer(erreurTexte(e), "erreur"),
  });
  const valider = () => {
    if (!action) return;
    const base = `/api/gestion/finances/pieces/${action.piece.id}`;
    if (action.type === "avoir") operation.mutate({ url: `${base}/avoir`, corps: { motif: saisie.motif, lignes: lignesAvoir } });
    if (action.type === "titre") operation.mutate({ url: `${base}/titre`, corps: { titre: saisie.titre } });
    if (action.type === "pointer") {
      const centimes = Math.round(Number(saisie.montant.replace(/\s/g, "").replace(",", ".")) * 100);
      operation.mutate({ url: `${base}/pointer`, corps: { montant: centimes, date: saisie.date, reference: saisie.reference } });
    }
  };
  return (
    <>
      <Tableau<Piece>
        legende={legende}
        lignes={pieces}
        cleLigne={(p) => p.id}
        messageVide="Aucune pièce."
        colonnes={[
          { cle: "numero", titre: "Numéro", rendu: (p) => p.numero ?? "—", valeurTri: (p) => p.numero ?? "" },
          { cle: "nature", titre: "Nature", rendu: (p) => NATURES[p.nature] ?? p.nature },
          { cle: "usager", titre: "Usager", rendu: (p) => `${p.usager_nom} — ${p.dossier_numero}` },
          { cle: "emise", titre: "Émise le", rendu: (p) => (p.emise_le ? dateSimple(p.emise_le) : "—"), valeurTri: (p) => p.emise_le ?? "" },
          {
            cle: "montant",
            titre: "Montant",
            rendu: (p) => (
              <span>
                {euros(p.total_du)}
                {p.total_reference !== p.total_du ? <span className="texte-doux"> (référence {euros(p.total_reference)})</span> : null}
                {p.acompte_deduit ? <span className="texte-doux">, acompte déduit {euros(p.acompte_deduit)}</span> : null}
              </span>
            ),
            valeurTri: (p) => p.total_du,
          },
          { cle: "reste", titre: "Reste dû", rendu: (p) => (p.nature === "devis" ? "—" : euros(p.reste_du)), valeurTri: (p) => p.reste_du },
          { cle: "statut", titre: "État", rendu: (p) => <Badge libelle={STATUTS_PIECE[p.statut]?.libelle ?? p.statut} ton={STATUTS_PIECE[p.statut]?.ton ?? "neutre"} /> },
        ]}
        actions={(p) => (
          <>
            {p.document ? (
              <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/finances/pieces/${p.id}/fichier`, `${p.numero ?? "piece"}.pdf`)}>
                PDF<span className="visuellement-masque"> de {p.numero}</span>
              </Bouton>
            ) : null}
            {peut("emettre_facture") && p.nature === "devis" && p.statut === "emis" ? (
              <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/finances/pieces/${p.id}/accepter` })}>
                Enregistrer l'acceptation<span className="visuellement-masque"> de {p.numero}</span>
              </Bouton>
            ) : null}
            {peut("emettre_avoir") && ["facture", "acompte"].includes(p.nature) && p.statut !== "annulee" ? (
              <Bouton
                variante="lien"
                onClick={() => {
                  setLignesAvoir([]);
                  setAction({ type: "avoir", piece: p });
                }}
              >
                Avoir…<span className="visuellement-masque"> sur {p.numero}</span>
              </Bouton>
            ) : null}
            {peut("encaisser") && ["facture", "acompte"].includes(p.nature) && ["a_titrer", "titre_emis", "solde_partiel", "en_recouvrement"].includes(p.statut) ? (
              <Bouton variante="lien" onClick={() => setAction({ type: "pointer", piece: p })}>
                Pointer un règlement<span className="visuellement-masque"> de {p.numero}</span>
              </Bouton>
            ) : null}
            {peut("exporter_titres") && p.nature !== "devis" && !p.titre_numero ? (
              <Bouton variante="lien" onClick={() => setAction({ type: "titre", piece: p })}>
                Numéro de titre…<span className="visuellement-masque"> de {p.numero}</span>
              </Bouton>
            ) : null}
          </>
        )}
      />
      <Dialogue
        ouvert={action !== null}
        titre={action?.type === "avoir" ? "Émettre un avoir" : action?.type === "pointer" ? "Pointer un règlement" : "Reporter le numéro de titre Ciril"}
        onFermer={() => setAction(null)}
      >
        {action ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              valider();
            }}
          >
            <p>
              {NATURES[action.piece.nature]} {action.piece.numero} — {action.piece.usager_nom} — reste dû {euros(action.piece.reste_du)}
            </p>
            {action.type === "avoir" ? (
              <>
                <ChampTexte libelle="Motif de l'avoir" obligatoire value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
                <fieldset className="groupe">
                  <legend>Lignes à créditer (aucune cochée : toute la facture)</legend>
                  {action.piece.lignes.map((ligne) => (
                    <CaseACocher
                      key={ligne.id}
                      libelle={`${ligne.libelle} — ${euros(ligne.montant_du)}`}
                      checked={lignesAvoir.includes(ligne.id)}
                      onChange={(e) => setLignesAvoir(e.target.checked ? [...lignesAvoir, ligne.id] : lignesAvoir.filter((id) => id !== ligne.id))}
                    />
                  ))}
                </fieldset>
                <p>La facture n'est pas modifiée : l'avoir crédite les lignes choisies et porte sa propre numérotation.</p>
              </>
            ) : null}
            {action.type === "pointer" ? (
              <>
                <ChampTexte libelle="Montant encaissé (€)" inputMode="decimal" obligatoire value={saisie.montant} onChange={(e) => setSaisie({ ...saisie, montant: e.target.value })} />
                <ChampTexte libelle="Date d'encaissement" type="date" obligatoire value={saisie.date} onChange={(e) => setSaisie({ ...saisie, date: e.target.value })} />
                <ChampTexte libelle="Référence (relevé, virement, titre)" obligatoire value={saisie.reference} onChange={(e) => setSaisie({ ...saisie, reference: e.target.value })} />
              </>
            ) : null}
            {action.type === "titre" ? (
              <ChampTexte libelle="Numéro du titre dans Ciril" obligatoire value={saisie.titre} onChange={(e) => setSaisie({ ...saisie, titre: e.target.value })} />
            ) : null}
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setAction(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" enCours={operation.isPending}>
                Valider
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </>
  );
}

export function PiecesComptables() {
  const { peut } = useSession();
  const client = useQueryClient();
  const [filtres, setFiltres] = useState({ nature: "", statut: "" });
  const pieces = useQuery({
    queryKey: ["pieces", filtres],
    queryFn: () => requete<PageApi<Piece>>("GET", construireChemin("/api/gestion/finances/pieces", { ...filtres, taille: 200 })),
    enabled: peut("lire_finances"),
  });
  if (!peut("lire_finances")) return <DroitsInsuffisants />;
  return (
    <Page titre="Devis, factures et avoirs" description="Pièces émises, numérotées sans trou par exercice. Une pièce émise ne se modifie pas : elle se corrige par un avoir.">
      <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Nature" options={Object.entries(NATURES).map(([valeur, libelle]) => ({ valeur, libelle }))} videLibelle="Toutes" value={filtres.nature} onChange={(e) => setFiltres({ ...filtres, nature: e.target.value })} />
        <ChampSelection libelle="État" options={Object.entries(STATUTS_PIECE).map(([valeur, s]) => ({ valeur, libelle: s.libelle }))} videLibelle="Tous" value={filtres.statut} onChange={(e) => setFiltres({ ...filtres, statut: e.target.value })} />
      </form>
      {pieces.isPending ? <Chargement /> : null}
      {pieces.isError ? <Erreur erreur={pieces.error} /> : null}
      {pieces.data ? (
        <TableauPieces pieces={pieces.data.results} legende="Pièces comptables" rafraichir={() => client.invalidateQueries({ queryKey: ["pieces"] })} />
      ) : null}
    </Page>
  );
}

export function Retards() {
  const { peut } = useSession();
  const client = useQueryClient();
  const retards = useQuery({ queryKey: ["pieces", "retards"], queryFn: () => requete<Piece[]>("GET", "/api/gestion/finances/pieces/retards"), enabled: peut("lire_finances") });
  if (!peut("lire_finances")) return <DroitsInsuffisants />;
  return (
    <Page titre="Factures en retard" description="Factures non soldées après leur échéance (TAR-10), dans votre périmètre.">
      {retards.isPending ? <Chargement /> : null}
      {retards.isError ? <Erreur erreur={retards.error} /> : null}
      {retards.data ? <TableauPieces pieces={retards.data} legende="Factures en retard" rafraichir={() => client.invalidateQueries({ queryKey: ["pieces"] })} /> : null}
    </Page>
  );
}

interface Lot {
  id: number;
  numero: string;
  format: string;
  pieces: string[];
  total_centimes: number;
  cree_le: string;
  annule_le: string | null;
  motif_annulation: string;
}

export function TitresCiril() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [format, setFormat] = useState("");
  const [rejet, setRejet] = useState<{ lot: Lot; motif: string } | null>(null);
  const annuler = useMutation({
    mutationFn: () => requete<Lot>("POST", `/api/gestion/finances/lots-titres/${rejet?.lot.id}/annuler`, { motif: rejet?.motif }),
    onSuccess: async (l) => {
      annoncer(`Lot ${l.numero} annulé : ses pièces sont de nouveau à exporter.`);
      setRejet(null);
      await client.invalidateQueries({ queryKey: ["a-titrer"] });
      await client.invalidateQueries({ queryKey: ["lots-titres"] });
    },
    onError: (e) => annoncer(erreurTexte(e), "erreur"),
  });
  const aTitrer = useQuery({ queryKey: ["a-titrer"], queryFn: () => requete<Piece[]>("GET", "/api/gestion/finances/lots-titres/a-titrer"), enabled: peut("exporter_titres") });
  const lots = useQuery({ queryKey: ["lots-titres"], queryFn: () => requete<PageApi<Lot>>("GET", "/api/gestion/finances/lots-titres"), enabled: peut("exporter_titres") });
  const exporter = useMutation({
    mutationFn: () => requete<Lot>("POST", "/api/gestion/finances/lots-titres", format ? { format } : {}),
    onSuccess: async (l) => {
      annoncer(`Lot ${l.numero} créé : ${l.pieces.length} pièce(s), ${euros(l.total_centimes)}.`);
      await client.invalidateQueries({ queryKey: ["a-titrer"] });
      await client.invalidateQueries({ queryKey: ["lots-titres"] });
      await telecharger(`/api/gestion/finances/lots-titres/${l.id}/fichier`, `titres-${l.numero}.${l.format}`);
    },
    onError: (e) => annoncer(erreurTexte(e), "erreur"),
  });
  if (!peut("exporter_titres")) return <DroitsInsuffisants />;
  return (
    <Page titre="Titres de recettes (Ciril)" description="Les factures, acomptes et avoirs émis sont exportés par lots vers CIVIL Finances Publiques. Un lot se retélécharge à l'identique.">
      <section aria-labelledby="titre-a-titrer" className="carte">
        <h2 id="titre-a-titrer">À exporter</h2>
        {aTitrer.isPending ? <Chargement lignes={2} /> : null}
        {aTitrer.data ? (
          <>
            <p>
              {aTitrer.data.length} pièce(s), {euros(aTitrer.data.reduce((total, p) => total + p.total_du - p.acompte_deduit, 0))}.
            </p>
            <form
              className="formulaire-ligne"
              onSubmit={(e) => {
                e.preventDefault();
                exporter.mutate();
              }}
            >
              <ChampSelection
                libelle="Format"
                videLibelle="Format paramétré"
                options={[
                  { valeur: "csv", libelle: "CSV" },
                  { valeur: "xlsx", libelle: "Tableur XLSX" },
                  { valeur: "xml", libelle: "XML" },
                ]}
                value={format}
                onChange={(e) => setFormat(e.target.value)}
              />
              <Bouton type="submit" enCours={exporter.isPending} disabled={!aTitrer.data.length}>
                Créer le lot et télécharger
              </Bouton>
            </form>
          </>
        ) : null}
      </section>
      {lots.data ? (
        <Tableau<Lot>
          legende="Lots exportés"
          lignes={lots.data.results}
          cleLigne={(l) => l.id}
          messageVide="Aucun lot exporté."
          colonnes={[
            { cle: "numero", titre: "Lot", rendu: (l) => l.numero },
            { cle: "date", titre: "Créé le", rendu: (l) => dateHeure(l.cree_le), valeurTri: (l) => l.cree_le },
            { cle: "pieces", titre: "Pièces", rendu: (l) => l.pieces.join(", ") },
            { cle: "total", titre: "Total", rendu: (l) => euros(l.total_centimes) },
            { cle: "etat", titre: "État", rendu: (l) => (l.annule_le ? <Badge libelle={`Annulé : ${l.motif_annulation}`} ton="neutre" /> : <Badge libelle="Transmis" ton="succes" />) },
          ]}
          actions={(l) => (
            <>
              <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/finances/lots-titres/${l.id}/fichier`, `titres-${l.numero}.${l.format}`)}>
                Retélécharger<span className="visuellement-masque"> le lot {l.numero}</span>
              </Bouton>
              {l.annule_le ? null : (
                <Bouton variante="lien" onClick={() => setRejet({ lot: l, motif: "" })}>
                  Rejeté par Ciril…<span className="visuellement-masque"> lot {l.numero}</span>
                </Bouton>
              )}
            </>
          )}
        />
      ) : null}
      <Dialogue ouvert={rejet !== null} titre="Annuler un lot rejeté par Ciril" onFermer={() => setRejet(null)}>
        {rejet ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              annuler.mutate();
            }}
          >
            <p>Le fichier du lot {rejet.lot.numero} reste consultable ; ses pièces redeviennent à exporter.</p>
            <ChampTexte libelle="Motif du rejet" obligatoire value={rejet.motif} onChange={(e) => setRejet({ ...rejet, motif: e.target.value })} />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setRejet(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" variante="danger" enCours={annuler.isPending}>
                Annuler le lot
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </Page>
  );
}

interface Import {
  id: number;
  lignes_lues: number;
  rapprochees: number;
  confirmees: number;
  rejets: { ligne: number; titre: string; facture: string; motif: string }[];
  cree_le: string;
}

export function Encaissements() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [fichier, setFichier] = useState<File | null>(null);
  const imports = useQuery({ queryKey: ["imports-encaissements"], queryFn: () => requete<PageApi<Import>>("GET", "/api/gestion/finances/imports-encaissements"), enabled: peut("encaisser") });
  const importer = useMutation({
    mutationFn: () => {
      const formulaire = new FormData();
      if (fichier) formulaire.append("fichier", fichier);
      return requete<Import>("POST", "/api/gestion/finances/imports-encaissements", formulaire);
    },
    onSuccess: async (r) => {
      annoncer(
        `${r.rapprochees} encaissement(s) rapproché(s) sur ${r.lignes_lues} ligne(s)${r.confirmees ? ` ; ${r.confirmees} paiement(s) en ligne confirmé(s) par le comptable` : ""} ; ${r.rejets.length} rejet(s).`,
        r.rejets.length ? "erreur" : "succes",
      );
      setFichier(null);
      await client.invalidateQueries({ queryKey: ["imports-encaissements"] });
      await client.invalidateQueries({ queryKey: ["pieces"] });
    },
    onError: (e) => annoncer(erreurTexte(e), "erreur"),
  });
  if (!peut("encaisser")) return <DroitsInsuffisants />;
  return (
    <Page titre="Encaissements" description="Import de l'état des titres soldés exporté de Ciril (CSV ou XLSX, colonnes paramétrées). Un import rejoué n'enregistre pas deux fois le même encaissement.">
      <form
        className="carte"
        onSubmit={(e) => {
          e.preventDefault();
          importer.mutate();
        }}
      >
        <ChampTexte libelle="État des titres soldés" type="file" accept=".csv,.xlsx,.txt" obligatoire aide="CSV ou XLSX, 10 Mo au plus." onChange={(e) => setFichier(e.target.files?.[0] ?? null)} />
        <Bouton type="submit" enCours={importer.isPending} disabled={!fichier}>
          Importer
        </Bouton>
      </form>
      {imports.data ? (
        <Tableau<Import>
          legende="Imports réalisés"
          lignes={imports.data.results}
          cleLigne={(i) => i.id}
          messageVide="Aucun import."
          colonnes={[
            { cle: "date", titre: "Importé le", rendu: (i) => dateHeure(i.cree_le), valeurTri: (i) => i.cree_le },
            { cle: "lues", titre: "Lignes lues", rendu: (i) => i.lignes_lues },
            { cle: "rapprochees", titre: "Rapprochées", rendu: (i) => i.rapprochees },
            { cle: "confirmees", titre: "Paiements en ligne confirmés", rendu: (i) => i.confirmees },
            {
              cle: "rejets",
              titre: "Rejets",
              rendu: (i) =>
                i.rejets.length ? (
                  <details>
                    <summary>{i.rejets.length} rejet(s)</summary>
                    <ul className="liste-simple">
                      {i.rejets.map((r) => (
                        <li key={r.ligne}>
                          Ligne {r.ligne} ({r.titre || r.facture}) : {r.motif}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  "Aucun"
                ),
            },
          ]}
        />
      ) : null}
    </Page>
  );
}
