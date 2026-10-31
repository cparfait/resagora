/** Saisie d'une demande au guichet (PLA-04, PLA-07) : usager, créneau, récurrence, aperçu des séances et conflits. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router";
import { construireChemin, ErreurApi, requete, type ErreursChamps, type Page as PageApi } from "../../api/http";
import type { Apercu, Dossier, Espace, Usager } from "../../api/types";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte } from "../../ui/Champ";
import { heure, jourLong } from "../../ui/metier";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";

const JOURS = [
  ["MO", "lundi"],
  ["TU", "mardi"],
  ["WE", "mercredi"],
  ["TH", "jeudi"],
  ["FR", "vendredi"],
  ["SA", "samedi"],
  ["SU", "dimanche"],
] as const;

interface Creneau {
  espace: string;
  date_debut: string;
  date_fin: string;
  heure_debut: string;
  heure_fin: string;
  frequence: "" | "WEEKLY" | "DAILY";
  intervalle: string;
  jours: string[];
  exclure_vacances: boolean;
  exclure_feries: boolean;
}

function regle(c: Creneau): string {
  if (!c.frequence) return "";
  const parties = [`FREQ=${c.frequence}`];
  if (Number(c.intervalle) > 1) parties.push(`INTERVAL=${Number(c.intervalle)}`);
  if (c.frequence === "WEEKLY" && c.jours.length) parties.push(`BYDAY=${c.jours.join(",")}`);
  return parties.join(";");
}

export default function NouvelleDemande() {
  const naviguer = useNavigate();
  const [recherche, setRecherche] = useState("");
  const [usager, setUsager] = useState("");
  const [typeReservation, setTypeReservation] = useState("");
  const [objet, setObjet] = useState("");
  const [effectif, setEffectif] = useState("");
  const [saison, setSaison] = useState("");
  const [creneau, setCreneau] = useState<Creneau>({
    espace: "", date_debut: "", date_fin: "", heure_debut: "18:00", heure_fin: "20:00", frequence: "", intervalle: "1", jours: [], exclure_vacances: true, exclure_feries: true,
  });
  const [apercu, setApercu] = useState<Apercu | null>(null);
  const [erreurs, setErreurs] = useState<ErreursChamps>({});
  const [message, setMessage] = useState<string | null>(null);
  const [dossierCree, setDossierCree] = useState<Dossier | null>(null);

  const usagers = useQuery({
    queryKey: ["usagers-recherche", recherche],
    queryFn: () => requete<PageApi<Usager>>("GET", construireChemin("/api/gestion/usagers/usagers", { recherche, statut: "valide", taille: 20 })),
    enabled: recherche.length >= 2,
  });
  const types = useOptions("types-reservation", "/api/gestion/reservations/types", (t) => String(t.libelle));
  const saisons = useOptions("saisons", "/api/gestion/referentiel/saisons", (s) => String(s.nom));
  const espaces = useQuery({ queryKey: ["options-objets", "espaces"], queryFn: () => requete<PageApi<Espace>>("GET", "/api/gestion/referentiel/espaces?taille=500&actif=true") });

  const corpsReservation = () => ({
    espace: Number(creneau.espace),
    date_debut: creneau.date_debut,
    date_fin: creneau.frequence ? creneau.date_fin : creneau.date_fin || creneau.date_debut,
    heure_debut: creneau.heure_debut,
    heure_fin: creneau.heure_fin,
    recurrence: regle(creneau),
    exclure_vacances: creneau.exclure_vacances,
    exclure_feries: creneau.exclure_feries,
  });

  const dossierAEnregistrer = async (): Promise<Dossier> => {
    if (dossierCree) return dossierCree;
    const d = await requete<Dossier>("POST", "/api/gestion/reservations/dossiers", {
      usager: Number(usager), type_reservation: Number(typeReservation), objet, effectif: Number(effectif || 0), saison: saison ? Number(saison) : null,
    });
    setDossierCree(d);
    return d;
  };

  const verifier = useMutation({
    mutationFn: () => requete<Apercu>("POST", "/api/gestion/reservations/dossiers/apercu", corpsReservation()),
    onSuccess: (a) => {
      setApercu(a);
      setErreurs({});
      setMessage(null);
    },
    onError: (e) => {
      if (e instanceof ErreurApi) {
        setErreurs(e.champs);
        setMessage(e.message);
      }
    },
  });

  const enregistrer = useMutation({
    mutationFn: async () => {
      const d = await dossierAEnregistrer();
      await requete("POST", `/api/gestion/reservations/dossiers/${d.id}/reservations`, corpsReservation());
      return d;
    },
    onSuccess: (d) => void naviguer(`/reservations/dossiers/${d.id}`),
    onError: (e) => {
      if (e instanceof ErreurApi) {
        setErreurs(e.champs);
        setMessage(e.message);
      }
    },
  });

  const soumettre = (e: FormEvent) => {
    e.preventDefault();
    enregistrer.mutate();
  };

  const optionsEspaces = (espaces.data?.results ?? []).map((e) => ({ valeur: String(e.id), libelle: `${e.site_nom} — ${e.nom}` }));
  const pret = Boolean(usager && typeReservation && objet && creneau.espace && creneau.date_debut);

  return (
    <Page titre="Nouvelle demande" description="La demande est enregistrée sans bloquer le créneau ; la validation vérifie les conflits.">
      {message ? (
        <div className="alerte alerte--erreur" role="alert">
          {message}
        </div>
      ) : null}
      <form onSubmit={soumettre} noValidate>
        <fieldset className="groupe">
          <legend>1. Demandeur</legend>
          <ChampTexte libelle="Rechercher un usager" aide="Nom, sigle, SIRET, RNA ou courriel d'un contact (2 caractères minimum)." value={recherche} onChange={(e) => setRecherche(e.target.value)} />
          <ChampSelection
            libelle="Usager"
            obligatoire
            options={(usagers.data?.results ?? []).map((u) => ({ valeur: String(u.id), libelle: `${u.nom} (${u.type_libelle})` }))}
            value={usager}
            onChange={(e) => {
              setUsager(e.target.value);
              setDossierCree(null);
            }}
            erreur={erreurs.usager}
          />
          <ChampSelection libelle="Type de réservation" obligatoire options={types} value={typeReservation} onChange={(e) => setTypeReservation(e.target.value)} erreur={erreurs.type_reservation} />
          <ChampTexte libelle="Objet" obligatoire value={objet} onChange={(e) => setObjet(e.target.value)} erreur={erreurs.objet} />
          <ChampTexte libelle="Effectif attendu" type="number" min={0} value={effectif} onChange={(e) => setEffectif(e.target.value)} />
          <ChampSelection libelle="Saison" options={saisons} value={saison} onChange={(e) => setSaison(e.target.value)} />
        </fieldset>
        <fieldset className="groupe">
          <legend>2. Créneau</legend>
          <ChampSelection libelle="Espace" obligatoire options={optionsEspaces} value={creneau.espace} onChange={(e) => setCreneau({ ...creneau, espace: e.target.value })} erreur={erreurs.espace} />
          <div className="formulaire__grille">
            <ChampTexte libelle="Date de début" type="date" obligatoire value={creneau.date_debut} onChange={(e) => setCreneau({ ...creneau, date_debut: e.target.value })} erreur={erreurs.date_debut} />
            <ChampTexte libelle="Date de fin" type="date" aide="Fin de la période pour une récurrence." value={creneau.date_fin} onChange={(e) => setCreneau({ ...creneau, date_fin: e.target.value })} erreur={erreurs.date_fin} />
            <ChampTexte libelle="Heure de début" type="time" obligatoire value={creneau.heure_debut} onChange={(e) => setCreneau({ ...creneau, heure_debut: e.target.value })} erreur={erreurs.heure_debut} />
            <ChampTexte libelle="Heure de fin" type="time" obligatoire value={creneau.heure_fin} onChange={(e) => setCreneau({ ...creneau, heure_fin: e.target.value })} erreur={erreurs.heure_fin} />
          </div>
          <ChampSelection
            libelle="Répétition"
            videLibelle="Séance unique"
            options={[
              { valeur: "WEEKLY", libelle: "Chaque semaine" },
              { valeur: "DAILY", libelle: "Chaque jour" },
            ]}
            value={creneau.frequence}
            onChange={(e) => setCreneau({ ...creneau, frequence: e.target.value as Creneau["frequence"] })}
          />
          {creneau.frequence ? (
            <>
              <ChampTexte libelle="Toutes les … (semaines ou jours)" type="number" min={1} max={8} value={creneau.intervalle} onChange={(e) => setCreneau({ ...creneau, intervalle: e.target.value })} />
              {creneau.frequence === "WEEKLY" ? (
                <fieldset className="groupe groupe--cases">
                  <legend>Jours</legend>
                  {JOURS.map(([code, libelle]) => (
                    <CaseACocher
                      key={code}
                      libelle={libelle}
                      checked={creneau.jours.includes(code)}
                      onChange={(e) => setCreneau({ ...creneau, jours: e.target.checked ? [...creneau.jours, code] : creneau.jours.filter((j) => j !== code) })}
                    />
                  ))}
                </fieldset>
              ) : null}
              <CaseACocher libelle="Hors vacances scolaires (zone C)" checked={creneau.exclure_vacances} onChange={(e) => setCreneau({ ...creneau, exclure_vacances: e.target.checked })} />
              <CaseACocher libelle="Hors jours fériés" checked={creneau.exclure_feries} onChange={(e) => setCreneau({ ...creneau, exclure_feries: e.target.checked })} />
            </>
          ) : null}
        </fieldset>
        {apercu ? (
          <section className="carte" aria-labelledby="apercu-titre">
            <h2 id="apercu-titre">Aperçu : {apercu.seances.length} séance(s)</h2>
            <p>{apercu.description}</p>
            {apercu.conflits.length ? (
              <div className="alerte alerte--attention" role="status">
                <p>{apercu.conflits.length} séance(s) en conflit avec une réservation validée :</p>
                <ul>
                  {apercu.conflits.slice(0, 10).map((c) => (
                    <li key={`${c.occurrence}-${c.debut}`}>
                      {jourLong(c.debut)} {heure(c.debut)} – {heure(c.fin)} : {c.usager} ({c.dossier})
                    </li>
                  ))}
                </ul>
                <p>La demande peut être enregistrée ; la validation sera refusée tant que ces conflits subsistent.</p>
              </div>
            ) : (
              <p className="alerte alerte--succes">Aucun conflit avec les réservations validées.</p>
            )}
            {apercu.hors_horaires.length ? <p className="alerte alerte--attention">{apercu.hors_horaires.length} séance(s) hors horaires d'ouverture.</p> : null}
            {apercu.fermetures.length ? <p className="alerte alerte--attention">{apercu.fermetures.length} séance(s) pendant une fermeture.</p> : null}
          </section>
        ) : null}
        <div className="formulaire__actions">
          <Bouton variante="secondaire" disabled={!pret} enCours={verifier.isPending} onClick={() => verifier.mutate()}>
            Vérifier les disponibilités
          </Bouton>
          <Bouton type="submit" disabled={!pret} enCours={enregistrer.isPending}>
            Enregistrer la demande
          </Bouton>
        </div>
      </form>
    </Page>
  );
}
