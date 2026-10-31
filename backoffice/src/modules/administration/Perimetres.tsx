/** ADM-03 / RG-14 : périmètres (ensembles de sites). */
import type { Perimetre } from "../../api/types";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function Perimetres() {
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom));
  const nom = (id: number) => sites.find((s) => s.valeur === String(id))?.libelle ?? `n° ${id}`;
  return (
    <EcranRessource<Perimetre & Record<string, unknown>>
      titre="Périmètres"
      chemin="/api/gestion/admin/perimetres"
      cleRequete="perimetres"
      actionLecture="administrer"
      actionEcriture="administrer"
      libelleObjet="Périmètre"
      suppression
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (p) => p.nom, valeurTri: (p) => p.nom },
        { cle: "sites", titre: "Sites", rendu: (p) => (p.tous_sites ? "Tous les sites" : (p.sites ?? []).map(nom).join(", ") || "—") },
      ]}
      champs={[
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "tous_sites", libelle: "Tous les sites de la Ville", type: "booleen" },
        { nom: "sites", libelle: "Sites", type: "multiple", options: sites },
      ]}
    />
  );
}
