/** TAR-01 à TAR-03, RG-05 : grilles tarifaires votées, tarifs par espace ou famille et catégorie, majorations,
 * prestations annexes et réductions fondées. Une grille votée ne se modifie plus : on la duplique. */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { ErreurApi, requete } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { euros } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource, useOptions } from "../../ui/Ressource";

type Ligne = Record<string, unknown> & { id: number };

export const CATEGORIES = [
  { valeur: "association_locale", libelle: "Association locale" },
  { valeur: "association", libelle: "Association extérieure" },
  { valeur: "ecole", libelle: "École ou établissement scolaire" },
  { valeur: "entreprise", libelle: "Entreprise ou CSE" },
  { valeur: "particulier", libelle: "Particulier" },
  { valeur: "service_municipal", libelle: "Service municipal" },
  { valeur: "autre_collectivite", libelle: "Autre collectivité ou organisme public" },
];
const UNITES = [
  { valeur: "heure", libelle: "Heure" },
  { valeur: "demi_journee", libelle: "Demi-journée (4 heures)" },
  { valeur: "journee", libelle: "Journée" },
  { valeur: "forfait", libelle: "Forfait par occupation" },
];
const MAJORATIONS = [
  { valeur: "week_end", libelle: "Week-end" },
  { valeur: "soiree", libelle: "Soirée" },
  { valeur: "ferie", libelle: "Jour férié" },
  { valeur: "non_resident", libelle: "Non-résident" },
];
const STATUTS_GRILLE: Record<string, { libelle: string; ton: "info" | "succes" | "neutre" }> = {
  brouillon: { libelle: "En préparation", ton: "info" },
  votee: { libelle: "Votée", ton: "succes" },
  archivee: { libelle: "Archivée", ton: "neutre" },
};
const libelle = (liste: { valeur: string; libelle: string }[], valeur: unknown) => liste.find((o) => o.valeur === valeur)?.libelle ?? String(valeur ?? "");

function useGrilles() {
  return useOptions("grilles", "/api/gestion/finances/grilles", (g) => `${String(g.nom)} (${STATUTS_GRILLE[String(g.statut)]?.libelle ?? ""})`);
}

export function Grilles() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const action = useMutation({
    mutationFn: ({ id, verbe }: { id: number; verbe: string }) => requete<{ nom: string }>("POST", `/api/gestion/finances/grilles/${id}/${verbe}`),
    onSuccess: async (g, { verbe }) => {
      annoncer(verbe === "voter" ? `Grille « ${g.nom} » votée : elle s'applique et ne se modifie plus.` : verbe === "dupliquer" ? `Grille « ${g.nom} » créée, à compléter.` : "Grille archivée.");
      await client.invalidateQueries({ queryKey: ["grilles"] });
      await client.invalidateQueries({ queryKey: ["options", "grilles"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Action impossible.", "erreur"),
  });
  return (
    <EcranRessource<Ligne>
      titre="Grilles tarifaires"
      description="Une grille est préparée, puis déclarée votée avec la référence de la délibération. Votée, elle ne se modifie plus : dupliquez-la pour préparer la suivante."
      chemin="/api/gestion/finances/grilles"
      cleRequete="grilles"
      actionLecture="lire_finances"
      actionEcriture="gerer_tarifs"
      libelleObjet="Grille"
      colonnes={[
        { cle: "nom", titre: "Grille", rendu: (g) => String(g.nom), valeurTri: (g) => String(g.nom) },
        { cle: "debut", titre: "Applicable du", rendu: (g) => `${String(g.debut)}${g.fin ? ` au ${String(g.fin)}` : ""}` },
        { cle: "deliberation", titre: "Délibération", rendu: (g) => (g.deliberation_reference ? `${String(g.deliberation_reference)} du ${String(g.deliberation_date ?? "")}` : "—") },
        { cle: "statut", titre: "État", rendu: (g) => <Badge libelle={STATUTS_GRILLE[String(g.statut)]?.libelle ?? String(g.statut)} ton={STATUTS_GRILLE[String(g.statut)]?.ton ?? "neutre"} /> },
      ]}
      actionsLigne={(g) =>
        peut("gerer_tarifs") ? (
          <>
            {g.statut === "brouillon" ? (
              <Bouton variante="lien" onClick={() => action.mutate({ id: g.id, verbe: "voter" })}>
                Déclarer votée<span className="sr-only"> : {String(g.nom)}</span>
              </Bouton>
            ) : null}
            <Bouton variante="lien" onClick={() => action.mutate({ id: g.id, verbe: "dupliquer" })}>
              Dupliquer<span className="sr-only"> : {String(g.nom)}</span>
            </Bouton>
            {g.statut === "votee" ? (
              <Bouton variante="lien" onClick={() => action.mutate({ id: g.id, verbe: "archiver" })}>
                Archiver<span className="sr-only"> : {String(g.nom)}</span>
              </Bouton>
            ) : null}
          </>
        ) : null
      }
      champs={[
        { nom: "nom", libelle: "Nom", type: "texte", obligatoire: true },
        { nom: "debut", libelle: "Applicable à partir du", type: "date", obligatoire: true },
        { nom: "fin", libelle: "Applicable jusqu'au", type: "date" },
        { nom: "deliberation_reference", libelle: "Référence de la délibération", type: "texte", aide: "Obligatoire pour déclarer la grille votée." },
        { nom: "deliberation_date", libelle: "Date de la délibération", type: "date" },
        { nom: "heure_soiree", libelle: "Début de la soirée (majoration)", type: "heure" },
      ]}
    />
  );
}

export function Tarifs() {
  const grilles = useGrilles();
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => String(e.nom));
  const familles = useOptions("familles", "/api/gestion/referentiel/familles", (f) => String(f.libelle));
  return (
    <EcranRessource<Ligne>
      titre="Tarifs"
      description="Prix par espace (ou par famille d'espaces) et par catégorie d'usager. Une gratuité s'applique en réduction sur ce tarif de référence, qui reste nécessaire (RG-05)."
      chemin="/api/gestion/finances/tarifs"
      cleRequete="tarifs"
      actionLecture="lire_finances"
      actionEcriture="gerer_tarifs"
      libelleObjet="Tarif"
      filtres={[
        { nom: "grille", libelle: "Grille", type: "selection", options: grilles },
        { nom: "categorie", libelle: "Catégorie", type: "selection", options: CATEGORIES },
      ]}
      colonnes={[
        { cle: "objet", titre: "Espace ou famille", rendu: (t) => String(t.espace_nom || t.famille_libelle) },
        { cle: "categorie", titre: "Catégorie", rendu: (t) => libelle(CATEGORIES, t.categorie) },
        { cle: "prix", titre: "Prix", rendu: (t) => `${euros(Number(t.prix_centimes))} / ${libelle(UNITES, t.unite).toLowerCase()}`, valeurTri: (t) => Number(t.prix_centimes) },
        { cle: "caution", titre: "Caution", rendu: (t) => (Number(t.caution_centimes) ? euros(Number(t.caution_centimes)) : "Aucune") },
      ]}
      champs={[
        { nom: "grille", libelle: "Grille", type: "selection", obligatoire: true, options: grilles },
        { nom: "espace", libelle: "Espace", type: "selection", options: espaces, aide: "Un espace ou une famille d'espaces." },
        { nom: "famille", libelle: "Famille d'espaces", type: "selection", options: familles },
        { nom: "categorie", libelle: "Catégorie d'usager", type: "selection", obligatoire: true, options: CATEGORIES },
        { nom: "unite", libelle: "Unité", type: "selection", obligatoire: true, options: UNITES },
        { nom: "prix_centimes", libelle: "Prix (€)", type: "euros", obligatoire: true },
        { nom: "caution_centimes", libelle: "Caution exigée (€)", type: "euros", aide: "0 : aucune caution." },
      ]}
      suppression
    />
  );
}

export function Majorations() {
  const grilles = useGrilles();
  return (
    <EcranRessource<Ligne>
      titre="Majorations"
      chemin="/api/gestion/finances/majorations"
      cleRequete="majorations"
      actionLecture="lire_finances"
      actionEcriture="gerer_tarifs"
      libelleObjet="Majoration"
      filtres={[{ nom: "grille", libelle: "Grille", type: "selection", options: grilles }]}
      colonnes={[
        { cle: "nature", titre: "Majoration", rendu: (m) => libelle(MAJORATIONS, m.nature) },
        { cle: "taux", titre: "Taux", rendu: (m) => `${Number(m.taux) / 100} %` },
        { cle: "categories", titre: "Catégories", rendu: (m) => ((m.categories as string[]).length ? (m.categories as string[]).map((c) => libelle(CATEGORIES, c)).join(", ") : "Toutes") },
      ]}
      champs={[
        { nom: "grille", libelle: "Grille", type: "selection", obligatoire: true, options: grilles },
        { nom: "nature", libelle: "Nature", type: "selection", obligatoire: true, options: MAJORATIONS },
        { nom: "taux", libelle: "Taux (en centièmes de pour cent : 2500 = 25 %)", type: "nombre", obligatoire: true },
        { nom: "categories", libelle: "Catégories concernées (aucune : toutes)", type: "multiple", options: CATEGORIES },
      ]}
      suppression
    />
  );
}

export function Prestations() {
  const grilles = useGrilles();
  return (
    <EcranRessource<Ligne>
      titre="Prestations annexes"
      chemin="/api/gestion/finances/prestations"
      cleRequete="prestations"
      actionLecture="lire_finances"
      actionEcriture="gerer_tarifs"
      libelleObjet="Prestation"
      filtres={[{ nom: "grille", libelle: "Grille", type: "selection", options: grilles }]}
      colonnes={[
        { cle: "libelle", titre: "Prestation", rendu: (p) => String(p.libelle) },
        { cle: "prix", titre: "Prix", rendu: (p) => `${euros(Number(p.prix_centimes))} / ${libelle(UNITES, p.unite).toLowerCase()}` },
      ]}
      champs={[
        { nom: "grille", libelle: "Grille", type: "selection", obligatoire: true, options: grilles },
        { nom: "code", libelle: "Code", type: "texte", obligatoire: true },
        { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
        { nom: "unite", libelle: "Unité", type: "selection", obligatoire: true, options: UNITES },
        { nom: "prix_centimes", libelle: "Prix (€)", type: "euros", obligatoire: true },
      ]}
      suppression
    />
  );
}

export function Reductions() {
  const usagers = useOptions("usagers", "/api/gestion/usagers/usagers", (u) => String(u.nom));
  const types = useOptions("types-reservation", "/api/gestion/reservations/types", (t) => String(t.libelle));
  return (
    <EcranRessource<Ligne>
      titre="Gratuités et réductions"
      description="Chaque réduction porte son fondement (délibération, convention). La valorisation des avantages en nature en dépend."
      chemin="/api/gestion/finances/reductions"
      cleRequete="reductions"
      actionLecture="lire_finances"
      actionEcriture="gerer_tarifs"
      libelleObjet="Réduction"
      colonnes={[
        { cle: "usager", titre: "Usager", rendu: (r) => String(r.usager_nom), valeurTri: (r) => String(r.usager_nom) },
        { cle: "taux", titre: "Réduction", rendu: (r) => (Number(r.taux) === 10000 ? "Gratuité" : `${Number(r.taux) / 100} %`) },
        { cle: "fondement", titre: "Fondement", rendu: (r) => String(r.fondement) },
        { cle: "periode", titre: "Période", rendu: (r) => `du ${String(r.debut)}${r.fin ? ` au ${String(r.fin)}` : ""}` },
      ]}
      champs={[
        { nom: "usager", libelle: "Usager", type: "selection", obligatoire: true, options: usagers },
        { nom: "type_reservation", libelle: "Type de réservation (aucun : tous)", type: "selection", options: types },
        { nom: "taux", libelle: "Réduction (10000 = gratuité, 5000 = 50 %)", type: "nombre", obligatoire: true },
        { nom: "fondement", libelle: "Fondement (délibération, convention)", type: "texte", obligatoire: true },
        { nom: "debut", libelle: "À partir du", type: "date", obligatoire: true },
        { nom: "fin", libelle: "Jusqu'au", type: "date" },
      ]}
    />
  );
}
