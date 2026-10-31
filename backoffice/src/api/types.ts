/** Types des objets métier, tirés du schéma OpenAPI généré (jamais écrits à la main). */
import type { components } from "./schema";

type S = components["schemas"];

export type Moi = S["Moi"];
export type HabilitationMoi = S["HabilitationMoi"];
export type EtapeConnexion = S["EtapeConnexion"];
export type Enrolement = S["Enrolement"];
export type Site = S["Site"];
export type Batiment = S["Batiment"];
export type FamilleEspace = S["FamilleEspace"];
export type Espace = S["Espace"];
export type Role = S["Role"];
export type Perimetre = S["Perimetre"];
export type GroupeAD = S["GroupeAD"];
export type Habilitation = S["Habilitation"];
export type Agent = S["Utilisateur"];
export type EntreeJournal = S["JournalAudit"];
export type Verification = S["Verification"];
