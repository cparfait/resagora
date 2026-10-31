/** POR-07 : paiement en ligne. Au départ, la page attend que la Ville ait préparé l'opération auprès de la DGFiP puis
 * redirige vers PayFiP ; au retour, elle affiche l'état relu par la Ville auprès de la DGFiP, jamais celui que
 * suggérerait l'adresse de retour. Interrogation espacée, arrêtée au bout de 10 minutes. */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router";
import { requete } from "../api/http";
import { Alerte, Chargement, ErreurChargement, TitrePage } from "../ui/Elements";

export interface EtatPaiement {
  uuid: string;
  facture: string;
  facture_id: number;
  montant: number;
  montant_texte: string;
  statut: "creee" | "redirigee" | "remplacee" | "payee" | "refusee" | "abandonnee" | "expiree" | "a_controler" | "erreur";
  message: string;
  termine: boolean;
  numero_autorisation: string;
  url: string;
}

const TONS: Record<EtatPaiement["statut"], "info" | "succes" | "attention" | "erreur"> = {
  creee: "info",
  redirigee: "info",
  remplacee: "info",
  payee: "succes",
  refusee: "erreur",
  abandonnee: "attention",
  expiree: "attention",
  a_controler: "attention",
  erreur: "erreur",
};
const DUREE_MAX = 10 * 60_000;

/** Seule une adresse HTTPS (ou le simulateur de recette sur le poste) est suivie : défense en profondeur. */
export function adresseDePaiementSure(url: string): boolean {
  try {
    const adresse = new URL(url);
    return adresse.protocol === "https:" || (adresse.protocol === "http:" && adresse.hostname === "localhost");
  } catch {
    return false;
  }
}

export function RetourPaiement() {
  const { uuid = "" } = useParams();
  const [parametres] = useSearchParams();
  const depart = parametres.get("depart") === "1";
  const [debut] = useState(() => Date.now());
  const [arrete, setArrete] = useState(false);
  const etat = useQuery({
    queryKey: ["paiement", uuid],
    queryFn: () => requete<EtatPaiement>("GET", `/api/portail/paiements/${encodeURIComponent(uuid)}`),
    refetchInterval: (q) => {
      if (arrete || (q.state.data?.termine ?? false)) return false;
      const ecoule = Date.now() - debut;
      return ecoule < 60_000 ? 3000 : 15_000;
    },
  });
  useEffect(() => {
    const minuterie = window.setTimeout(() => setArrete(true), DUREE_MAX);
    return () => window.clearTimeout(minuterie);
  }, []);
  const url = etat.data?.url ?? "";
  const redirection = depart && etat.data?.statut === "redirigee" && adresseDePaiementSure(url);
  useEffect(() => {
    if (redirection) window.location.assign(url);
  }, [redirection, url]);
  return (
    <>
      <TitrePage titre="Paiement en ligne" />
      {etat.isPending ? <Chargement texte="Préparation du paiement auprès de la DGFiP…" /> : null}
      {etat.isError ? <ErreurChargement erreur={etat.error} reessayer={() => void etat.refetch()} /> : null}
      {etat.data ? (
        <>
          <div aria-live="polite">
            {redirection ? (
              <Alerte ton="info" titre={`Facture ${etat.data.facture} — ${etat.data.montant_texte}`}>
                <p>Vous allez être redirigé vers PayFiP, le site de paiement de la DGFiP.</p>
                <p>
                  <a href={url}>Continuer vers PayFiP</a>
                </p>
              </Alerte>
            ) : (
              <Alerte ton={TONS[etat.data.statut]} titre={`Facture ${etat.data.facture} — ${etat.data.montant_texte}`}>
                <p>{depart && etat.data.statut === "creee" ? "Préparation du paiement auprès de la DGFiP…" : etat.data.message}</p>
                {etat.data.numero_autorisation ? <p>Numéro d'autorisation : {etat.data.numero_autorisation}</p> : null}
                {!etat.data.termine && !arrete ? <p>Cette page se met à jour automatiquement.</p> : null}
                {!etat.data.termine && arrete ? (
                  <p>
                    La vérification prend plus de temps que prévu : vous pouvez fermer cette page, l'état de votre facture sera mis à jour dans « Mes factures ».
                  </p>
                ) : null}
              </Alerte>
            )}
          </div>
          <p className="actions">
            <Link to="/espace/factures">Retour à mes factures</Link>
          </p>
        </>
      ) : null}
    </>
  );
}
