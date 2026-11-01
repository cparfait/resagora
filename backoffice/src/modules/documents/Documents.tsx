/** DOC-01 modèles versionnés (Word), DOC-06 génération en lot avec progression et rapport d'erreurs. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateHeure } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

interface Modele {
  id: number;
  code: string;
  libelle: string;
  nature: string;
  description: string;
  signature_requise: boolean;
  signataires: string[];
  actif: boolean;
  version_active: number | null;
  version_active_numero: number | null;
  variables: string[];
}
interface Version {
  id: number;
  numero: number;
  nom_fichier: string;
  sha256: string;
  commentaire: string;
  deposee_par: string;
  deposee_le: string;
}

function Versions({ modele, fermer }: { modele: Modele; fermer: () => void }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [fichier, setFichier] = useState<File | null>(null);
  const [commentaire, setCommentaire] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const versions = useQuery({ queryKey: ["versions", modele.id], queryFn: () => requete<Version[]>("GET", `/api/gestion/documents/modeles/${modele.id}/versions`) });
  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["versions", modele.id] });
    await client.invalidateQueries({ queryKey: ["modeles-documents"] });
  };
  const deposer = useMutation({
    mutationFn: () => {
      const formulaire = new FormData();
      if (fichier) formulaire.append("fichier", fichier);
      formulaire.append("commentaire", commentaire);
      return requete<Version>("POST", `/api/gestion/documents/modeles/${modele.id}/deposer-version`, formulaire);
    },
    onSuccess: async (v) => {
      annoncer(`Version ${v.numero} déposée et activée.`);
      setFichier(null);
      setCommentaire("");
      setErreur(null);
      await rafraichir();
    },
    onError: (e) => setErreur(e instanceof ErreurApi ? e.message : "Dépôt impossible."),
  });
  const activer = useMutation({
    mutationFn: (version: number) => requete("POST", `/api/gestion/documents/modeles/${modele.id}/activer-version`, { version }),
    onSuccess: async () => {
      annoncer("Version activée.");
      await rafraichir();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Activation impossible.", "erreur"),
  });
  return (
    <Dialogue ouvert titre={`Versions — ${modele.libelle}`} onFermer={fermer}>
      <p>Téléchargez la version active, modifiez-la dans Word en conservant les champs entre accolades, puis déposez-la : elle est testée avec des données d'exemple avant d'être activée.</p>
      <details>
        <summary>Champs de fusion disponibles</summary>
        <ul className="liste-simple">
          {modele.variables.map((v) => (
            <li key={v}>
              <code>{v}</code>
            </li>
          ))}
        </ul>
      </details>
      {versions.isPending ? <Chargement lignes={2} /> : null}
      {versions.data ? (
        <Tableau<Version>
          legende="Versions du modèle"
          lignes={versions.data}
          cleLigne={(v) => v.id}
          colonnes={[
            { cle: "numero", titre: "Version", rendu: (v) => (v.id === modele.version_active ? <strong>v{v.numero} (active)</strong> : `v${v.numero}`) },
            { cle: "depot", titre: "Déposée", rendu: (v) => `${dateHeure(v.deposee_le)} par ${v.deposee_par}` },
            { cle: "commentaire", titre: "Commentaire", rendu: (v) => v.commentaire || "—" },
          ]}
          actions={(v) => (
            <>
              <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/documents/modeles/${modele.id}/versions/${v.id}/fichier`, v.nom_fichier)} aria-label={`Télécharger la version ${v.numero}`}>
                Télécharger
              </Bouton>
              {peut("gerer_modele") && v.id !== modele.version_active ? (
                <Bouton variante="lien" onClick={() => activer.mutate(v.id)} aria-label={`Activer la version ${v.numero}`}>
                  Activer
                </Bouton>
              ) : null}
            </>
          )}
        />
      ) : null}
      {peut("gerer_modele") ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            deposer.mutate();
          }}
        >
          {erreur ? (
            <p className="alerte alerte--erreur" role="alert">
              {erreur}
            </p>
          ) : null}
          <ChampTexte libelle="Nouvelle version (.docx)" type="file" accept=".docx" obligatoire aide="Document Word, 10 Mo au plus." onChange={(e) => setFichier(e.target.files?.[0] ?? null)} />
          <ChampTexte libelle="Ce qui change" value={commentaire} onChange={(e) => setCommentaire(e.target.value)} maxLength={250} />
          <div className="formulaire__actions">
            <Bouton type="submit" enCours={deposer.isPending} disabled={!fichier}>
              Déposer et activer
            </Bouton>
          </div>
        </form>
      ) : null}
    </Dialogue>
  );
}

export function ModelesDocuments() {
  const modeles = useQuery({ queryKey: ["modeles-documents"], queryFn: () => requete<Modele[]>("GET", "/api/gestion/documents/modeles") });
  const [ouvert, setOuvert] = useState<Modele | null>(null);
  return (
    <Page titre="Modèles de documents" description="Conventions, contrats, devis, factures, avoirs, états des lieux, courriers et attestations, éditables dans Word et versionnés.">
      {modeles.isPending ? <Chargement /> : null}
      {modeles.isError ? <Erreur erreur={modeles.error} reessayer={() => void modeles.refetch()} /> : null}
      {modeles.data ? (
        <Tableau<Modele>
          legende="Modèles de documents"
          lignes={modeles.data}
          cleLigne={(m) => m.id}
          colonnes={[
            { cle: "libelle", titre: "Modèle", rendu: (m) => m.libelle },
            { cle: "description", titre: "Usage", rendu: (m) => m.description },
            { cle: "version", titre: "Version active", rendu: (m) => (m.version_active_numero ? `v${m.version_active_numero}` : "—") },
            { cle: "signature", titre: "Signature", rendu: (m) => (m.signature_requise ? <Badge libelle={`Signataires : ${m.signataires.join(" puis ")}`} ton="info" /> : "Non") },
          ]}
          actions={(m) => (
            <Bouton variante="lien" onClick={() => setOuvert(m)} aria-label={`Versions de ${m.libelle}`}>
              Versions
            </Bouton>
          )}
        />
      ) : null}
      {ouvert ? <Versions modele={ouvert} fermer={() => setOuvert(null)} /> : null}
    </Page>
  );
}

interface Lot {
  id: number;
  modele_code: string;
  libelle: string;
  statut: string;
  total: number;
  faits: number;
  erreurs: { dossier: string; erreur: string }[];
  cree_le: string;
  termine_le: string | null;
}

export function LotsDocuments() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const campagnes = useOptions("campagnes", "/api/gestion/reservations/campagnes", (c) => String(c.nom));
  const [valeurs, setValeurs] = useState({ libelle: "", modele: "convention", campagne: "", signature: false });
  const modeles = useQuery({ queryKey: ["modeles-documents"], queryFn: () => requete<Modele[]>("GET", "/api/gestion/documents/modeles") });
  const lots = useQuery({
    queryKey: ["lots"],
    queryFn: () => requete<PageApi<Lot>>("GET", "/api/gestion/documents/lots"),
    refetchInterval: (q) => (q.state.data?.results.some((l) => ["en_attente", "en_cours"].includes(l.statut)) ? 3000 : false),
  });
  const creer = useMutation({
    mutationFn: async () => {
      const dossiers = await requete<PageApi<{ id: number; statut: string }>>("GET", construireChemin("/api/gestion/reservations/dossiers", { campagne: valeurs.campagne, taille: 500 }));
      return requete<Lot>("POST", "/api/gestion/documents/lots", {
        modele_code: valeurs.modele,
        libelle: valeurs.libelle,
        dossiers: dossiers.results.filter((d) => ["validee", "confirmee"].includes(d.statut)).map((d) => d.id),
        envoyer_signature: valeurs.signature,
      });
    },
    onSuccess: async (l) => {
      annoncer(`Génération lancée : ${l.total} document(s).`);
      await client.invalidateQueries({ queryKey: ["lots"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Lancement impossible.", "erreur"),
  });
  const relancer = useMutation({
    mutationFn: (l: Lot) => requete<Lot>("POST", `/api/gestion/documents/lots/${l.id}/relancer`),
    onSuccess: async (l) => {
      annoncer(`Lot « ${l.libelle} » relancé : les dossiers déjà traités ne le sont pas une seconde fois.`);
      await client.invalidateQueries({ queryKey: ["lots"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Relance impossible.", "erreur"),
  });
  const STATUTS: Record<string, string> = { en_attente: "En attente", en_cours: "En cours", termine: "Terminé", echec: "En échec" };
  return (
    <Page titre="Génération en lot" description="Produire en une fois les conventions (ou tout autre modèle) des dossiers attribués d'une campagne, et les envoyer en signature.">
      {peut("generer_document") ? (
        <form
          className="formulaire"
          onSubmit={(e) => {
            e.preventDefault();
            creer.mutate();
          }}
        >
          <div className="formulaire__grille">
            <ChampTexte libelle="Libellé du lot" obligatoire value={valeurs.libelle} onChange={(e) => setValeurs({ ...valeurs, libelle: e.target.value })} />
            <ChampSelection
              libelle="Modèle"
              obligatoire
              options={(modeles.data ?? []).map((m) => ({ valeur: m.code, libelle: m.libelle }))}
              value={valeurs.modele}
              onChange={(e) => setValeurs({ ...valeurs, modele: e.target.value })}
            />
            <ChampSelection libelle="Campagne (dossiers attribués)" obligatoire options={campagnes} value={valeurs.campagne} onChange={(e) => setValeurs({ ...valeurs, campagne: e.target.value })} />
          </div>
          <CaseACocher libelle="Envoyer chaque document en signature électronique" checked={valeurs.signature} onChange={(e) => setValeurs({ ...valeurs, signature: e.target.checked })} />
          <div className="formulaire__actions formulaire__actions--gauche">
            <Bouton type="submit" enCours={creer.isPending}>
              Lancer la génération
            </Bouton>
          </div>
        </form>
      ) : null}
      {lots.isPending ? <Chargement /> : null}
      {lots.data ? (
        <Tableau<Lot>
          legende="Lots de génération"
          lignes={lots.data.results}
          cleLigne={(l) => l.id}
          messageVide="Aucun lot lancé."
          actions={(l) =>
            peut("generer_document") && (l.statut === "echec" || l.erreurs.length > 0) ? (
              <Bouton variante="lien" onClick={() => relancer.mutate(l)} enCours={relancer.isPending}>
                Relancer<span className="sr-only"> le lot {l.libelle}</span>
              </Bouton>
            ) : null
          }
          colonnes={[
            { cle: "libelle", titre: "Lot", rendu: (l) => `${l.libelle} (${l.modele_code})` },
            { cle: "date", titre: "Lancé le", rendu: (l) => dateHeure(l.cree_le), valeurTri: (l) => l.cree_le },
            {
              cle: "progression",
              titre: "Progression",
              rendu: (l) => (
                <span>
                  <progress max={l.total} value={l.faits} aria-label={`Progression du lot ${l.libelle}`} /> {l.faits} sur {l.total} — {STATUTS[l.statut] ?? l.statut}
                </span>
              ),
            },
            {
              cle: "erreurs",
              titre: "Erreurs",
              rendu: (l) =>
                l.erreurs.length ? (
                  <details>
                    <summary>{l.erreurs.length} erreur(s)</summary>
                    <ul className="liste-simple">
                      {l.erreurs.map((e) => (
                        <li key={e.dossier}>
                          {e.dossier} : {e.erreur}
                        </li>
                      ))}
                    </ul>
                  </details>
                ) : (
                  "Aucune"
                ),
            },
          ]}
        />
      ) : null}
    </Page>
  );
}

interface DocumentAControler {
  id: number;
  numero: string;
  titre: string;
  dossier: number | null;
  dossier_numero: string | null;
  usager_nom: string | null;
  statut: string;
}

/** SIG-05, DSH-06 : scans signés déposés par les usagers, en attente du constat d'un agent (depuis le tableau de bord). */
export function DocumentsAControler() {
  const { peut } = useSession();
  const documents = useQuery({
    queryKey: ["documents-a-controler"],
    queryFn: async () => (await requete<PageApi<DocumentAControler>>("GET", construireChemin("/api/gestion/documents/documents", { statut: "scan_a_controler", taille: 200 }))).results,
    enabled: peut("lire_document"),
  });
  return (
    <Page titre="Documents signés à contrôler" description="Exemplaires signés à la main et déposés par les usagers : le constat se fait depuis la fiche du dossier.">
      {documents.isPending ? <Chargement /> : null}
      {documents.isError ? <Erreur erreur={documents.error} /> : null}
      {documents.data ? (
        <Tableau<DocumentAControler>
          legende="Scans en attente de contrôle"
          lignes={documents.data}
          cleLigne={(d) => d.id}
          messageVide="Aucun document à contrôler."
          colonnes={[
            { cle: "numero", titre: "Document", rendu: (d) => `${d.numero} — ${d.titre}` },
            { cle: "usager", titre: "Usager", rendu: (d) => d.usager_nom ?? "—" },
            {
              cle: "dossier",
              titre: "Dossier",
              rendu: (d) => (d.dossier ? <Link to={`/reservations/dossiers/${d.dossier}`}>Ouvrir le dossier {d.dossier_numero}</Link> : "—"),
            },
          ]}
        />
      ) : null}
    </Page>
  );
}
