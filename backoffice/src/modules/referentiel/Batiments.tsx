/** REF-01 : bâtiments rattachés aux sites. */
import type { Batiment } from "../../api/types";
import { useSession } from "../../auth/session";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function Batiments() {
  const { peut } = useSession();
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), peut("lire_referentiel"));
  return (
    <EcranRessource<Batiment & Record<string, unknown>>
      titre="Bâtiments"
      chemin="/api/gestion/referentiel/batiments"
      cleRequete="batiments"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Bâtiment"
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (b) => b.nom, valeurTri: (b) => b.nom },
        { cle: "site", titre: "Site", rendu: (b) => b.site_nom, valeurTri: (b) => b.site_nom },
        { cle: "erp", titre: "Classement ERP", rendu: (b) => (b.erp_type ? `Type ${b.erp_type}, catégorie ${b.erp_categorie}` : "—") },
      ]}
      champs={[
        { nom: "site", libelle: "Site", type: "selection", obligatoire: true, options: sites },
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "erp_type", libelle: "Type ERP", type: "texte", aide: "Par exemple X (établissement sportif couvert) ou L." },
        { nom: "erp_categorie", libelle: "Catégorie ERP", type: "texte", aide: "De 1 à 5." },
        { nom: "actif", libelle: "Bâtiment actif", type: "booleen" },
      ]}
      valeursInitiales={{ actif: true }}
      filtres={[{ nom: "site", libelle: "Site", options: sites }]}
    />
  );
}
