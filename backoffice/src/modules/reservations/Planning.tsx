/** Planning des équipements (PLA-01, PLA-02, PLA-03) : six vues, filtres, coloration, vues enregistrées. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight, SlidersHorizontal } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router";
import { construireChemin, ErreurApi, requete, type Page as PageApi } from "../../api/http";
import type { Controle, Espace, SeancePlanning, Site, VueEnregistree } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { cn } from "../../ui/cn";
import { CaseACocher, ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { ajouterJours, dateHeure, debutMois, debutSemaine, heure, isoJour, jourLong, STATUTS, TYPES_USAGER } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { useOptions } from "../../ui/Ressource";
import { Legende, VueChronologie, VueListe, VueMois, VueMultiSites, VueSemaine, type Coloration, type Deplacement, type Mode } from "./planning/vues";

const MODES: { valeur: Mode; libelle: string }[] = [
  { valeur: "jour", libelle: "Jour" },
  { valeur: "semaine", libelle: "Semaine" },
  { valeur: "mois", libelle: "Mois" },
  { valeur: "chronologie", libelle: "Chronologie par espace" },
  { valeur: "multi_sites", libelle: "Multi-sites" },
  { valeur: "liste", libelle: "Liste" },
];

interface Filtres {
  site: string;
  espace: string;
  famille: string;
  statut: string;
  type_usager: string;
}

const FILTRES_VIDES: Filtres = { site: "", espace: "", famille: "", statut: "", type_usager: "" };

function periode(mode: Mode, reference: Date): { debut: Date; fin: Date; jours: number } {
  if (mode === "jour") {
    const debut = new Date(reference.getFullYear(), reference.getMonth(), reference.getDate());
    return { debut, fin: ajouterJours(debut, 1), jours: 1 };
  }
  if (mode === "mois") {
    const debut = debutSemaine(debutMois(reference));
    return { debut, fin: ajouterJours(debut, 42), jours: 42 };
  }
  const debut = debutSemaine(reference);
  return { debut, fin: ajouterJours(debut, 7), jours: 7 };
}

function versLocalInput(d: Date): string {
  return `${isoJour(d)}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export default function Planning() {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [mode, setMode] = useState<Mode>("semaine");
  const [reference, setReference] = useState(() => new Date());
  const [coloration, setColoration] = useState<Coloration>("statut");
  const [filtres, setFiltres] = useState<Filtres>(FILTRES_VIDES);
  const [voirAnnulees, setVoirAnnulees] = useState(false);
  const [filtresOuverts, setFiltresOuverts] = useState(false);
  const [ouverte, setOuverte] = useState<SeancePlanning | null>(null);
  const [proposition, setProposition] = useState<{ deplacement: Deplacement; controle: Controle } | null>(null);
  const [deplacementClavier, setDeplacementClavier] = useState<{ espace: string; debut: string; fin: string } | null>(null);
  const [nomVue, setNomVue] = useState("");
  const [sauvegarde, setSauvegarde] = useState(false);

  const { debut, fin, jours } = periode(mode, reference);
  const sites = useQuery({ queryKey: ["options-objets", "sites"], queryFn: () => requete<PageApi<Site>>("GET", "/api/gestion/referentiel/sites?taille=500") });
  const espaces = useQuery({ queryKey: ["options-objets", "espaces"], queryFn: () => requete<PageApi<Espace>>("GET", "/api/gestion/referentiel/espaces?taille=500&actif=true") });
  const familles = useOptions("familles", "/api/gestion/referentiel/familles", (f) => String(f.libelle));
  const vues = useQuery({ queryKey: ["vues-planning"], queryFn: () => requete<VueEnregistree[]>("GET", "/api/gestion/reservations/vues") });

  const parametres = { debut: debut.toISOString(), fin: fin.toISOString(), ...filtres, annulees: voirAnnulees ? "1" : "" };
  const seances = useQuery({
    queryKey: ["planning", parametres],
    queryFn: ({ signal }) => requete<SeancePlanning[]>("GET", construireChemin("/api/gestion/reservations/planning", parametres), undefined, signal),
  });

  const espacesAffiches = useMemo(() => {
    const tous = espaces.data?.results ?? [];
    return tous.filter((e) => (!filtres.site || String(e.site) === filtres.site) && (!filtres.famille || String(e.famille) === filtres.famille) && (!filtres.espace || String(e.id) === filtres.espace));
  }, [espaces.data, filtres]);

  const actualiser = () => client.invalidateQueries({ queryKey: ["planning"] });

  const deplacer = useMutation({
    mutationFn: (d: { seance: number; espace: number; debut: string; fin: string }) =>
      requete("POST", `/api/gestion/reservations/seances/${d.seance}/deplacer`, { espace: d.espace, debut: d.debut, fin: d.fin }),
    onSuccess: async () => {
      annoncer("Séance déplacée.");
      setProposition(null);
      setDeplacementClavier(null);
      setOuverte(null);
      await actualiser();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Déplacement impossible.", "erreur"),
  });

  const controler = async (deplacement: Deplacement) => {
    try {
      const controle = await requete<Controle>("POST", `/api/gestion/reservations/seances/${deplacement.seance.id}/controle-deplacement`, {
        espace: deplacement.espace,
        debut: deplacement.debut.toISOString(),
        fin: deplacement.fin.toISOString(),
      });
      setDeplacementClavier(null);
      setOuverte(null);
      setProposition({ deplacement, controle });
      if (!controle.possible) annoncer("Ce créneau n'est pas disponible : la séance reste à sa place.", "erreur");
    } catch (e) {
      annoncer(e instanceof ErreurApi ? e.message : "Contrôle impossible.", "erreur");
    }
  };

  const enregistrerVue = useMutation({
    mutationFn: () => requete<VueEnregistree>("POST", "/api/gestion/reservations/vues", { nom: nomVue, mode, filtres, coloration, par_defaut: false }),
    onSuccess: async () => {
      annoncer("Vue enregistrée.");
      setSauvegarde(false);
      setNomVue("");
      await client.invalidateQueries({ queryKey: ["vues-planning"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Enregistrement impossible.", "erreur"),
  });

  const appliquerVue = (identifiant: string) => {
    const vue = vues.data?.find((v) => String(v.id) === identifiant);
    if (!vue) return;
    setMode(vue.mode as Mode);
    setColoration((vue.coloration as Coloration) ?? "statut");
    setFiltres({ ...FILTRES_VIDES, ...(vue.filtres as Partial<Filtres>) });
  };

  const naviguer = (sens: -1 | 1) => setReference((r) => ajouterJours(r, sens * (mode === "mois" ? 30 : mode === "jour" ? 1 : 7)));
  const glisserAutorise = peut("valider_reservation") && mode !== "liste" && mode !== "mois" && mode !== "multi_sites";
  const pleineHauteur = mode === "semaine" || mode === "jour";
  const filtresActifs = Object.values(filtres).filter(Boolean).length + (coloration === "statut" ? 0 : 1) + (voirAnnulees ? 1 : 0);
  const libellePeriode = mode === "jour" ? jourLong(debut) : mode === "mois" ? new Intl.DateTimeFormat("fr-FR", { month: "long", year: "numeric" }).format(reference) : `Semaine du ${jourLong(debut)}`;

  const optionsSites = (sites.data?.results ?? []).map((s) => ({ valeur: String(s.id), libelle: s.nom }));
  const optionsEspaces = espacesAffiches.map((e) => ({ valeur: String(e.id), libelle: `${e.site_nom} — ${e.nom}` }));

  return (
    // Vues semaine et jour : la page occupe la hauteur de la fenêtre (en-tête, onglets de la rubrique et marges déduits)
    // et la grille l'espace restant (sans défilement).
    <Page titre="Planning" className={cn(pleineHauteur && "flex flex-col lg:h-[calc(100dvh-11rem)]")}>
      <div className="barre-planning">
        <div className="segments" role="group" aria-label="Vue du planning">
          {MODES.map((m) => (
            <button key={m.valeur} type="button" className={`segment${mode === m.valeur ? " segment--actif" : ""}`} aria-pressed={mode === m.valeur} onClick={() => setMode(m.valeur)}>
              {m.libelle}
            </button>
          ))}
        </div>
        <div className="navigation-periode">
          <Bouton variante="secondaire" className="px-0 size-11" onClick={() => naviguer(-1)} aria-label="Période précédente" title="Période précédente">
            <ChevronLeft aria-hidden="true" size={20} strokeWidth={1.8} />
          </Bouton>
          <Bouton variante="secondaire" onClick={() => setReference(new Date())}>
            Aujourd'hui
          </Bouton>
          <Bouton variante="secondaire" className="px-0 size-11" onClick={() => naviguer(1)} aria-label="Période suivante" title="Période suivante">
            <ChevronRight aria-hidden="true" size={20} strokeWidth={1.8} />
          </Bouton>
          <p className="periode-libelle" aria-live="polite">
            {libellePeriode}
          </p>
        </div>
        <Bouton
          variante={filtresOuverts ? "principal" : "secondaire"}
          aria-expanded={filtresOuverts}
          aria-controls="filtres-planning"
          onClick={() => setFiltresOuverts((ouverts) => !ouverts)}
          icone={<SlidersHorizontal size={18} strokeWidth={1.8} />}
        >
          Filtres{filtresActifs ? ` (${filtresActifs} actif${filtresActifs > 1 ? "s" : ""})` : ""}
        </Bouton>
      </div>

      <form id="filtres-planning" hidden={!filtresOuverts} className="filtres" role="search" aria-label="Filtrer le planning" onSubmit={(e) => e.preventDefault()}>
        <ChampSelection libelle="Site" videLibelle="Tous les sites" options={optionsSites} value={filtres.site} onChange={(e) => setFiltres({ ...filtres, site: e.target.value, espace: "" })} />
        <ChampSelection libelle="Famille" videLibelle="Toutes" options={familles} value={filtres.famille} onChange={(e) => setFiltres({ ...filtres, famille: e.target.value })} />
        <ChampSelection libelle="Espace" videLibelle="Tous" options={optionsEspaces} value={filtres.espace} onChange={(e) => setFiltres({ ...filtres, espace: e.target.value })} />
        <ChampSelection libelle="Statut" videLibelle="Tous" options={Object.entries(STATUTS).map(([valeur, s]) => ({ valeur, libelle: s.libelle }))} value={filtres.statut} onChange={(e) => setFiltres({ ...filtres, statut: e.target.value })} />
        <ChampSelection libelle="Type d'usager" videLibelle="Tous" options={Object.entries(TYPES_USAGER).map(([valeur, libelle]) => ({ valeur, libelle }))} value={filtres.type_usager} onChange={(e) => setFiltres({ ...filtres, type_usager: e.target.value })} />
        <ChampSelection
          libelle="Couleurs"
          videLibelle="Par statut"
          options={[{ valeur: "type_usager", libelle: "Par type d'usager" }]}
          value={coloration === "statut" ? "" : coloration}
          onChange={(e) => setColoration(e.target.value === "type_usager" ? "type_usager" : "statut")}
        />
        <CaseACocher libelle="Afficher les annulations" checked={voirAnnulees} onChange={(e) => setVoirAnnulees(e.target.checked)} />
        <ChampSelection libelle="Vue enregistrée" videLibelle="— Mes vues —" options={(vues.data ?? []).map((v) => ({ valeur: String(v.id), libelle: v.nom }))} value="" onChange={(e) => appliquerVue(e.target.value)} />
        <Bouton variante="secondaire" onClick={() => setSauvegarde(true)}>
          Enregistrer cette vue
        </Bouton>
      </form>

      <div className="planning__aide">
        <Legende coloration={coloration} />
        <p className="m-0">Les séances validées et confirmées bloquent le créneau ; les demandes et options apparaissent hachurées.</p>
      </div>

      {seances.isPending || espaces.isPending ? (
        <Chargement libelle="Chargement du planning…" />
      ) : seances.isError ? (
        <Erreur erreur={seances.error} reessayer={() => void seances.refetch()} />
      ) : (
        <>
          <p className="compteur" aria-live="polite">
            {seances.data.length} séance{seances.data.length > 1 ? "s" : ""} sur la période.
            {glisserAutorise ? " Faites glisser une séance pour la déplacer, ou ouvrez-la et choisissez « Déplacer »." : ""}
          </p>
          {mode === "semaine" || mode === "jour" ? (
            <VueSemaine seances={seances.data} debut={debut} jours={jours} coloration={coloration} onOuvrir={setOuverte} onDeposer={glisserAutorise ? (d) => void controler(d) : undefined} />
          ) : null}
          {mode === "chronologie" ? (
            <VueChronologie seances={seances.data} debut={debut} jours={7} espaces={espacesAffiches} coloration={coloration} onOuvrir={setOuverte} onDeposer={glisserAutorise ? (d) => void controler(d) : undefined} />
          ) : null}
          {mode === "mois" ? (
            <VueMois
              seances={seances.data}
              debut={reference}
              coloration={coloration}
              onOuvrir={setOuverte}
              onJour={(jour) => {
                setReference(jour);
                setMode("jour");
              }}
            />
          ) : null}
          {mode === "multi_sites" ? <VueMultiSites seances={seances.data} debut={debut} sites={sites.data?.results ?? []} espaces={espaces.data?.results ?? []} /> : null}
          {mode === "liste" ? <VueListe seances={seances.data} onOuvrir={setOuverte} /> : null}
        </>
      )}

      <Dialogue ouvert={ouverte !== null && deplacementClavier === null} titre={ouverte ? `${ouverte.usager} — ${ouverte.espace_nom}` : ""} onFermer={() => setOuverte(null)}>
        {ouverte ? (
          <>
            <dl className="details">
              <dt>Quand</dt>
              <dd>
                {jourLong(ouverte.debut)}, {heure(ouverte.debut)} – {heure(ouverte.fin)}
              </dd>
              <dt>Dossier</dt>
              <dd>
                <Link to={`/reservations/dossiers/${ouverte.dossier}`}>
                  {ouverte.numero} — {ouverte.objet}
                </Link>
              </dd>
              <dt>Statut</dt>
              <dd>
                <Badge libelle={STATUTS[ouverte.statut]?.libelle ?? ouverte.statut} ton={STATUTS[ouverte.statut]?.ton ?? "neutre"} />
              </dd>
              {ouverte.signalement ? (
                <>
                  <dt>À traiter</dt>
                  <dd>{ouverte.signalement}</dd>
                </>
              ) : null}
            </dl>
            {peut("valider_reservation") && !["annulee", "realisee", "cloturee", "refusee"].includes(ouverte.statut) ? (
              <div className="formulaire__actions">
                <Bouton
                  variante="secondaire"
                  onClick={() => setDeplacementClavier({ espace: String(ouverte.espace), debut: versLocalInput(new Date(ouverte.debut)), fin: versLocalInput(new Date(ouverte.fin)) })}
                >
                  Déplacer…
                </Bouton>
              </div>
            ) : null}
          </>
        ) : null}
      </Dialogue>

      <Dialogue ouvert={deplacementClavier !== null} titre="Déplacer la séance" onFermer={() => setDeplacementClavier(null)}>
        {deplacementClavier && ouverte ? (
          <form
            noValidate
            onSubmit={(e) => {
              e.preventDefault();
              void controler({ seance: ouverte, espace: Number(deplacementClavier.espace), debut: new Date(deplacementClavier.debut), fin: new Date(deplacementClavier.fin) });
            }}
          >
            <ChampSelection libelle="Espace" obligatoire options={(espaces.data?.results ?? []).map((e) => ({ valeur: String(e.id), libelle: `${e.site_nom} — ${e.nom}` }))} value={deplacementClavier.espace} onChange={(e) => setDeplacementClavier({ ...deplacementClavier, espace: e.target.value })} />
            <ChampTexte libelle="Début" type="datetime-local" obligatoire value={deplacementClavier.debut} onChange={(e) => setDeplacementClavier({ ...deplacementClavier, debut: e.target.value })} />
            <ChampTexte libelle="Fin" type="datetime-local" obligatoire value={deplacementClavier.fin} onChange={(e) => setDeplacementClavier({ ...deplacementClavier, fin: e.target.value })} />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setDeplacementClavier(null)}>
                Annuler
              </Bouton>
              <Bouton type="submit">Vérifier la disponibilité</Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>

      <Dialogue ouvert={proposition !== null} titre={proposition?.controle.possible ? "Confirmer le déplacement" : "Créneau indisponible"} onFermer={() => setProposition(null)}>
        {proposition ? (
          <>
            <p>
              {proposition.deplacement.seance.usager} : {dateHeure(proposition.deplacement.debut)} – {heure(proposition.deplacement.fin)}
            </p>
            {proposition.controle.conflits.length ? (
              <div className="alerte alerte--erreur" role="alert">
                <p>Créneau déjà occupé :</p>
                <ul>
                  {proposition.controle.conflits.map((c) => (
                    <li key={c.occurrence}>
                      {c.usager} ({c.dossier}), {heure(c.debut)} – {heure(c.fin)}, {c.espace}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {proposition.controle.hors_horaires ? <p className="alerte alerte--attention">Le créneau est en dehors des horaires d'ouverture.</p> : null}
            {proposition.controle.fermeture ? <p className="alerte alerte--attention">L'espace est fermé à ce moment-là.</p> : null}
            {proposition.controle.alternatives.length ? (
              <>
                <h3>Créneaux libres proposés</h3>
                <ul className="liste-compacte">
                  {proposition.controle.alternatives.map((a) => (
                    <li key={`${a.espace}-${a.debut}`}>
                      <Bouton variante="lien" onClick={() => deplacer.mutate({ seance: proposition.deplacement.seance.id, espace: a.espace, debut: a.debut, fin: a.fin })}>
                        {a.espace_nom}, {dateHeure(a.debut)} – {heure(a.fin)}
                      </Bouton>{" "}
                      <span className="texte-doux">({a.raison})</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setProposition(null)}>
                {proposition.controle.possible ? "Annuler" : "Fermer"}
              </Bouton>
              {proposition.controle.possible ? (
                <Bouton
                  enCours={deplacer.isPending}
                  onClick={() =>
                    deplacer.mutate({
                      seance: proposition.deplacement.seance.id,
                      espace: proposition.deplacement.espace,
                      debut: proposition.deplacement.debut.toISOString(),
                      fin: proposition.deplacement.fin.toISOString(),
                    })
                  }
                >
                  Déplacer
                </Bouton>
              ) : null}
            </div>
          </>
        ) : null}
      </Dialogue>

      <Dialogue ouvert={sauvegarde} titre="Enregistrer la vue du planning" onFermer={() => setSauvegarde(false)}>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            enregistrerVue.mutate();
          }}
        >
          <ChampTexte libelle="Nom de la vue" obligatoire value={nomVue} onChange={(e) => setNomVue(e.target.value)} />
          <div className="formulaire__actions">
            <Bouton variante="secondaire" onClick={() => setSauvegarde(false)}>
              Annuler
            </Bouton>
            <Bouton type="submit" enCours={enregistrerVue.isPending}>
              Enregistrer
            </Bouton>
          </div>
        </form>
      </Dialogue>
    </Page>
  );
}
