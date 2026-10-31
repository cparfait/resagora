/** REF-03 horaires d'ouverture et REF-06 fermetures exceptionnelles des espaces. */
import type { Fermeture, Horaire } from "../../api/types";
import { dateHeure } from "../../ui/metier";
import { EcranRessource, useOptions } from "../../ui/Ressource";

const JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"];

export function Horaires() {
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`);
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom));
  const nom = (id: number | null | undefined, options: { valeur: string; libelle: string }[]) => options.find((o) => o.valeur === String(id))?.libelle ?? "—";
  return (
    <EcranRessource<Horaire & Record<string, unknown>>
      titre="Horaires d'ouverture"
      description="Sans horaire saisi, un espace est réservable à toute heure. Une plage propre à une saison remplace les plages générales."
      chemin="/api/gestion/referentiel/horaires"
      cleRequete="horaires"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Plage"
      suppression
      colonnes={[
        { cle: "espace", titre: "Espace", rendu: (h) => nom(h.espace, espaces) },
        { cle: "jour", titre: "Jour", rendu: (h) => JOURS[h.jour_semaine] ?? "", valeurTri: (h) => h.jour_semaine },
        { cle: "heures", titre: "Plage", rendu: (h) => `${h.debut.slice(0, 5)} – ${h.fin.slice(0, 5)}` },
        { cle: "saison", titre: "Saison", rendu: (h) => (h.saison ? nom(h.saison, saisons) : "Toutes") },
        { cle: "vacances", titre: "Pendant les vacances", rendu: (h) => (h.pendant_vacances ? "Oui" : "Non") },
      ]}
      champs={[
        { nom: "espace", libelle: "Espace", type: "selection", obligatoire: true, options: espaces },
        { nom: "jour_semaine", libelle: "Jour", type: "selection", obligatoire: true, options: JOURS.map((j, i) => ({ valeur: String(i), libelle: j })) },
        { nom: "debut", libelle: "Ouverture", type: "heure", obligatoire: true },
        { nom: "fin", libelle: "Fermeture", type: "heure", obligatoire: true },
        { nom: "saison", libelle: "Saison (facultatif)", type: "selection", options: saisons },
        { nom: "pendant_vacances", libelle: "Ouvert pendant les vacances scolaires", type: "booleen" },
      ]}
      valeursInitiales={{ pendant_vacances: true }}
      filtres={[{ nom: "espace", libelle: "Espace", options: espaces }]}
    />
  );
}

export function Fermetures() {
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`);
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom));
  const nom = (id: number | null | undefined, options: { valeur: string; libelle: string }[]) => options.find((o) => o.valeur === String(id))?.libelle ?? "";
  return (
    <EcranRessource<Fermeture & Record<string, unknown>>
      titre="Fermetures exceptionnelles"
      description="À l'enregistrement, les séances touchées sont signalées au planning et les usagers concernés sont prévenus par courriel."
      chemin="/api/gestion/referentiel/fermetures"
      cleRequete="fermetures"
      actionLecture="lire_referentiel"
      actionEcriture="gerer_referentiel"
      libelleObjet="Fermeture"
      suppression
      colonnes={[
        { cle: "lieu", titre: "Lieu", rendu: (f) => (f.espace ? nom(f.espace, espaces) : `Site entier : ${nom(f.site, sites)}`) },
        { cle: "periode", titre: "Période", rendu: (f) => `du ${dateHeure(f.debut)} au ${dateHeure(f.fin)}`, valeurTri: (f) => f.debut },
        { cle: "motif", titre: "Motif", rendu: (f) => f.motif },
      ]}
      champs={[
        { nom: "espace", libelle: "Espace", type: "selection", options: espaces, aide: "Choisissez un espace ou un site entier." },
        { nom: "site", libelle: "Site entier", type: "selection", options: sites },
        { nom: "debut", libelle: "Début", type: "dateheure", obligatoire: true },
        { nom: "fin", libelle: "Fin", type: "dateheure", obligatoire: true },
        { nom: "motif", libelle: "Motif", type: "texte", obligatoire: true },
      ]}
    />
  );
}

export default Horaires;
