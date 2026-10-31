/** VAL-04 : attestations annuelles des concours en nature (mises à disposition gratuites ou à tarif réduit, matériel,
 * personnel), à reprendre dans le compte rendu financier et l'annexe des comptes de l'association. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { messageErreur, requete, telecharger } from "../api/http";
import { Bouton } from "../ui/Bouton";
import { Alerte, Chargement, ErreurChargement, TitrePage, date } from "../ui/Elements";

interface AttestationPortail {
  id: number;
  exercice: number;
  usager: number;
  usager_nom: string;
  montant: number;
  montant_texte: string;
  deposee_le: string;
  numero: string;
}

export function MesAttestations() {
  const attestations = useQuery({ queryKey: ["attestations"], queryFn: () => requete<AttestationPortail[]>("GET", "/api/portail/attestations") });
  const [erreur, setErreur] = useState<string | null>(null);
  return (
    <>
      <TitrePage titre="Attestations de valorisation">
        <p className="chapo">
          Chaque année, la Ville vous adresse le montant des avantages en nature dont votre association a bénéficié (salles, matériel, personnel). Ce montant figure au compte rendu financier et dans
          l'annexe de vos comptes, en contributions volontaires en nature.
        </p>
      </TitrePage>
      {erreur ? <Alerte ton="erreur">{erreur}</Alerte> : null}
      {attestations.isPending ? <Chargement /> : null}
      {attestations.isError ? <ErreurChargement erreur={attestations.error} reessayer={() => void attestations.refetch()} /> : null}
      {attestations.data?.length === 0 ? <p>Aucune attestation pour le moment : elle est déposée ici après la clôture de l'exercice.</p> : null}
      {attestations.data?.length ? (
        <table className="tableau">
          <caption>Attestations déposées par la Ville</caption>
          <thead>
            <tr>
              <th scope="col">Année</th>
              <th scope="col">Structure</th>
              <th scope="col">Montant valorisé</th>
              <th scope="col">Déposée le</th>
              <th scope="col">Document</th>
            </tr>
          </thead>
          <tbody>
            {attestations.data.map((a) => (
              <tr key={a.id}>
                <th scope="row">{a.exercice}</th>
                <td>{a.usager_nom}</td>
                <td>{a.montant_texte}</td>
                <td>{date(a.deposee_le)}</td>
                <td>
                  <Bouton
                    variante="lien"
                    onClick={() => {
                      setErreur(null);
                      telecharger(`/api/portail/attestations/${a.id}/fichier`, `attestation-${a.exercice}-${a.numero || a.id}.pdf`).catch((e: unknown) => setErreur(messageErreur(e)));
                    }}
                  >
                    Télécharger l'attestation {a.exercice}
                    <span className="visuellement-masque"> de {a.usager_nom} (PDF)</span>
                  </Bouton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
    </>
  );
}
