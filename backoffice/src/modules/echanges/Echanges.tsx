/** COM-02 messages en attente, COM-03 information groupée, COM-04 journal des envois, ADM-04 modèles de messages. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { ErreurApi, requete } from "../../api/http";
import { useSession } from "../../auth/session";
import { Badge } from "../../ui/Badge";
import { Bouton } from "../../ui/Bouton";
import { CaseACocher, ChampSelection, ChampTexte, ChampZone } from "../../ui/Champ";
import { Dialogue } from "../../ui/Dialogue";
import { Chargement, Erreur } from "../../ui/Etats";
import { dateHeure } from "../../ui/metier";
import { useNotifications } from "../../ui/Notifications";
import { Page } from "../../ui/Page";
import { EcranRessource, useOptions } from "../../ui/Ressource";
import { Tableau } from "../../ui/Tableau";

interface NonLu {
  dossier: number;
  numero: string;
  usager: string;
  nombre: number;
}

export function MessagesEnAttente() {
  const liste = useQuery({ queryKey: ["messages-non-lus"], queryFn: () => requete<NonLu[]>("GET", "/api/gestion/communication/messages/non-lus") });
  return (
    <Page titre="Messages des usagers" description="Dossiers sur lesquels un usager a écrit et dont le message n'a pas encore été lu.">
      {liste.isPending ? <Chargement /> : null}
      {liste.isError ? <Erreur erreur={liste.error} reessayer={() => void liste.refetch()} /> : null}
      {liste.data ? (
        <Tableau<NonLu>
          legende="Messages non lus par dossier"
          lignes={liste.data}
          cleLigne={(l) => l.dossier}
          messageVide="Aucun message en attente."
          colonnes={[
            { cle: "dossier", titre: "Dossier", rendu: (l) => <Link to={`/reservations/dossiers/${l.dossier}`}>{l.numero}</Link> },
            { cle: "usager", titre: "Usager", rendu: (l) => l.usager },
            { cle: "nombre", titre: "Messages non lus", rendu: (l) => l.nombre, valeurTri: (l) => l.nombre },
          ]}
        />
      ) : null}
    </Page>
  );
}

interface Envoi extends Record<string, unknown> {
  id: number;
  canal: string;
  modele_libelle: string;
  destinataire: string;
  sujet: string;
  corps: string;
  statut: string;
  erreur: string;
  tentatives: number;
  cree_le: string;
  envoyee_le: string | null;
}

const STATUTS_ENVOI: Record<string, { libelle: string; ton: "neutre" | "info" | "succes" | "attention" | "danger" }> = {
  a_envoyer: { libelle: "En file d'attente", ton: "info" },
  envoyee: { libelle: "Envoyé", ton: "succes" },
  echec: { libelle: "Échec", ton: "danger" },
  ignoree: { libelle: "Non envoyé (préférences ou SMS désactivé)", ton: "neutre" },
};

export function JournalEnvois() {
  const { peut } = useSession();
  const { annoncer } = useNotifications();
  const [detail, setDetail] = useState<Envoi | null>(null);
  const renvoyer = useMutation({
    mutationFn: (id: number) => requete("POST", `/api/gestion/communication/envois/${id}/renvoyer`),
    onSuccess: () => annoncer("Envoi relancé."),
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Relance impossible.", "erreur"),
  });
  return (
    <>
      <EcranRessource<Envoi>
        titre="Journal des envois"
        description="Courriels et SMS envoyés aux usagers ; les liens personnels (confirmation, réinitialisation) y sont masqués."
        chemin="/api/gestion/communication/envois"
        cleRequete="envois"
        actionLecture="lire_message"
        libelleObjet="Envoi"
        filtres={[
          { nom: "recherche", libelle: "Destinataire ou objet" },
          { nom: "statut", libelle: "État", options: Object.entries(STATUTS_ENVOI).map(([valeur, s]) => ({ valeur, libelle: s.libelle })) },
          { nom: "canal", libelle: "Canal", options: [{ valeur: "courriel", libelle: "Courriel" }, { valeur: "sms", libelle: "SMS" }] },
        ]}
        colonnes={[
          { cle: "date", titre: "Date", rendu: (e) => dateHeure(e.cree_le), valeurTri: (e) => e.cree_le },
          { cle: "canal", titre: "Canal", rendu: (e) => (e.canal === "sms" ? "SMS" : "Courriel") },
          { cle: "destinataire", titre: "Destinataire", rendu: (e) => e.destinataire },
          { cle: "sujet", titre: "Objet", rendu: (e) => e.sujet },
          { cle: "statut", titre: "État", rendu: (e) => <Badge libelle={STATUTS_ENVOI[e.statut]?.libelle ?? e.statut} ton={STATUTS_ENVOI[e.statut]?.ton ?? "neutre"} /> },
        ]}
        actionsLigne={(e) => (
          <>
            <Bouton variante="lien" onClick={() => setDetail(e)} aria-label={`Lire l'envoi à ${e.destinataire}`}>
              Lire
            </Bouton>
            {peut("envoyer_message") && e.statut === "echec" ? (
              <Bouton variante="lien" onClick={() => renvoyer.mutate(e.id)} aria-label={`Renvoyer à ${e.destinataire}`}>
                Renvoyer
              </Bouton>
            ) : null}
          </>
        )}
      />
      <Dialogue ouvert={detail !== null} titre={detail?.sujet ?? ""} onFermer={() => setDetail(null)}>
        {detail ? (
          <>
            <p>
              À {detail.destinataire} — {dateHeure(detail.cree_le)} — {STATUTS_ENVOI[detail.statut]?.libelle ?? detail.statut}
              {detail.erreur ? ` (${detail.erreur})` : ""}
            </p>
            <pre className="texte-message">{detail.corps}</pre>
          </>
        ) : null}
      </Dialogue>
    </>
  );
}

export function EnvoiGroupe() {
  const { annoncer } = useNotifications();
  const espaces = useOptions("espaces", "/api/gestion/referentiel/espaces", (e) => String(e.nom));
  const [valeurs, setValeurs] = useState({ titre: "", texte: "", espace: "", debut: "", fin: "", sms: false });
  const envoyer = useMutation({
    mutationFn: () =>
      requete<{ usagers: number }>("POST", "/api/gestion/communication/envois-groupes", {
        titre: valeurs.titre,
        texte: valeurs.texte,
        espace: Number(valeurs.espace),
        debut: new Date(valeurs.debut).toISOString(),
        fin: new Date(valeurs.fin).toISOString(),
        sms: valeurs.sms,
      }),
    onSuccess: (r) => annoncer(`Information envoyée à ${r.usagers} usager(s) ; suivez l'envoi dans le journal.`),
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Envoi impossible.", "erreur"),
  });
  return (
    <Page titre="Information groupée" description="Prévenir tous les usagers qui occupent un espace sur une période (travaux, événement, consigne). Les usagers qui ont refusé les informations générales ne la reçoivent pas.">
      <form
        className="formulaire"
        onSubmit={(e) => {
          e.preventDefault();
          envoyer.mutate();
        }}
      >
        <ChampTexte libelle="Objet du message" obligatoire value={valeurs.titre} onChange={(e) => setValeurs({ ...valeurs, titre: e.target.value })} maxLength={150} />
        <ChampZone libelle="Texte" obligatoire value={valeurs.texte} onChange={(e) => setValeurs({ ...valeurs, texte: e.target.value })} maxLength={4000} />
        <div className="formulaire__grille">
          <ChampSelection libelle="Espace concerné" obligatoire options={espaces} value={valeurs.espace} onChange={(e) => setValeurs({ ...valeurs, espace: e.target.value })} />
          <ChampTexte libelle="Du" type="datetime-local" obligatoire value={valeurs.debut} onChange={(e) => setValeurs({ ...valeurs, debut: e.target.value })} />
          <ChampTexte libelle="Au" type="datetime-local" obligatoire value={valeurs.fin} onChange={(e) => setValeurs({ ...valeurs, fin: e.target.value })} />
        </div>
        <CaseACocher libelle="Envoyer aussi un SMS aux usagers qui l'ont demandé" checked={valeurs.sms} onChange={(e) => setValeurs({ ...valeurs, sms: e.target.checked })} />
        <div className="formulaire__actions formulaire__actions--gauche">
          <Bouton type="submit" enCours={envoyer.isPending}>
            Envoyer l'information
          </Bouton>
        </div>
      </form>
    </Page>
  );
}

interface ModeleMessage extends Record<string, unknown> {
  id: number;
  code: string;
  libelle: string;
  sujet: string;
  corps: string;
  sms: string;
  actif: boolean;
}

export function ModelesMessages() {
  const { annoncer } = useNotifications();
  const [apercu, setApercu] = useState<{ sujet: string; corps: string; sms: string } | null>(null);
  const previsualiser = useMutation({
    mutationFn: (id: number) => requete<{ sujet: string; corps: string; sms: string }>("POST", `/api/gestion/communication/modeles/${id}/apercu`),
    onSuccess: setApercu,
    onError: (e) => annoncer(e instanceof ErreurApi ? e.message : "Aperçu impossible.", "erreur"),
  });
  return (
    <>
      <EcranRessource<ModeleMessage>
        titre="Modèles de messages"
        description="Textes des courriels et SMS envoyés par l'application. Les variables s'écrivent entre doubles accolades, par exemple {{ contact.prenom }} ou {{ dossier.numero }}."
        chemin="/api/gestion/communication/modeles"
        cleRequete="modeles-messages"
        actionLecture="lire_message"
        actionEcriture="gerer_modele"
        libelleObjet="Modèle"
        colonnes={[
          { cle: "libelle", titre: "Message", rendu: (m) => m.libelle },
          { cle: "sujet", titre: "Objet", rendu: (m) => m.sujet },
          { cle: "sms", titre: "SMS", rendu: (m) => (m.sms ? "Oui" : "Non") },
          { cle: "actif", titre: "État", rendu: (m) => (m.actif ? <Badge libelle="Actif" ton="succes" /> : <Badge libelle="Désactivé" />) },
        ]}
        champs={[
          { nom: "libelle", libelle: "Libellé", type: "texte", obligatoire: true },
          { nom: "sujet", libelle: "Objet du courriel", type: "texte", obligatoire: true },
          { nom: "corps", libelle: "Texte du courriel", type: "zone", obligatoire: true },
          { nom: "sms", libelle: "Texte du SMS (vide : pas de SMS)", type: "zone" },
          { nom: "actif", libelle: "Modèle actif", type: "booleen" },
        ]}
        actionsLigne={(m) => (
          <Bouton variante="lien" onClick={() => previsualiser.mutate(m.id)} aria-label={`Aperçu de ${m.libelle}`}>
            Aperçu
          </Bouton>
        )}
      />
      <Dialogue ouvert={apercu !== null} titre="Aperçu avec des valeurs d'exemple" onFermer={() => setApercu(null)}>
        {apercu ? (
          <>
            <p>
              <strong>{apercu.sujet}</strong>
            </p>
            <pre className="texte-message">{apercu.corps}</pre>
            {apercu.sms ? <p>SMS : {apercu.sms}</p> : null}
          </>
        ) : null}
      </Dialogue>
    </>
  );
}
