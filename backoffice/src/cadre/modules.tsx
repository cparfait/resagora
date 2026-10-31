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
  { chemin: "/referentiel/sites", libelle: "Sites", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Sites")) },
  { chemin: "/referentiel/batiments", libelle: "Bâtiments", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Batiments")) },
  { chemin: "/referentiel/espaces", libelle: "Espaces", groupe: "Référentiel", action: "lire_referentiel", composant: charger(() => import("../modules/referentiel/Espaces")) },
  { chemin: "/referentiel/familles", libelle: "Familles d'espaces", groupe: "Référentiel", action: "gerer_referentiel", composant: charger(() => import("../modules/referentiel/Familles")) },
  { chemin: "/administration/agents", libelle: "Agents et habilitations", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Agents")) },
  { chemin: "/administration/roles", libelle: "Rôles", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Roles")) },
  { chemin: "/administration/perimetres", libelle: "Périmètres", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/Perimetres")) },
  { chemin: "/administration/groupes-ad", libelle: "Groupes de l'annuaire", groupe: "Administration", action: "administrer", composant: charger(() => import("../modules/administration/GroupesAD")) },
  { chemin: "/administration/journal", libelle: "Journal d'audit", groupe: "Administration", action: "lire_audit", composant: charger(() => import("../modules/administration/Journal")) },
];
