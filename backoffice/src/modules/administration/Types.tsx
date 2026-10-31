/** Types de réservation (conditions de confirmation RG-06) et types de pièces justificatives (USR-03). */
import type { TypePiece, TypeReservation } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { TYPES_USAGER } from "../../ui/metier";
import { EcranRessource } from "../../ui/Ressource";

export function TypesReservation() {
  return (
    <EcranRessource<TypeReservation & Record<string, unknown>>
      titre="Types de réservation"
      description="Pour chaque type, les conditions à réunir avant de confirmer une réservation."
      chemin="/api/gestion/reservations/types"
      cleRequete="types-reservation"
      actionLecture="lire_reservation"
      actionEcriture="gerer_parametres"
      libelleObjet="Type"
      colonnes={[
        { cle: "libelle", titre: "Type", rendu: (t) => t.libelle },
        {
          cle: "conditions",
          titre: "Conditions de confirmation",
          rendu: (t) => (
            <span className="badges">
              {t.exige_pieces ? <Badge libelle="Pièces valides" /> : null}
              {t.exige_convention ? <Badge libelle="Convention signée" /> : null}
              {t.exige_acompte ? <Badge libelle="Acompte payé" /> : null}
              {t.exige_caution ? <Badge libelle="Caution reçue" /> : null}
            </span>
          ),
        },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true, enCreationSeulement: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "exige_pieces", libelle: "Exige des pièces justificatives valides", type: "booleen" },
        { nom: "exige_convention", libelle: "Exige une convention ou un contrat signé", type: "booleen" },
        { nom: "exige_acompte", libelle: "Exige un acompte payé", type: "booleen" },
        { nom: "exige_caution", libelle: "Exige une caution reçue", type: "booleen" },
        { nom: "ordre", libelle: "Ordre d'affichage", type: "nombre" },
      ]}
    />
  );
}

export function TypesPieces() {
  return (
    <EcranRessource<TypePiece & Record<string, unknown>>
      titre="Pièces justificatives demandées"
      chemin="/api/gestion/usagers/types-pieces"
      cleRequete="types-pieces-ecran"
      actionLecture="lire_usager"
      actionEcriture="gerer_parametres"
      libelleObjet="Type de pièce"
      colonnes={[
        { cle: "libelle", titre: "Pièce", rendu: (t) => t.libelle },
        { cle: "usagers", titre: "Demandée aux", rendu: (t) => (t.types_usager ?? []).map((u) => TYPES_USAGER[u] ?? u).join(", ") },
        { cle: "obligatoire", titre: "Obligatoire", rendu: (t) => (t.obligatoire ? "Oui" : "Non") },
        { cle: "validite", titre: "Validité", rendu: (t) => (t.validite_mois ? `${t.validite_mois} mois` : "Sans limite") },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true, enCreationSeulement: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "description", libelle: "Description", type: "zone" },
        { nom: "types_usager", libelle: "Types d'usagers concernés", type: "multiple", options: Object.entries(TYPES_USAGER).map(([valeur, libelle]) => ({ valeur, libelle })) },
        { nom: "obligatoire", libelle: "Obligatoire", type: "booleen" },
        { nom: "validite_mois", libelle: "Durée de validité (mois)", type: "nombre" },
      ]}
    />
  );
}

export default TypesReservation;
