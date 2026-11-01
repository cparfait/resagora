/**
 * Menu du back-office, sur le modèle de CityResa : une douzaine de rubriques à plat (« Général ») et une section
 * « Administration » repliable. Chaque rubrique regroupe plusieurs écrans du registre (`modules.tsx`), proposés en
 * onglets en haut de la page ; le lien du menu ouvre le premier écran permis. Les adresses ne changent pas.
 */
import {
  Boxes,
  CalendarDays,
  ChartColumn,
  ClipboardList,
  ContactRound,
  FileText,
  HandCoins,
  LayoutDashboard,
  List,
  MapPin,
  MessageCircle,
  NotebookText,
  Receipt,
  Settings,
  Tags,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { Module } from "./modules";

export interface Rubrique {
  id: string;
  libelle: string;
  icone: LucideIcon;
  section: "general" | "administration";
  /** Écrans de la rubrique, dans l'ordre des onglets ; le premier permis est la page d'arrivée. */
  chemins: string[];
  /** Pages sans entrée propre rattachées à la rubrique (fiches). */
  prefixes?: string[];
}

export const RUBRIQUES: Rubrique[] = [
  { id: "tableau", libelle: "Tableau de bord", icone: LayoutDashboard, section: "general", chemins: ["/", "/pilotage/direction"] },
  {
    id: "reservations",
    libelle: "Réservations",
    icone: ClipboardList,
    section: "general",
    chemins: ["/reservations/dossiers", "/reservations/nouvelle", "/reservations/campagnes"],
    prefixes: ["/reservations/dossiers/"],
  },
  {
    id: "planning",
    libelle: "Planning",
    icone: CalendarDays,
    section: "general",
    chemins: ["/reservations/planning", "/pilotage/semaine-type", "/pilotage/editions"],
  },
  {
    id: "sites",
    libelle: "Sites et espaces",
    icone: MapPin,
    section: "general",
    chemins: ["/referentiel/sites", "/referentiel/espaces", "/referentiel/batiments", "/referentiel/horaires", "/referentiel/fermetures", "/referentiel/calendrier"],
  },
  {
    id: "usagers",
    libelle: "Usagers",
    icone: Users,
    section: "general",
    chemins: ["/usagers", "/usagers/comptes", "/usagers/alertes-pieces"],
    prefixes: ["/usagers/"],
  },
  { id: "messages", libelle: "Messages", icone: MessageCircle, section: "general", chemins: ["/echanges/messages", "/echanges/information", "/echanges/journal"] },
  {
    id: "documents",
    libelle: "Documents",
    icone: FileText,
    section: "general",
    chemins: ["/documents/a-controler", "/documents/lots", "/documents/modeles", "/echanges/modeles"],
  },
  {
    id: "finances",
    libelle: "Finances",
    icone: Receipt,
    section: "general",
    chemins: [
      "/finances/pieces",
      "/finances/retards",
      "/finances/encaissements",
      "/finances/paiements-en-ligne",
      "/finances/titres",
      "/finances/cautions",
      "/finances/cautions-en-retard",
    ],
  },
  {
    id: "tarifs",
    libelle: "Tarifs",
    icone: Tags,
    section: "general",
    chemins: ["/finances/grilles", "/finances/tarifs", "/finances/majorations", "/finances/prestations", "/finances/reductions"],
  },
  {
    id: "personnel",
    libelle: "Personnel",
    icone: ContactRound,
    section: "general",
    chemins: [
      "/personnel/vacations",
      "/personnel/agents",
      "/personnel/absences",
      "/personnel/trames",
      "/personnel/compteurs",
      "/personnel/habilitations",
      "/personnel/incidents",
      "/personnel/saisies",
      "/personnel/appareils",
    ],
  },
  {
    id: "materiel",
    libelle: "Matériel",
    icone: Boxes,
    section: "general",
    chemins: ["/materiel/stocks", "/materiel/prets", "/materiel/controles", "/materiel/pannes", "/materiel/mouvements", "/materiel/catalogue"],
  },
  { id: "subventions", libelle: "Subventions", icone: HandCoins, section: "general", chemins: ["/pilotage/valorisation", "/pilotage/methodes-valorisation"] },
  { id: "statistiques", libelle: "Statistiques", icone: ChartColumn, section: "general", chemins: ["/pilotage/statistiques"] },
  {
    id: "parametres",
    libelle: "Paramètres",
    icone: Settings,
    section: "administration",
    chemins: ["/administration/parametres", "/administration/types-reservation", "/administration/types-pieces"],
  },
  {
    id: "droits",
    libelle: "Agents et droits",
    icone: UserCog,
    section: "administration",
    chemins: ["/administration/agents", "/administration/roles", "/administration/perimetres", "/administration/groupes-ad"],
  },
  { id: "referentiels", libelle: "Référentiels", icone: List, section: "administration", chemins: ["/referentiel/familles"] },
  { id: "journal", libelle: "Journal d'audit", icone: NotebookText, section: "administration", chemins: ["/administration/journal"] },
];

/** Rubrique d'une adresse : écran de la rubrique, ou fiche rattachée (préfixe le plus long). */
export function rubriqueDe(chemin: string): Rubrique | undefined {
  const exacte = RUBRIQUES.find((r) => r.chemins.includes(chemin));
  if (exacte) return exacte;
  let meilleure: [Rubrique, number] | undefined;
  for (const r of RUBRIQUES) {
    for (const prefixe of r.prefixes ?? []) {
      if (chemin.startsWith(prefixe) && (!meilleure || prefixe.length > meilleure[1])) meilleure = [r, prefixe.length];
    }
  }
  return meilleure?.[0];
}

/** Écrans d'une rubrique que l'agent peut ouvrir, dans l'ordre des onglets. */
export function ecransPermis(rubrique: Rubrique, modules: Module[], peut: (action: string) => boolean): Module[] {
  return rubrique.chemins.flatMap((chemin) => modules.filter((m) => m.chemin === chemin && !m.masque && peut(m.action)));
}

/** Rubrique d'un lien de compteur (« /reservations/dossiers?statut=… ») pour les pastilles du menu. */
export function rubriqueDuLien(lien: string): Rubrique | undefined {
  return rubriqueDe(lien.split("?")[0] ?? lien);
}
