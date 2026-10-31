/** TAR-07 : suivi des paiements en ligne PayFiP — tentatives, résultat relu auprès de la DGFiP (notification, retour,
 * rapprochement horaire), contrôles (résultat incohérent ou inconnu, paiement déjà encaissé), trop-perçus et leur
 * remboursement. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErreurApi, requete } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge, type Ton } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { dateHeure, dateSimple, euros, isoJour } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource } from "../../ui/Ressource";

interface Tentative extends Record<string, unknown> {
  id: number;
  facture: string;
  usager_nom: string;
  mode: string;
  refdet: string;
  montant: number;
  statut: string;
  statut_libelle: string;
  numauto: string;
  paye_le: string | null;
  trop_percu: number;
  controle: string;
  controle_libelle: string;
  rembourse_le: string | null;
  erreur: string;
  motif_cloture: string;
  cree_le: string;
  verifiee_le: string | null;
}

const TONS: Record<string, Ton> = {
  creee: "neutre",
  redirigee: "info",
  remplacee: "info",
  payee: "succes",
  refusee: "attention",
  abandonnee: "neutre",
  expiree: "neutre",
  a_controler: "danger",
  erreur: "neutre",
};

const STATUTS = [
  { valeur: "a_controler", libelle: "À contrôler" },
  { valeur: "creee,redirigee,remplacee", libelle: "En attente d'un résultat" },
  { valeur: "payee", libelle: "Payées" },
  { valeur: "refusee", libelle: "Refusées par la banque" },
  { valeur: "abandonnee", libelle: "Abandonnées" },
  { valeur: "expiree", libelle: "Sans résultat (relues 7 jours)" },
  { valeur: "erreur", libelle: "Closes sans paiement" },
];
const CONTROLES = [
  { valeur: "trop_percu,doublon_probable", libelle: "Trop-perçus" },
  { valeur: "incoherent,resultat_inconnu,saisie_test", libelle: "Résultats à vérifier" },
];

type Action = { genre: "clore" | "rembourser"; tentative: Tentative } | null;

export default function PaiementsEnLigne() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [action, setAction] = useState<Action>(null);
  const [saisie, setSaisie] = useState(() => ({ motif: "", date: isoJour(new Date()), reference: "", par: "ville" }));
  const operation = useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete<Record<string, unknown>>("POST", url, corps),
    onSuccess: async (r) => {
      annoncer("programme" in r ? "Rapprochement lancé : les résultats apparaîtront dans quelques instants." : `Enregistré : ${String(r.statut_libelle ?? "")}.`);
      setAction(null);
      await client.invalidateQueries({ queryKey: ["paiements-en-ligne"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Action impossible.", "erreur"),
  });
  const regie = peut("encaisser");
  const base = "/api/gestion/finances/paiements-en-ligne";
  return (
    <>
      <EcranRessource<Tentative>
        titre="Paiements en ligne (PayFiP)"
        description="Chaque passage d'un usager sur PayFiP. Le résultat est lu auprès de la DGFiP (notification, retour de l'usager, rapprochement chaque heure) : seul un paiement « payé » crée un encaissement. Une tentative remplacée ou sans résultat reste relue : un paiement tardif n'est jamais perdu."
        chemin={base}
        cleRequete="paiements-en-ligne"
        actionLecture="lire_finances"
        libelleObjet="Paiement"
        filtres={[
          { nom: "statut__in", libelle: "État", options: STATUTS },
          { nom: "controle__in", libelle: "Contrôle", options: CONTROLES },
        ]}
        actionsPage={
          regie ? (
            <Bouton variante="secondaire" onClick={() => operation.mutate({ url: `${base}/rapprocher` })} enCours={operation.isPending}>
              Rapprocher maintenant
            </Bouton>
          ) : null
        }
        colonnes={[
          { cle: "cree_le", titre: "Le", rendu: (t) => dateHeure(t.cree_le), valeurTri: (t) => t.cree_le },
          { cle: "facture", titre: "Facture", rendu: (t) => `${t.facture} (${t.mode === "titres" ? "titre " : "réf. "}${t.refdet})` },
          { cle: "usager", titre: "Usager", rendu: (t) => t.usager_nom },
          { cle: "montant", titre: "Montant", rendu: (t) => euros(t.montant), valeurTri: (t) => t.montant },
          {
            cle: "statut",
            titre: "État",
            rendu: (t) => (
              <>
                <Badge libelle={t.statut_libelle} ton={TONS[t.statut] ?? "neutre"} />
                {t.numauto ? ` autorisation ${t.numauto}` : ""}
                {t.controle ? <Badge libelle={t.trop_percu ? `${t.controle_libelle} : ${euros(t.trop_percu)}` : t.controle_libelle} ton={t.rembourse_le ? "succes" : "danger"} /> : null}
                {t.rembourse_le ? <span className="aide"> remboursé le {dateSimple(t.rembourse_le)}</span> : null}
                {t.erreur ? <span className="aide"> {t.erreur}</span> : null}
                {t.motif_cloture ? <span className="aide"> Clôture : {t.motif_cloture}</span> : null}
              </>
            ),
          },
          { cle: "verifiee", titre: "Relu auprès de PayFiP", rendu: (t) => (t.verifiee_le ? dateHeure(t.verifiee_le) : "—") },
        ]}
        actionsLigne={(t) =>
          regie ? (
            <span className="actions">
              {["creee", "redirigee", "remplacee", "expiree"].includes(t.statut) ? (
                <Bouton variante="lien" onClick={() => operation.mutate({ url: `${base}/${t.id}/verifier` })}>
                  Vérifier auprès de PayFiP<span className="visuellement-masque"> : {t.facture}</span>
                </Bouton>
              ) : null}
              {t.statut === "a_controler" ? (
                <Bouton variante="lien" onClick={() => setAction({ genre: "clore", tentative: t })}>
                  Clore après contrôle<span className="visuellement-masque"> : {t.facture}</span>
                </Bouton>
              ) : null}
              {t.trop_percu > 0 && !t.rembourse_le ? (
                <Bouton variante="lien" onClick={() => setAction({ genre: "rembourser", tentative: t })}>
                  Enregistrer le remboursement<span className="visuellement-masque"> : {t.facture}</span>
                </Bouton>
              ) : null}
            </span>
          ) : null
        }
      />
      <Dialogue ouvert={action?.genre === "clore"} titre="Clore un paiement à contrôler" onFermer={() => setAction(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (action) operation.mutate({ url: `${base}/${action.tentative.id}/clore`, corps: { motif: saisie.motif } });
          }}
        >
          <p>Après vérification auprès de la DGFiP. Un paiement réellement reçu se pointe comme tout règlement (Encaissements) avant la clôture.</p>
          <ChampZone libelle="Résultat de la vérification" obligatoire value={saisie.motif} onChange={(e) => setSaisie({ ...saisie, motif: e.target.value })} />
          <Bouton type="submit" enCours={operation.isPending}>
            Clore
          </Bouton>
        </form>
      </Dialogue>
      <Dialogue ouvert={action?.genre === "rembourser"} titre="Remboursement d'un trop-perçu" onFermer={() => setAction(null)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (action) operation.mutate({ url: `${base}/${action.tentative.id}/rembourser`, corps: { date: saisie.date, reference: saisie.reference, par: saisie.par } });
          }}
        >
          <p>{action ? `${euros(action.tentative.trop_percu)} sur la facture ${action.tentative.facture}.` : ""}</p>
          <ChampTexte libelle="Date du remboursement" type="date" obligatoire value={saisie.date} onChange={(e) => setSaisie({ ...saisie, date: e.target.value })} />
          <ChampTexte libelle="Référence (mandat, virement)" obligatoire value={saisie.reference} onChange={(e) => setSaisie({ ...saisie, reference: e.target.value })} />
          <ChampSelection
            libelle="Remboursé par"
            obligatoire
            options={[
              { valeur: "ville", libelle: "La régie de la Ville" },
              { valeur: "comptable", libelle: "Le comptable public" },
            ]}
            value={saisie.par}
            onChange={(e) => setSaisie({ ...saisie, par: e.target.value })}
          />
          <Bouton type="submit" enCours={operation.isPending}>
            Enregistrer
          </Bouton>
        </form>
      </Dialogue>
    </>
  );
}
