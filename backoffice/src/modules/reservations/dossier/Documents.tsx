/** DOC-02 à DOC-07, SIG-01 à SIG-05 : documents du dossier, génération, signature, avenant, scan signé. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../../api/http";
import { useSession } from "../../../auth/session";
import { Badge } from "../../../ui/Badge";
import { Bouton } from "../../../ui/Bouton";
import { ChampSelection, ChampTexte, ChampZone } from "../../../ui/Champ";
import { Dialogue } from "../../../ui/Dialogue";
import { Chargement, Erreur } from "../../../ui/Etats";
import { dateHeure, dateSimple } from "../../../ui/metier";
import { useNotifications } from "../../../ui/Notifications";
import { Tableau } from "../../../ui/Tableau";

interface Signataire {
  ordre: number;
  role: string;
  nom: string;
  statut: string;
  signe_le: string | null;
}
interface Circuit {
  id: number;
  mode: string;
  statut: string;
  expire_le: string | null;
  erreur: string;
  signataires: Signataire[];
}
interface DocumentDossier {
  id: number;
  numero: string;
  titre: string;
  modele_libelle: string;
  version_numero: number;
  statut: string;
  signature_requise: boolean;
  parent_numero: string;
  signe_le: string | null;
  cree_le: string;
  circuits: Circuit[];
}
interface Modele {
  id: number;
  code: string;
  libelle: string;
  actif: boolean;
}

const TONS: Record<string, "neutre" | "info" | "succes" | "attention" | "danger"> = {
  genere: "info",
  en_signature: "attention",
  signe: "succes",
  signe_manuellement: "succes",
  annule: "neutre",
};
const LIBELLES: Record<string, string> = {
  genere: "Généré",
  en_signature: "En signature",
  signe: "Signé électroniquement",
  signe_manuellement: "Signé manuellement",
  annule: "Annulé",
};
const STATUTS_CIRCUIT: Record<string, string> = {
  preparation: "dépôt en cours",
  envoye: "en attente de signature",
  signe: "signé",
  expire: "délai dépassé",
  annule: "annulé",
  refuse: "refusé",
  erreur: "erreur d'envoi",
};

type Action = { type: "avenant" | "annuler" | "annuler_signature"; document: DocumentDossier } | { type: "scan"; document: DocumentDossier } | null;

export function DocumentsDossier({ dossier }: { dossier: number }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [modele, setModele] = useState("");
  const [action, setAction] = useState<Action>(null);
  const [motif, setMotif] = useState("");
  const [scan, setScan] = useState<File | null>(null);
  const documents = useQuery({
    queryKey: ["documents", dossier],
    queryFn: () => requete<PageApi<DocumentDossier>>("GET", construireChemin("/api/gestion/documents/documents", { dossier, taille: 100 })),
  });
  const modeles = useQuery({ queryKey: ["modeles-documents"], queryFn: () => requete<Modele[]>("GET", "/api/gestion/documents/modeles") });
  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["documents", dossier] });
    await client.invalidateQueries({ queryKey: ["dossier"] });
  };
  const operation = useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete<DocumentDossier>("POST", url, corps),
    onSuccess: async (d) => {
      annoncer(`Document ${d.numero} : ${LIBELLES[d.statut] ?? d.statut}.`);
      setAction(null);
      setMotif("");
      setScan(null);
      await rafraichir();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });

  const soumettreAction = () => {
    if (!action) return;
    const base = `/api/gestion/documents/documents/${action.document.id}`;
    if (action.type === "scan") {
      if (!scan) return;
      const formulaire = new FormData();
      formulaire.append("fichier", scan);
      operation.mutate({ url: `${base}/scan-signe`, corps: formulaire });
    } else {
      const verbe = { avenant: "avenant", annuler: "annuler", annuler_signature: "annuler-signature" }[action.type];
      operation.mutate({ url: `${base}/${verbe}`, corps: { motif } });
    }
  };

  return (
    <section aria-labelledby="titre-documents" className="carte">
      <h2 id="titre-documents">Documents</h2>
      {peut("generer_document") && modeles.data ? (
        <form
          className="formulaire-ligne"
          onSubmit={(e) => {
            e.preventDefault();
            if (modele) operation.mutate({ url: "/api/gestion/documents/documents/generer", corps: { modele, dossier } });
          }}
        >
          <ChampSelection
            libelle="Modèle à générer"
            options={modeles.data.filter((m) => m.actif).map((m) => ({ valeur: m.code, libelle: m.libelle }))}
            value={modele}
            onChange={(e) => setModele(e.target.value)}
          />
          <Bouton type="submit" variante="secondaire" enCours={operation.isPending} disabled={!modele}>
            Générer le PDF
          </Bouton>
        </form>
      ) : null}
      {documents.isPending ? <Chargement lignes={2} /> : null}
      {documents.isError ? <Erreur erreur={documents.error} /> : null}
      {documents.data ? (
        <Tableau<DocumentDossier>
          legende="Documents du dossier"
          lignes={documents.data.results}
          cleLigne={(d) => d.id}
          messageVide="Aucun document pour ce dossier."
          colonnes={[
            { cle: "numero", titre: "Numéro", rendu: (d) => d.numero, valeurTri: (d) => d.numero },
            { cle: "titre", titre: "Document", rendu: (d) => `${d.modele_libelle} (modèle v${d.version_numero})${d.parent_numero ? ` — avenant à ${d.parent_numero}` : ""}` },
            { cle: "date", titre: "Généré le", rendu: (d) => dateSimple(d.cree_le), valeurTri: (d) => d.cree_le },
            {
              cle: "statut",
              titre: "État",
              rendu: (d) => {
                const circuit = d.circuits[0];
                return (
                  <span className="badges">
                    <Badge libelle={LIBELLES[d.statut] ?? d.statut} ton={TONS[d.statut] ?? "neutre"} />
                    {circuit && d.statut === "en_signature" ? (
                      <span className="texte-doux">
                        Signature {STATUTS_CIRCUIT[circuit.statut] ?? circuit.statut}
                        {circuit.expire_le ? `, échéance ${dateHeure(circuit.expire_le)}` : ""}
                        {circuit.signataires.map((s) => ` — ${s.nom} : ${s.statut === "signe" ? "signé" : "en attente"}`).join("")}
                        {circuit.erreur ? ` (${circuit.erreur})` : ""}
                      </span>
                    ) : null}
                  </span>
                );
              },
            },
          ]}
          actions={(d) => (
            <>
              <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/documents/documents/${d.id}/fichier`, `${d.numero}.pdf`)} aria-label={`Télécharger ${d.numero}`}>
                Télécharger
              </Bouton>
              {peut("envoyer_signature") && d.statut === "genere" && d.signature_requise ? (
                <>
                  <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/documents/documents/${d.id}/envoyer-signature`, corps: { mode: "docuseal" } })}>
                    Signature électronique
                  </Bouton>
                  <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/documents/documents/${d.id}/envoyer-signature`, corps: { mode: "manuel" } })}>
                    Signature papier
                  </Bouton>
                </>
              ) : null}
              {peut("envoyer_signature") && ["genere", "en_signature"].includes(d.statut) && d.signature_requise ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "scan", document: d })}>
                  Déposer le scan signé
                </Bouton>
              ) : null}
              {peut("envoyer_signature") && d.statut === "en_signature" ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "annuler_signature", document: d })}>
                  Annuler la signature
                </Bouton>
              ) : null}
              {peut("generer_document") && ["signe", "signe_manuellement"].includes(d.statut) ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "avenant", document: d })}>
                  Avenant…
                </Bouton>
              ) : null}
              {peut("generer_document") && d.statut === "genere" ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "annuler", document: d })}>
                  Annuler
                </Bouton>
              ) : null}
            </>
          )}
        />
      ) : null}
      <Dialogue
        ouvert={action !== null}
        titre={
          action?.type === "scan"
            ? "Déposer le document signé"
            : action?.type === "avenant"
              ? "Produire un avenant"
              : action?.type === "annuler_signature"
                ? "Annuler la signature en cours"
                : "Annuler le document"
        }
        onFermer={() => setAction(null)}
      >
        {action ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              soumettreAction();
            }}
          >
            <p>{action.document.numero} — {action.document.titre}</p>
            {action.type === "scan" ? (
              <ChampTexte
                libelle="Scan du document signé"
                type="file"
                accept=".pdf,application/pdf"
                obligatoire
                aide="PDF uniquement, 10 Mo au plus."
                onChange={(e) => setScan(e.target.files?.[0] ?? null)}
              />
            ) : (
              <ChampZone
                libelle={action.type === "avenant" ? "Objet de l'avenant (repris dans le document)" : "Motif"}
                obligatoire
                value={motif}
                onChange={(e) => setMotif(e.target.value)}
              />
            )}
            {action.type === "avenant" ? <p>Le document signé reste inchangé ; l'avenant reprend les créneaux en vigueur du dossier.</p> : null}
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setAction(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" variante={action.type === "annuler" || action.type === "annuler_signature" ? "danger" : "principal"} enCours={operation.isPending}>
                Valider
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </section>
  );
}
