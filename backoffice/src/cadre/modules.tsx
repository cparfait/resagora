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
  { chemin: "/pilotage/statistiques", libelle: "Statistiques", groupe: "Pilotage", action: "lire_statistiques", composant: charger(() => import("../modules/pilotage/Pilotage").then((m) => ({ default: m.Statistiques }))) },
  { chemin: "/pilotage/direction", libelle: "Tableau de bord de la direction", groupe: "Pilotage", action: "lire_tableau_direction", composant: charger(() => import("../modules/pilotage/Pilotage").then((m) => ({ default: m.Direction }))) },
  { chemin: "/pilotage/valorisation", libelle: "Valorisation des avantages en nature", groupe: "Pilotage", action: "lire_valorisation", composant: charger(() => import("../modules/pilotage/Valorisation").then((m) => ({ default: m.Valorisation }))) },
  { chemin: "/pilotage/methodes-valorisation", libelle: "Méthodes de valorisation", groupe: "Pilotage", action: "lire_valorisation", composant: charger(() => import("../modules/pilotage/Valorisation").then((m) => ({ default: m.MethodesValorisation }))) },
  { chemin: "/pilotage/editions", libelle: "Éditions du planning", groupe: "Pilotage", action: "lire_reservation", composant: charger(() => import("../modules/pilotage/Valorisation").then((m) => ({ default: m.Editions }))) },
  { chemin: "/reservations/planning", libelle: "Planning", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Planning")) },
  { chemin: "/reservations/dossiers", libelle: "Dossiers", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Dossiers")) },
  { chemin: "/reservations/dossiers/:id", libelle: "Dossier", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Dossier")), masque: true },
  { chemin: "/reservations/nouvelle", libelle: "Nouvelle demande", groupe: "Réservations", action: "creer_reservation", composant: charger(() => import("../modules/reservations/NouvelleDemande")) },
  { chemin: "/reservations/campagnes", libelle: "Campagnes annuelles", groupe: "Réservations", action: "lire_reservation", composant: charger(() => import("../modules/reservations/Campagnes")) },
  { chemin: "/usagers", libelle: "Usagers", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/Usagers")) },
  { chemin: "/usagers/:id", libelle: "Fiche usager", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/FicheUsager")), masque: true },
  { chemin: "/usagers/alertes-pieces", libelle: "Pièces à renouveler", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/AlertesPieces")) },
  { chemin: "/usagers/comptes", libelle: "Comptes du portail", groupe: "Usagers", action: "lire_usager", composant: charger(() => import("../modules/usagers/Comptes")) },
  { chemin: "/echanges/messages", libelle: "Messages des usagers", groupe: "Documents et échanges", action: "lire_message", composant: charger(() => import("../modules/echanges/Echanges").then((m) => ({ default: m.MessagesEnAttente }))) },
  { chemin: "/echanges/information", libelle: "Information groupée", groupe: "Documents et échanges", action: "notifier_groupe", composant: charger(() => import("../modules/echanges/Echanges").then((m) => ({ default: m.EnvoiGroupe }))) },
  { chemin: "/echanges/journal", libelle: "Journal des envois", groupe: "Documents et échanges", action: "lire_message", composant: charger(() => import("../modules/echanges/Echanges").then((m) => ({ default: m.JournalEnvois }))) },
  { chemin: "/documents/modeles", libelle: "Modèles de documents", groupe: "Documents et échanges", action: "lire_document", composant: charger(() => import("../modules/documents/Documents").then((m) => ({ default: m.ModelesDocuments }))) },
  { chemin: "/documents/a-controler", libelle: "Documents signés à contrôler", groupe: "Documents et échanges", action: "lire_document", composant: charger(() => import("../modules/documents/Documents").then((m) => ({ default: m.DocumentsAControler }))) },
  { chemin: "/documents/lots", libelle: "Génération en lot", groupe: "Documents et échanges", action: "generer_document", composant: charger(() => import("../modules/documents/Documents").then((m) => ({ default: m.LotsDocuments }))) },
  { chemin: "/echanges/modeles", libelle: "Modèles de messages", groupe: "Documents et échanges", action: "lire_message", composant: charger(() => import("../modules/echanges/Echanges").then((m) => ({ default: m.ModelesMessages }))) },
  { chemin: "/finances/pieces", libelle: "Devis et factures", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Pieces").then((m) => ({ default: m.PiecesComptables }))) },
  { chemin: "/finances/retards", libelle: "Factures en retard", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Pieces").then((m) => ({ default: m.Retards }))) },
  { chemin: "/finances/titres", libelle: "Titres vers Ciril", groupe: "Finances", action: "exporter_titres", composant: charger(() => import("../modules/finances/Pieces").then((m) => ({ default: m.TitresCiril }))) },
  { chemin: "/finances/encaissements", libelle: "Encaissements", groupe: "Finances", action: "encaisser", composant: charger(() => import("../modules/finances/Pieces").then((m) => ({ default: m.Encaissements }))) },
  { chemin: "/finances/paiements-en-ligne", libelle: "Paiements en ligne (PayFiP)", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/PaiementsEnLigne")) },
  { chemin: "/finances/cautions", libelle: "Cautions", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Cautions")) },
  { chemin: "/finances/cautions-en-retard", libelle: "Cautions en retard", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Cautions").then((m) => ({ default: m.CautionsEnAlerte }))) },
  { chemin: "/finances/grilles", libelle: "Grilles tarifaires", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Tarifs").then((m) => ({ default: m.Grilles }))) },
  { chemin: "/finances/tarifs", libelle: "Tarifs", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Tarifs").then((m) => ({ default: m.Tarifs }))) },
  { chemin: "/finances/majorations", libelle: "Majorations", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Tarifs").then((m) => ({ default: m.Majorations }))) },
  { chemin: "/finances/prestations", libelle: "Prestations annexes", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Tarifs").then((m) => ({ default: m.Prestations }))) },
  { chemin: "/finances/reductions", libelle: "Gratuités et réductions", groupe: "Finances", action: "lire_finances", composant: charger(() => import("../modules/finances/Tarifs").then((m) => ({ default: m.Reductions }))) },
  { chemin: "/personnel/vacations", libelle: "Planning du personnel", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Vacations")) },
  { chemin: "/personnel/agents", libelle: "Agents et gardiens", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Agents }))) },
  { chemin: "/personnel/habilitations", libelle: "Habilitations", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Habilitations }))) },
  { chemin: "/personnel/trames", libelle: "Trames hebdomadaires", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Trames }))) },
  { chemin: "/personnel/absences", libelle: "Absences", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Absences }))) },
  { chemin: "/personnel/compteurs", libelle: "Compteurs d'heures", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Compteurs }))) },
  { chemin: "/personnel/incidents", libelle: "Incidents", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Incidents }))) },
  { chemin: "/personnel/saisies", libelle: "Saisies du terrain", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Saisies }))) },
  { chemin: "/personnel/appareils", libelle: "Appareils mobiles", groupe: "Personnel", action: "lire_personnel", composant: charger(() => import("../modules/personnel/Personnel").then((m) => ({ default: m.Appareils }))) },
  { chemin: "/materiel/stocks", libelle: "État du stock", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Stocks }))) },
  { chemin: "/materiel/prets", libelle: "Prêts de matériel", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Prets }))) },
  { chemin: "/materiel/controles", libelle: "Contrôles et maintenance", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Controles }))) },
  { chemin: "/materiel/pannes", libelle: "Pannes", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Pannes }))) },
  { chemin: "/materiel/mouvements", libelle: "Mouvements de stock", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Mouvements }))) },
  { chemin: "/materiel/catalogue", libelle: "Catalogue du matériel", groupe: "Matériel", action: "lire_materiel", composant: charger(() => import("../modules/materiel/Materiel").then((m) => ({ default: m.Catalogue }))) },
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
