/** ADM-01 : saisons, vacances scolaires de la zone C, jours fériés et fermetures générales de la Ville. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { ErreurApi, requete } from "../../api/http";
import type { Periode, Saison } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection, ChampTexte } from "../../ui/Champ";
import { dateSimple } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

const NATURES: Record<string, string> = { vacances: "Vacances scolaires", ferie: "Jour férié", fermeture_ville: "Fermeture générale" };

export default function Calendrier() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom));
  const [saison, setSaison] = useState("");
  const periodes = useQuery({ queryKey: ["periodes", saison], queryFn: () => requete<Periode[]>("GET", `/api/gestion/referentiel/periodes?saison=${saison}`), enabled: Boolean(saison) });
  const [fichier, setFichier] = useState<File | null>(null);
  const importer = useMutation({
    mutationFn: ({ identifiant, depot }: { identifiant: number | string; depot?: File }) => {
      let corps: FormData | undefined;
      if (depot) {
        corps = new FormData();
        corps.append("fichier", depot);
      }
      return requete<{ periodes: number }>("POST", `/api/gestion/referentiel/saisons/${identifiant}/importer-calendrier`, corps);
    },
    onSuccess: async (r) => {
      annoncer(`Calendrier importé : ${r.periodes} périodes (vacances de la zone et jours fériés).`);
      await client.invalidateQueries({ queryKey: ["periodes"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Import impossible.", "erreur"),
  });
  return (
    <>
      <EcranRessource<Saison & Record<string, unknown>>
        titre="Saisons et calendrier"
        description="Les créneaux récurrents excluent automatiquement les vacances de la zone C, les jours fériés et les fermetures générales."
        chemin="/api/gestion/referentiel/saisons"
        cleRequete="saisons"
        actionLecture="lire_referentiel"
        actionEcriture="gerer_parametres"
        libelleObjet="Saison"
        colonnes={[
          { cle: "nom", titre: "Saison", rendu: (s) => s.nom },
          { cle: "periode", titre: "Période", rendu: (s) => `du ${dateSimple(s.debut)} au ${dateSimple(s.fin)}` },
          { cle: "active", titre: "État", rendu: (s) => (s.cloturee ? <Badge libelle="Close" ton="attention" /> : s.active ? <Badge libelle="Saison en cours" ton="succes" /> : <Badge libelle="Inactive" />) },
        ]}
        actionsLigne={(s) =>
          peut("gerer_parametres") ? (
            <Bouton variante="lien" enCours={importer.isPending} onClick={() => importer.mutate({ identifiant: s.id })}>
              Importer vacances et fériés
            </Bouton>
          ) : null
        }
        champs={[
          { nom: "nom", libelle: "Nom (ex. 2026-2027)", type: "texte", obligatoire: true },
          { nom: "debut", libelle: "Début", type: "date", obligatoire: true },
          { nom: "fin", libelle: "Fin", type: "date", obligatoire: true },
          { nom: "active", libelle: "Saison en cours", type: "booleen" },
          { nom: "cloturee", libelle: "Saison close (plus aucune création ni modification de réservation)", type: "booleen" },
        ]}
      />
      <section aria-labelledby="titre-periodes">
        <h2 id="titre-periodes">Périodes de la saison</h2>
        <ChampSelection libelle="Saison affichée" options={saisons} value={saison} onChange={(e) => setSaison(e.target.value)} />
        {saison && peut("gerer_parametres") ? (
          <form
            className="formulaire-ligne"
            onSubmit={(e) => {
              e.preventDefault();
              if (fichier) importer.mutate({ identifiant: saison, depot: fichier });
            }}
          >
            <ChampTexte
              libelle="Importer un fichier du calendrier scolaire"
              type="file"
              accept=".json,application/json"
              aide="Export JSON du jeu « fr-en-calendrier-scolaire » (data.education.gouv.fr), pour un poste sans accès Internet. 1 Mo au plus."
              onChange={(e) => setFichier(e.target.files?.[0] ?? null)}
            />
            <Bouton type="submit" variante="secondaire" disabled={!fichier} enCours={importer.isPending}>
              Importer le fichier
            </Bouton>
          </form>
        ) : null}
        {periodes.data ? (
          <Tableau<Periode>
            legende="Périodes exclues des créneaux récurrents"
            lignes={periodes.data}
            cleLigne={(p) => p.id}
            messageVide="Aucune période : importez le calendrier de la saison."
            colonnes={[
              { cle: "nature", titre: "Nature", rendu: (p) => NATURES[p.nature] ?? p.nature },
              { cle: "libelle", titre: "Libellé", rendu: (p) => p.libelle },
              { cle: "dates", titre: "Dates", rendu: (p) => (p.debut === p.fin ? dateSimple(p.debut) : `du ${dateSimple(p.debut)} au ${dateSimple(p.fin)}`), valeurTri: (p) => p.debut },
              { cle: "source", titre: "Origine", rendu: (p) => ({ import: "Éducation nationale", calcul: "Calcul", saisie: "Saisie" })[p.source] ?? p.source },
            ]}
          />
        ) : null}
      </section>
    </>
  );
}
