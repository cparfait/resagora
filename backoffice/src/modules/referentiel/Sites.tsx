/** REF-01 : sites de la Ville. */
import type { Site } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { EcranRessource } from "../../ui/Ressource";

export default function Sites() {
  return (
    <EcranRessource<Site & Record<string, unknown>>
      titre="Sites"
      description="Complexes sportifs, gymnases, salles et équipements de plein air."
      chemin="/api/gestion/referentiel/sites"
      cleRequete="sites"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Site"
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (s) => s.nom, valeurTri: (s) => s.nom },
        { cle: "adresse", titre: "Adresse", rendu: (s) => `${s.adresse} ${s.code_postal} ${s.commune}`.trim() },
        { cle: "telephone", titre: "Téléphone", rendu: (s) => s.telephone || "—" },
        { cle: "actif", titre: "État", rendu: (s) => (s.actif ? <Badge libelle="Actif" ton="succes" /> : <Badge libelle="Inactif" />) },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true, aide: "Lettres minuscules, chiffres et tirets." },
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "adresse", libelle: "Adresse", type: "texte" },
        { nom: "code_postal", libelle: "Code postal", type: "texte" },
        { nom: "commune", libelle: "Commune", type: "texte" },
        { nom: "telephone", libelle: "Téléphone", type: "texte" },
        { nom: "actif", libelle: "Site actif", type: "booleen" },
      ]}
      valeursInitiales={{ actif: true, code_postal: "92320", commune: "Châtillon" }}
      filtres={[{ nom: "actif", libelle: "État", options: [{ valeur: "true", libelle: "Actifs" }, { valeur: "false", libelle: "Inactifs" }] }]}
    />
  );
}
