/** USR-03 : pièces expirées ou qui expirent dans le délai d'alerte paramétré. */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { requete } from "../../api/http";
import type { Piece } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateSimple } from "../../ui/metier";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

export default function AlertesPieces() {
  const alertes = useQuery({ queryKey: ["alertes-pieces"], queryFn: () => requete<Piece[]>("GET", "/api/gestion/usagers/pieces/alertes") });
  const [aujourdhui] = useState(() => new Date().toISOString().slice(0, 10));
  return (
    <Page titre="Pièces à renouveler" description="Pièces justificatives expirées ou proches de l'expiration.">
      {alertes.isPending ? (
        <Chargement />
      ) : alertes.isError ? (
        <Erreur erreur={alertes.error} reessayer={() => void alertes.refetch()} />
      ) : (
        <Tableau<Piece>
          legende="Pièces à renouveler"
          lignes={alertes.data}
          cleLigne={(p) => p.id}
          messageVide="Aucune pièce à renouveler."
          colonnes={[
            { cle: "usager", titre: "Usager", rendu: (p) => <Link to={`/usagers/${p.usager}`}>{p.usager_nom}</Link>, valeurTri: (p) => p.usager_nom },
            { cle: "piece", titre: "Pièce", rendu: (p) => p.type_libelle },
            {
              cle: "fin",
              titre: "Fin de validité",
              rendu: (p) => (
                <>
                  {p.valide_jusqu_au ? dateSimple(p.valide_jusqu_au) : ""}{" "}
                  {p.valide_jusqu_au && p.valide_jusqu_au < aujourdhui ? <Badge libelle="Expirée" ton="danger" /> : <Badge libelle="Bientôt expirée" ton="attention" />}
                </>
              ),
              valeurTri: (p) => p.valide_jusqu_au ?? "",
            },
          ]}
        />
      )}
    </Page>
  );
}
