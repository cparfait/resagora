/** IMP-01 : semaine type d'un espace ou d'un site — les créneaux réguliers de la saison posés sur une semaine sans
 * dates (lundi → dimanche), comme la vue semaine du planning. Les créneaux simultanés sont côte à côte ; le tableau
 * en dessous donne la même information aux lecteurs d'écran. Impression au format calendrier ou liste. */
import { useQuery } from "@tanstack/react-query";
import type { CSSProperties } from "react";
import { Link, useSearchParams } from "react-router";
import { construireChemin, requete, telecharger } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { ChampSelection } from "../../ui/Champ";
import { Chargement, DroitsInsuffisants, Erreur, Vide } from "../../ui/Etats";
import { COULEURS_TYPE, dateSimple } from "../../ui/metier";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

export interface Creneau {
  jour: number;
  jour_libelle: string;
  debut: string;
  fin: string;
  espace: number;
  espace_nom: string;
  occupant: string;
  type_usager: string;
  activite: string;
  statut: string;
  provisoire: boolean;
  frequence: string;
  pendant_vacances: boolean;
  du: string;
  au: string;
  dossier: string;
  dossier_id: number;
  reservation: number;
}

interface Reponse {
  saison: { id: number; nom: string; debut: string; fin: string };
  jours: string[];
  creneaux: Creneau[];
}

const HAUTEUR_HEURE = 48;

const minutes = (h: string) => {
  const [hh = "0", mm = "0"] = h.split(":");
  return Number(hh) * 60 + Number(mm);
};
const minutesFin = (c: Creneau) => Math.max(minutes(c.debut) + 30, minutes(c.fin) || 24 * 60);

/** Sous-colonne de chaque créneau d'un jour : partition gloutonne des intervalles, comme l'impression. */
export function couloirs(creneaux: Creneau[]): { rangs: Map<Creneau, number>; nombre: number } {
  const fins: number[] = [];
  const rangs = new Map<Creneau, number>();
  for (const c of creneaux.toSorted((a, b) => minutes(a.debut) - minutes(b.debut) || minutesFin(b) - minutesFin(a))) {
    const libre = fins.findIndex((fin) => fin <= minutes(c.debut));
    const rang = libre === -1 ? fins.length : libre;
    fins[rang] = minutesFin(c);
    rangs.set(c, rang);
  }
  return { rangs, nombre: Math.max(1, fins.length) };
}

function details(c: Creneau): string {
  return [c.frequence !== "chaque semaine" ? c.frequence : "", c.pendant_vacances ? "aussi pendant les vacances" : "", c.provisoire ? "provisoire" : ""].filter(Boolean).join(", ");
}

function Grille({ donnees, espace }: { donnees: Reponse; espace: string }) {
  const heureMin = Math.floor(Math.min(8 * 60, ...donnees.creneaux.map((c) => minutes(c.debut))) / 60);
  const heureMax = Math.min(24, Math.ceil(Math.max(22 * 60, ...donnees.creneaux.map(minutesFin)) / 60));
  return (
    <div className="grille" role="group" aria-label={`Semaine type, saison ${donnees.saison.nom}`}>
      <div className="grille__heures" aria-hidden="true">
        {Array.from({ length: heureMax - heureMin }, (_, i) => (
          <div key={i} className="grille__heure" style={{ height: HAUTEUR_HEURE }}>
            {heureMin + i} h
          </div>
        ))}
      </div>
      {donnees.jours.map((libelle, jour) => {
        const duJour = donnees.creneaux.filter((c) => c.jour === jour);
        const { rangs, nombre } = couloirs(duJour);
        return (
          <div key={libelle} className="grille__colonne">
            <div className="grille__entete">{libelle}</div>
            <div className="grille__corps" style={{ height: (heureMax - heureMin) * HAUTEUR_HEURE }}>
              {duJour.map((c) => {
                const rang = rangs.get(c) ?? 0;
                const style: CSSProperties = {
                  top: ((minutes(c.debut) - heureMin * 60) / 60) * HAUTEUR_HEURE,
                  height: Math.max(18, ((minutesFin(c) - minutes(c.debut)) / 60) * HAUTEUR_HEURE - 2),
                  left: `calc(${(100 * rang) / nombre}% + 2px)`,
                  width: `calc(${100 / nombre}% - 4px)`,
                  right: "auto",
                };
                const classe = `seance ${c.provisoire ? "statut-demande motif-pointille" : (COULEURS_TYPE[c.type_usager] ?? "type-autre")}`;
                return (
                  <Link key={`${String(c.reservation)}-${String(jour)}`} to={`/reservations/dossiers/${String(c.dossier_id)}`} className={classe} style={style}>
                    <span className="seance__heure">
                      {c.debut}–{c.fin}
                    </span>
                    <span className="seance__titre">{c.occupant}</span>
                    {espace !== String(c.espace) ? <span className="seance__titre">{c.espace_nom}</span> : null}
                    <span className="sr-only">{`, ${libelle}${details(c) ? `, ${details(c)}` : ""}`}</span>
                  </Link>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function SemaineType() {
  const { peut } = useSession();
  const lecture = peut("lire_reservation");
  const [parametres, setParametres] = useSearchParams();
  const site = parametres.get("site") ?? "";
  const espace = parametres.get("espace") ?? "";
  const saison = parametres.get("saison") ?? "";
  const papier = parametres.get("papier") ?? "A4";
  const sites = useOptions("sites", "/api/gestion/referentiel/sites", (s) => String(s.nom), lecture);
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => `${String(e.site_nom)} — ${String(e.nom)}`, lecture);
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom), lecture);
  const cible = { site: site || undefined, espace: espace || undefined, saison: saison || undefined };
  const requeteSemaine = useQuery({
    queryKey: ["semaine-type", site, espace, saison],
    queryFn: () => requete<Reponse>("GET", construireChemin("/api/gestion/pilotage/semaine-type", cible)),
    enabled: lecture && Boolean(site || espace),
  });
  if (!lecture) return <DroitsInsuffisants />;
  const changer = (valeurs: Record<string, string>) => {
    const suivant = new URLSearchParams(parametres);
    for (const [cle, valeur] of Object.entries(valeurs)) {
      if (valeur) suivant.set(cle, valeur);
      else suivant.delete(cle);
    }
    setParametres(suivant, { replace: true });
  };
  const imprimer = (miseEnPage: "calendrier" | "liste") =>
    void telecharger(construireChemin("/api/gestion/pilotage/semaine-type.pdf", { ...cible, papier, mise_en_page: miseEnPage }), "semaine-type.pdf");
  const donnees = requeteSemaine.data;
  return (
    <Page
      titre="Semaine type"
      description="Les créneaux réguliers de la saison (réservations hebdomadaires), jour par jour, pour un gymnase, une salle ou tout un site. Un espace montre aussi ce qui l'occupe : le gymnase entier occupe ses moitiés. Sauf mention, les créneaux s'arrêtent pendant les vacances scolaires."
      actions={
        <>
          <Bouton disabled={!site && !espace} onClick={() => imprimer("calendrier")}>
            Imprimer le calendrier
          </Bouton>
          <Bouton variante="secondaire" disabled={!site && !espace} onClick={() => imprimer("liste")}>
            Imprimer en liste
          </Bouton>
        </>
      }
    >
      <form className="formulaire" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Saison" videLibelle="Saison en cours" options={saisons} value={saison} onChange={(e) => changer({ saison: e.target.value })} />
        <ChampSelection libelle="Site" videLibelle="—" options={sites} value={site} onChange={(e) => changer({ site: e.target.value, espace: "" })} />
        <ChampSelection libelle="ou espace" videLibelle="—" options={espaces} value={espace} onChange={(e) => changer({ espace: e.target.value, site: "" })} />
        <ChampSelection libelle="Format d'impression" options={[{ valeur: "A4", libelle: "A4" }, { valeur: "A3", libelle: "A3" }]} value={papier} onChange={(e) => changer({ papier: e.target.value })} />
      </form>
      {!site && !espace ? (
        <Vide message="Choisissez un site ou un espace pour afficher sa semaine type." />
      ) : requeteSemaine.isPending ? (
        <Chargement />
      ) : requeteSemaine.isError ? (
        <Erreur erreur={requeteSemaine.error} reessayer={() => void requeteSemaine.refetch()} />
      ) : donnees ? (
        <>
          <p>
            Saison {donnees.saison.nom}, du {dateSimple(donnees.saison.debut)} au {dateSimple(donnees.saison.fin)} — {donnees.creneaux.length} créneau{donnees.creneaux.length > 1 ? "x" : ""} par semaine. Les créneaux en pointillés sont des demandes ou options non confirmées.
          </p>
          <Grille donnees={donnees} espace={espace} />
          <Tableau<Creneau>
            legende="Créneaux de la semaine type"
            lignes={donnees.creneaux}
            cleLigne={(c) => `${String(c.reservation)}-${String(c.jour)}`}
            messageVide="Aucun créneau régulier sur cette saison."
            colonnes={[
              { cle: "jour", titre: "Jour", rendu: (c) => c.jour_libelle, valeurTri: (c) => c.jour * 10000 + minutes(c.debut) },
              { cle: "horaires", titre: "Horaires", rendu: (c) => `${c.debut} – ${c.fin}` },
              { cle: "espace", titre: "Espace", rendu: (c) => c.espace_nom, valeurTri: (c) => c.espace_nom },
              { cle: "occupant", titre: "Occupant", rendu: (c) => <Link to={`/reservations/dossiers/${String(c.dossier_id)}`}>{c.occupant}</Link>, valeurTri: (c) => c.occupant },
              { cle: "activite", titre: "Activité", rendu: (c) => c.activite || "—" },
              { cle: "periode", titre: "Période", rendu: (c) => `du ${dateSimple(c.du)} au ${dateSimple(c.au)}` },
              { cle: "details", titre: "Fréquence", rendu: (c) => (c.provisoire ? <Badge ton="attention" libelle={details(c)} /> : details(c) || "chaque semaine") },
            ]}
          />
        </>
      ) : null}
    </Page>
  );
}
