/** Fiche d'un dossier : réservations, séances, transitions de statut, conditions de confirmation (PLA-06, RG-06). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router";
import { construireChemin, ErreurApi, requete, type Page as PageApi } from "../../api/http";
import type { Dossier as TypeDossier, Reservation, Seance } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateHeure, heure, jourLong, STATUTS } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

const CONDITIONS: Record<string, string> = {
  pieces: "Pièces justificatives",
  convention: "Convention ou contrat signé",
  acompte: "Acompte payé",
  caution: "Caution reçue",
};

type ActionMotivee = { reservation: Reservation; type: "refuser" | "annuler" } | { seance: Seance; type: "annuler_seance" } | null;

function Seances({ reservation }: { reservation: Reservation }) {
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [motif, setMotif] = useState<{ seance: Seance; texte: string; parUsager: boolean } | null>(null);
  const [maintenant] = useState(() => Date.now());
  const seances = useQuery({
    queryKey: ["seances", reservation.id],
    queryFn: () => requete<PageApi<Seance>>("GET", construireChemin("/api/gestion/reservations/seances", { reservation: reservation.id, taille: 500 })),
  });
  const action = useMutation({
    mutationFn: ({ url, corps }: { url: string; corps?: unknown }) => requete("POST", url, corps),
    onSuccess: async () => {
      annoncer("Séance mise à jour.");
      setMotif(null);
      await client.invalidateQueries({ queryKey: ["seances", reservation.id] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Action impossible.", "erreur"),
  });
  if (seances.isPending) return <Chargement lignes={2} />;
  if (seances.isError) return <Erreur erreur={seances.error} />;
  return (
    <>
      <Tableau<Seance>
        legende={`Séances de ${reservation.espace_nom}`}
        lignes={seances.data.results}
        cleLigne={(s) => s.id}
        colonnes={[
          { cle: "date", titre: "Date", rendu: (s) => `${jourLong(s.debut)}, ${heure(s.debut)} – ${heure(s.fin)}`, valeurTri: (s) => s.debut },
          { cle: "espace", titre: "Espace", rendu: (s) => s.espace_nom + (s.modifiee_individuellement ? " (déplacée)" : "") },
          {
            cle: "statut",
            titre: "Statut",
            rendu: (s) => (
              <span className="badges">
                <Badge libelle={STATUTS[s.statut]?.libelle ?? s.statut} ton={STATUTS[s.statut]?.ton ?? "neutre"} />
                {s.annulation_tardive ? <Badge libelle="Annulation tardive" ton="attention" /> : null}
                {s.signalement ? <Badge libelle={s.signalement} ton="attention" /> : null}
                {s.presence ? <Badge libelle={{ present: "Présent", absent_signale: "Absence signalée", absent_non_signale: "Absence non signalée" }[s.presence] ?? s.presence} /> : null}
              </span>
            ),
          },
        ]}
        actions={(s) => (
          <>
            {peut("annuler_reservation") && ["demande", "en_instruction", "option", "validee", "confirmee"].includes(s.statut) ? (
              <Bouton variante="lien" onClick={() => setMotif({ seance: s, texte: "", parUsager: false })} aria-label={`Annuler la séance du ${jourLong(s.debut)}`}>
                Annuler
              </Bouton>
            ) : null}
            {peut("cloturer_reservation") && ["validee", "confirmee", "realisee"].includes(s.statut) && new Date(s.debut).getTime() < maintenant
              ? (["present", "absent_signale", "absent_non_signale"] as const).map((p) => (
                  <Bouton key={p} variante="lien" onClick={() => action.mutate({ url: `/api/gestion/reservations/seances/${s.id}/presence`, corps: { presence: p } })}>
                    {{ present: "Présent", absent_signale: "Absence signalée", absent_non_signale: "Absence non signalée" }[p]}
                  </Bouton>
                ))
              : null}
          </>
        )}
      />
      <Dialogue ouvert={motif !== null} titre="Annuler une séance" onFermer={() => setMotif(null)}>
        {motif ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              action.mutate({ url: `/api/gestion/reservations/seances/${motif.seance.id}/annuler`, corps: { motif: motif.texte, par_usager: motif.parUsager } });
            }}
          >
            <p>{dateHeure(motif.seance.debut)}</p>
            <ChampZone libelle="Motif de l'annulation" obligatoire value={motif.texte} onChange={(e) => setMotif({ ...motif, texte: e.target.value })} />
            <CaseACocher
              libelle="À la demande de l'usager"
              aide="Dans le délai paramétré avant la séance, l'annulation est tardive et peut donner lieu à des frais."
              checked={motif.parUsager}
              onChange={(e) => setMotif({ ...motif, parUsager: e.target.checked })}
            />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setMotif(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" variante="danger" enCours={action.isPending}>
                Annuler la séance
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </>
  );
}

export default function Dossier() {
  const { id } = useParams();
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [actionMotivee, setActionMotivee] = useState<ActionMotivee>(null);
  const [motif, setMotif] = useState("");
  const [parUsager, setParUsager] = useState(false);
  const [attestation, setAttestation] = useState<{ condition: string; motif: string } | null>(null);
  const [optionJours, setOptionJours] = useState("7");
  const dossier = useQuery({ queryKey: ["dossier", id], queryFn: () => requete<TypeDossier>("GET", `/api/gestion/reservations/dossiers/${id}`) });

  const transition = useMutation({
    mutationFn: ({ reservation, verbe, corps }: { reservation: number; verbe: string; corps?: unknown }) => requete<Reservation>("POST", `/api/gestion/reservations/reservations/${reservation}/${verbe}`, corps),
    onSuccess: async (r) => {
      annoncer(`Réservation : ${STATUTS[r.statut]?.libelle ?? r.statut}.`);
      setActionMotivee(null);
      setMotif("");
      await client.invalidateQueries({ queryKey: ["dossier", id] });
      await client.invalidateQueries({ queryKey: ["seances"] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Action impossible.", "erreur"),
  });
  const attester = useMutation({
    mutationFn: (corps: { condition: string; motif: string }) => requete<TypeDossier>("POST", `/api/gestion/reservations/dossiers/${id}/attester`, corps),
    onSuccess: async () => {
      annoncer("Condition constatée et tracée au journal.");
      setAttestation(null);
      await client.invalidateQueries({ queryKey: ["dossier", id] });
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Constat impossible.", "erreur"),
  });

  if (dossier.isPending) return <Chargement />;
  if (dossier.isError) return <Erreur erreur={dossier.error} reessayer={() => void dossier.refetch()} />;
  const d = dossier.data;

  const boutons = (r: Reservation) => {
    const possibles: { verbe: string; libelle: string; action: string; variante?: "secondaire" | "danger" }[] = [];
    if (r.statut === "demande") possibles.push({ verbe: "instruire", libelle: "Mettre en instruction", action: "instruire_reservation", variante: "secondaire" });
    if (["demande", "en_instruction"].includes(r.statut)) possibles.push({ verbe: "option", libelle: "Poser une option", action: "valider_reservation", variante: "secondaire" });
    if (["demande", "en_instruction", "option"].includes(r.statut)) possibles.push({ verbe: "valider", libelle: "Valider", action: "valider_reservation" });
    if (r.statut === "validee") possibles.push({ verbe: "confirmer", libelle: "Confirmer", action: "confirmer_reservation" });
    if (["validee", "confirmee", "realisee"].includes(r.statut)) possibles.push({ verbe: "cloturer", libelle: "Clôturer", action: "cloturer_reservation", variante: "secondaire" });
    return possibles.filter((p) => peut(p.action));
  };

  return (
    <Page titre={`Dossier ${d.numero}`} description={`${d.objet} — ${d.usager_nom}`}>
      <dl className="details details--grille">
        <dt>Usager</dt>
        <dd>
          <Link to={`/usagers/${d.usager}`}>{d.usager_nom}</Link>
        </dd>
        <dt>Type</dt>
        <dd>{d.type_reservation_libelle}</dd>
        <dt>Statut</dt>
        <dd>
          <Badge libelle={STATUTS[d.statut]?.libelle ?? d.statut} ton={STATUTS[d.statut]?.ton ?? "neutre"} />
        </dd>
        <dt>Effectif</dt>
        <dd>{d.effectif || "—"}</dd>
        <dt>Origine</dt>
        <dd>{{ guichet: "Guichet", portail: "Portail", campagne: "Campagne annuelle", ville: "Service municipal" }[d.origine] ?? d.origine}</dd>
        {Object.keys(d.conditions_attestees ?? {}).length ? (
          <>
            <dt>Conditions constatées</dt>
            <dd>
              <ul className="liste-simple">
                {Object.entries(d.conditions_attestees as Record<string, { par: string; le: string; motif: string }>).map(([code, a]) => (
                  <li key={code}>
                    {CONDITIONS[code] ?? code} : {a.motif} ({a.par}, {dateHeure(a.le)})
                  </li>
                ))}
              </ul>
            </dd>
          </>
        ) : null}
      </dl>
      {d.reservations.length === 0 ? <p>Aucune réservation dans ce dossier.</p> : null}
      {d.reservations.map((r) => (
        <section key={r.id} className="carte carte--reservation" aria-labelledby={`reservation-${r.id}`}>
          <header className="carte__entete">
            <h2 id={`reservation-${r.id}`}>
              {r.espace_nom} <span className="texte-doux">({r.site_nom})</span>
            </h2>
            <Badge libelle={STATUTS[r.statut]?.libelle ?? r.statut} ton={STATUTS[r.statut]?.ton ?? "neutre"} />
          </header>
          <p>{r.description}</p>
          {r.option_expire_le ? <p>Option valable jusqu'au {dateHeure(r.option_expire_le)}.</p> : null}
          {r.motif_refus ? <p>Motif du refus : {r.motif_refus}</p> : null}
          {r.conditions_manquantes.length ? (
            <div className="alerte alerte--attention">
              <p>Avant confirmation :</p>
              <ul>
                {r.conditions_manquantes.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
              {peut("valider_reservation") ? (
                <Bouton variante="lien" onClick={() => setAttestation({ condition: "caution", motif: "" })}>
                  Constater une condition remplie hors application…
                </Bouton>
              ) : null}
            </div>
          ) : null}
          <div className="formulaire__actions formulaire__actions--gauche">
            {boutons(r).map((b) =>
              b.verbe === "option" ? (
                <span key={b.verbe} className="option-jours">
                  <ChampTexte libelle="Durée de l'option (jours)" type="number" min={1} max={60} value={optionJours} onChange={(e) => setOptionJours(e.target.value)} />
                  <Bouton variante="secondaire" onClick={() => transition.mutate({ reservation: r.id, verbe: "option", corps: { jours: Number(optionJours) } })}>
                    {b.libelle}
                  </Bouton>
                </span>
              ) : (
                <Bouton key={b.verbe} variante={b.variante ?? "principal"} enCours={transition.isPending} onClick={() => transition.mutate({ reservation: r.id, verbe: b.verbe })}>
                  {b.libelle}
                </Bouton>
              ),
            )}
            {peut("valider_reservation") && ["demande", "en_instruction", "option"].includes(r.statut) ? (
              <Bouton variante="danger" onClick={() => setActionMotivee({ reservation: r, type: "refuser" })}>
                Refuser
              </Bouton>
            ) : null}
            {peut("annuler_reservation") && ["demande", "en_instruction", "option", "validee", "confirmee"].includes(r.statut) ? (
              <Bouton variante="danger" onClick={() => setActionMotivee({ reservation: r, type: "annuler" })}>
                Annuler la réservation
              </Bouton>
            ) : null}
          </div>
          <details>
            <summary>Séances ({r.nombre_occurrences})</summary>
            <Seances reservation={r} />
          </details>
        </section>
      ))}
      <Dialogue ouvert={actionMotivee !== null} titre={actionMotivee?.type === "refuser" ? "Refuser la demande" : "Annuler la réservation"} onFermer={() => setActionMotivee(null)}>
        {actionMotivee && "reservation" in actionMotivee ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const corps = actionMotivee.type === "annuler" ? { motif, par_usager: parUsager } : { motif };
              transition.mutate({ reservation: actionMotivee.reservation.id, verbe: actionMotivee.type, corps });
            }}
          >
            <ChampZone libelle="Motif (communiqué à l'usager)" obligatoire value={motif} onChange={(e) => setMotif(e.target.value)} />
            {actionMotivee.type === "annuler" ? (
              <CaseACocher
                libelle="À la demande de l'usager"
                aide="Les séances dans le délai d'annulation tardive seront marquées comme telles (frais possibles)."
                checked={parUsager}
                onChange={(e) => setParUsager(e.target.checked)}
              />
            ) : null}
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setActionMotivee(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" variante="danger" enCours={transition.isPending}>
                {actionMotivee.type === "refuser" ? "Refuser" : "Annuler la réservation"}
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
      <Dialogue ouvert={attestation !== null} titre="Constater une condition de confirmation" onFermer={() => setAttestation(null)}>
        {attestation ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              attester.mutate(attestation);
            }}
          >
            <p>Le constat est enregistré au journal d'audit avec votre nom ; il remplace la vérification automatique.</p>
            <ChampSelection
              libelle="Condition"
              obligatoire
              options={Object.entries(CONDITIONS).map(([valeur, libelle]) => ({ valeur, libelle }))}
              value={attestation.condition}
              onChange={(e) => setAttestation({ ...attestation, condition: e.target.value })}
            />
            <ChampZone
              libelle="Ce qui a été constaté"
              obligatoire
              aide="Exemple : chèque de caution n° 1234 remis au guichet le 3 novembre."
              value={attestation.motif}
              onChange={(e) => setAttestation({ ...attestation, motif: e.target.value })}
            />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setAttestation(null)}>
                Retour
              </Bouton>
              <Bouton type="submit" enCours={attester.isPending}>
                Enregistrer le constat
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </Page>
  );
}
