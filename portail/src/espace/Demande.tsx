/**
 * POR-04 : demande guidée en quatre étapes (espace et dates → détails → pièces → récapitulatif), avec
 * brouillon enregistré à chaque étape. L'indicateur d'étape est textuel ; chaque étape a son titre.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { chemin, ErreurApi, messageErreur, requete } from "../api/http";
import type { Creneau, Dossier, EspacePublic, MaterielDemande, Page, PieceExigee, Structure, TypeDemande } from "../api/types";
import { ChoixMateriel } from "./Materiel";
import { Bouton } from "../ui/Bouton";
import { Case, Champ, Liste, ResumeErreurs, Zone } from "../ui/Champs";
import { Alerte, Chargement, ErreurChargement, TitrePage, date } from "../ui/Elements";

const ETAPES = ["Espace et dates", "Détails de l'activité", "Pièces justificatives", "Récapitulatif et envoi"];
const JOURS = [
  { code: "MO", libelle: "Lundi" },
  { code: "TU", libelle: "Mardi" },
  { code: "WE", libelle: "Mercredi" },
  { code: "TH", libelle: "Jeudi" },
  { code: "FR", libelle: "Vendredi" },
  { code: "SA", libelle: "Samedi" },
  { code: "SU", libelle: "Dimanche" },
];

export function Indicateur({ etape }: { etape: number }) {
  return (
    <nav aria-label="Étapes de la demande" className="etapes">
      <p className="etapes__texte">
        Étape {etape} sur 4 : {ETAPES[etape - 1]}
      </p>
      <ol>
        {ETAPES.map((libelle, i) => (
          <li key={libelle} aria-current={i + 1 === etape ? "step" : undefined} className={i + 1 < etape ? "etapes__faite" : undefined}>
            {libelle}
            {i + 1 < etape ? <span className="sr-only"> (terminée)</span> : null}
          </li>
        ))}
      </ol>
    </nav>
  );
}

function creneauVide(espace = ""): Creneau {
  return { espace: Number(espace) || 0, date_debut: "", date_fin: "", heure_debut: "18:00", heure_fin: "20:00", jours: [], toutes_les_semaines: 1, exclure_vacances: true };
}

function EditeurCreneau({ creneau, rang, espaces, changer, retirer }: { creneau: Creneau; rang: number; espaces: EspacePublic[]; changer: (c: Creneau) => void; retirer?: () => void }) {
  const serie = creneau.jours.length > 0 || (creneau.date_fin !== "" && creneau.date_fin !== creneau.date_debut);
  const [repetition, setRepetition] = useState(serie);
  return (
    <fieldset className="carte">
      <legend>Créneau {rang}</legend>
      <Liste
        libelle="Équipement"
        nom={`creneau-${rang}-espace`}
        obligatoire
        options={espaces.map((e) => ({ valeur: String(e.id), libelle: `${e.nom} — ${e.site_nom} (${e.capacite} pers.)` }))}
        value={creneau.espace ? String(creneau.espace) : ""}
        onChange={(e) => changer({ ...creneau, espace: Number(e.target.value) })}
      />
      <Case
        libelle="Plusieurs séances (chaque semaine)"
        nom={`creneau-${rang}-repetition`}
        checked={repetition}
        onChange={(e) => {
          setRepetition(e.target.checked);
          if (!e.target.checked) changer({ ...creneau, jours: [], date_fin: creneau.date_debut });
        }}
      />
      <div className="formulaire__ligne">
        <Champ libelle={repetition ? "Première date" : "Date"} nom={`creneau-${rang}-debut`} type="date" obligatoire aide="Format : jj/mm/aaaa." value={creneau.date_debut} onChange={(e) => changer({ ...creneau, date_debut: e.target.value, date_fin: repetition ? creneau.date_fin : e.target.value })} />
        {repetition ? <Champ libelle="Dernière date" nom={`creneau-${rang}-fin`} type="date" obligatoire aide="Format : jj/mm/aaaa." value={creneau.date_fin} onChange={(e) => changer({ ...creneau, date_fin: e.target.value })} /> : null}
      </div>
      <div className="formulaire__ligne">
        <Champ libelle="Heure de début" nom={`creneau-${rang}-heure-debut`} type="time" obligatoire aide="Format : hh:mm." value={creneau.heure_debut} onChange={(e) => changer({ ...creneau, heure_debut: e.target.value })} />
        <Champ libelle="Heure de fin" nom={`creneau-${rang}-heure-fin`} type="time" obligatoire aide="Format : hh:mm." value={creneau.heure_fin} onChange={(e) => changer({ ...creneau, heure_fin: e.target.value })} />
      </div>
      {repetition ? (
        <>
          <fieldset className="champ champ--groupe">
            <legend>
              Jours de la semaine<span className="champ__obligatoire"> (obligatoire)</span>
            </legend>
            <div className="cases-en-ligne">
              {JOURS.map((j) => (
                <Case
                  key={j.code}
                  libelle={j.libelle}
                  nom={`creneau-${rang}-jour-${j.code}`}
                  checked={creneau.jours.includes(j.code)}
                  onChange={(e) => changer({ ...creneau, jours: e.target.checked ? [...creneau.jours, j.code] : creneau.jours.filter((x) => x !== j.code) })}
                />
              ))}
            </div>
          </fieldset>
          <Liste
            libelle="Fréquence"
            nom={`creneau-${rang}-frequence`}
            vide={null}
            options={[
              { valeur: "1", libelle: "Chaque semaine" },
              { valeur: "2", libelle: "Une semaine sur deux" },
            ]}
            value={String(creneau.toutes_les_semaines)}
            onChange={(e) => changer({ ...creneau, toutes_les_semaines: Number(e.target.value) })}
          />
          <Case libelle="Hors vacances scolaires (zone C)" nom={`creneau-${rang}-vacances`} checked={creneau.exclure_vacances} onChange={(e) => changer({ ...creneau, exclure_vacances: e.target.checked })} />
        </>
      ) : null}
      {creneau.description ? (
        <p className="creneau__resume">
          {creneau.espace_nom} : {creneau.description} — {creneau.seances} séance{(creneau.seances ?? 0) > 1 ? "s" : ""}
        </p>
      ) : null}
      {creneau.erreur ? <Alerte ton="erreur">{creneau.erreur}</Alerte> : null}
      {creneau.indisponibles?.length ? (
        <Alerte ton="attention" titre="Déjà occupé à ces dates (votre demande peut être enregistrée, la Ville vous proposera une solution) :">
          <ul>
            {creneau.indisponibles.map((d) => (
              <li key={d}>{d}</li>
            ))}
          </ul>
        </Alerte>
      ) : null}
      {retirer ? (
        <Bouton variante="lien" onClick={retirer}>
          Retirer le créneau {rang}
        </Bouton>
      ) : null}
    </fieldset>
  );
}

export function Demande() {
  const { id } = useParams();
  const [parametres] = useSearchParams();
  const naviguer = useNavigate();
  const client = useQueryClient();
  const [message, setMessage] = useState<string | null>(null);
  const [champs, setChamps] = useState<Record<string, string[]>>({});
  const structures = useQuery({ queryKey: ["structures"], queryFn: () => requete<Structure[]>("GET", "/api/portail/usagers") });
  const espaces = useQuery({ queryKey: ["espaces-tous"], queryFn: () => requete<Page<EspacePublic>>("GET", chemin("/api/portail/catalogue/espaces", { taille: 200 })) });
  const dossier = useQuery({ queryKey: ["dossier", id], queryFn: () => requete<Dossier>("GET", `/api/portail/dossiers/${id}`), enabled: Boolean(id) });
  const valides = (structures.data ?? []).filter((s) => s.statut === "valide");
  const [usager, setUsager] = useState("");
  const [type, setType] = useState("");
  const [creneaux, setCreneaux] = useState<Creneau[]>([creneauVide(parametres.get("espace") ?? "")]);
  const [details, setDetails] = useState({ objet: "", activite: "", effectif: "", observations: "" });
  const [materiel, setMateriel] = useState<MaterielDemande[]>([]);
  const etape = id ? (dossier.data?.etape ?? 1) : 1;
  const usagerCourant = dossier.data ? String(dossier.data.usager) : usager || (valides.length === 1 ? String(valides[0]?.id) : "");
  const types = useQuery({
    queryKey: ["types-demande", usagerCourant],
    queryFn: () => requete<TypeDemande[]>("GET", `/api/portail/types-demande?usager=${usagerCourant}`),
    enabled: Boolean(usagerCourant) && !dossier.data?.campagne,
  });
  const pieces = useQuery({
    queryKey: ["pieces-exigees", usagerCourant],
    queryFn: () => requete<PieceExigee[]>("GET", `/api/portail/pieces-exigees?usager=${usagerCourant}`),
    enabled: Boolean(usagerCourant) && etape >= 3,
  });

  // Reprise d'un brouillon : le formulaire est rempli une fois, à partir du dossier enregistré.
  const [charge, setCharge] = useState<string | null>(null);
  const cleBrouillon = dossier.data ? `${dossier.data.id}-${dossier.data.etape}` : null;
  if (dossier.data && cleBrouillon !== charge) {
    setCharge(cleBrouillon);
    setType(String(dossier.data.type_reservation));
    if (dossier.data.creneaux?.length) setCreneaux(dossier.data.creneaux);
    setDetails({
      objet: dossier.data.objet === "Demande en cours de saisie" ? "" : dossier.data.objet,
      activite: dossier.data.activite ?? "",
      effectif: dossier.data.effectif ? String(dossier.data.effectif) : "",
      observations: dossier.data.observations ?? "",
    });
    setMateriel(dossier.data.materiel_demande ?? []);
  }

  const echec = (e: unknown) => {
    if (e instanceof ErreurApi) {
      setMessage(e.message);
      setChamps(e.champs);
    } else setMessage("Une erreur est survenue.");
  };
  const reussite = async (d: Dossier) => {
    setMessage(null);
    setChamps({});
    client.setQueryData(["dossier", String(d.id)], d);
    await client.invalidateQueries({ queryKey: ["dossiers"] });
    if (!id) void naviguer(`/espace/demande/${d.id}`, { replace: true });
  };
  const creer = useMutation({
    mutationFn: () => requete<Dossier>("POST", "/api/portail/dossiers", { usager: Number(usagerCourant), type_reservation: Number(type), creneaux: creneaux.map(nettoyer) }),
    onSuccess: reussite,
    onError: echec,
  });
  const modifier = useMutation({
    mutationFn: (corps: Record<string, unknown>) => requete<Dossier>("PATCH", `/api/portail/dossiers/${id}`, corps),
    onSuccess: reussite,
    onError: echec,
  });
  const envoyer = useMutation({
    mutationFn: () => requete<Dossier>("POST", `/api/portail/dossiers/${id}/envoyer`),
    onSuccess: async (d) => {
      await client.invalidateQueries({ queryKey: ["dossiers"] });
      void naviguer(`/espace/dossiers/${d.id}`, { state: { envoye: true } });
    },
    onError: echec,
  });
  const abandonner = useMutation({
    mutationFn: () => requete("DELETE", `/api/portail/dossiers/${id}`),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: ["dossiers"] });
      void naviguer("/espace/dossiers");
    },
    onError: echec,
  });
  const deposer = useMutation({
    mutationFn: ({ typePiece, fichier, fin }: { typePiece: number; fichier: File; fin: string }) => {
      const formulaire = new FormData();
      formulaire.append("type_piece", String(typePiece));
      formulaire.append("fichier", fichier);
      if (fin) formulaire.append("valide_jusqu_au", fin);
      return requete("POST", `/api/portail/dossiers/${id}/pieces`, formulaire);
    },
    onSuccess: async () => {
      setMessage(null);
      await client.invalidateQueries({ queryKey: ["pieces-exigees"] });
    },
    onError: echec,
  });

  if (structures.isPending || (id && dossier.isPending)) return <Chargement />;
  if (dossier.isError) return <ErreurChargement erreur={dossier.error} />;
  if (dossier.data && !dossier.data.brouillon) {
    void naviguer(`/espace/dossiers/${dossier.data.id}`, { replace: true });
    return null;
  }
  if (!valides.length)
    return (
      <>
        <TitrePage titre="Nouvelle demande" />
        <Alerte ton="attention">Votre structure doit être validée par la Ville avant de déposer une demande.</Alerte>
      </>
    );

  const apercuCreneaux = dossier.data?.creneaux ?? [];
  const bloquant = apercuCreneaux.some((c) => c.erreur);

  const soumettreEtape1 = (e: FormEvent) => {
    e.preventDefault();
    if (!id) creer.mutate();
    else modifier.mutate({ type_reservation: Number(type) || undefined, creneaux: creneaux.map(nettoyer) });
  };
  const titreEtape = ETAPES[etape - 1] ?? "";

  return (
    <>
      <TitrePage titre={dossier.data?.campagne ? "Demande de créneaux de la saison" : "Nouvelle demande"} sousTitre={`étape ${etape} sur 4`} />
      <Indicateur etape={etape} />
      <ResumeErreurs message={message} champs={champs} libelles={{ objet: "Objet", effectif: "Effectif", creneaux: "Créneaux", type_reservation: "Type de demande" }} />
      <h2>{titreEtape}</h2>
      {etape === 1 ? (
        <form className="formulaire" onSubmit={soumettreEtape1}>
          {!id && valides.length > 1 ? (
            <Liste libelle="Structure" nom="usager" obligatoire options={valides.map((s) => ({ valeur: String(s.id), libelle: s.nom }))} value={usager} onChange={(e) => setUsager(e.target.value)} />
          ) : null}
          {!dossier.data?.campagne ? (
            <Liste libelle="Type de demande" nom="type_reservation" obligatoire options={(types.data ?? []).map((t) => ({ valeur: String(t.id), libelle: t.libelle }))} value={type} onChange={(e) => setType(e.target.value)} />
          ) : null}
          {creneaux.map((c, i) => (
            <EditeurCreneau
              key={i}
              rang={i + 1}
              creneau={{ ...c, ...apercuCreneaux[i], ...c }}
              espaces={espaces.data?.results ?? []}
              changer={(nouveau) => setCreneaux(creneaux.map((x, j) => (j === i ? nouveau : x)))}
              retirer={creneaux.length > 1 ? () => setCreneaux(creneaux.filter((_, j) => j !== i)) : undefined}
            />
          ))}
          {apercuCreneaux.length ? (
            <ul className="sr-only" aria-live="polite">
              {apercuCreneaux.map((c, i) => (
                <li key={i}>
                  Créneau {i + 1} : {c.erreur || `${c.seances} séance(s)`}
                </li>
              ))}
            </ul>
          ) : null}
          {creneaux.length < 10 ? (
            <Bouton variante="secondaire" onClick={() => setCreneaux([...creneaux, creneauVide()])}>
              Ajouter un créneau
            </Bouton>
          ) : null}
          <div className="actions">
            <Bouton type="submit" variante="secondaire" enCours={creer.isPending || modifier.isPending}>
              Vérifier les disponibilités
            </Bouton>
            {id && apercuCreneaux.length && !bloquant ? (
              <Bouton onClick={() => modifier.mutate({ etape: 2, creneaux: creneaux.map(nettoyer), type_reservation: Number(type) || undefined })}>
                Continuer vers l'étape 2
              </Bouton>
            ) : null}
          </div>
        </form>
      ) : null}
      {etape === 2 ? (
        <form
          className="formulaire"
          onSubmit={(e) => {
            e.preventDefault();
            modifier.mutate({ etape: 3, objet: details.objet, activite: details.activite, effectif: Number(details.effectif) || 0, observations: details.observations, materiel });
          }}
        >
          <Champ libelle="Objet de la demande" nom="objet" obligatoire aide="Par exemple : entraînements de l'équipe senior, tournoi de fin d'année." value={details.objet} onChange={(e) => setDetails({ ...details, objet: e.target.value })} erreur={champs.objet?.join(" ")} />
          <Champ libelle="Activité pratiquée" nom="activite" value={details.activite} onChange={(e) => setDetails({ ...details, activite: e.target.value })} />
          <Champ libelle="Nombre de personnes attendues" nom="effectif" type="number" min={1} inputMode="numeric" obligatoire value={details.effectif} onChange={(e) => setDetails({ ...details, effectif: e.target.value })} erreur={champs.effectif?.join(" ")} />
          <ChoixMateriel espace={creneaux[0]?.espace ? Number(creneaux[0].espace) : null} valeurs={materiel} onChange={setMateriel} />
          <Zone libelle="Précisions (besoins particuliers…)" nom="observations" maxLength={2000} value={details.observations} onChange={(e) => setDetails({ ...details, observations: e.target.value })} />
          <div className="actions">
            <Bouton variante="secondaire" onClick={() => modifier.mutate({ etape: 1 })}>
              Revenir à l'étape 1
            </Bouton>
            <Bouton type="submit" enCours={modifier.isPending}>
              Continuer vers l'étape 3
            </Bouton>
          </div>
        </form>
      ) : null}
      {etape === 3 ? (
        <div className="formulaire">
          <p>Les pièces sont vérifiées par la Ville ; elles servent pour toutes vos demandes tant qu'elles sont valables. Formats acceptés : PDF, JPEG ou PNG, 10 Mo au plus.</p>
          {pieces.isPending ? <Chargement /> : null}
          <ul className="liste-pieces">
            {(pieces.data ?? []).map((p) => (
              <li key={p.type_piece}>
                <PieceADeposer piece={p} deposer={(fichier, fin) => deposer.mutate({ typePiece: p.type_piece, fichier, fin })} enCours={deposer.isPending} />
              </li>
            ))}
          </ul>
          <div className="actions">
            <Bouton variante="secondaire" onClick={() => modifier.mutate({ etape: 2 })}>
              Revenir à l'étape 2
            </Bouton>
            <Bouton onClick={() => modifier.mutate({ etape: 4 })} enCours={modifier.isPending}>
              Continuer vers le récapitulatif
            </Bouton>
          </div>
        </div>
      ) : null}
      {etape === 4 && dossier.data ? (
        <div className="formulaire">
          <dl className="details">
            <dt>Structure</dt>
            <dd>{dossier.data.usager_nom}</dd>
            <dt>Type de demande</dt>
            <dd>{dossier.data.type_libelle}</dd>
            <dt>Objet</dt>
            <dd>{dossier.data.objet}</dd>
            <dt>Personnes attendues</dt>
            <dd>{dossier.data.effectif || "Non précisé"}</dd>
            {dossier.data.materiel_demande?.length ? (
              <>
                <dt>Matériel demandé</dt>
                <dd>{dossier.data.materiel_demande.reduce((total, m) => total + m.quantite, 0)} élément(s), examinés par la Ville avec la réservation</dd>
              </>
            ) : null}
            <dt>Créneaux</dt>
            <dd>
              <ul>
                {apercuCreneaux.map((c, i) => (
                  <li key={i}>
                    {c.espace_nom} : {c.description || `${date(c.date_debut)}, ${c.heure_debut} – ${c.heure_fin}`}
                    {c.indisponibles?.length ? ` (${c.indisponibles.length} date(s) déjà occupée(s))` : ""}
                  </li>
                ))}
              </ul>
            </dd>
          </dl>
          {(pieces.data ?? []).some((p) => p.obligatoire && ["manquante", "expiree", "refusee"].includes(p.etat)) ? (
            <Alerte ton="attention">Des pièces justificatives manquent encore : votre demande peut être envoyée, mais elle ne sera confirmée qu'une fois le dossier complet.</Alerte>
          ) : null}
          <div className="actions">
            <Bouton variante="secondaire" onClick={() => modifier.mutate({ etape: 3 })}>
              Revenir à l'étape 3
            </Bouton>
            <Bouton onClick={() => envoyer.mutate()} enCours={envoyer.isPending}>
              Envoyer ma demande
            </Bouton>
          </div>
        </div>
      ) : null}
      {id ? (
        <p className="actions actions--secondaires">
          <Link to="/espace/dossiers">Enregistrer le brouillon et reprendre plus tard</Link>
          <Bouton variante="lien" onClick={() => abandonner.mutate()}>
            Abandonner cette demande
          </Bouton>
        </p>
      ) : null}
      {deposer.isError ? <Alerte ton="erreur">{messageErreur(deposer.error)}</Alerte> : null}
    </>
  );
}

function nettoyer(c: Creneau): Partial<Creneau> {
  const fin = c.date_fin || c.date_debut;
  return {
    espace: c.espace,
    date_debut: c.date_debut,
    date_fin: fin,
    heure_debut: c.heure_debut,
    heure_fin: c.heure_fin,
    jours: fin !== c.date_debut ? c.jours : [],
    toutes_les_semaines: c.toutes_les_semaines,
    exclure_vacances: c.exclure_vacances,
  };
}

const ETATS_PIECE: Record<string, string> = {
  valide: "Valide",
  a_verifier: "Déposée, en cours de vérification",
  refusee: "Refusée",
  expiree: "Expirée",
  manquante: "À fournir",
};

function PieceADeposer({ piece, deposer, enCours }: { piece: PieceExigee; deposer: (fichier: File, fin: string) => void; enCours: boolean }) {
  const [fichier, setFichier] = useState<File | null>(null);
  const [fin, setFin] = useState("");
  return (
    <fieldset className="carte">
      <legend>
        {piece.libelle} — {ETATS_PIECE[piece.etat]}
        {piece.valide_jusqu_au ? `, jusqu'au ${date(piece.valide_jusqu_au)}` : ""}
      </legend>
      {piece.description ? <p>{piece.description}</p> : null}
      {piece.motif_refus ? <p>Motif du refus : {piece.motif_refus}</p> : null}
      {piece.etat !== "valide" && piece.etat !== "a_verifier" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (fichier) deposer(fichier, fin);
          }}
        >
          <Champ libelle={`Fichier : ${piece.libelle}`} type="file" accept=".pdf,.jpg,.jpeg,.png" obligatoire aide="PDF, JPEG ou PNG, 10 Mo au plus." onChange={(e) => setFichier(e.target.files?.[0] ?? null)} />
          <Champ libelle="Valable jusqu'au (si indiqué sur le document)" type="date" aide="Format : jj/mm/aaaa." value={fin} onChange={(e) => setFin(e.target.value)} />
          <Bouton type="submit" variante="secondaire" enCours={enCours} disabled={!fichier}>
            Déposer<span className="sr-only"> {piece.libelle}</span>
          </Bouton>
        </form>
      ) : null}
    </fieldset>
  );
}
