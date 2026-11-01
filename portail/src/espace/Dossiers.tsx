/** POR-05 suivi des dossiers ; POR-08 messagerie ; POR-10 signature ; SIG-05 scan signé ; PLA-10 annulation. */
import { classesBouton } from "../ui/Bouton";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { messageErreur, requete, telecharger } from "../api/http";
import type { DocumentPortail, Dossier, Message, NotificationPortail, PieceExigee, Seance, Structure } from "../api/types";
import { PiecesDuDossier } from "./Finances";
import { MaterielDuDossier } from "./Materiel";
import { Bouton } from "../ui/Bouton";
import { Champ, Zone } from "../ui/Champs";
import { Dialogue } from "../ui/Dialogue";
import { Alerte, Chargement, ErreurChargement, Etiquette, TONS_STATUT, TitrePage, date, dateHeure, taille } from "../ui/Elements";

export function TableauDeBord() {
  const structures = useQuery({ queryKey: ["structures"], queryFn: () => requete<Structure[]>("GET", "/api/portail/usagers") });
  const dossiers = useQuery({ queryKey: ["dossiers"], queryFn: () => requete<Dossier[]>("GET", "/api/portail/dossiers") });
  const notifications = useQuery({ queryKey: ["notifications"], queryFn: () => requete<NotificationPortail[]>("GET", "/api/portail/notifications") });
  const premiere = structures.data?.find((s) => s.statut === "valide");
  const pieces = useQuery({
    queryKey: ["pieces-exigees", premiere?.id],
    queryFn: () => requete<PieceExigee[]>("GET", `/api/portail/pieces-exigees?usager=${premiere?.id}`),
    enabled: Boolean(premiere),
  });
  const aFournir = (pieces.data ?? []).filter((p) => p.etat !== "valide" && p.etat !== "a_verifier");
  const enAttente = structures.data?.filter((s) => s.statut === "en_attente") ?? [];
  return (
    <>
      <TitrePage titre="Mon espace" />
      {enAttente.length ? (
        <Alerte ton="attention" titre="Compte en cours de validation">
          <p>La Ville vérifie les informations de {enAttente.map((s) => s.nom).join(", ")}. Vous pourrez déposer des demandes dès la validation.</p>
        </Alerte>
      ) : null}
      <div className="colonnes">
        <section aria-labelledby="titre-mes-dossiers">
          <h2 id="titre-mes-dossiers">Mes demandes récentes</h2>
          {dossiers.isPending ? <Chargement /> : null}
          {dossiers.isError ? <ErreurChargement erreur={dossiers.error} /> : null}
          {dossiers.data ? (
            dossiers.data.length ? (
              <ul className="liste-simple">
                {dossiers.data.slice(0, 5).map((d) => (
                  <li key={d.id}>
                    <Link to={d.brouillon ? `/espace/demande/${d.id}` : `/espace/dossiers/${d.id}`}>
                      {d.numero} — {d.objet}
                    </Link>{" "}
                    <Etiquette texte={d.statut_libelle} ton={TONS_STATUT[d.statut] ?? "neutre"} />
                    {d.messages_non_lus ? <Etiquette texte={`${d.messages_non_lus} message(s) non lu(s)`} ton="attention" /> : null}
                  </li>
                ))}
              </ul>
            ) : (
              <p>Vous n'avez pas encore de demande.</p>
            )
          ) : null}
          <p className="actions">
            {premiere ? (
              <Link className={classesBouton("principal")} to="/espace/demande">
                Nouvelle demande
              </Link>
            ) : null}
            <Link to="/espace/dossiers">Toutes mes demandes</Link>
            <Link to="/espace/campagnes">Créneaux de la saison (campagne annuelle)</Link>
            {structures.data?.some((s) => s.type === "association") ? <Link to="/espace/attestations">Attestations de valorisation</Link> : null}
          </p>
        </section>
        <section aria-labelledby="titre-pieces">
          <h2 id="titre-pieces">Pièces justificatives</h2>
          {premiere ? (
            aFournir.length ? (
              <>
                <p>À fournir pour {premiere.nom} :</p>
                <ul className="liste-simple">
                  {aFournir.map((p) => (
                    <li key={p.type_piece}>
                      {p.libelle} — {p.etat === "refusee" ? `refusée (${p.motif_refus})` : p.etat === "expiree" ? "expirée" : "manquante"}
                    </li>
                  ))}
                </ul>
                <Link to={`/espace/structures/${premiere.id}`}>Déposer les pièces</Link>
              </>
            ) : (
              <p>Toutes les pièces demandées sont fournies.</p>
            )
          ) : (
            <p>Disponible après validation de votre compte.</p>
          )}
        </section>
        <section aria-labelledby="titre-structures">
          <h2 id="titre-structures">Mes structures</h2>
          <ul className="liste-simple">
            {(structures.data ?? []).map((s) => (
              <li key={s.id}>
                <Link to={`/espace/structures/${s.id}`}>{s.nom}</Link> <Etiquette texte={s.statut_libelle} ton={s.statut === "valide" ? "succes" : "attention"} />
              </li>
            ))}
          </ul>
        </section>
        <section aria-labelledby="titre-notifications">
          <h2 id="titre-notifications">Derniers messages reçus</h2>
          {notifications.data?.length ? (
            <ul className="liste-simple">
              {notifications.data.slice(0, 5).map((n) => (
                <li key={n.id}>
                  {dateHeure(n.cree_le)} — {n.sujet}
                </li>
              ))}
            </ul>
          ) : (
            <p>Aucun message.</p>
          )}
        </section>
      </div>
    </>
  );
}

export function MesDossiers() {
  const dossiers = useQuery({ queryKey: ["dossiers"], queryFn: () => requete<Dossier[]>("GET", "/api/portail/dossiers") });
  return (
    <>
      <TitrePage titre="Mes demandes" />
      <p>
        <Link className={classesBouton("principal")} to="/espace/demande">
          Nouvelle demande
        </Link>
      </p>
      {dossiers.isPending ? <Chargement /> : null}
      {dossiers.isError ? <ErreurChargement erreur={dossiers.error} reessayer={() => void dossiers.refetch()} /> : null}
      {dossiers.data ? (
        <table className="tableau">
          <caption>Mes demandes et dossiers</caption>
          <thead>
            <tr>
              <th scope="col">Dossier</th>
              <th scope="col">Objet</th>
              <th scope="col">Structure</th>
              <th scope="col">État</th>
              <th scope="col">Déposée le</th>
            </tr>
          </thead>
          <tbody>
            {dossiers.data.length === 0 ? (
              <tr>
                <td colSpan={5}>Aucune demande pour le moment.</td>
              </tr>
            ) : (
              dossiers.data.map((d) => (
                <tr key={d.id}>
                  <th scope="row">
                    <Link to={d.brouillon ? `/espace/demande/${d.id}` : `/espace/dossiers/${d.id}`}>{d.numero}</Link>
                  </th>
                  <td>{d.objet}</td>
                  <td>{d.usager_nom}</td>
                  <td>
                    <Etiquette texte={d.statut_libelle} ton={TONS_STATUT[d.statut] ?? "neutre"} />
                    {d.messages_non_lus ? <Etiquette texte={`${d.messages_non_lus} message(s) non lu(s)`} ton="attention" /> : null}
                  </td>
                  <td>{d.depose_le ? date(d.depose_le) : "Brouillon"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      ) : null}
    </>
  );
}

function Documents({ dossier }: { dossier: number }) {
  const client = useQueryClient();
  const [annonce, setAnnonce] = useState<string | null>(null);
  const [scan, setScan] = useState<{ document: DocumentPortail; fichier: File | null } | null>(null);
  const documents = useQuery({ queryKey: ["documents", dossier], queryFn: () => requete<DocumentPortail[]>("GET", `/api/portail/dossiers/${dossier}/documents`) });
  const signer = useMutation({
    mutationFn: (document: DocumentPortail) => requete<{ lien: string }>("GET", `/api/portail/dossiers/${dossier}/documents/${document.id}/signature`),
    onSuccess: (r) => window.location.assign(r.lien),
    onError: (e) => setAnnonce(messageErreur(e)),
  });
  const deposer = useMutation({
    mutationFn: () => {
      const formulaire = new FormData();
      if (scan?.fichier) formulaire.append("fichier", scan.fichier);
      return requete<DocumentPortail>("POST", `/api/portail/dossiers/${dossier}/documents/${scan?.document.id}/scan-signe`, formulaire);
    },
    onSuccess: async () => {
      setAnnonce("Document signé déposé : le service le vérifie, puis le contresigne.");
      setScan(null);
      await client.invalidateQueries({ queryKey: ["documents", dossier] });
    },
    onError: (e) => setAnnonce(messageErreur(e)),
  });
  return (
    <section aria-labelledby="titre-documents">
      <h2 id="titre-documents">Documents</h2>
      {annonce ? <Alerte>{annonce}</Alerte> : null}
      {documents.isPending ? <Chargement /> : null}
      {documents.data?.length === 0 ? <p>Aucun document pour le moment.</p> : null}
      <ul className="liste-documents">
        {(documents.data ?? []).map((d) => (
          <li key={d.id}>
            <p>
              <strong>{d.titre}</strong> — {d.statut_libelle}
              {d.echeance_signature && d.statut === "en_signature" ? `, à signer avant le ${dateHeure(d.echeance_signature)}` : ""}
            </p>
            <p className="actions">
              <Bouton variante="secondaire" onClick={() => void telecharger(`/api/portail/dossiers/${dossier}/documents/${d.id}/fichier`, `${d.numero}.pdf`)}>
                Télécharger<span className="sr-only"> {d.titre}</span> (PDF, {taille(d.taille)})
              </Bouton>
              {d.a_signer_en_ligne ? (
                <Bouton onClick={() => signer.mutate(d)} enCours={signer.isPending}>
                  Signer en ligne<span className="sr-only"> {d.titre}</span>
                </Bouton>
              ) : null}
              {d.scan_attendu ? (
                <Bouton variante="lien" onClick={() => setScan({ document: d, fichier: null })}>
                  Déposer le document signé à la main<span className="sr-only"> : {d.titre}</span>
                </Bouton>
              ) : null}
            </p>
          </li>
        ))}
      </ul>
      <Dialogue ouvert={scan !== null} titre="Déposer le document signé" onFermer={() => setScan(null)}>
        {scan ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              deposer.mutate();
            }}
          >
            <p>Imprimez le document, signez-le, puis déposez-le numérisé.</p>
            <Champ libelle="Document signé numérisé" type="file" accept=".pdf,application/pdf" obligatoire aide="Format PDF, 10 Mo au plus." onChange={(e) => setScan({ ...scan, fichier: e.target.files?.[0] ?? null })} />
            <div className="actions">
              <Bouton type="submit" enCours={deposer.isPending} disabled={!scan.fichier}>
                Déposer
              </Bouton>
              <Bouton variante="secondaire" onClick={() => setScan(null)}>
                Annuler
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </section>
  );
}

function Messagerie({ dossier }: { dossier: number }) {
  const client = useQueryClient();
  const [texte, setTexte] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const messages = useQuery({ queryKey: ["messages", dossier], queryFn: () => requete<Message[]>("GET", `/api/portail/dossiers/${dossier}/messages`) });
  const envoyer = useMutation({
    mutationFn: () => requete<Message>("POST", `/api/portail/dossiers/${dossier}/messages`, { corps: texte }),
    onSuccess: async () => {
      setTexte("");
      setErreur(null);
      await client.invalidateQueries({ queryKey: ["messages", dossier] });
    },
    onError: (e) => setErreur(messageErreur(e)),
  });
  return (
    <section aria-labelledby="titre-messages">
      <h2 id="titre-messages">Échanges avec la Ville</h2>
      {messages.data?.length ? (
        <ol className="fil-messages">
          {messages.data.map((m) => (
            <li key={m.id} className={m.de_la_ville ? "message message--ville" : "message message--usager"}>
              <p className="message__entete">
                <strong>{m.de_la_ville ? "Service des équipements" : "Vous"}</strong> — {dateHeure(m.cree_le)}
              </p>
              <p className="message__corps">{m.corps}</p>
            </li>
          ))}
        </ol>
      ) : (
        <p>Aucun échange pour le moment.</p>
      )}
      {erreur ? <Alerte ton="erreur">{erreur}</Alerte> : null}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (texte.trim()) envoyer.mutate();
        }}
      >
        <Zone libelle="Votre message" nom="message" obligatoire maxLength={5000} value={texte} onChange={(e) => setTexte(e.target.value)} aide="5 000 caractères au plus. Le service vous répond ici et vous prévient par courriel." />
        <Bouton type="submit" enCours={envoyer.isPending}>
          Envoyer le message
        </Bouton>
      </form>
    </section>
  );
}

export function FicheDossier() {
  const { id } = useParams();
  const naviguer = useNavigate();
  const client = useQueryClient();
  const [annulation, setAnnulation] = useState<{ seance?: Seance; motif: string } | null>(null);
  const [annonce, setAnnonce] = useState<string | null>(null);
  const dossier = useQuery({ queryKey: ["dossier", id], queryFn: () => requete<Dossier>("GET", `/api/portail/dossiers/${id}`) });
  const annuler = useMutation({
    mutationFn: () =>
      annulation?.seance
        ? requete("POST", `/api/portail/dossiers/${id}/occurrences/${annulation.seance.id}/annuler`, { motif: annulation.motif })
        : requete("POST", `/api/portail/dossiers/${id}/annuler`, { motif: annulation?.motif ?? "" }),
    onSuccess: async () => {
      setAnnonce(annulation?.seance ? "La séance est annulée." : "Votre demande est annulée.");
      setAnnulation(null);
      await client.invalidateQueries({ queryKey: ["dossier", id] });
    },
    onError: (e) => setAnnonce(messageErreur(e)),
  });
  if (dossier.isPending) return <Chargement />;
  if (dossier.isError) return <ErreurChargement erreur={dossier.error} />;
  const d = dossier.data;
  if (d.brouillon) {
    void naviguer(`/espace/demande/${d.id}`, { replace: true });
    return null;
  }
  const annulable = (d.reservations ?? []).some((r) => ["demande", "en_instruction", "option", "validee", "confirmee"].includes(r.statut));
  const tardives = (d.reservations ?? []).flatMap((r) => r.seances).filter((s) => s.annulation_tardive_si_annulee);
  return (
    <>
      <TitrePage titre={`Dossier ${d.numero}`}>
        <p className="chapo">
          {d.objet} — {d.usager_nom} — <Etiquette texte={d.statut_libelle} ton={TONS_STATUT[d.statut] ?? "neutre"} />
        </p>
      </TitrePage>
      {annonce ? <Alerte>{annonce}</Alerte> : null}
      <section aria-labelledby="titre-creneaux">
        <h2 id="titre-creneaux">Créneaux demandés</h2>
        {(d.reservations ?? []).map((r) => (
          <article key={r.id} className="carte">
            <h3>
              {r.espace_nom} ({r.site_nom})
            </h3>
            <p>
              {r.description} — <Etiquette texte={r.statut_libelle} ton={TONS_STATUT[r.statut] ?? "neutre"} />
            </p>
            {r.motif_refus ? <p>Motif : {r.motif_refus}</p> : null}
            {r.option_expire_le ? <p>Pré-réservation valable jusqu'au {dateHeure(r.option_expire_le)}.</p> : null}
            {r.a_faire.length ? (
              <Alerte ton="attention" titre="Pour confirmer votre réservation :">
                <ul>
                  {r.a_faire.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              </Alerte>
            ) : null}
            <details>
              <summary>Séances ({r.seances.length})</summary>
              <ul className="liste-simple">
                {r.seances.map((s) => (
                  <li key={s.id}>
                    {dateHeure(s.debut)} — {s.statut_libelle}
                    {s.annulation_tardive ? " (annulation tardive)" : ""}
                    {s.signalement ? ` — ${s.signalement}` : ""}{" "}
                    {s.annulable ? (
                      <Bouton variante="lien" onClick={() => setAnnulation({ seance: s, motif: "" })}>
                        Annuler<span className="sr-only"> la séance du {dateHeure(s.debut)}</span>
                      </Bouton>
                    ) : null}
                  </li>
                ))}
              </ul>
            </details>
          </article>
        ))}
        {annulable ? (
          <Bouton variante="danger" onClick={() => setAnnulation({ motif: "" })}>
            Annuler toute la demande
          </Bouton>
        ) : null}
      </section>
      <MaterielDuDossier dossier={d} />
      <PiecesDuDossier dossier={d.id} />
      <Documents dossier={d.id} />
      <Messagerie dossier={d.id} />
      <Dialogue ouvert={annulation !== null} titre={annulation?.seance ? "Annuler une séance" : "Annuler la demande"} onFermer={() => setAnnulation(null)}>
        {annulation ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              annuler.mutate();
            }}
          >
            {annulation.seance ? <p>Séance du {dateHeure(annulation.seance.debut)}.</p> : <p>Toutes les séances à venir de ce dossier seront annulées.</p>}
            {annulation.seance?.annulation_tardive_si_annulee ? (
              <Alerte ton="attention">Cette séance est proche : l'annulation sera considérée comme tardive et peut donner lieu à des frais.</Alerte>
            ) : null}
            {!annulation.seance && tardives.length ? (
              <Alerte ton="attention">
                {tardives.length === 1 ? "Une séance est proche" : `${tardives.length} séances sont proches`} : leur annulation sera considérée comme tardive et peut donner lieu à des frais
                ({tardives.map((s) => dateHeure(s.debut)).join(", ")}).
              </Alerte>
            ) : null}
            <Champ libelle="Motif de l'annulation" obligatoire value={annulation.motif} onChange={(e) => setAnnulation({ ...annulation, motif: e.target.value })} />
            <div className="actions">
              <Bouton type="submit" variante="danger" enCours={annuler.isPending}>
                Confirmer l'annulation
              </Bouton>
              <Bouton variante="secondaire" onClick={() => setAnnulation(null)}>
                Ne pas annuler
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </>
  );
}
