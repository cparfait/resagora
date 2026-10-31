/** ADM-03 : rôles (ensembles d'actions) et double authentification exigée (SEC-03). */
import { useQuery } from "@tanstack/react-query";
import { requete } from "../../api/http";
import type { Role } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { EcranRessource } from "../../ui/Ressource";

export default function Roles() {
  const catalogue = useQuery({ queryKey: ["actions"], queryFn: () => requete<Record<string, string>>("GET", "/api/gestion/admin/actions") });
  const options = Object.entries(catalogue.data ?? {}).map(([valeur, libelle]) => ({ valeur, libelle: `${libelle} (${valeur})` }));
  return (
    <EcranRessource<Role & Record<string, unknown>>
      titre="Rôles"
      description="Un rôle regroupe des actions ; il s'exerce sur un périmètre de sites attribué à l'agent."
      chemin="/api/gestion/admin/roles"
      cleRequete="roles"
      actionLecture="administrer"
      actionEcriture="administrer"
      libelleObjet="Rôle"
      colonnes={[
        { cle: "libelle", titre: "Rôle", rendu: (r) => r.libelle, valeurTri: (r) => r.libelle },
        { cle: "actions", titre: "Actions", rendu: (r) => `${r.actions?.length ?? 0} actions` },
        {
          cle: "totp",
          titre: "Double authentification",
          rendu: (r) => (r.double_authentification ? <Badge libelle="Obligatoire" ton="attention" /> : <Badge libelle="Non exigée" />),
        },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true, enCreationSeulement: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "actions", libelle: "Actions autorisées", type: "multiple", options },
        { nom: "double_authentification", libelle: "Double authentification obligatoire", type: "booleen" },
      ]}
    />
  );
}
