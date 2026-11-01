/**
 * Formes des réponses de l'API portail (représentations construites par `apps/portail`, voir D-029).
 * Le contrat est vérifié par les tests de l'API et par les parcours Playwright du portail.
 */

export interface EtatSession {
  connecte: boolean;
  csrf: string;
  expire_dans: number;
  contact: { id: number; prenom: string; nom: string; totp: boolean } | null;
}

export interface Page<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export interface Site {
  id: number;
  nom: string;
  adresse: string;
  code_postal: string;
  commune: string;
  latitude: number | null;
  longitude: number | null;
  acces: string;
}

export interface Famille {
  id: number;
  code: string;
  libelle: string;
}

export interface EspacePublic {
  id: number;
  nom: string;
  site: number;
  site_nom: string;
  adresse: string;
  code_postal: string;
  commune: string;
  latitude: number | null;
  longitude: number | null;
  acces: string;
  famille: number;
  famille_libelle: string;
  parent: number | null;
  parent_nom: string | null;
  description: string;
  capacite: number;
  surface_m2: number | null;
  accessible_pmr: boolean;
  equipements: string;
  activites: string;
  partageable: boolean;
  photos: { id: number; description: string; url: string }[];
  documents: { id: number; titre: string; nature: string; taille: number; format: string; url: string }[];
}

export interface AbonnementAgenda {
  actif: boolean;
  cree_le: string | null;
  expire_le: string | null;
  dernier_acces: string | null;
}

export interface Disponibilites {
  espace: number;
  espace_nom: string;
  debut: string;
  jours: { jour: string; vacances: boolean; ferie: boolean; horaires: { debut: string; fin: string }[] }[];
  plages: { debut: string; fin: string; etat: "occupe" | "demande" | "ferme" }[];
}

export interface Structure {
  id: number;
  nom: string;
  type: string;
  type_libelle: string;
  statut: string;
  statut_libelle: string;
  sigle: string;
  siret: string;
  rna: string;
  adresse: string;
  code_postal: string;
  commune: string;
  telephone: string;
  courriel: string;
  resident: boolean;
  conventionne: boolean;
  mon_role: string;
  principal: boolean;
  peut_signer: boolean;
}

export interface Compte {
  identifiant: string;
  civilite: string;
  prenom: string;
  nom: string;
  courriel: string;
  telephone: string;
  totp: boolean;
  derniere_connexion: string | null;
  mot_de_passe_modifie_le: string;
  usagers: { id: number; nom: string; role: string; statut: string; peut_signer: boolean }[];
}

export interface Preferences {
  sms: boolean;
  telephone_sms: string;
  telephone_confirme?: boolean;
  rappels: boolean;
  informations: boolean;
}

export interface ContactStructure {
  id: number;
  prenom: string;
  nom: string;
  /** Coordonnées visibles du seul contact principal (et de soi-même). */
  courriel?: string;
  telephone?: string;
  role: string;
  role_code: string;
  principal: boolean;
  peut_signer: boolean;
  compte?: string | null;
}

export interface Piece {
  id: number;
  type_piece: number;
  type_libelle: string;
  nom_fichier: string;
  statut: string;
  statut_libelle: string;
  motif_refus: string;
  valide_jusqu_au: string | null;
  depose_le: string;
}

export interface PieceExigee {
  type_piece: number;
  libelle: string;
  description: string;
  obligatoire: boolean;
  etat: "valide" | "a_verifier" | "refusee" | "expiree" | "manquante";
  valide_jusqu_au: string | null;
  motif_refus: string;
}

export interface Creneau {
  espace: number;
  date_debut: string;
  date_fin: string;
  heure_debut: string;
  heure_fin: string;
  jours: string[];
  toutes_les_semaines: number;
  exclure_vacances: boolean;
  espace_nom?: string;
  site_nom?: string;
  description?: string;
  seances?: number;
  indisponibles?: string[];
  erreur?: string;
}

export interface Seance {
  id: number;
  debut: string;
  fin: string;
  espace_nom: string;
  statut: string;
  statut_libelle: string;
  annulable: boolean;
  annulation_tardive_si_annulee: boolean;
  annulation_tardive: boolean;
  signalement: string;
}

export interface ReservationDossier {
  id: number;
  espace: number;
  espace_nom: string;
  site_nom: string;
  description: string;
  statut: string;
  statut_libelle: string;
  motif_refus: string;
  option_expire_le: string | null;
  a_faire: string[];
  seances: Seance[];
}

export interface Dossier {
  id: number;
  numero: string;
  objet: string;
  usager: number;
  usager_nom: string;
  type_reservation: number;
  type_libelle: string;
  campagne: number | null;
  brouillon: boolean;
  etape: number;
  statut: string;
  statut_libelle: string;
  cree_le: string;
  depose_le: string | null;
  messages_non_lus: number;
  activite?: string;
  effectif?: number;
  observations?: string;
  creneaux?: Creneau[];
  reservations?: ReservationDossier[];
  materiel_demande?: MaterielDemande[];
  materiel?: PretPortail[];
}

/** Matériel proposé en ligne sur le site d'un équipement (MAT-02) : quantité maximale en état, aucun montant. */
export interface MaterielPropose {
  id: number;
  libelle: string;
  description: string;
  unite: string;
  maximum: number;
}

export interface MaterielDemande {
  materiel: number;
  quantite: number;
}

export interface PretPortail {
  id: number;
  materiel: string;
  unite: string;
  quantite: number;
  debut: string;
  fin: string;
  reservation: number | null;
  statut: string;
  statut_libelle: string;
  motif: string;
}

export interface DocumentPortail {
  id: number;
  numero: string;
  titre: string;
  nature: string;
  statut: string;
  statut_libelle: string;
  cree_le: string;
  signe_le: string | null;
  taille: number;
  a_signer_en_ligne: boolean;
  scan_attendu: boolean;
  echeance_signature: string | null;
}

export interface Message {
  id: number;
  de_la_ville: boolean;
  auteur: string;
  corps: string;
  cree_le: string;
  lu: boolean;
}

export interface NotificationPortail {
  id: number;
  sujet: string;
  corps: string;
  cree_le: string;
  lue: boolean;
}

export interface Campagne {
  id: number;
  nom: string;
  saison: string;
  saison_debut: string;
  saison_fin: string;
  cloture: string;
  sites: string[];
}

export interface Declaration {
  etat: string;
  taux: number;
  date_audit: string;
  auditeur: string;
  non_conformites: string;
  contact: string;
  date_declaration: string;
  referentiel: string;
  conservation: { inactivite_mois: number; pieces_expirees_mois: number; service: string; courriel: string };
}

export interface TypeDemande {
  id: number;
  libelle: string;
}
