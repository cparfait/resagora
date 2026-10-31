/** ADM-06 : correspondance groupes de l'Active Directory → rôle × périmètre. */
import type { GroupeAD } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function GroupesAD() {
  const roles = useOptions("roles", "/api/gestion/admin/roles", (r) => String(r.libelle));
  const perimetres = useOptions("perimetres", "/api/gestion/admin/perimetres", (p) => String(p.nom));
  const libelle = (options: { valeur: string; libelle: string }[], id: number) => options.find((o) => o.valeur === String(id))?.libelle ?? "—";
  return (
    <EcranRessource<GroupeAD & Record<string, unknown>>
      titre="Groupes de l'annuaire"
      description="À chaque connexion, les rôles des agents sont recalculés à partir de leurs groupes dans l'Active Directory."
      chemin="/api/gestion/admin/groupes-ad"
      cleRequete="groupes-ad"
      actionLecture="administrer"
      actionEcriture="administrer"
      libelleObjet="Correspondance"
      suppression
      colonnes={[
        { cle: "dn", titre: "Groupe (DN)", rendu: (g) => <code>{g.dn}</code>, valeurTri: (g) => g.dn },
        { cle: "libelle", titre: "Libellé", rendu: (g) => g.libelle || "—" },
        { cle: "role", titre: "Rôle", rendu: (g) => libelle(roles, g.role) },
        { cle: "perimetre", titre: "Périmètre", rendu: (g) => libelle(perimetres, g.perimetre) },
        { cle: "actif", titre: "État", rendu: (g) => (g.actif ? <Badge libelle="Actif" ton="succes" /> : <Badge libelle="Suspendu" />) },
      ]}
      champs={[
        { nom: "dn", libelle: "DN du groupe", type: "texte", obligatoire: true, aide: "Par exemple CN=GG-Equipements-Gestionnaires,OU=Groupes,DC=ville,DC=local" },
        { nom: "libelle", libelle: "Libellé", type: "texte" },
        { nom: "role", libelle: "Rôle", type: "selection", obligatoire: true, options: roles },
        { nom: "perimetre", libelle: "Périmètre", type: "selection", obligatoire: true, options: perimetres },
        { nom: "actif", libelle: "Correspondance active", type: "booleen" },
      ]}
      valeursInitiales={{ actif: true }}
    />
  );
}
