/** POR-01, SEC-04 : connexion (avec double authentification), inscription, confirmation, mot de passe oublié, invitation. */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";
import { ErreurApi, requete } from "../api/http";
import type { EtatSession } from "../api/types";
import { useSession } from "../session";
import { Bouton } from "../ui/Bouton";
import { Case, Champ, Choix, Liste, ResumeErreurs } from "../ui/Champs";
import { Alerte, TitrePage } from "../ui/Elements";

type ReponseConnexion = { etape?: "totp"; defi?: string; csrf?: string; expire_dans?: number; contact?: EtatSession["contact"] };

function useErreurs() {
  const [message, setMessage] = useState<string | null>(null);
  const [champs, setChamps] = useState<Record<string, string[]>>({});
  return {
    message,
    champs,
    effacer: () => {
      setMessage(null);
      setChamps({});
    },
    depuis: (erreur: unknown) => {
      if (erreur instanceof ErreurApi) {
        setMessage(erreur.message);
        setChamps(erreur.champs);
      } else setMessage("Une erreur est survenue. Réessayez.");
    },
  };
}

export const REGLES_MOT_DE_PASSE =
  "Au moins 12 caractères avec trois types parmi minuscules, majuscules, chiffres et caractères spéciaux, ou une phrase de passe d'au moins 16 caractères. Évitez les mots de passe courants et votre nom.";

export function Connexion() {
  const { ouvrir } = useSession();
  const naviguer = useNavigate();
  const [parametres] = useSearchParams();
  const [identifiant, setIdentifiant] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [defi, setDefi] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const erreurs = useErreurs();
  const champCode = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (defi) champCode.current?.focus();
  }, [defi]);
  const terminer = (r: ReponseConnexion) => {
    if (r.etape === "totp" && r.defi) {
      setDefi(r.defi);
      return;
    }
    if (r.csrf && r.contact) {
      ouvrir({ csrf: r.csrf, expire_dans: r.expire_dans ?? 0, contact: r.contact });
      const retour = parametres.get("retour");
      naviguer(retour?.startsWith("/espace") ? retour : "/espace");
    }
  };
  const connexion = useMutation({
    mutationFn: () => requete<ReponseConnexion>("POST", "/api/portail/auth/connexion", { identifiant, mot_de_passe: motDePasse }),
    onSuccess: terminer,
    onError: erreurs.depuis,
  });
  const totp = useMutation({
    mutationFn: () => requete<ReponseConnexion>("POST", "/api/portail/auth/totp", { defi, code }),
    onSuccess: terminer,
    onError: (e) => {
      erreurs.depuis(e);
      if (e instanceof ErreurApi && e.code === "defi_expire") setDefi(null);
    },
  });
  const soumettre = (e: FormEvent) => {
    e.preventDefault();
    erreurs.effacer();
    if (defi) totp.mutate();
    else connexion.mutate();
  };
  return (
    <>
      <TitrePage titre="Se connecter" sousTitre={defi ? "code de sécurité" : undefined} />
      <ResumeErreurs message={erreurs.message} champs={erreurs.champs} libelles={{ identifiant: "Adresse électronique", mot_de_passe: "Mot de passe", code: "Code" }} />
      <form className="formulaire formulaire--etroit" onSubmit={soumettre} noValidate={false}>
        {defi ? (
          <>
            <p>Saisissez le code à 6 chiffres affiché par votre application d'authentification.</p>
            <Champ
              ref={champCode}
              libelle="Code de sécurité"
              nom="code"
              obligatoire
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={6}
              aide="6 chiffres, sans espace."
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
            <Bouton type="submit" enCours={totp.isPending}>
              Valider le code
            </Bouton>
          </>
        ) : (
          <>
            <Champ libelle="Adresse électronique" nom="identifiant" type="email" obligatoire autoComplete="username" value={identifiant} onChange={(e) => setIdentifiant(e.target.value)} />
            <Champ libelle="Mot de passe" nom="mot_de_passe" type="password" obligatoire autoComplete="current-password" value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} />
            <Bouton type="submit" enCours={connexion.isPending}>
              Se connecter
            </Bouton>
          </>
        )}
      </form>
      <ul className="liens-secondaires">
        <li>
          <Link to="/mot-de-passe-oublie">Mot de passe oublié</Link>
        </li>
        <li>
          <Link to="/inscription">Créer un compte</Link>
        </li>
      </ul>
    </>
  );
}

const TYPES = [
  { valeur: "association", libelle: "Association" },
  { valeur: "ecole", libelle: "École ou établissement scolaire" },
  { valeur: "entreprise", libelle: "Entreprise ou comité social et économique" },
  { valeur: "autre_collectivite", libelle: "Autre collectivité ou organisme public" },
  { valeur: "particulier", libelle: "Particulier" },
];

const LIBELLES_INSCRIPTION: Record<string, string> = {
  "contact.prenom": "Prénom",
  "contact.nom": "Nom",
  "contact.courriel": "Adresse électronique",
  "contact.telephone": "Téléphone",
  "usager.type": "Vous êtes",
  "usager.nom": "Nom de la structure",
  "usager.adresse": "Adresse",
  "usager.code_postal": "Code postal",
  "usager.commune": "Commune",
  "usager.siret": "SIRET",
  "usager.rna": "Numéro RNA",
  mot_de_passe: "Mot de passe",
  consentement: "Conditions d'utilisation",
};

export function Inscription() {
  const [valeurs, setValeurs] = useState({
    type: "association",
    nom: "",
    sigle: "",
    siret: "",
    rna: "",
    adresse: "",
    code_postal: "",
    commune: "",
    civilite: "",
    prenom: "",
    nomContact: "",
    courriel: "",
    telephone: "",
    role: "president",
    motDePasse: "",
    confirmation: "",
    consentement: false,
  });
  const [envoye, setEnvoye] = useState<string | null>(null);
  const erreurs = useErreurs();
  const changer = (cle: keyof typeof valeurs) => (e: { target: { value: string } }) => setValeurs({ ...valeurs, [cle]: e.target.value });
  const inscrire = useMutation({
    mutationFn: () =>
      requete<{ message: string }>("POST", "/api/portail/auth/inscription", {
        contact: { civilite: valeurs.civilite, prenom: valeurs.prenom, nom: valeurs.nomContact, courriel: valeurs.courriel, telephone: valeurs.telephone },
        usager: {
          type: valeurs.type,
          nom: valeurs.type === "particulier" ? "" : valeurs.nom,
          sigle: valeurs.sigle,
          siret: valeurs.siret.replaceAll(" ", ""),
          rna: valeurs.rna.trim().toUpperCase(),
          adresse: valeurs.adresse,
          code_postal: valeurs.code_postal,
          commune: valeurs.commune,
          role_contact: valeurs.type === "particulier" ? "responsable" : valeurs.role,
        },
        mot_de_passe: valeurs.motDePasse,
        consentement: valeurs.consentement,
      }),
    onSuccess: (r) => setEnvoye(r.message),
    onError: erreurs.depuis,
  });
  const soumettre = (e: FormEvent) => {
    e.preventDefault();
    erreurs.effacer();
    if (valeurs.motDePasse !== valeurs.confirmation) {
      erreurs.depuis(new ErreurApi(400, "validation", "Certains champs sont à corriger.", { mot_de_passe: ["Les deux mots de passe saisis sont différents."] }));
      return;
    }
    inscrire.mutate();
  };
  if (envoye)
    return (
      <>
        <TitrePage titre="Demande de compte envoyée" />
        <Alerte ton="succes">
          <p>{envoye}</p>
          <p>Ouvrez le lien reçu pour confirmer votre adresse ; la Ville validera ensuite votre compte.</p>
        </Alerte>
      </>
    );
  const structure = valeurs.type !== "particulier";
  const e = (cle: string) => erreurs.champs[cle]?.join(" ");
  return (
    <>
      <TitrePage titre="Créer un compte" />
      <p>Les champs obligatoires sont signalés par la mention « obligatoire ». Votre compte sera vérifié par le service des équipements avant votre première demande.</p>
      <ResumeErreurs message={erreurs.message} champs={erreurs.champs} libelles={LIBELLES_INSCRIPTION} />
      <form className="formulaire" onSubmit={soumettre}>
        <fieldset>
          <legend>Votre structure</legend>
          <Choix legende="Vous êtes" nom="usager.type" options={TYPES} valeur={valeurs.type} onChange={(v) => setValeurs({ ...valeurs, type: v })} obligatoire erreur={e("usager.type")} />
          {structure ? (
            <>
              <Champ libelle="Nom de la structure" nom="usager-nom" obligatoire autoComplete="organization" value={valeurs.nom} onChange={changer("nom")} erreur={e("usager.nom")} />
              <Champ libelle="Sigle" nom="usager-sigle" value={valeurs.sigle} onChange={changer("sigle")} />
              {valeurs.type === "association" ? (
                <Champ libelle="Numéro RNA" nom="usager-rna" aide="Format : W suivi de 9 chiffres (ex. W921234567)." value={valeurs.rna} onChange={changer("rna")} erreur={e("usager.rna")} />
              ) : (
                <Champ libelle="SIRET" nom="usager-siret" inputMode="numeric" aide="14 chiffres." value={valeurs.siret} onChange={changer("siret")} erreur={e("usager.siret")} />
              )}
            </>
          ) : null}
          <Champ libelle={structure ? "Adresse du siège" : "Votre adresse"} nom="usager-adresse" obligatoire autoComplete="street-address" value={valeurs.adresse} onChange={changer("adresse")} erreur={e("usager.adresse")} />
          <div className="formulaire__ligne">
            <Champ libelle="Code postal" nom="usager-code_postal" obligatoire autoComplete="postal-code" inputMode="numeric" aide="5 chiffres." value={valeurs.code_postal} onChange={changer("code_postal")} erreur={e("usager.code_postal")} />
            <Champ libelle="Commune" nom="usager-commune" obligatoire autoComplete="address-level2" value={valeurs.commune} onChange={changer("commune")} erreur={e("usager.commune")} />
          </div>
        </fieldset>
        <fieldset>
          <legend>{structure ? "Vous, représentant de la structure" : "Vous"}</legend>
          <Liste libelle="Civilité" nom="contact-civilite" options={[{ valeur: "Madame", libelle: "Madame" }, { valeur: "Monsieur", libelle: "Monsieur" }]} vide="Non précisée" value={valeurs.civilite} onChange={changer("civilite")} autoComplete="honorific-prefix" />
          <div className="formulaire__ligne">
            <Champ libelle="Prénom" nom="contact-prenom" obligatoire autoComplete="given-name" value={valeurs.prenom} onChange={changer("prenom")} erreur={e("contact.prenom")} />
            <Champ libelle="Nom" nom="contact-nom" obligatoire autoComplete="family-name" value={valeurs.nomContact} onChange={changer("nomContact")} erreur={e("contact.nom")} />
          </div>
          {structure ? (
            <Liste
              libelle="Votre fonction"
              nom="contact-role"
              vide={null}
              options={[
                { valeur: "president", libelle: "Président(e)" },
                { valeur: "tresorier", libelle: "Trésorier(ère)" },
                { valeur: "secretaire", libelle: "Secrétaire" },
                { valeur: "directeur", libelle: "Directeur(trice)" },
                { valeur: "responsable", libelle: "Responsable" },
                { valeur: "referent", libelle: "Référent(e)" },
              ]}
              value={valeurs.role}
              onChange={changer("role")}
            />
          ) : null}
          <Champ libelle="Adresse électronique" nom="contact-courriel" type="email" obligatoire autoComplete="email" aide="Elle servira d'identifiant." value={valeurs.courriel} onChange={changer("courriel")} erreur={e("contact.courriel")} />
          <Champ libelle="Téléphone" nom="contact-telephone" type="tel" autoComplete="tel" value={valeurs.telephone} onChange={changer("telephone")} />
        </fieldset>
        <fieldset>
          <legend>Mot de passe</legend>
          <Champ libelle="Mot de passe" nom="mot_de_passe" type="password" obligatoire autoComplete="new-password" aide={REGLES_MOT_DE_PASSE} value={valeurs.motDePasse} onChange={changer("motDePasse")} erreur={e("mot_de_passe")} />
          <Champ libelle="Confirmez le mot de passe" nom="confirmation" type="password" obligatoire autoComplete="new-password" value={valeurs.confirmation} onChange={changer("confirmation")} />
        </fieldset>
        <Case
          libelle="J'accepte les conditions d'utilisation du portail et j'ai pris connaissance de la politique de protection des données personnelles"
          nom="consentement"
          obligatoire
          aide={<Link to="/donnees-personnelles">Lire la politique de protection des données personnelles</Link>}
          checked={valeurs.consentement}
          onChange={(ev) => setValeurs({ ...valeurs, consentement: ev.target.checked })}
          erreur={e("consentement")}
        />
        <Bouton type="submit" enCours={inscrire.isPending}>
          Créer mon compte
        </Bouton>
      </form>
    </>
  );
}

function ActionParJeton({ titre, url, succes }: { titre: string; url: string; succes: string }) {
  const [parametres] = useSearchParams();
  const jeton = parametres.get("jeton") ?? "";
  const [resultat, setResultat] = useState<{ ton: "succes" | "erreur"; message: string } | null>(null);
  const envoye = useRef(false);
  useEffect(() => {
    if (envoye.current || !jeton) return;
    envoye.current = true;
    requete<{ message: string }>("POST", url, { jeton })
      .then((r) => setResultat({ ton: "succes", message: r.message }))
      .catch((e: unknown) => setResultat({ ton: "erreur", message: e instanceof ErreurApi ? e.message : "Ce lien n'est plus valable." }));
  }, [jeton, url]);
  return (
    <>
      <TitrePage titre={titre} />
      {!jeton ? <Alerte ton="erreur">Lien incomplet : ouvrez le lien reçu par courriel.</Alerte> : null}
      {resultat ? (
        <Alerte ton={resultat.ton}>
          <p>{resultat.message}</p>
          {resultat.ton === "succes" ? <p>{succes}</p> : null}
        </Alerte>
      ) : jeton ? (
        <p role="status">Vérification du lien…</p>
      ) : null}
      <p>
        <Link to="/connexion">Aller à la connexion</Link>
      </p>
    </>
  );
}

export function Confirmation() {
  return <ActionParJeton titre="Confirmation de votre adresse" url="/api/portail/auth/confirmation-courriel" succes="Vous recevrez un courriel dès que la Ville aura validé votre compte." />;
}

export function MotDePasseOublie() {
  const [identifiant, setIdentifiant] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const erreurs = useErreurs();
  const demander = useMutation({
    mutationFn: () => requete<{ message: string }>("POST", "/api/portail/auth/mot-de-passe-oublie", { identifiant }),
    onSuccess: (r) => setMessage(r.message),
    onError: erreurs.depuis,
  });
  return (
    <>
      <TitrePage titre="Mot de passe oublié" />
      {message ? (
        <Alerte ton="succes">{message}</Alerte>
      ) : (
        <>
          <ResumeErreurs message={erreurs.message} champs={erreurs.champs} libelles={{ identifiant: "Adresse électronique" }} />
          <form
            className="formulaire formulaire--etroit"
            onSubmit={(e) => {
              e.preventDefault();
              erreurs.effacer();
              demander.mutate();
            }}
          >
            <p>Indiquez l'adresse de votre compte : vous recevrez un lien valable une seule fois pour choisir un nouveau mot de passe.</p>
            <Champ libelle="Adresse électronique" nom="identifiant" type="email" obligatoire autoComplete="username" value={identifiant} onChange={(e) => setIdentifiant(e.target.value)} />
            <Bouton type="submit" enCours={demander.isPending}>
              Recevoir le lien
            </Bouton>
          </form>
        </>
      )}
    </>
  );
}

function NouveauMotDePasse({ titre, url, bouton }: { titre: string; url: string; bouton: string }) {
  const [parametres] = useSearchParams();
  const jeton = parametres.get("jeton") ?? "";
  const [motDePasse, setMotDePasse] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const erreurs = useErreurs();
  const envoyer = useMutation({
    mutationFn: () => requete<{ message: string }>("POST", url, { jeton, mot_de_passe: motDePasse }),
    onSuccess: (r) => setMessage(r.message),
    onError: erreurs.depuis,
  });
  if (message)
    return (
      <>
        <TitrePage titre={titre} />
        <Alerte ton="succes">{message}</Alerte>
        <p>
          <Link to="/connexion">Se connecter</Link>
        </p>
      </>
    );
  return (
    <>
      <TitrePage titre={titre} />
      <ResumeErreurs message={erreurs.message} champs={erreurs.champs} libelles={{ mot_de_passe: "Nouveau mot de passe", jeton: "Lien" }} />
      <form
        className="formulaire formulaire--etroit"
        onSubmit={(e) => {
          e.preventDefault();
          erreurs.effacer();
          if (motDePasse !== confirmation) {
            erreurs.depuis(new ErreurApi(400, "validation", "Certains champs sont à corriger.", { mot_de_passe: ["Les deux mots de passe saisis sont différents."] }));
            return;
          }
          envoyer.mutate();
        }}
      >
        <Champ libelle="Nouveau mot de passe" nom="mot_de_passe" type="password" obligatoire autoComplete="new-password" aide={REGLES_MOT_DE_PASSE} value={motDePasse} onChange={(e) => setMotDePasse(e.target.value)} erreur={erreurs.champs.mot_de_passe?.join(" ")} />
        <Champ libelle="Confirmez le mot de passe" nom="confirmation" type="password" obligatoire autoComplete="new-password" value={confirmation} onChange={(e) => setConfirmation(e.target.value)} />
        <Bouton type="submit" enCours={envoyer.isPending}>
          {bouton}
        </Bouton>
      </form>
    </>
  );
}

export function Reinitialisation() {
  return <NouveauMotDePasse titre="Choisir un nouveau mot de passe" url="/api/portail/auth/reinitialisation" bouton="Enregistrer le mot de passe" />;
}

export function Invitation() {
  return <NouveauMotDePasse titre="Activer votre compte" url="/api/portail/auth/invitation" bouton="Activer mon compte" />;
}
