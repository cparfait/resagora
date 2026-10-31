/**
 * Registre des écrans du back-office : chaque entrée déclare l'action exigée (RG-14).
 * La navigation n'affiche que les écrans permis ; l'API refuse de toute façon le reste.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from "react";

export interface Module {
  chemin: string;
  libelle: string;
  groupe: string;
  action: string;
  composant: LazyExoticComponent<ComponentType>;
  masque?: boolean;
}

const charger = (fabrique: () => Promise<{ default: ComponentType }>) => lazy(fabrique);

export const GROUPES = ["Pilotage", "Réservations", "Usagers", "Documents et échanges", "Finances", "Personnel", "Matériel", "Référentiel", "Administration"];

export const MODULES: Module[] = [
  { chemin: "/", libelle: "Accueil", groupe: "Pilotage", action: "lire_referentiel", composant: charger(() => import("../modules/accueil/Accueil")) },
  { chemin: "/reservations/planning", libelle: "Planning", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Planning")) },
  { chemin: "/reservations/dossiers", libelle: "Dossiers", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Dossiers")) },
  { chemin: "/reservations/dossiers/:id", libelle: "Dossier", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Dossier")), masque: true },
  { chemin: "/reservations/nouvelle", libelle: "Nouvelle demande", groupe: "Réservations", action: "creer_reservation", composant: charger(() => import("../modules/reservations/NouvelleDemande")) },
  { chemin: "/reservations/campagnes", libelle: "Campagnes annuelles", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Campagnes")) },
  { chemin: "/usagers", libelle: "Usagers", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/Usagers")) },
  { chemin: "/usagers/:id", libelle: "Fiche usager", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/FicheUsager")), masque: true },
  { chemin: "/usagers/alertes-pieces", libelle: "Pièces à renouveler", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/AlertesPieces")) },
  { chemin: "/referentiel/sites", libelle: "Sites", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Sites")) },
  { chemin: "/referentiel/batiments", libelle: "Bâtiments", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Batiments")) },
  { chemin: "/referentiel/espaces", libelle: "Espaces", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Espaces")) },
  { chemin: "/referentiel/familles", libelle: "Familles d'espaces", groupe: "Référentiel", action: "gerer_referentiel", composant: charger(() => import("../modules/referentiel/Familles")) },
  { chemin: "/referentiel/horaires", libelle: "Horaires d'ouverture", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Disponibilite").then((m) => ({ default: m.Horaires }))) },
  { chemin: "/referentiel/fermetures", libelle: "Fermetures", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Disponibilite").then((m) => ({ default: m.Fermetures }))) },
  { chemin: "/referentiel/calendrier", libelle: "Saisons et calendrier", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Calendrier")) },
  { chemin: "/administration/parametres", libelle: "Paramètres", groupe: "Administration", action: "gerer_parametres", composant: charger(() => import("../modules/administration/Parametres")) },
  { chemin: "/administration/types-reservation", libelle: "Types de réservation", groupe: "Administration", action: "gerer_parametres", composant: charger(() => import("../modules/administration/Types").then((m) => ({ default: m.TypesReservation }))) },
  { chemin: "/administration/types-pieces", libelle: "Pièces demandées", groupe: "Administration", action: "gerer_parametres", composant: charger(() => import("../modules/administration/Types").then((m) => ({ default: m.TypesPieces }))) },
  { chemin: "/administration/agents", libelle: "Agents et habilitations", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Agents")) },
  { chemin: "/administration/roles", libelle: "Rôles", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Roles")) },
  { chemin: "/administration/perimetres", libelle: "Périmètres", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Perimetres")) },
  { chemin: "/administration/groupes-ad", libelle: "Groupes de l'annuaire", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/GroupesAD")) },
  { chemin: "/administration/journal", libelle: "Journal d'audit", groupe: "Administration", action: "lire_audit", composant: charger(() => import("../modules/administration/Journal")) },
];
