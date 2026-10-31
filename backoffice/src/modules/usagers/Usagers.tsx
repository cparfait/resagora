/** USR-01 : usagers (associations, écoles, entreprises, particuliers, services municipaux). */
import { useNavigate } from "react-router";
import type { Usager } from "../../api/types";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { TYPES_USAGER } from "../../ui/metier";
import { EcranRessource } from "../../ui/Ressource";

const TYPES = Object.entries(TYPES_USAGER).map(([valeur, libelle]) => ({ valeur, libelle }));
const STATUTS_USAGER = [
  { valeur: "en_attente", libelle: "En attente de validation" },
  { valeur: "valide", libelle: "Validé" },
  { valeur: "suspendu", libelle: "Suspendu" },
];

export default function Usagers() {
  const naviguer = useNavigate();
  return (
    <EcranRessource<Usager & Record<string, unknown>>
      titre="Usagers"
      description="Associations, écoles, entreprises et CSE, particuliers et services municipaux."
      chemin="/api/gestion/usagers/usagers"
      cleRequete="usagers"
      actionLecture="lire_usager"
      actionEcriture="gerer_usager"
      libelleObjet="Usager"
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (u) => `${u.nom}${u.sigle ? ` (${u.sigle})` : ""}`, valeurTri: (u) => u.nom },
        { cle: "type", titre: "Type", rendu: (u) => u.type_libelle },
        { cle: "commune", titre: "Commune", rendu: (u) => u.commune || "—" },
        {
          cle: "statut",
          titre: "Situation",
          rendu: (u) => (
            <span className="badges">
              {u.statut === "en_attente" ? <Badge libelle="À valider" ton="attention" /> : null}
              {u.statut === "suspendu" ? <Badge libelle="Suspendu" ton="danger" /> : null}
              {u.resident ? <Badge libelle="Résident" ton="info" /> : null}
              {u.conventionne ? <Badge libelle="Conventionné" ton="succes" /> : null}
            </span>
          ),
        },
      ]}
      actionsLigne={(u) => (
        <Bouton variante="lien" onClick={() => void naviguer(`/usagers/${u.id}`)} aria-label={`Ouvrir la fiche de ${u.nom}`}>
          Fiche
        </Bouton>
      )}
      champs={[
        { nom: "type", libelle: "Type d'usager", type: "selection", obligatoire: true, options: TYPES },
        { nom: "nom", libelle: "Nom ou raison sociale", type: "texte", obligatoire: true },
        { nom: "sigle", libelle: "Sigle", type: "texte" },
        { nom: "siret", libelle: "SIRET", type: "texte", aide: "14 chiffres." },
        { nom: "rna", libelle: "Numéro RNA", type: "texte", aide: "Forme W123456789 (associations)." },
        { nom: "adresse", libelle: "Adresse", type: "texte" },
        { nom: "code_postal", libelle: "Code postal", type: "texte" },
        { nom: "commune", libelle: "Commune", type: "texte" },
        { nom: "telephone", libelle: "Téléphone", type: "texte" },
        { nom: "courriel", libelle: "Courriel", type: "courriel" },
        { nom: "local", libelle: "Siège sur la commune (association locale)", type: "booleen" },
        { nom: "conventionne", libelle: "Conventionné avec la Ville", type: "booleen" },
        { nom: "convention_reference", libelle: "Référence de la convention", type: "texte" },
        { nom: "convention_fin", libelle: "Fin de la convention", type: "date" },
        { nom: "observations", libelle: "Observations", type: "zone" },
      ]}
      valeursInitiales={{ type: "association", commune: "Châtillon", code_postal: "92320" }}
      filtres={[
        { nom: "recherche", libelle: "Nom, SIRET, RNA, contact" },
        { nom: "type", libelle: "Type", options: TYPES },
        { nom: "statut", libelle: "Statut", options: STATUTS_USAGER },
        { nom: "conventionne", libelle: "Conventionnement", options: [{ valeur: "true", libelle: "Conventionnés" }, { valeur: "false", libelle: "Non conventionnés" }] },
      ]}
    />
  );
}
