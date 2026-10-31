/** Liste des dossiers de réservation (PLA-06) et accès à la nouvelle demande. */
import { useNavigate } from "react-router";
import type { Dossier } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { dateSimple, STATUTS, TYPES_USAGER } from "../../ui/metier";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function Dossiers() {
  const { peut } = useSession();
  const naviguer = useNavigate();
  const types = useOptions("types-reservation", "/api/gestion/reservations/types", (t) => String(t.libelle));
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom));
  return (
    <EcranRessource<Dossier & Record<string, unknown>>
      titre="Dossiers de réservation"
      chemin="/api/gestion/reservations/dossiers"
      cleRequete="dossiers"
      actionLecture="lire_reservation"
      libelleObjet="Dossier"
      actionsPage={
        peut("creer_reservation") ? (
          <Bouton icone="+" onClick={() => void naviguer("/reservations/nouvelle")}>
            Nouvelle demande
          </Bouton>
        ) : null
      }
      colonnes={[
        { cle: "numero", titre: "Numéro", rendu: (d) => d.numero, valeurTri: (d) => d.numero },
        { cle: "usager", titre: "Usager", rendu: (d) => `${d.usager_nom} (${TYPES_USAGER[d.usager_type] ?? d.usager_type})`, valeurTri: (d) => d.usager_nom },
        { cle: "objet", titre: "Objet", rendu: (d) => d.objet },
        { cle: "type", titre: "Type", rendu: (d) => d.type_reservation_libelle },
        { cle: "statut", titre: "Statut", rendu: (d) => <Badge libelle={STATUTS[d.statut]?.libelle ?? d.statut} ton={STATUTS[d.statut]?.ton ?? "neutre"} /> },
        { cle: "cree_le", titre: "Créé le", rendu: (d) => dateSimple(d.cree_le), valeurTri: (d) => d.cree_le },
      ]}
      actionsLigne={(d) => (
        <Bouton variante="lien" onClick={() => void naviguer(`/reservations/dossiers/${d.id}`)} aria-label={`Ouvrir le dossier ${d.numero}`}>
          Ouvrir
        </Bouton>
      )}
      filtres={[
        { nom: "recherche", libelle: "Numéro, objet ou usager" },
        { nom: "statut", libelle: "Statut", options: [{ valeur: "demande,en_instruction", libelle: "À instruire (demandes et instruction)" }, ...Object.entries(STATUTS).map(([valeur, s]) => ({ valeur, libelle: s.libelle }))] },
        { nom: "options_expirant_heures", libelle: "Options expirant sous", options: [{ valeur: "48", libelle: "48 heures" }, { valeur: "168", libelle: "7 jours" }] },
        { nom: "type_reservation", libelle: "Type", options: types },
        { nom: "site", libelle: "Site", options: sites },
      ]}
    />
  );
}
