/** Mes devis, factures et cautions (TAR-04, TAR-12, CAU-02) et simulateur de tarif public (TAR-11). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { messageErreur, requete, telecharger } from "../api/http";
import { Bouton } from "../ui/Bouton";
import { Case, Champ, Liste } from "../ui/Champs";
import { Alerte, Chargement, ErreurChargement, TitrePage, date } from "../ui/Elements";

export interface PiecePortail {
  id: number;
  numero: string;
  nature: string;
  nature_libelle: string;
  dossier: number;
  dossier_numero: string;
  objet: string;
  statut: string;
  statut_libelle: string;
  emise_le: string | null;
  echeance: string | null;
  validite: string | null;
  total_du: number;
  total_texte: string;
  reste_texte: string;
  facture_origine: string;
  lignes: { libelle: string; montant_reference: number; reduction: number; montant_du: number }[];
  a_accepter: boolean;
  pdf: boolean;
  reglement: { titulaire: string; iban: string; bic: string; reference: string } | null;
}

interface CautionPortail {
  id: number;
  dossier_numero: string;
  espace: string;
  montant_texte: string;
  statut_libelle: string;
  motif_retenue: string;
  a_deposer_avant: string | null;
  restituee_le: string | null;
}

const euros = (centimes: number) => new Intl.NumberFormat("fr-FR", { style: "currency", currency: "EUR" }).format(centimes / 100);

/** Liste des pièces, avec acceptation du devis et coordonnées de règlement par virement. */
export function ListePieces({ pieces, dossier }: { pieces: PiecePortail[]; dossier?: number }) {
  const client = useQueryClient();
  const [annonce, setAnnonce] = useState<{ ton: "succes" | "erreur"; texte: string } | null>(null);
  const accepter = useMutation({
    mutationFn: (p: PiecePortail) => requete<PiecePortail>("POST", `/api/portail/dossiers/${p.dossier}/devis/${p.id}/accepter`),
    onSuccess: async (p) => {
      setAnnonce({ ton: "succes", texte: `Devis ${p.numero} accepté. Le service vous adresse la suite (acompte, convention).` });
      await client.invalidateQueries({ queryKey: ["factures"] });
    },
    onError: (e) => setAnnonce({ ton: "erreur", texte: messageErreur(e) }),
  });
  if (!pieces.length) return <p>{dossier ? "Aucun devis ni facture pour ce dossier." : "Aucun devis ni facture pour le moment."}</p>;
  return (
    <>
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      <ul className="liste-documents">
        {pieces.map((p) => (
          <li key={p.id}>
            <p>
              <strong>
                {p.nature_libelle} {p.numero}
              </strong>{" "}
              — {p.statut_libelle} — {p.total_texte}
              {p.emise_le ? `, émis le ${date(p.emise_le)}` : ""}
              {p.nature === "devis" && p.validite ? `, valable jusqu'au ${date(p.validite)}` : ""}
              {p.facture_origine ? `, sur la facture ${p.facture_origine}` : ""}
            </p>
            {p.lignes.length ? (
              <table className="tableau">
                <caption className="visuellement-masque">Détail de {p.numero}</caption>
                <thead>
                  <tr>
                    <th scope="col">Désignation</th>
                    <th scope="col">Tarif</th>
                    <th scope="col">Réduction</th>
                    <th scope="col">Montant</th>
                  </tr>
                </thead>
                <tbody>
                  {p.lignes.map((l, rang) => (
                    <tr key={rang}>
                      <th scope="row">{l.libelle}</th>
                      <td>{euros(l.montant_reference)}</td>
                      <td>{l.reduction ? (l.reduction === 10000 ? "Gratuité" : `${l.reduction / 100} %`) : "—"}</td>
                      <td>{euros(l.montant_du)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
            {p.reglement ? (
              <div className="encadre">
                <p>
                  Reste à régler : <strong>{p.reste_texte}</strong>
                  {p.echeance ? ` avant le ${date(p.echeance)}` : ""}. Règlement par virement au comptable public :
                </p>
                <dl className="details">
                  <dt>Titulaire</dt>
                  <dd>{p.reglement.titulaire}</dd>
                  <dt>IBAN</dt>
                  <dd>{p.reglement.iban}</dd>
                  <dt>BIC</dt>
                  <dd>{p.reglement.bic}</dd>
                  <dt>Référence à indiquer</dt>
                  <dd>{p.reglement.reference}</dd>
                </dl>
              </div>
            ) : null}
            <p className="actions">
              {p.pdf ? (
                <Bouton variante="secondaire" onClick={() => void telecharger(`/api/portail/factures/${p.id}/fichier`, `${p.numero}.pdf`)}>
                  Télécharger<span className="visuellement-masque"> {p.nature_libelle} {p.numero}</span> (PDF)
                </Bouton>
              ) : null}
              {p.a_accepter ? (
                <Bouton onClick={() => accepter.mutate(p)} enCours={accepter.isPending}>
                  Accepter le devis<span className="visuellement-masque"> {p.numero}</span>
                </Bouton>
              ) : null}
            </p>
          </li>
        ))}
      </ul>
    </>
  );
}

export function PiecesDuDossier({ dossier }: { dossier: number }) {
  const pieces = useQuery({ queryKey: ["factures", dossier], queryFn: () => requete<PiecePortail[]>("GET", `/api/portail/factures?dossier=${dossier}`) });
  return (
    <section aria-labelledby="titre-pieces-dossier">
      <h2 id="titre-pieces-dossier">Devis et factures</h2>
      {pieces.isPending ? <Chargement /> : null}
      {pieces.isError ? <ErreurChargement erreur={pieces.error} /> : null}
      {pieces.data ? <ListePieces pieces={pieces.data} dossier={dossier} /> : null}
    </section>
  );
}

export function MesFinances() {
  const pieces = useQuery({ queryKey: ["factures"], queryFn: () => requete<PiecePortail[]>("GET", "/api/portail/factures") });
  const cautions = useQuery({ queryKey: ["cautions"], queryFn: () => requete<CautionPortail[]>("GET", "/api/portail/cautions") });
  return (
    <>
      <TitrePage titre="Mes devis, factures et cautions">
        <p className="chapo">Les factures sont réglées par virement au comptable public, en indiquant la référence de la facture. Un titre de recettes vous est ensuite adressé.</p>
      </TitrePage>
      <section aria-labelledby="titre-pieces">
        <h2 id="titre-pieces">Devis et factures</h2>
        {pieces.isPending ? <Chargement /> : null}
        {pieces.isError ? <ErreurChargement erreur={pieces.error} /> : null}
        {pieces.data ? <ListePieces pieces={pieces.data} /> : null}
      </section>
      <section aria-labelledby="titre-cautions">
        <h2 id="titre-cautions">Cautions</h2>
        {cautions.isPending ? <Chargement /> : null}
        {cautions.data?.length === 0 ? <p>Aucune caution.</p> : null}
        {cautions.data?.length ? (
          <table className="tableau">
            <caption>Cautions de vos réservations</caption>
            <thead>
              <tr>
                <th scope="col">Dossier</th>
                <th scope="col">Équipement</th>
                <th scope="col">Montant</th>
                <th scope="col">État</th>
              </tr>
            </thead>
            <tbody>
              {cautions.data.map((c) => (
                <tr key={c.id}>
                  <th scope="row">{c.dossier_numero}</th>
                  <td>{c.espace}</td>
                  <td>{c.montant_texte}</td>
                  <td>
                    {c.statut_libelle}
                    {c.a_deposer_avant ? ` (avant le ${date(c.a_deposer_avant)})` : ""}
                    {c.restituee_le ? ` le ${date(c.restituee_le)}` : ""}
                    {c.motif_retenue ? ` — motif : ${c.motif_retenue}` : ""}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </section>
    </>
  );
}

const CATEGORIES = [
  { valeur: "particulier", libelle: "Particulier" },
  { valeur: "association_locale", libelle: "Association de Châtillon" },
  { valeur: "association", libelle: "Autre association" },
  { valeur: "entreprise", libelle: "Entreprise ou comité social et économique" },
  { valeur: "ecole", libelle: "École ou établissement scolaire" },
  { valeur: "autre_collectivite", libelle: "Autre collectivité ou organisme public" },
];

interface Simulation {
  lignes: { libelle: string; montant: number; montant_texte: string }[];
  total_texte: string;
  caution: number;
  caution_texte: string;
  mention: string;
}

export function SimulateurTarif({ espace }: { espace: number }) {
  const [valeurs, setValeurs] = useState({ date: "", heure_debut: "", heure_fin: "", categorie: "particulier", resident: true });
  const [resultat, setResultat] = useState<Simulation | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const simuler = useMutation({
    mutationFn: () => requete<Simulation>("POST", "/api/portail/simulation-tarif", { espace, ...valeurs }),
    onSuccess: (r) => {
      setResultat(r);
      setErreur(null);
    },
    onError: (e) => {
      setResultat(null);
      setErreur(messageErreur(e));
    },
  });
  return (
    <section aria-labelledby="titre-simulation">
      <h2 id="titre-simulation">Estimer le tarif</h2>
      <form
        className="formulaire"
        onSubmit={(e) => {
          e.preventDefault();
          simuler.mutate();
        }}
      >
        <div className="formulaire__ligne">
          <Champ libelle="Date" type="date" obligatoire aide="Format : jj/mm/aaaa." value={valeurs.date} onChange={(e) => setValeurs({ ...valeurs, date: e.target.value })} />
          <Champ libelle="Heure de début" type="time" obligatoire value={valeurs.heure_debut} onChange={(e) => setValeurs({ ...valeurs, heure_debut: e.target.value })} />
          <Champ libelle="Heure de fin" type="time" obligatoire value={valeurs.heure_fin} onChange={(e) => setValeurs({ ...valeurs, heure_fin: e.target.value })} />
        </div>
        <Liste libelle="Vous êtes" vide={null} options={CATEGORIES} value={valeurs.categorie} onChange={(e) => setValeurs({ ...valeurs, categorie: e.target.value })} />
        <Case libelle="Domicile ou siège à Châtillon" checked={valeurs.resident} onChange={(e) => setValeurs({ ...valeurs, resident: e.target.checked })} />
        <Bouton type="submit" variante="secondaire" enCours={simuler.isPending}>
          Estimer
        </Bouton>
      </form>
      <div aria-live="polite">
        {erreur ? <Alerte ton="erreur">{erreur}</Alerte> : null}
        {resultat ? (
          <div className="encadre">
            <ul className="liste-simple">
              {resultat.lignes.map((l) => (
                <li key={l.libelle}>
                  {l.libelle} : {l.montant_texte}
                </li>
              ))}
            </ul>
            <p>
              Total estimé : <strong>{resultat.total_texte}</strong>
              {resultat.caution ? `. Caution demandée : ${resultat.caution_texte}` : ""}.
            </p>
            <p className="aide">{resultat.mention}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
