/**
 * Connexion des agents avec leur compte de la Ville (Active Directory, SEC-02), puis double
 * authentification par application TOTP pour les rôles sensibles (SEC-03).
 */
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState, type FormEvent } from "react";
import { ErreurApi, requete } from "../api/http";
import type { Enrolement, EtapeConnexion } from "../api/types";
import { Bouton } from "../ui/Bouton";
import { ChampTexte } from "../ui/Champ";

type Etape = "identifiants" | "code_totp" | "enrolement_totp" | "jeton_enrolement";

export function Connexion() {
  const client = useQueryClient();
  const [etape, setEtape] = useState<Etape>("identifiants");
  const [identifiant, setIdentifiant] = useState("");
  const [motDePasse, setMotDePasse] = useState("");
  const [code, setCode] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const [enrolement, setEnrolement] = useState<Enrolement | null>(null);
  const titre = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    document.title = "Connexion — Gestion des équipements — Ville de Châtillon";
    void requete<void>("GET", "/api/gestion/auth/csrf");
  }, []);

  useEffect(() => {
    titre.current?.focus();
    if (etape === "enrolement_totp")
      requete<Enrolement>("GET", "/api/gestion/auth/totp/enrolement")
        .then(setEnrolement)
        .catch((e: unknown) => setErreur(e instanceof ErreurApi ? e.message : "Enrôlement impossible."));
  }, [etape]);

  const terminer = async (resultat: EtapeConnexion) => {
    if (resultat.etape === "connecte") {
      await client.invalidateQueries({ queryKey: ["moi"] });
      return;
    }
    setCode("");
    setEtape(resultat.etape);
  };

  const soumettre = async (evenement: FormEvent) => {
    evenement.preventDefault();
    setErreur(null);
    setEnCours(true);
    try {
      if (etape === "identifiants") {
        await terminer(await requete<EtapeConnexion>("POST", "/api/gestion/auth/connexion", { identifiant, mot_de_passe: motDePasse }));
        setMotDePasse("");
      } else if (etape === "code_totp") {
        await terminer(await requete<EtapeConnexion>("POST", "/api/gestion/auth/totp", { code }));
      } else if (etape === "jeton_enrolement") {
        await terminer(await requete<EtapeConnexion>("POST", "/api/gestion/auth/totp/jeton", { jeton: code }));
      } else {
        await terminer(await requete<EtapeConnexion>("POST", "/api/gestion/auth/totp/enrolement", { code }));
      }
    } catch (e) {
      setErreur(e instanceof ErreurApi ? e.message : "La connexion a échoué. Réessayez.");
    } finally {
      setEnCours(false);
    }
  };

  const titres: Record<Etape, string> = {
    identifiants: "Connexion",
    code_totp: "Vérification en deux étapes",
    enrolement_totp: "Activer la vérification en deux étapes",
    jeton_enrolement: "Réactiver la vérification en deux étapes",
  };

  return (
    <main id="contenu" className="connexion">
      <div className="connexion__carte">
        <p className="connexion__marque">Ville de Châtillon · Équipements sportifs et associatifs</p>
        <h1 ref={titre} tabIndex={-1}>
          {titres[etape]}
        </h1>
        {erreur ? (
          <div className="alerte alerte--erreur" role="alert">
            {erreur}
          </div>
        ) : null}
        <form onSubmit={(e) => void soumettre(e)} noValidate>
          {etape === "identifiants" ? (
            <>
              <p>Utilisez votre identifiant et votre mot de passe de session Windows de la Ville.</p>
              <ChampTexte libelle="Identifiant" name="identifiant" autoComplete="username" obligatoire value={identifiant} onChange={(e) => setIdentifiant(e.target.value)} />
              <ChampTexte
                libelle="Mot de passe"
                name="mot_de_passe"
                type="password"
                autoComplete="current-password"
                obligatoire
                value={motDePasse}
                onChange={(e) => setMotDePasse(e.target.value)}
              />
            </>
          ) : null}
          {etape === "enrolement_totp" ? (
            <div className="connexion__enrolement">
              <p>Votre rôle exige une vérification en deux étapes. Scannez ce code avec l'application d'authentification de votre téléphone professionnel, puis saisissez le code à 6 chiffres affiché.</p>
              {enrolement ? (
                <>
                  <img
                    src={`data:image/svg+xml;charset=utf-8,${encodeURIComponent(enrolement.qr_svg)}`}
                    alt="Code QR d'enrôlement de l'application d'authentification"
                    width={200}
                    height={200}
                  />
                  <p>
                    Saisie manuelle de la clé : <code className="connexion__graine">{enrolement.graine}</code>
                  </p>
                </>
              ) : (
                <p role="status">Préparation du code QR…</p>
              )}
            </div>
          ) : null}
          {etape === "jeton_enrolement" ? (
            <>
              <p>Votre appareil d'authentification a été réinitialisé. Saisissez le code de réactivation à 8 chiffres que l'administrateur vous a transmis.</p>
              <ChampTexte
                libelle="Code de réactivation"
                name="jeton"
                inputMode="numeric"
                autoComplete="off"
                pattern="[0-9]{8}"
                maxLength={9}
                obligatoire
                value={code}
                onChange={(e) => setCode(e.target.value)}
              />
            </>
          ) : null}
          {etape === "code_totp" || etape === "enrolement_totp" ? (
            <ChampTexte
              libelle="Code à 6 chiffres"
              name="code"
              inputMode="numeric"
              autoComplete="one-time-code"
              pattern="[0-9]{6}"
              maxLength={7}
              obligatoire
              aide="Le code change toutes les 30 secondes."
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          ) : null}
          <Bouton type="submit" enCours={enCours}>
            {etape === "identifiants" ? "Se connecter" : "Valider le code"}
          </Bouton>
        </form>
      </div>
    </main>
  );
}
