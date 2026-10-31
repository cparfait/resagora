/** Fiche usager : contacts (USR-02), pièces justificatives (USR-03), historique (USR-05). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { construireChemin, ErreurApi, requete, telecharger, type Page as PageApi } from "../../api/http";
import type { Piece, TypePiece, Usager } from "../../api/types";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateSimple, STATUTS } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { Tableau } from "../../ui/Tableau";

const ROLES = [
  { valeur: "president", libelle: "Président(e)" },
  { valeur: "tresorier", libelle: "Trésorier(ère)" },
  { valeur: "secretaire", libelle: "Secrétaire" },
  { valeur: "referent", libelle: "Référent(e)" },
  { valeur: "directeur", libelle: "Directeur(trice)" },
  { valeur: "responsable", libelle: "Responsable" },
  { valeur: "autre", libelle: "Autre" },
];

interface Historique {
  occurrences_total: number;
  occurrences_realisees: number;
  occurrences_annulees: number;
  absences_non_signalees: number;
  dossiers: { id: number; numero: string; objet: string; statut: string; cree_le: string }[];
}

export default function FicheUsager() {
  const { id } = useParams();
  const { peut } = useSession();
  const client = useQueryClient();
  const { annoncer } = useNotifications();
  const [nouveauContact, setNouveauContact] = useState<{ prenom: string; nom: string; courriel: string; telephone: string; role: string; principal: boolean; peut_signer: boolean } | null>(null);
  const [depot, setDepot] = useState<{ type: string; fichier: File | null; fin: string } | null>(null);
  const [refus, setRefus] = useState<{ piece: Piece; motif: string } | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);

  const usager = useQuery({ queryKey: ["usager", id], queryFn: () => requete<Usager>("GET", `/api/gestion/usagers/usagers/${id}`) });
  const pieces = useQuery({ queryKey: ["pieces", id], queryFn: () => requete<PageApi<Piece>>("GET", construireChemin("/api/gestion/usagers/pieces", { usager: id, taille: 200 })) });
  const types = useQuery({ queryKey: ["types-pieces"], queryFn: () => requete<TypePiece[]>("GET", "/api/gestion/usagers/types-pieces") });
  const historique = useQuery({ queryKey: ["historique", id], queryFn: () => requete<Historique>("GET", `/api/gestion/usagers/usagers/${id}/historique`) });

  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["usager", id] });
    await client.invalidateQueries({ queryKey: ["pieces", id] });
  };

  const ajouterContact = useMutation({
    mutationFn: async () => {
      if (!nouveauContact) return;
      const contact = await requete<{ id: number }>("POST", "/api/gestion/usagers/contacts", {
        prenom: nouveauContact.prenom, nom: nouveauContact.nom, courriel: nouveauContact.courriel, telephone: nouveauContact.telephone,
      });
      await requete("POST", "/api/gestion/usagers/rattachements", {
        usager: Number(id), contact: contact.id, role: nouveauContact.role, principal: nouveauContact.principal, peut_signer: nouveauContact.peut_signer,
      });
    },
    onSuccess: async () => {
      annoncer("Contact ajouté.");
      setNouveauContact(null);
      await rafraichir();
    },
    onError: (e) => setErreur(e instanceof ErreurApi ? e.message : "Ajout impossible."),
  });

  const deposer = useMutation({
    mutationFn: async () => {
      if (!depot?.fichier) throw new ErreurApi(400, "fichier_absent", "Choisissez un fichier.");
      const formulaire = new FormData();
      formulaire.append("usager", String(id));
      formulaire.append("type_piece", depot.type);
      formulaire.append("fichier", depot.fichier);
      if (depot.fin) formulaire.append("valide_jusqu_au", depot.fin);
      return requete<Piece>("POST", "/api/gestion/usagers/pieces", formulaire);
    },
    onSuccess: async () => {
      annoncer("Pièce déposée : elle doit maintenant être vérifiée.");
      setDepot(null);
      await rafraichir();
    },
    onError: (e) => setErreur(e instanceof ErreurApi ? e.message : "Dépôt impossible."),
  });

  const verifier = useMutation({
    mutationFn: ({ piece, valide, motif }: { piece: number; valide: boolean; motif?: string }) => requete("POST", `/api/gestion/usagers/pieces/${piece}/verifier`, { valide, motif: motif ?? "" }),
    onSuccess: async () => {
      annoncer("Vérification enregistrée.");
      setRefus(null);
      await rafraichir();
    },
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Vérification impossible.", "erreur"),
  });

  if (usager.isPending) return <Chargement />;
  if (usager.isError) return <Erreur erreur={usager.error} reessayer={() => void usager.refetch()} />;
  const u = usager.data;
  const gerer = peut("gerer_usager");

  const soumettreContact = (e: FormEvent) => {
    e.preventDefault();
    setErreur(null);
    ajouterContact.mutate();
  };

  return (
    <Page titre={u.nom} description={`${u.type_libelle}${u.commune ? ` — ${u.commune}` : ""}`}>
      <dl className="details details--grille">
        <dt>SIRET</dt>
        <dd>{u.siret || "—"}</dd>
        <dt>RNA</dt>
        <dd>{u.rna || "—"}</dd>
        <dt>Adresse</dt>
        <dd>{[u.adresse, u.code_postal, u.commune].filter(Boolean).join(" ") || "—"}</dd>
        <dt>Résident</dt>
        <dd>{u.resident ? "Oui" : "Non"}</dd>
        <dt>Convention</dt>
        <dd>{u.conventionne ? `Oui${u.convention_reference ? ` (${u.convention_reference})` : ""}${u.convention_fin ? `, jusqu'au ${dateSimple(u.convention_fin)}` : ""}` : "Non"}</dd>
      </dl>

      <section aria-labelledby="titre-contacts">
        <div className="page__entete">
          <h2 id="titre-contacts">Contacts</h2>
          {gerer ? (
            <Bouton variante="secondaire" onClick={() => setNouveauContact({ prenom: "", nom: "", courriel: "", telephone: "", role: "referent", principal: false, peut_signer: false })}>
              Ajouter un contact
            </Bouton>
          ) : null}
        </div>
        <Tableau
          legende="Contacts de l'usager"
          lignes={u.rattachements}
          cleLigne={(r) => r.id}
          messageVide="Aucun contact."
          colonnes={[
            { cle: "nom", titre: "Contact", rendu: (r) => r.contact_nom },
            { cle: "courriel", titre: "Courriel", rendu: (r) => r.contact_courriel },
            { cle: "role", titre: "Rôle", rendu: (r) => ROLES.find((x) => x.valeur === r.role)?.libelle ?? r.role },
            { cle: "drapeaux", titre: "", rendu: (r) => <span className="badges">{r.principal ? <Badge libelle="Principal" ton="info" /> : null}{r.peut_signer ? <Badge libelle="Signataire" /> : null}</span> },
          ]}
        />
      </section>

      <section aria-labelledby="titre-pieces">
        <div className="page__entete">
          <h2 id="titre-pieces">Pièces justificatives</h2>
          {gerer ? (
            <Bouton variante="secondaire" onClick={() => setDepot({ type: "", fichier: null, fin: "" })}>
              Déposer une pièce
            </Bouton>
          ) : null}
        </div>
        {pieces.isPending ? (
          <Chargement lignes={2} />
        ) : pieces.isError ? (
          <Erreur erreur={pieces.error} />
        ) : (
          <Tableau<Piece>
            legende="Pièces de l'usager"
            lignes={pieces.data.results}
            cleLigne={(p) => p.id}
            messageVide="Aucune pièce déposée."
            colonnes={[
              { cle: "type", titre: "Pièce", rendu: (p) => p.type_libelle },
              { cle: "depot", titre: "Déposée le", rendu: (p) => `${dateSimple(p.depose_le)}${p.depose_par_portail ? " (portail)" : ""}` },
              { cle: "fin", titre: "Valable jusqu'au", rendu: (p) => (p.valide_jusqu_au ? dateSimple(p.valide_jusqu_au) : "sans limite") },
              {
                cle: "statut",
                titre: "Statut",
                rendu: (p) => (
                  <Badge libelle={{ a_verifier: "À vérifier", valide: "Valide", refuse: `Refusée : ${p.motif_refus}` }[p.statut] ?? p.statut} ton={p.statut === "valide" ? "succes" : p.statut === "refuse" ? "danger" : "attention"} />
                ),
              },
            ]}
            actions={(p) => (
              <>
                <Bouton variante="lien" onClick={() => void telecharger(`/api/gestion/usagers/pieces/${p.id}/fichier`, p.nom_fichier)} aria-label={`Télécharger ${p.type_libelle}`}>
                  Télécharger
                </Bouton>
                {gerer && p.statut === "a_verifier" ? (
                  <>
                    <Bouton variante="lien" onClick={() => verifier.mutate({ piece: p.id, valide: true })}>
                      Valider
                    </Bouton>
                    <Bouton variante="lien" onClick={() => setRefus({ piece: p, motif: "" })}>
                      Refuser
                    </Bouton>
                  </>
                ) : null}
              </>
            )}
          />
        )}
      </section>

      <section aria-labelledby="titre-historique">
        <h2 id="titre-historique">Historique</h2>
        {historique.data ? (
          <>
            <p>
              {historique.data.occurrences_total} séances dont {historique.data.occurrences_realisees} réalisées, {historique.data.occurrences_annulees} annulées et {historique.data.absences_non_signalees} absences non signalées.
            </p>
            <ul className="liste-compacte">
              {historique.data.dossiers.map((d) => (
                <li key={d.id}>
                  <Link to={`/reservations/dossiers/${d.id}`}>
                    {d.numero} — {d.objet}
                  </Link>{" "}
                  <Badge libelle={STATUTS[d.statut]?.libelle ?? d.statut} ton={STATUTS[d.statut]?.ton ?? "neutre"} />
                </li>
              ))}
            </ul>
          </>
        ) : (
          <Chargement lignes={2} />
        )}
      </section>

      <Dialogue ouvert={nouveauContact !== null} titre="Ajouter un contact" onFermer={() => setNouveauContact(null)}>
        {nouveauContact ? (
          <form onSubmit={soumettreContact}>
            {erreur ? <div className="alerte alerte--erreur" role="alert">{erreur}</div> : null}
            <ChampTexte libelle="Prénom" obligatoire autoComplete="off" value={nouveauContact.prenom} onChange={(e) => setNouveauContact({ ...nouveauContact, prenom: e.target.value })} />
            <ChampTexte libelle="Nom" obligatoire autoComplete="off" value={nouveauContact.nom} onChange={(e) => setNouveauContact({ ...nouveauContact, nom: e.target.value })} />
            <ChampTexte libelle="Courriel" type="email" obligatoire autoComplete="off" value={nouveauContact.courriel} onChange={(e) => setNouveauContact({ ...nouveauContact, courriel: e.target.value })} />
            <ChampTexte libelle="Téléphone" type="tel" autoComplete="off" value={nouveauContact.telephone} onChange={(e) => setNouveauContact({ ...nouveauContact, telephone: e.target.value })} />
            <ChampSelection libelle="Rôle" options={ROLES} value={nouveauContact.role} onChange={(e) => setNouveauContact({ ...nouveauContact, role: e.target.value })} />
            <CaseACocher libelle="Contact principal" checked={nouveauContact.principal} onChange={(e) => setNouveauContact({ ...nouveauContact, principal: e.target.checked })} />
            <CaseACocher libelle="Signe les conventions" checked={nouveauContact.peut_signer} onChange={(e) => setNouveauContact({ ...nouveauContact, peut_signer: e.target.checked })} />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setNouveauContact(null)}>
                Annuler
              </Bouton>
              <Bouton type="submit" enCours={ajouterContact.isPending}>
                Ajouter
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>

      <Dialogue ouvert={depot !== null} titre="Déposer une pièce justificative" onFermer={() => setDepot(null)}>
        {depot ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setErreur(null);
              deposer.mutate();
            }}
          >
            {erreur ? <div className="alerte alerte--erreur" role="alert">{erreur}</div> : null}
            <ChampSelection
              libelle="Type de pièce"
              obligatoire
              options={(types.data ?? []).filter((t) => (t.types_usager ?? []).includes(u.type as never)).map((t) => ({ valeur: String(t.id), libelle: t.libelle }))}
              value={depot.type}
              onChange={(e) => setDepot({ ...depot, type: e.target.value })}
            />
            <ChampTexte libelle="Fichier" type="file" accept=".pdf,.jpg,.jpeg,.png" obligatoire aide="PDF, JPEG ou PNG, 10 Mo au plus." onChange={(e) => setDepot({ ...depot, fichier: e.target.files?.[0] ?? null })} />
            <ChampTexte libelle="Valable jusqu'au" type="date" aide="Laisser vide pour appliquer la durée de validité du type de pièce." value={depot.fin} onChange={(e) => setDepot({ ...depot, fin: e.target.value })} />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setDepot(null)}>
                Annuler
              </Bouton>
              <Bouton type="submit" enCours={deposer.isPending}>
                Déposer
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>

      <Dialogue ouvert={refus !== null} titre="Refuser la pièce" onFermer={() => setRefus(null)}>
        {refus ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              verifier.mutate({ piece: refus.piece.id, valide: false, motif: refus.motif });
            }}
          >
            <ChampTexte libelle="Motif du refus (communiqué à l'usager)" obligatoire value={refus.motif} onChange={(e) => setRefus({ ...refus, motif: e.target.value })} />
            <div className="formulaire__actions">
              <Bouton variante="secondaire" onClick={() => setRefus(null)}>
                Annuler
              </Bouton>
              <Bouton type="submit" variante="danger" enCours={verifier.isPending}>
                Refuser
              </Bouton>
            </div>
          </form>
        ) : null}
      </Dialogue>
    </Page>
  );
}
