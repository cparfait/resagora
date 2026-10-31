/** CAU-01 à CAU-07, RG-11 : cautions attendues, reçues, restituées après l'état des lieux de sortie, retenues
 * motivées avec photos et validées par un second agent au-delà du seuil ; état exportable et alertes de délai. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, DroitsInsuffisants, Erreur } from "../../ui/Etats";
import { dateSimple, euros } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

interface Mouvement {
  action: string;
  de: string;
  vers: string;
  montant: number;
  motif: string;
  agent: string;
  le: string;
}
interface Caution {
  id: number;
  dossier: number;
  dossier_numero: string;
  usager_nom: string;
  espace_nom: string;
  fin_occupation: string;
  montant: number;
  statut: string;
  mode: string;
  reference: string;
  recue_le: string | null;
  montant_retenu: number;
  motif_retenue: string;
  restituee_le: string | null;
  mouvements: Mouvement[];
  derniere_seance: number | null;
  etat_sortie: string | null;
  photos_retenue: number[];
}

const STATUTS: Record<string, { libelle: string; ton: "neutre" | "info" | "succes" | "attention" | "danger" }> = {
  attendue: { libelle: "Attendue", ton: "attention" },
  recue: { libelle: "Reçue", ton: "info" },
  restituable: { libelle: "Restituable", ton: "info" },
  retenue_a_valider: { libelle: "Retenue à valider", ton: "danger" },
  restituee: { libelle: "Restituée", ton: "succes" },
  retenue_partielle: { libelle: "Retenue partielle", ton: "attention" },
  retenue_totale: { libelle: "Retenue totale", ton: "danger" },
  solde_restitue: { libelle: "Solde restitué, retenue à encaisser", ton: "attention" },
  encaissee: { libelle: "Retenue encaissée", ton: "neutre" },
};
const MODES = [
  { valeur: "cheque", libelle: "Chèque (non encaissé)" },
  { valeur: "consignation", libelle: "Consignation auprès du comptable" },
  { valeur: "virement", libelle: "Virement" },
];

type Action = { type: "recevoir" | "etat" | "retenue" | "validation" | "encaisser"; caution: Caution } | null;

const VIDE = { mode: "cheque", reference: "", constat: "conforme", observations: "", montant: "", motif: "", accepter: "oui", commentaire: "" };

export function Cautions({ alertes = false }: { alertes?: boolean }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [statut, setStatut] = useState("");
  const [action, setAction] = useState<Action>(null);
  const [saisie, setSaisie] = useState(VIDE);
  const [photos, setPhotos] = useState<File[]>([]);
  const cautions = useQuery({
    queryKey: ["cautions", alertes, statut],
    queryFn: async () =>
      alertes
        ? requete<Caution[]>("GET", "/api/gestion/finances/cautions/alertes")
        : (await requete<PageApi<Caution>>("GET", construireChemin("/api/gestion/finances/cautions", { statut, taille: 200 }))).results,
    enabled: peut("lire_finances"),
  });
  const operation = useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete<Caution | { id: number }>("POST", url, corps),
    onSuccess: async () => {
      annoncer("Caution mise à jour.");
      setAction(null);
      setSaisie(VIDE);
      setPhotos([]);
      await client.invalidateQueries({ queryKey: ["cautions"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Opération impossible.", "erreur"),
  });
  const valider = () => {
    if (!action) return;
    const c = action.caution;
    const base = `/api/gestion/finances/cautions/${c.id}`;
    const avecPhotos = (champs: Record<string, string>) => {
      const formulaire = new FormData();
      for (const [cle, valeur] of Object.entries(champs)) formulaire.append(cle, valeur);
      for (const photo of photos) formulaire.append("photos", photo);
      return formulaire;
    };
    if (action.type === "recevoir") operation.mutate({ url: `${base}/recevoir`, corps: { mode: saisie.mode, reference: saisie.reference } });
    if (action.type === "etat" && c.derniere_seance)
      operation.mutate({ url: "/api/gestion/finances/etats-des-lieux", corps: avecPhotos({ occurrence: String(c.derniere_seance), constat: saisie.constat, observations: saisie.observations }) });
    if (action.type === "retenue") {
      const centimes = Math.round(Number(saisie.montant.replace(/\s/g, "").replace(",", ".")) * 100);
      operation.mutate({ url: `${base}/retenue`, corps: avecPhotos({ montant: String(centimes), motif: saisie.motif }) });
    }
    if (action.type === "validation") operation.mutate({ url: `${base}/valider-retenue`, corps: { accepter: saisie.accepter === "oui", commentaire: saisie.commentaire } });
    if (action.type === "encaisser") operation.mutate({ url: `${base}/encaisser`, corps: { reference: saisie.reference } });
  };
  if (!peut("lire_finances")) return <DroitsInsuffisants />;
  return (
    <Page
      titre={alertes ? "Cautions à restituer en retard" : "Cautions"}
      description={alertes ? "Cautions dont le délai de restitution après la fin d'occupation est dépassé (CAU-07)." : "La restitution n'est possible qu'après l'état des lieux de sortie (RG-11) ; une retenue est motivée et illustrée de photos."}
      actions={
        alertes ? null : (
          <Bouton variante="secondaire" onClick={() => void telecharger(construireChemin("/api/gestion/finances/cautions/export", { statut }), "etat-cautions.csv")}>
            Exporter l'état (tableur)
          </Bouton>
        )
      }
    >
      {alertes ? null : (
        <form className="formulaire-ligne" onSubmit={(e) => e.preventDefault()}>
          <ChampSelection libelle="État" videLibelle="Tous" options={Object.entries(STATUTS).map(([valeur, s]) => ({ valeur, libelle: s.libelle }))} value={statut} onChange={(e) => setStatut(e.target.value)} />
        </form>
      )}
      {cautions.isPending ? <Chargement /> : null}
      {cautions.isError ? <Erreur erreur={cautions.error} /> : null}
      {cautions.data ? (
        <Tableau<Caution>
          legende={alertes ? "Cautions en retard" : "Cautions"}
          lignes={cautions.data}
          cleLigne={(c) => c.id}
          messageVide="Aucune caution."
          colonnes={[
            { cle: "dossier", titre: "Dossier", rendu: (c) => `${c.dossier_numero} — ${c.usager_nom}` },
            { cle: "espace", titre: "Espace", rendu: (c) => `${c.espace_nom}, jusqu'au ${dateSimple(c.fin_occupation)}`, valeurTri: (c) => c.fin_occupation },
            { cle: "montant", titre: "Montant", rendu: (c) => `${euros(c.montant)}${c.montant_retenu ? `, retenue ${euros(c.montant_retenu)}` : ""}`, valeurTri: (c) => c.montant },
            { cle: "depot", titre: "Dépôt", rendu: (c) => (c.recue_le ? `${MODES.find((m) => m.valeur === c.mode)?.libelle ?? c.mode} ${c.reference}, le ${dateSimple(c.recue_le)}` : "—") },
            { cle: "sortie", titre: "État des lieux de sortie", rendu: (c) => (c.etat_sortie === "conforme" ? "Conforme" : c.etat_sortie === "degats" ? "Dégâts constatés" : "Non établi") },
            { cle: "statut", titre: "État", rendu: (c) => <Badge libelle={STATUTS[c.statut]?.libelle ?? c.statut} ton={STATUTS[c.statut]?.ton ?? "neutre"} /> },
          ]}
          actions={(c) => (
            <>
              {peut("gerer_caution") && c.statut === "attendue" ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "recevoir", caution: c })}>
                  Enregistrer le dépôt<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("gerer_caution") && ["recue", "restituable"].includes(c.statut) && !c.etat_sortie && c.derniere_seance ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "etat", caution: c })}>
                  État des lieux de sortie<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("gerer_caution") && c.statut === "restituable" ? (
                <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/finances/cautions/${c.id}/restituer` })}>
                  Restituer<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("proposer_retenue") && ["recue", "restituable"].includes(c.statut) && c.etat_sortie ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "retenue", caution: c })}>
                  Proposer une retenue<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("valider_retenue") && c.statut === "retenue_a_valider" ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "validation", caution: c })}>
                  Statuer sur la retenue<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("gerer_caution") && c.statut === "retenue_partielle" ? (
                <Bouton variante="lien" onClick={() => operation.mutate({ url: `/api/gestion/finances/cautions/${c.id}/restituer` })}>
                  Restituer le solde<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
              {peut("gerer_caution") && ["solde_restitue", "retenue_totale"].includes(c.statut) ? (
                <Bouton variante="lien" onClick={() => setAction({ type: "encaisser", caution: c })}>
                  Encaisser la retenue<span className="visuellement-masque"> : {c.dossier_numero}</span>
                </Bouton>
              ) : null}
            </>
          )}
        />
      ) : null}
      <Dialogue ouvert={action !== null} titre="Caution" onFermer={() => setAction(null)}>
        {action ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              valider();
            }}
          >
            <p>
              {action.caution.dossier_numero} — {action.caution.usager_nom} — {euros(action.caution.montant)}
            </p>
            {action.type === "recevoir" ? (
              <>
                <ChampSelection libelle="Mode de dépôt" obligatoire options={MODES} videLibelle="— Choisir —" value={saisie.mode} onChange={(e) => setSaisie({ ...saisie, mode: e.target.value })} />
                <ChampTexte libelle="Référence (n° de chèque, de consignation…)" obligatoire value={saisie.reference} onChange={(e) => setSaisie({ ...saisie, reference: e.target.value })} />
              </>
            ) : null}
            {action.type === "etat" ? (
              <>
                <ChampSelection
                  libelle="Constat"
                  obligatoire
                  options={[
                    { valeur: "conforme", libelle: "Conforme" },
                    { valeur: "degats", libelle: "Dégâts constatés" },
                  ]}
                  value={saisie.constat}
                  onChange={(e) => setSaisie({ ...saisie, constat: e.target.value })}
                />
                <ChampZone libelle="Observations" obligatoire={saisie.constat === "degats"} value={saisie.observations} onChange={(e) => setSaisie({ ...saisie, observations: e.target.value })} />
              </>
            ) : null}
            {action.type === "retenue" ? (
              <>
                <ChampTexte libelle="Montant retenu (€)" inputMode="decimal" obligatoire value={saisie.montant} onChange={(e) => setSaisie({ ...saisie, montant: e.target.value })} />
                <ChampZone libelle="Motif (nature des dégâts, coût de remise en état)" obligatoire value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
              </>
            ) : null}
            {action.type === "etat" || action.type === "retenue" ? (
              <ChampTexte
                libelle="Photos"
                type="file"
                accept=".jpg,.jpeg,.png"
                multiple
                obligatoire={action.type === "retenue"}
                aide="JPEG ou PNG, 10 photos au plus."
                onChange={(e) => setPhotos(Array.from(e.target.files ?? []))}
              />
            ) : null}
            {action.type === "validation" ? (
              <>
                <p>
                  Retenue proposée : {euros(action.caution.montant_retenu)} — {action.caution.motif_retenue}
                </p>
                <ul className="liste-simple">
                  {action.caution.photos_retenue.map((photo, rang) => (
                    <li key={photo}>
                      <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/finances/cautions/${action.caution.id}/photos/${photo}`, `photo-${rang + 1}.jpg`)}>
                        Voir la photo {rang + 1}
                      </Bouton>
                    </li>
                  ))}
                </ul>
                <ChampSelection
                  libelle="Décision"
                  obligatoire
                  options={[
                    { valeur: "oui", libelle: "Valider la retenue" },
                    { valeur: "non", libelle: "Refuser la retenue (caution restituable)" },
                  ]}
                  value={saisie.accepter}
                  onChange={(e) => setSaisie({ ...saisie, accepter: e.target.value })}
                />
                <ChampTexte libelle="Commentaire" value={saisie.commentaire} onChange={(e) => setSaisie({ ...saisie, commentaire: e.target.value })} />
              </>
            ) : null}
            {action.type === "encaisser" ? (
              <ChampTexte libelle="Référence de l'encaissement (titre)" obligatoire value={saisie.reference} onChange={(e) => setSaisie({ ...saisie, reference: e.target.value })} />
            ) : null}
            {action.caution.mouvements.length ? (
              <details>
                <summary>Journal de la caution</summary>
                <ul className="liste-simple">
                  {action.caution.mouvements.map((m) => (
                    <li key={`${m.le}-${m.action}`}>
                      {dateSimple(m.le)} — {STATUTS[m.vers]?.libelle ?? m.vers} {m.montant ? `(${euros(m.montant)})` : ""} — {m.agent}
                      {m.motif ? ` — ${m.motif}` : ""}
                    </li>
                  ))}
                </ul>
              </details>
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
    </Page>
  );
}

export default function CautionsPage() {
  return <Cautions />;
}

export function CautionsEnAlerte() {
  return <Cautions alertes />;
}
