/** Mon compte (SEC-04, COM-04, USR-06), mes structures et contacts (POR-01), pièces (POR-06), campagnes (PLA-05). */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate, useParams } from "react-router";
import { ErreurApi, messageErreur, requete, telecharger } from "../api/http";
import type { Campagne, Compte, ContactStructure, Piece, PieceExigee, Preferences, Structure } from "../api/types";
import { REGLES_MOT_DE_PASSE } from "../pages/Comptes";
import { Bouton } from "../ui/Bouton";
import { Case, Champ, Liste } from "../ui/Champs";
import { Alerte, Chargement, ErreurChargement, Etiquette, TitrePage, date, dateHeure } from "../ui/Elements";
import { AgendaStructure } from "./Agenda";

function useAnnonce() {
  const [annonce, setAnnonce] = useState<{ ton: "succes" | "erreur"; texte: string } | null>(null);
  return {
    annonce,
    succes: (texte: string) => setAnnonce({ ton: "succes", texte }),
    erreur: (e: unknown) => setAnnonce({ ton: "erreur", texte: messageErreur(e) }),
  };
}

export function MonCompte() {
  const client = useQueryClient();
  const { annonce, succes, erreur } = useAnnonce();
  const compte = useQuery({ queryKey: ["compte"], queryFn: () => requete<Compte>("GET", "/api/portail/compte") });
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: () => requete<Preferences>("GET", "/api/portail/compte/preferences") });
  const [profil, setProfil] = useState<{ prenom: string; nom: string; telephone: string } | null>(null);
  const [motsDePasse, setMotsDePasse] = useState({ actuel: "", nouveau: "", confirmation: "" });
  const [totp, setTotp] = useState<{ qr_svg?: string; cle?: string; code: string; mot_de_passe: string } | null>(null);
  const [prefs, setPrefs] = useState<Preferences | null>(null);
  const [codeSms, setCodeSms] = useState("");
  const [adresse, setAdresse] = useState({ nouveau: "", mot_de_passe: "" });
  const valeursProfil = profil ?? (compte.data ? { prenom: compte.data.prenom, nom: compte.data.nom, telephone: compte.data.telephone } : null);
  const valeursPrefs = prefs ?? preferences.data ?? null;

  const enregistrerProfil = useMutation({
    mutationFn: () => requete<Compte>("PATCH", "/api/portail/compte", valeursProfil),
    onSuccess: async () => {
      succes("Vos coordonnées sont enregistrées.");
      setProfil(null);
      await client.invalidateQueries({ queryKey: ["compte"] });
    },
    onError: erreur,
  });
  const changerMotDePasse = useMutation({
    mutationFn: () => {
      if (motsDePasse.nouveau !== motsDePasse.confirmation) throw new ErreurApi(400, "validation", "Les deux nouveaux mots de passe sont différents.");
      return requete<{ message: string }>("POST", "/api/portail/compte/mot-de-passe", { actuel: motsDePasse.actuel, nouveau: motsDePasse.nouveau });
    },
    onSuccess: (r) => {
      succes(r.message);
      setMotsDePasse({ actuel: "", nouveau: "", confirmation: "" });
    },
    onError: erreur,
  });
  const commencerTotp = useMutation({
    mutationFn: () => requete<{ actif: boolean; qr_svg?: string; cle?: string }>("GET", "/api/portail/compte/totp"),
    onSuccess: (r) => setTotp({ qr_svg: r.qr_svg, cle: r.cle, code: "", mot_de_passe: "" }),
    onError: erreur,
  });
  const activerTotp = useMutation({
    mutationFn: () => requete<{ message: string }>("POST", "/api/portail/compte/totp", { code: totp?.code, mot_de_passe: totp?.mot_de_passe }),
    onSuccess: async (r) => {
      succes(r.message);
      setTotp(null);
      await client.invalidateQueries({ queryKey: ["compte"] });
    },
    onError: erreur,
  });
  const desactiverTotp = useMutation({
    mutationFn: () => requete<{ message: string }>("DELETE", "/api/portail/compte/totp", { mot_de_passe: totp?.mot_de_passe }),
    onSuccess: async (r) => {
      succes(r.message);
      setTotp(null);
      await client.invalidateQueries({ queryKey: ["compte"] });
    },
    onError: erreur,
  });
  const enregistrerPrefs = useMutation({
    mutationFn: () => requete<Preferences>("PATCH", "/api/portail/compte/preferences", valeursPrefs),
    onSuccess: async (r) => {
      succes(r.sms && !r.telephone_confirme ? "Vos préférences sont enregistrées. Saisissez le code reçu par SMS pour confirmer votre numéro." : "Vos préférences sont enregistrées.");
      setPrefs(null);
      await client.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: erreur,
  });
  const confirmerTelephone = useMutation({
    mutationFn: (renvoyer: boolean) => requete<Preferences>("POST", "/api/portail/compte/preferences/telephone", renvoyer ? { renvoyer: true } : { code: codeSms }),
    onSuccess: async (r, renvoyer) => {
      succes(renvoyer ? "Un nouveau code vous a été envoyé par SMS." : r.telephone_confirme ? "Votre numéro est confirmé : vous recevrez les SMS." : "Code enregistré.");
      setCodeSms("");
      await client.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: erreur,
  });
  const changerAdresse = useMutation({
    mutationFn: () => requete<{ message: string }>("POST", "/api/portail/compte/courriel", adresse),
    onSuccess: (r) => {
      succes(r.message);
      setAdresse({ nouveau: "", mot_de_passe: "" });
    },
    onError: erreur,
  });

  if (compte.isPending) return <Chargement />;
  if (compte.isError) return <ErreurChargement erreur={compte.error} />;
  const c = compte.data;
  return (
    <>
      <TitrePage titre="Mon compte" />
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      <section aria-labelledby="titre-coordonnees" className="carte">
        <h2 id="titre-coordonnees">Mes coordonnées</h2>
        <p>Identifiant : {c.identifiant}. Dernière connexion : {c.derniere_connexion ? dateHeure(c.derniere_connexion) : "—"}.</p>
        {valeursProfil ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              enregistrerProfil.mutate();
            }}
          >
            <div className="formulaire__ligne">
              <Champ libelle="Prénom" obligatoire autoComplete="given-name" value={valeursProfil.prenom} onChange={(e) => setProfil({ ...valeursProfil, prenom: e.target.value })} />
              <Champ libelle="Nom" obligatoire autoComplete="family-name" value={valeursProfil.nom} onChange={(e) => setProfil({ ...valeursProfil, nom: e.target.value })} />
            </div>
            <Champ libelle="Téléphone" type="tel" autoComplete="tel" value={valeursProfil.telephone} onChange={(e) => setProfil({ ...valeursProfil, telephone: e.target.value })} />
            <Bouton type="submit" enCours={enregistrerProfil.isPending}>
              Enregistrer mes coordonnées
            </Bouton>
          </form>
        ) : null}
      </section>
      <section aria-labelledby="titre-adresse" className="carte">
        <h2 id="titre-adresse">Adresse électronique</h2>
        <p>Votre adresse actuelle est {c.courriel}. La nouvelle adresse sera confirmée par un lien qui lui est envoyé ; l'ancienne sera prévenue.</p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            changerAdresse.mutate();
          }}
        >
          <Champ libelle="Nouvelle adresse électronique" type="email" obligatoire autoComplete="email" value={adresse.nouveau} onChange={(e) => setAdresse({ ...adresse, nouveau: e.target.value })} />
          <Champ libelle="Mot de passe" type="password" obligatoire autoComplete="current-password" value={adresse.mot_de_passe} onChange={(e) => setAdresse({ ...adresse, mot_de_passe: e.target.value })} />
          <Bouton type="submit" variante="secondaire" enCours={changerAdresse.isPending}>
            Changer d'adresse
          </Bouton>
        </form>
      </section>
      <section aria-labelledby="titre-mot-de-passe" className="carte">
        <h2 id="titre-mot-de-passe">Mot de passe</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            changerMotDePasse.mutate();
          }}
        >
          <Champ libelle="Mot de passe actuel" type="password" obligatoire autoComplete="current-password" value={motsDePasse.actuel} onChange={(e) => setMotsDePasse({ ...motsDePasse, actuel: e.target.value })} />
          <Champ libelle="Nouveau mot de passe" type="password" obligatoire autoComplete="new-password" aide={REGLES_MOT_DE_PASSE} value={motsDePasse.nouveau} onChange={(e) => setMotsDePasse({ ...motsDePasse, nouveau: e.target.value })} />
          <Champ libelle="Confirmez le nouveau mot de passe" type="password" obligatoire autoComplete="new-password" value={motsDePasse.confirmation} onChange={(e) => setMotsDePasse({ ...motsDePasse, confirmation: e.target.value })} />
          <Bouton type="submit" enCours={changerMotDePasse.isPending}>
            Changer de mot de passe
          </Bouton>
        </form>
      </section>
      <section aria-labelledby="titre-totp" className="carte">
        <h2 id="titre-totp">Double authentification</h2>
        <p>
          {c.totp
            ? "Activée : un code de votre application d'authentification vous est demandé à chaque connexion."
            : "Recommandée : en plus du mot de passe, un code à 6 chiffres affiché par une application (Authenticator, FreeOTP…) vous est demandé."}
        </p>
        {!c.totp && !totp ? (
          <Bouton variante="secondaire" onClick={() => commencerTotp.mutate()} enCours={commencerTotp.isPending}>
            Activer la double authentification
          </Bouton>
        ) : null}
        {!c.totp && totp ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              activerTotp.mutate();
            }}
          >
            <p>Scannez ce code avec votre application, ou saisissez la clé : {totp.cle}</p>
            {totp.qr_svg ? <img className="qr" src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(totp.qr_svg)}`} alt="Code QR à scanner avec l'application d'authentification" width={200} height={200} /> : null}
            <Champ libelle="Code affiché par l'application" inputMode="numeric" autoComplete="one-time-code" maxLength={6} obligatoire value={totp.code} onChange={(e) => setTotp({ ...totp, code: e.target.value })} />
            <Champ libelle="Mot de passe (pour confirmer)" type="password" autoComplete="current-password" obligatoire value={totp.mot_de_passe} onChange={(e) => setTotp({ ...totp, mot_de_passe: e.target.value })} />
            <Bouton type="submit" enCours={activerTotp.isPending}>
              Confirmer l'activation
            </Bouton>
          </form>
        ) : null}
        {c.totp ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              desactiverTotp.mutate();
            }}
          >
            <Champ libelle="Mot de passe (pour désactiver)" type="password" autoComplete="current-password" obligatoire value={totp?.mot_de_passe ?? ""} onChange={(e) => setTotp({ code: "", mot_de_passe: e.target.value })} />
            <Bouton type="submit" variante="danger" enCours={desactiverTotp.isPending}>
              Désactiver la double authentification
            </Bouton>
          </form>
        ) : null}
      </section>
      {valeursPrefs ? (
        <section aria-labelledby="titre-preferences" className="carte">
          <h2 id="titre-preferences">Notifications</h2>
          <p>Les messages liés à vos demandes (accusés de réception, validations, documents à signer) vous sont toujours envoyés par courriel.</p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              enregistrerPrefs.mutate();
            }}
          >
            <Case libelle="Recevoir aussi certains messages par SMS (rappels, fermetures)" checked={valeursPrefs.sms} onChange={(e) => setPrefs({ ...valeursPrefs, sms: e.target.checked })} />
            {valeursPrefs.sms ? <Champ libelle="Téléphone mobile" type="tel" autoComplete="tel" aide="Numéro commençant par 06 ou 07." value={valeursPrefs.telephone_sms} onChange={(e) => setPrefs({ ...valeursPrefs, telephone_sms: e.target.value })} /> : null}
            {valeursPrefs.sms && preferences.data?.telephone_sms && !preferences.data.telephone_confirme ? (
              <p className="aide">Numéro {preferences.data.telephone_sms} non confirmé : aucun SMS ne vous est envoyé tant que vous n'avez pas saisi le code reçu.</p>
            ) : null}
            <Case libelle="Rappel la veille de chaque séance" checked={valeursPrefs.rappels} onChange={(e) => setPrefs({ ...valeursPrefs, rappels: e.target.checked })} />
            <Case libelle="Informations générales de la Ville sur les équipements" checked={valeursPrefs.informations} onChange={(e) => setPrefs({ ...valeursPrefs, informations: e.target.checked })} />
            <Bouton type="submit" enCours={enregistrerPrefs.isPending}>
              Enregistrer mes préférences
            </Bouton>
          </form>
          {preferences.data?.sms && preferences.data.telephone_sms && !preferences.data.telephone_confirme ? (
            <form
              onSubmit={(e) => {
                e.preventDefault();
                confirmerTelephone.mutate(false);
              }}
            >
              <h3>Confirmer votre numéro de mobile</h3>
              <Champ libelle="Code reçu par SMS" inputMode="numeric" autoComplete="one-time-code" maxLength={6} obligatoire aide="Code à 6 chiffres, valable 15 minutes." value={codeSms} onChange={(e) => setCodeSms(e.target.value)} />
              <div className="actions">
                <Bouton type="submit" enCours={confirmerTelephone.isPending}>
                  Confirmer le numéro
                </Bouton>
                <Bouton variante="lien" onClick={() => confirmerTelephone.mutate(true)}>
                  Recevoir un nouveau code
                </Bouton>
              </div>
            </form>
          ) : null}
        </section>
      ) : null}
      <section aria-labelledby="titre-donnees" className="carte">
        <h2 id="titre-donnees">Mes données personnelles</h2>
        <p>Téléchargez l'ensemble des données vous concernant (fichier JSON lisible par un tableur ou un éditeur de texte).</p>
        <Bouton variante="secondaire" onClick={() => void telecharger("/api/portail/compte/export", "mes-donnees.json").catch(erreur)}>
          Télécharger mes données
        </Bouton>
      </section>
    </>
  );
}

export function MaStructure() {
  const { id } = useParams();
  const client = useQueryClient();
  const { annonce, succes, erreur } = useAnnonce();
  const structure = useQuery({ queryKey: ["structure", id], queryFn: () => requete<Structure>("GET", `/api/portail/usagers/${id}`) });
  const contacts = useQuery({ queryKey: ["contacts", id], queryFn: () => requete<ContactStructure[]>("GET", `/api/portail/usagers/${id}/contacts`) });
  const pieces = useQuery({ queryKey: ["pieces", id], queryFn: () => requete<Piece[]>("GET", `/api/portail/usagers/${id}/pieces`) });
  const exigees = useQuery({ queryKey: ["pieces-exigees", id], queryFn: () => requete<PieceExigee[]>("GET", `/api/portail/pieces-exigees?usager=${id}`) });
  const [coordonnees, setCoordonnees] = useState<Partial<Structure> | null>(null);
  const [contact, setContact] = useState({ prenom: "", nom: "", courriel: "", telephone: "", role: "referent", peut_signer: false });
  const [depot, setDepot] = useState<{ type: string; fichier: File | null; fin: string }>({ type: "", fichier: null, fin: "" });
  const rafraichir = async () => {
    await client.invalidateQueries({ queryKey: ["structure", id] });
    await client.invalidateQueries({ queryKey: ["contacts", id] });
    await client.invalidateQueries({ queryKey: ["pieces", id] });
    await client.invalidateQueries({ queryKey: ["pieces-exigees"] });
  };
  const enregistrer = useMutation({
    mutationFn: () => requete("PATCH", `/api/portail/usagers/${id}`, coordonnees),
    onSuccess: async () => {
      succes("Coordonnées de la structure enregistrées.");
      setCoordonnees(null);
      await rafraichir();
    },
    onError: erreur,
  });
  const ajouter = useMutation({
    mutationFn: () => requete("POST", `/api/portail/usagers/${id}/contacts`, { ...contact, inviter: true }),
    onSuccess: async () => {
      succes("Contact ajouté ; il reçoit une invitation pour créer son compte.");
      setContact({ prenom: "", nom: "", courriel: "", telephone: "", role: "referent", peut_signer: false });
      await rafraichir();
    },
    onError: erreur,
  });
  const modifierContact = useMutation({
    mutationFn: (c: { id: number; role?: string; peut_signer?: boolean }) => requete("PATCH", `/api/portail/usagers/${id}/contacts/${c.id}`, c),
    onSuccess: async () => {
      succes("Contact modifié.");
      await rafraichir();
    },
    onError: erreur,
  });
  const retirerContact = useMutation({
    mutationFn: (c: ContactStructure) => requete("DELETE", `/api/portail/usagers/${id}/contacts/${c.id}`),
    onSuccess: async () => {
      succes("Contact retiré de la structure.");
      await rafraichir();
    },
    onError: erreur,
  });
  const deposer = useMutation({
    mutationFn: () => {
      const formulaire = new FormData();
      formulaire.append("type_piece", depot.type);
      if (depot.fichier) formulaire.append("fichier", depot.fichier);
      if (depot.fin) formulaire.append("valide_jusqu_au", depot.fin);
      return requete("POST", `/api/portail/usagers/${id}/pieces`, formulaire);
    },
    onSuccess: async () => {
      succes("Pièce déposée : elle sera vérifiée par la Ville.");
      setDepot({ type: "", fichier: null, fin: "" });
      await rafraichir();
    },
    onError: erreur,
  });
  if (structure.isPending) return <Chargement />;
  if (structure.isError) return <ErreurChargement erreur={structure.error} />;
  const s = structure.data;
  const valeurs = coordonnees ?? s;
  return (
    <>
      <TitrePage titre={s.nom}>
        <p className="chapo">
          {s.type_libelle} — <Etiquette texte={s.statut_libelle} ton={s.statut === "valide" ? "succes" : "attention"} /> — votre rôle : {s.mon_role}
        </p>
      </TitrePage>
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      <section aria-labelledby="titre-structure" className="carte">
        <h2 id="titre-structure">Coordonnées</h2>
        {s.principal ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              enregistrer.mutate();
            }}
          >
            <Champ libelle="Adresse" autoComplete="street-address" value={valeurs.adresse ?? ""} onChange={(e) => setCoordonnees({ ...valeurs, adresse: e.target.value })} />
            <div className="formulaire__ligne">
              <Champ libelle="Code postal" autoComplete="postal-code" inputMode="numeric" value={valeurs.code_postal ?? ""} onChange={(e) => setCoordonnees({ ...valeurs, code_postal: e.target.value })} />
              <Champ libelle="Commune" autoComplete="address-level2" value={valeurs.commune ?? ""} onChange={(e) => setCoordonnees({ ...valeurs, commune: e.target.value })} />
            </div>
            <Champ libelle="Téléphone" type="tel" autoComplete="tel" value={valeurs.telephone ?? ""} onChange={(e) => setCoordonnees({ ...valeurs, telephone: e.target.value })} />
            <Champ libelle="Courriel de la structure" type="email" autoComplete="email" value={valeurs.courriel ?? ""} onChange={(e) => setCoordonnees({ ...valeurs, courriel: e.target.value })} />
            <Bouton type="submit" enCours={enregistrer.isPending}>
              Enregistrer
            </Bouton>
          </form>
        ) : (
          <p>
            {s.adresse} {s.code_postal} {s.commune} — {s.telephone} — {s.courriel}
          </p>
        )}
      </section>
      <section aria-labelledby="titre-pieces-structure" className="carte">
        <h2 id="titre-pieces-structure">Pièces justificatives</h2>
        <table className="tableau">
          <caption>Pièces demandées par la Ville</caption>
          <thead>
            <tr>
              <th scope="col">Pièce</th>
              <th scope="col">État</th>
            </tr>
          </thead>
          <tbody>
            {(exigees.data ?? []).map((p) => (
              <tr key={p.type_piece}>
                <th scope="row">{p.libelle}</th>
                <td>
                  {{ valide: "Valide", a_verifier: "En cours de vérification", refusee: `Refusée : ${p.motif_refus}`, expiree: "Expirée", manquante: "À fournir" }[p.etat]}
                  {p.valide_jusqu_au ? ` (jusqu'au ${date(p.valide_jusqu_au)})` : ""}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            deposer.mutate();
          }}
        >
          <h3>Déposer une pièce</h3>
          <Liste libelle="Type de pièce" obligatoire options={(exigees.data ?? []).map((p) => ({ valeur: String(p.type_piece), libelle: p.libelle }))} value={depot.type} onChange={(e) => setDepot({ ...depot, type: e.target.value })} />
          <Champ libelle="Fichier" type="file" accept=".pdf,.jpg,.jpeg,.png" obligatoire aide="PDF, JPEG ou PNG, 10 Mo au plus." onChange={(e) => setDepot({ ...depot, fichier: e.target.files?.[0] ?? null })} />
          <Champ libelle="Valable jusqu'au (si indiqué)" type="date" aide="Format : jj/mm/aaaa." value={depot.fin} onChange={(e) => setDepot({ ...depot, fin: e.target.value })} />
          <Bouton type="submit" variante="secondaire" enCours={deposer.isPending} disabled={!depot.fichier || !depot.type}>
            Déposer la pièce
          </Bouton>
        </form>
        {pieces.data?.length ? (
          <>
            <h3>Pièces déposées</h3>
            <ul className="liste-simple">
              {pieces.data.map((p) => (
                <li key={p.id}>
                  {p.type_libelle} — {p.nom_fichier} — {p.statut_libelle}, déposée le {date(p.depose_le)}{" "}
                  <Bouton variante="lien" onClick={() => void telecharger(`/api/portail/usagers/${id}/pieces/${p.id}/fichier`, p.nom_fichier)}>
                    Télécharger<span className="sr-only"> {p.nom_fichier}</span>
                  </Bouton>
                </li>
              ))}
            </ul>
          </>
        ) : null}
      </section>
      <AgendaStructure usager={s.id} />
      <section aria-labelledby="titre-contacts" className="carte">
        <h2 id="titre-contacts">Contacts</h2>
        <ul className="liste-simple">
          {(contacts.data ?? []).map((c) => (
            <li key={c.id}>
              {c.prenom} {c.nom} — {c.role}
              {c.principal ? " (contact principal)" : ""}
              {c.peut_signer ? ", habilité(e) à signer" : ""}
              {c.courriel ? ` — ${c.courriel}` : ""}
              {c.courriel !== undefined && !c.compte ? " — sans compte sur le portail" : ""}
              {s.principal && !c.principal ? (
                <span className="actions">
                  <Bouton variante="lien" onClick={() => modifierContact.mutate({ id: c.id, peut_signer: !c.peut_signer })}>
                    {c.peut_signer ? "Retirer l'habilitation à signer" : "Habiliter à signer"}
                    <span className="sr-only">
                      {" "}
                      : {c.prenom} {c.nom}
                    </span>
                  </Bouton>
                  <Bouton variante="lien" onClick={() => retirerContact.mutate(c)}>
                    Retirer de la structure
                    <span className="sr-only">
                      {" "}
                      : {c.prenom} {c.nom}
                    </span>
                  </Bouton>
                </span>
              ) : null}
            </li>
          ))}
        </ul>
        {s.principal && s.statut === "valide" ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ajouter.mutate();
            }}
          >
            <h3>Ajouter un contact</h3>
            <div className="formulaire__ligne">
              <Champ libelle="Prénom" obligatoire value={contact.prenom} onChange={(e) => setContact({ ...contact, prenom: e.target.value })} />
              <Champ libelle="Nom" obligatoire value={contact.nom} onChange={(e) => setContact({ ...contact, nom: e.target.value })} />
            </div>
            <Champ libelle="Adresse électronique" type="email" obligatoire value={contact.courriel} onChange={(e) => setContact({ ...contact, courriel: e.target.value })} />
            <Liste
              libelle="Rôle"
              vide={null}
              options={[
                { valeur: "tresorier", libelle: "Trésorier(ère)" },
                { valeur: "secretaire", libelle: "Secrétaire" },
                { valeur: "referent", libelle: "Référent(e)" },
                { valeur: "autre", libelle: "Autre" },
              ]}
              value={contact.role}
              onChange={(e) => setContact({ ...contact, role: e.target.value })}
            />
            <Case libelle="Habilité(e) à signer les conventions" checked={contact.peut_signer} onChange={(e) => setContact({ ...contact, peut_signer: e.target.checked })} />
            <Bouton type="submit" variante="secondaire" enCours={ajouter.isPending}>
              Ajouter et inviter
            </Bouton>
          </form>
        ) : null}
      </section>
    </>
  );
}

export function Campagnes() {
  const naviguer = useNavigate();
  const { annonce, erreur } = useAnnonce();
  const campagnes = useQuery({ queryKey: ["campagnes"], queryFn: () => requete<Campagne[]>("GET", "/api/portail/campagnes") });
  const structures = useQuery({ queryKey: ["structures"], queryFn: () => requete<Structure[]>("GET", "/api/portail/usagers") });
  const [usager, setUsager] = useState("");
  const valides = (structures.data ?? []).filter((s) => s.statut === "valide");
  const deposer = useMutation({
    mutationFn: (campagne: Campagne) => requete<{ id: number }>("POST", `/api/portail/campagnes/${campagne.id}/demandes`, { usager: Number(usager || valides[0]?.id), objet: "" }),
    onSuccess: (d) => void naviguer(`/espace/demande/${d.id}`),
    onError: erreur,
  });
  return (
    <>
      <TitrePage titre="Créneaux de la saison" />
      <p>Chaque année, les associations et écoles demandent leurs créneaux réguliers pendant la campagne ; une commission les attribue selon les priorités fixées par la Ville.</p>
      {annonce ? <Alerte ton={annonce.ton}>{annonce.texte}</Alerte> : null}
      {valides.length > 1 ? <Liste libelle="Structure" options={valides.map((s) => ({ valeur: String(s.id), libelle: s.nom }))} value={usager} onChange={(e) => setUsager(e.target.value)} /> : null}
      {campagnes.isPending ? <Chargement /> : null}
      {campagnes.data?.length === 0 ? <p>Aucune campagne n'est ouverte en ce moment.</p> : null}
      <ul className="cartes">
        {(campagnes.data ?? []).map((c) => (
          <li key={c.id} className="carte">
            <h2>{c.nom}</h2>
            <p>
              Saison {c.saison} ({date(c.saison_debut)} – {date(c.saison_fin)}). Demandes jusqu'au {date(c.cloture)}.
            </p>
            {c.sites.length ? <p>Sites : {c.sites.join(", ")}</p> : null}
            <Bouton onClick={() => deposer.mutate(c)} enCours={deposer.isPending} disabled={!valides.length}>
              Demander des créneaux<span className="sr-only"> — {c.nom}</span>
            </Bouton>
          </li>
        ))}
      </ul>
    </>
  );
}
