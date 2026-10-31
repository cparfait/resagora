/** REF-02 : familles d'espaces. */
import type { FamilleEspace } from "../../api/types";
import { EcranRessource } from "../../ui/Ressource";

export default function Familles() {
  return (
    <EcranRessource<FamilleEspace & Record<string, unknown>>
      titre="Familles d'espaces"
      chemin="/api/gestion/referentiel/familles"
      cleRequete="familles"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Famille"
      colonnes={[
        { cle: "libelle", titre: "Libellé", rendu: (f) => f.libelle, valeurTri: (f) => f.libelle },
        { cle: "code", titre: "Code", rendu: (f) => f.code },
        { cle: "ordre", titre: "Ordre d'affichage", rendu: (f) => f.ordre ?? 0, valeurTri: (f) => f.ordre ?? 0 },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "ordre", libelle: "Ordre d'affichage", type: "nombre" },
      ]}
    />
  );
}
