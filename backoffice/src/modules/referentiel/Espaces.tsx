/** REF-01, REF-02, REF-04, REF-05, REF-07 : espaces réservables, hiérarchie, gardiennage, partage. */
import type { Espace } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { EcranRessource, useOptions } from "../../ui/Ressource";

export default function Espaces() {
  const { peut } = useSession();
  const lecture = peut("lire_referentiel");
  const batiments = useOptions("batiments", "/api/gestion/referentiel/batiments", (b) => `${String(b.site_nom)} — ${String(b.nom)}`, lecture);
  const familles = useOptions("familles", "/api/gestion/referentiel/familles", (f) => String(f.libelle), lecture);
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`, lecture);
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  return (
    <EcranRessource<Espace & Record<string, unknown>>
      titre="Espaces"
      description="Salles, gymnases et terrains réservables. Un sous-espace (tiers de terrain) bloque son espace parent et inversement."
      chemin="/api/gestion/referentiel/espaces"
      cleRequete="espaces"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Espace"
      colonnes={[
        { cle: "nom", titre: "Nom", rendu: (e) => e.nom, valeurTri: (e) => e.nom },
        { cle: "site", titre: "Site", rendu: (e) => e.site_nom, valeurTri: (e) => e.site_nom },
        { cle: "famille", titre: "Famille", rendu: (e) => e.famille_libelle },
        { cle: "capacite", titre: "Capacité", rendu: (e) => `${e.capacite} pers.`, valeurTri: (e) => e.capacite ?? 0 },
        {
          cle: "options",
          titre: "Particularités",
          rendu: (e) => (
            <span className="badges">
              {e.gardiennage_requis ? <Badge libelle="Gardiennage" ton="info" /> : null}
              {e.partageable ? <Badge libelle={`Partageable (${e.capacite_simultanee})`} ton="info" /> : null}
              {e.parent ? <Badge libelle="Sous-espace" /> : null}
              {e.accessible_pmr ? <Badge libelle="Accessible PMR" ton="succes" /> : null}
              {!e.actif ? <Badge libelle="Inactif" ton="attention" /> : null}
            </span>
          ),
        },
      ]}
      champs={[
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true },
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "batiment", libelle: "Bâtiment", type: "selection", obligatoire: true, options: batiments },
        { nom: "famille", libelle: "Famille", type: "selection", obligatoire: true, options: familles },
        { nom: "parent", libelle: "Espace englobant", type: "selection", options: espaces, aide: "Pour un tiers ou une moitié de gymnase." },
        { nom: "capacite", libelle: "Capacité d'accueil (personnes)", type: "nombre" },
        { nom: "surface_m2", libelle: "Surface (m²)", type: "nombre" },
        { nom: "description", libelle: "Description", type: "zone" },
        { nom: "equipements", libelle: "Équipements fixes", type: "zone" },
        { nom: "activites", libelle: "Activités possibles", type: "texte" },
        { nom: "accessible_pmr", libelle: "Accessible aux personnes à mobilité réduite", type: "booleen" },
        { nom: "gardiennage_requis", libelle: "Gardiennage requis", type: "booleen" },
        { nom: "temps_ouverture_min", libelle: "Temps d'ouverture avant le créneau (min)", type: "nombre" },
        { nom: "temps_fermeture_min", libelle: "Temps de fermeture après le créneau (min)", type: "nombre" },
        { nom: "partageable", libelle: "Espace partageable", type: "booleen" },
        { nom: "capacite_simultanee", libelle: "Réservations simultanées maximum", type: "nombre" },
        { nom: "reservable_portail", libelle: "Réservable depuis le portail", type: "booleen" },
        { nom: "actif", libelle: "Espace actif", type: "booleen" },
      ]}
      valeursInitiales={{ actif: true, reservable_portail: true, capacite_simultanee: 1, temps_ouverture_min: 15, temps_fermeture_min: 15 }}
      filtres={[
        { nom: "batiment__site", libelle: "Site", options: sites },
        { nom: "famille", libelle: "Famille", options: familles },
        { nom: "gardiennage_requis", libelle: "Gardiennage", options: [{ valeur: "true", libelle: "Requis" }, { valeur: "false", libelle: "Non requis" }] },
      ]}
    />
  );
}
