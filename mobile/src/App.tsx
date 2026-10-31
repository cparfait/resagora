/** Application des gardiens (MOB-01 à MOB-08) : connexion, déverrouillage hors ligne par un code propre à
 * l'application, planning local, pointage, états des lieux avec photos et signature, incidents, file d'envoi et
 * fraîcheur des données. */
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  ajouterPhoto,
  CodeIncorrect,
  CodeInvalide,
  compterSaisies,
  creerCoffre,
  deverrouiller,
  effacerTout,
  identifiantAppareil,
  lireMeta,
  lirePaquet,
  purgerSiPerime,
  rechiffrer,
  remplacerJeton,
  verifierCode,
} from "./coffre";
import { compresser } from "./images";
import { Signature } from "./Signature";
import { reseauDisponible, saisir, SessionExpiree, synchroniser, type Paquet, type Seance, type Vacation } from "./synchro";

type Etat =
  | { ecran: "chargement" }
  | { ecran: "connexion"; message?: string }
  | { ecran: "deverrouillage"; identifiant: string; message?: string }
  | { ecran: "principal"; cle: CryptoKey; jeton: string };

const heure = (iso: string) => new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });
const jour = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Paris" });
const dateHeure = (instant: number | string) => new Date(instant).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });
const MESSAGE_PURGE = "Plus de 7 jours sans synchronisation : le planning a été effacé de l'appareil. Vos saisies non transmises sont conservées ; synchronisez dès que vous avez du réseau.";

export function App() {
  const [etat, setEtat] = useState<Etat>({ ecran: "chargement" });
  useEffect(() => {
    void (async () => {
      // MOB-08 : la purge est vérifiée dès l'ouverture, avant le déverrouillage.
      const purge = await purgerSiPerime(Date.now());
      const meta = await lireMeta();
      setEtat(meta ? { ecran: "deverrouillage", identifiant: meta.identifiant, message: purge || meta.planning_efface_le ? MESSAGE_PURGE : undefined } : { ecran: "connexion" });
    })();
  }, []);
  if (etat.ecran === "chargement") return <p role="status">Ouverture de l'application…</p>;
  if (etat.ecran === "connexion") return <Connexion message={etat.message} onConnecte={(cle, jeton) => setEtat({ ecran: "principal", cle, jeton })} />;
  if (etat.ecran === "deverrouillage")
    return (
      <Deverrouillage
        identifiant={etat.identifiant}
        message={etat.message}
        onDeverrouille={(cle, jeton) => setEtat({ ecran: "principal", cle, jeton })}
        onEfface={(message) => setEtat({ ecran: "connexion", message })}
        onChangerCompte={() => setEtat({ ecran: "connexion" })}
      />
    );
  return <Principal cle={etat.cle} jeton={etat.jeton} onDeconnecte={(message) => setEtat({ ecran: "connexion", message })} />;
}

function Cadre({ titre, children }: { titre: string; children: ReactNode }) {
  return (
    <main className="cadre">
      <h1>{titre}</h1>
      {children}
    </main>
  );
}

function Alerte({ message }: { message: string | null }) {
  return message ? (
    <p className="alerte alerte--erreur" role="alert">
      {message}
    </p>
  ) : null;
}

/** Connexion à l'API mobile (mot de passe de l'annuaire puis, si exigé, code TOTP) ; renvoie le jeton de session. */
function FormulaireConnexion({ identifiantFixe, onJeton }: { identifiantFixe?: string; onJeton: (jeton: string, identifiant: string) => void }) {
  const [valeurs, setValeurs] = useState({ identifiant: identifiantFixe ?? "", mot_de_passe: "", code: "" });
  const [defi, setDefi] = useState<string | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    setEnCours(true);
    setErreur(null);
    try {
      const chemin = defi ? "/api/mobile/auth/totp" : "/api/mobile/auth/connexion";
      const corps = defi
        ? { defi, code: valeurs.code }
        : { identifiant: valeurs.identifiant, mot_de_passe: valeurs.mot_de_passe, appareil: navigator.userAgent.slice(0, 100), appareil_id: await identifiantAppareil() };
      const reponse = await fetch(chemin, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps), credentials: "omit" });
      const donnees = (await reponse.json()) as { etape?: string; defi?: string; jeton?: string; message?: string };
      if (!reponse.ok) throw new Error(donnees.message ?? "Connexion impossible.");
      if (donnees.etape === "totp" && donnees.defi) {
        setDefi(donnees.defi);
        return;
      }
      if (!donnees.jeton) throw new Error("Connexion impossible.");
      onJeton(donnees.jeton, valeurs.identifiant);
    } catch (probleme) {
      setErreur(probleme instanceof TypeError ? "Pas de réseau : la connexion se fait avec le réseau (VPN)." : (probleme as Error).message);
    } finally {
      setEnCours(false);
    }
  };
  return (
    <>
      <Alerte message={erreur} />
      <form onSubmit={(e) => void envoyer(e)}>
        {defi ? (
          <Champ libelle="Code de l'application d'authentification" valeur={valeurs.code} onChange={(code) => setValeurs({ ...valeurs, code })} mode="numeric" complete="one-time-code" />
        ) : (
          <>
            {identifiantFixe ? null : <Champ libelle="Identifiant" valeur={valeurs.identifiant} onChange={(identifiant) => setValeurs({ ...valeurs, identifiant })} complete="username" />}
            <Champ libelle="Mot de passe" type="password" valeur={valeurs.mot_de_passe} onChange={(mot_de_passe) => setValeurs({ ...valeurs, mot_de_passe })} complete="current-password" />
          </>
        )}
        <button type="submit" className="bouton bouton--principal" disabled={enCours}>
          {enCours ? "Connexion…" : defi ? "Valider le code" : "Se connecter"}
        </button>
      </form>
    </>
  );
}

/** Choix (ou changement) du code de déverrouillage : distinct du mot de passe de l'annuaire (D-047). */
function ChoixCode({ bouton, onCode }: { bouton: string; onCode: (code: string) => Promise<void> }) {
  const [code, setCode] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enCours, setEnCours] = useState(false);
  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    const probleme = verifierCode(code) ?? (code === confirmation ? null : "Les deux codes ne sont pas identiques.");
    if (probleme) {
      setErreur(probleme);
      return;
    }
    setEnCours(true);
    try {
      await onCode(code);
    } catch (refus) {
      setErreur(refus instanceof CodeInvalide ? refus.message : "Enregistrement du code impossible.");
    } finally {
      setEnCours(false);
    }
  };
  return (
    <form onSubmit={(e) => void envoyer(e)}>
      <p className="aide">Ce code de 6 à 12 chiffres ouvre l'application sans réseau. Ne réutilisez pas votre mot de passe Windows.</p>
      <Alerte message={erreur} />
      <Champ libelle="Code de déverrouillage" type="password" mode="numeric" valeur={code} onChange={setCode} complete="new-password" />
      <Champ libelle="Confirmez le code" type="password" mode="numeric" valeur={confirmation} onChange={setConfirmation} complete="new-password" />
      <button type="submit" className="bouton bouton--principal" disabled={enCours}>
        {enCours ? "Enregistrement…" : bouton}
      </button>
    </form>
  );
}

function Connexion({ message, onConnecte }: { message?: string; onConnecte: (cle: CryptoKey, jeton: string) => void }) {
  const [session, setSession] = useState<{ jeton: string; identifiant: string } | null>(null);
  return (
    <Cadre titre={session ? "Choisissez votre code" : "Connexion des gardiens"}>
      {message ? <p className="alerte">{message}</p> : null}
      {session ? (
        <ChoixCode bouton="Enregistrer le code" onCode={async (code) => onConnecte(await creerCoffre(code, session.identifiant, session.jeton), session.jeton)} />
      ) : (
        <FormulaireConnexion onJeton={(jeton, identifiant) => setSession({ jeton, identifiant })} />
      )}
      <p className="aide">Les données de vos vacations sont gardées sur le téléphone, chiffrées, pour fonctionner sans réseau dans les gymnases.</p>
    </Cadre>
  );
}

function Deverrouillage({
  identifiant,
  message,
  onDeverrouille,
  onEfface,
  onChangerCompte,
}: {
  identifiant: string;
  message?: string;
  onDeverrouille: (cle: CryptoKey, jeton: string) => void;
  onEfface: (message: string) => void;
  onChangerCompte: () => void;
}) {
  const [code, setCode] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const [enAttente, setEnAttente] = useState(0);
  useEffect(() => {
    void compterSaisies().then(setEnAttente);
  }, []);
  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    try {
      const { cle, jeton } = await deverrouiller(code);
      onDeverrouille(cle, jeton);
    } catch (probleme) {
      if (probleme instanceof CodeIncorrect && probleme.efface) {
        onEfface(probleme.message);
        return;
      }
      setCode("");
      setErreur(probleme instanceof CodeIncorrect ? probleme.message : "Déverrouillage impossible.");
    }
  };
  return (
    <Cadre titre="Déverrouiller l'application">
      <p>Compte : {identifiant}. Fonctionne sans réseau.</p>
      {message ? <p className="alerte">{message}</p> : null}
      <Alerte message={erreur} />
      <form onSubmit={(e) => void envoyer(e)}>
        <Champ libelle="Code de déverrouillage" type="password" mode="numeric" valeur={code} onChange={setCode} complete="current-password" />
        <button type="submit" className="bouton bouton--principal">
          Déverrouiller
        </button>
      </form>
      {enAttente ? (
        <p className="alerte">
          {enAttente} saisie{enAttente > 1 ? "s" : ""} pas encore transmise{enAttente > 1 ? "s" : ""} : déverrouillez et synchronisez avant de changer de compte.
        </p>
      ) : null}
      <button type="button" className="bouton bouton--lien" onClick={onChangerCompte}>
        Changer de compte ou code oublié (efface les données de cet appareil{enAttente ? ", y compris les saisies non transmises" : ""})
      </button>
    </Cadre>
  );
}

function Champ({ libelle, valeur, onChange, type = "text", mode, complete }: { libelle: string; valeur: string; onChange: (v: string) => void; type?: string; mode?: "numeric" | "text"; complete?: string }) {
  const id = `champ-${libelle.replace(/\W+/g, "-").toLowerCase()}`;
  return (
    <div className="champ">
      <label htmlFor={id}>{libelle}</label>
      <input id={id} type={type} inputMode={mode} autoComplete={complete} required value={valeur} onChange={(e) => onChange(e.target.value)} />
    </div>
  );
}

type Vue = { nom: "planning" } | { nom: "etat"; seance: Seance } | { nom: "incident"; seance: Seance | null; site: number } | { nom: "code" };

function Principal({ cle: cleInitiale, jeton: jetonInitial, onDeconnecte }: { cle: CryptoKey; jeton: string; onDeconnecte: (message?: string) => void }) {
  const [{ cle, jeton }, setSession] = useState({ cle: cleInitiale, jeton: jetonInitial });
  const [expiree, setExpiree] = useState(false);
  const [identifiant, setIdentifiant] = useState("");
  const [paquet, setPaquet] = useState<Paquet | null>(null);
  const [enLigne, setEnLigne] = useState(typeof navigator === "undefined" ? true : navigator.onLine);
  const [attente, setAttente] = useState(0);
  const [synchro, setSynchro] = useState<number | null>(null);
  const [efface, setEfface] = useState(false);
  const [maintenant, setMaintenant] = useState(0);
  const [annonce, setAnnonce] = useState<string | null>(null);
  const [vue, setVue] = useState<Vue>({ nom: "planning" });
  const enCours = useRef(false);

  const rafraichir = useCallback(async () => {
    const meta = await lireMeta();
    setAttente(await compterSaisies());
    setSynchro(meta?.derniere_synchronisation ?? null);
    setEfface(Boolean(meta?.planning_efface_le));
    setMaintenant(Date.now());
  }, []);

  const lancer = useCallback(async () => {
    if (enCours.current) return;
    enCours.current = true;
    try {
      const bilan = await synchroniser(cle, jeton);
      if (bilan.paquet) setPaquet(bilan.paquet);
      const messages = [...bilan.conflits, ...bilan.rejets].map((a) => a.message);
      setAnnonce(bilan.envoyees ? `${bilan.envoyees} saisie(s) transmise(s).${messages.length ? ` ${messages.join(" ")}` : ""}` : messages.length ? messages.join(" ") : "Données à jour.");
      setEnLigne(true);
    } catch (probleme) {
      if (probleme instanceof SessionExpiree) {
        setAnnonce(probleme.message);
        setExpiree(true);
        setIdentifiant((await lireMeta())?.identifiant ?? "");
      } else {
        setEnLigne(await reseauDisponible());
      }
    } finally {
      enCours.current = false;
      const meta = await lireMeta();
      setAttente(await compterSaisies());
      setSynchro(meta?.derniere_synchronisation ?? null);
      setEfface(Boolean(meta?.planning_efface_le));
      setMaintenant(Date.now());
    }
  }, [cle, jeton]);

  useEffect(() => {
    void (async () => {
      setPaquet(await lirePaquet<Paquet>(cle));
      await rafraichir();
      await lancer();
    })();
    const enLigneEvt = () => {
      setEnLigne(true);
      void lancer();
    };
    const horsLigneEvt = () => setEnLigne(false);
    window.addEventListener("online", enLigneEvt);
    window.addEventListener("offline", horsLigneEvt);
    const minuterie = window.setInterval(() => void lancer(), 60_000);
    return () => {
      window.removeEventListener("online", enLigneEvt);
      window.removeEventListener("offline", horsLigneEvt);
      window.clearInterval(minuterie);
    };
  }, [cle, lancer, rafraichir]);

  const pointer = async (vacation: Vacation, moment: "arrivee" | "depart") => {
    await saisir(cle, "pointage", { vacation: vacation.id, moment, instant: new Date().toISOString() });
    setAnnonce(moment === "arrivee" ? "Arrivée pointée." : "Départ pointé.");
    await rafraichir();
    void lancer();
  };

  const deconnecter = async () => {
    try {
      await fetch("/api/mobile/auth/deconnexion", { method: "POST", headers: { Authorization: `Appareil ${jeton}` }, credentials: "omit" });
    } catch {
      // hors ligne : la session expirera d'elle-même ; les données locales sont effacées quoi qu'il arrive
    }
    await effacerTout();
    onDeconnecte();
  };

  const alerteHeures = paquet?.parametres.alerte_heures ?? 24;
  const ancienne = synchro !== null && maintenant - synchro > alerteHeures * 3_600_000;
  return (
    <div className="cadre">
      <header className="bandeau">
        <p className={`etat ${enLigne ? "etat--en-ligne" : "etat--hors-ligne"}`}>
          {enLigne ? "Connecté" : "Hors ligne"} — {attente} saisie{attente > 1 ? "s" : ""} en attente
        </p>
        <p className={ancienne || efface ? "fraicheur fraicheur--alerte" : "fraicheur"}>
          {efface ? "Planning effacé (plus de 7 jours sans synchronisation)" : synchro ? `Données du ${dateHeure(synchro)}` : "Données jamais synchronisées"}
          {ancienne && !efface ? " — plus de 24 h : synchronisez dès que possible" : ""}
        </p>
        <div className="actions">
          <button type="button" className="bouton" onClick={() => void lancer()}>
            Synchroniser
          </button>
          <button type="button" className="bouton bouton--lien" onClick={() => setVue({ nom: "code" })}>
            Changer mon code
          </button>
          <button type="button" className="bouton bouton--lien" onClick={() => void deconnecter()}>
            Se déconnecter
          </button>
        </div>
      </header>
      <div aria-live="polite" className="annonce">
        {annonce}
      </div>
      {expiree && identifiant ? (
        <section className="carte" aria-labelledby="titre-reconnexion">
          <h2 id="titre-reconnexion">Reconnexion nécessaire</h2>
          <p>Vos saisies restent sur l'appareil. Saisissez votre mot de passe Windows (le nouveau s'il a changé) pour reprendre les envois.</p>
          <FormulaireConnexion
            identifiantFixe={identifiant}
            onJeton={(nouveau) => {
              void remplacerJeton(cle, nouveau).then(() => {
                setSession({ cle, jeton: nouveau });
                setExpiree(false);
                setAnnonce("Reconnecté : envoi des saisies en cours.");
              });
            }}
          />
        </section>
      ) : null}
      <main>
        {vue.nom === "planning" ? (
          <Planning paquet={paquet} onPointer={(v, m) => void pointer(v, m)} onEtat={(seance) => setVue({ nom: "etat", seance })} onIncident={(seance, site) => setVue({ nom: "incident", seance, site })} />
        ) : null}
        {vue.nom === "code" ? (
          <section className="carte" aria-labelledby="titre-code">
            <h1 id="titre-code">Changer mon code de déverrouillage</h1>
            <ChoixCode
              bouton="Changer le code"
              onCode={async (code) => {
                const nouvelle = await rechiffrer(cle, code, jeton);
                setSession({ cle: nouvelle, jeton });
                setVue({ nom: "planning" });
                setAnnonce("Code de déverrouillage changé.");
              }}
            />
            <button type="button" className="bouton bouton--lien" onClick={() => setVue({ nom: "planning" })}>
              Revenir au planning
            </button>
          </section>
        ) : null}
        {vue.nom === "etat" && paquet ? (
          <EtatDesLieux
            cle={cle}
            seance={vue.seance}
            grille={paquet.grilles[vue.seance.famille] ?? paquet.grilles.commune ?? []}
            onTermine={async (message) => {
              setAnnonce(message);
              setVue({ nom: "planning" });
              await rafraichir();
              void lancer();
            }}
            onAnnuler={() => setVue({ nom: "planning" })}
          />
        ) : null}
        {vue.nom === "incident" ? (
          <FormulaireIncident
            cle={cle}
            seance={vue.seance}
            site={vue.site}
            onTermine={async (message) => {
              setAnnonce(message);
              setVue({ nom: "planning" });
              await rafraichir();
              void lancer();
            }}
            onAnnuler={() => setVue({ nom: "planning" })}
          />
        ) : null}
      </main>
    </div>
  );
}

function Planning({ paquet, onPointer, onEtat, onIncident }: { paquet: Paquet | null; onPointer: (v: Vacation, m: "arrivee" | "depart") => void; onEtat: (s: Seance) => void; onIncident: (s: Seance | null, site: number) => void }) {
  if (!paquet) return <p>Aucune donnée : synchronisez avec le réseau pour recevoir votre planning.</p>;
  if (!paquet.vacations.length) return <p>Aucune vacation prévue dans les 14 prochains jours.</p>;
  return (
    <>
      <h1>
        Bonjour {paquet.agent.prenom} — mes vacations
      </h1>
      <ol className="vacations">
        {paquet.vacations.map((v) => (
          <li key={v.id} className="carte">
            <h2>
              {jour(v.debut)}, {heure(v.debut)} – {heure(v.fin)}
            </h2>
            <p>
              {v.site_nom} — {v.type}
              {v.statut === "a_revoir" ? ` — à revoir : ${v.signalement}` : ""}
            </p>
            <div className="actions">
              <button type="button" className="bouton bouton--grand" onClick={() => onPointer(v, "arrivee")}>
                Pointer mon arrivée<span className="visuellement-masque"> — vacation du {jour(v.debut)}</span>
              </button>
              <button type="button" className="bouton bouton--grand" onClick={() => onPointer(v, "depart")}>
                Pointer mon départ<span className="visuellement-masque"> — vacation du {jour(v.debut)}</span>
              </button>
            </div>
            <ul className="seances">
              {paquet.seances
                .filter((s) => s.vacation === v.id)
                .map((s) => (
                  <li key={s.id}>
                    <p>
                      <strong>
                        {heure(s.debut)} – {heure(s.fin)}
                      </strong>{" "}
                      {s.espace} — {s.usager}
                      {s.activite ? ` (${s.activite})` : ""}
                      {s.effectif ? `, ${s.effectif} pers.` : ""}
                      {s.statut === "annulee" ? " — séance annulée" : ""}
                    </p>
                    {s.materiel.length ? (
                      <p className="aide">
                        Matériel à remettre : {s.materiel.map((m) => `${m.quantite} × ${m.libelle}`).join(", ")}
                      </p>
                    ) : null}
                    {s.referent ? (
                      <p className="aide">
                        Référent : {s.referent.nom}
                        {s.referent.telephone ? (
                          <>
                            {" "}
                            — <a href={`tel:${s.referent.telephone.replace(/\s/g, "")}`}>{s.referent.telephone}</a>
                          </>
                        ) : null}
                      </p>
                    ) : null}
                    <div className="actions">
                      <button type="button" className="bouton" onClick={() => onEtat(s)}>
                        État des lieux<span className="visuellement-masque"> — {s.espace} {heure(s.debut)}</span>
                      </button>
                      <button type="button" className="bouton bouton--secondaire" onClick={() => onIncident(s, v.site)}>
                        Signaler un incident<span className="visuellement-masque"> — {s.espace} {heure(s.debut)}</span>
                      </button>
                    </div>
                  </li>
                ))}
            </ul>
            <button type="button" className="bouton bouton--lien" onClick={() => onIncident(null, v.site)}>
              Incident sans séance sur ce site
            </button>
          </li>
        ))}
      </ol>
    </>
  );
}

async function enregistrerPhotos(cle: CryptoKey, fichiers: FileList | null): Promise<string[]> {
  const identifiants: string[] = [];
  for (const fichier of Array.from(fichiers ?? []).slice(0, 10)) {
    const uuid = crypto.randomUUID();
    await ajouterPhoto(cle, uuid, await compresser(fichier));
    identifiants.push(uuid);
  }
  return identifiants;
}

function EtatDesLieux({ cle, seance, grille, onTermine, onAnnuler }: { cle: CryptoKey; seance: Seance; grille: string[]; onTermine: (m: string) => Promise<void>; onAnnuler: () => void }) {
  // La sortie n'est proposée par défaut qu'en fin de séance (RG-11) : avant, c'est l'état des lieux d'entrée.
  const [moment, setMoment] = useState<"entree" | "sortie">(() => (Date.now() >= new Date(seance.fin).getTime() - 15 * 60_000 ? "sortie" : "entree"));
  const [controles, setControles] = useState<Record<string, boolean>>(Object.fromEntries(grille.map((g) => [g, true])));
  const [observations, setObservations] = useState("");
  const [photos, setPhotos] = useState<FileList | null>(null);
  const [signature, setSignature] = useState<Blob | null>(null);
  const [signataire, setSignataire] = useState("");
  const [erreur, setErreur] = useState<string | null>(null);
  const degats = Object.values(controles).some((v) => !v);
  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    if (degats && observations.trim().length < 5) {
      setErreur("Décrivez les dégâts constatés.");
      return;
    }
    const identifiants = await enregistrerPhotos(cle, photos);
    let idSignature: string | null = null;
    if (signature) {
      idSignature = crypto.randomUUID();
      await ajouterPhoto(cle, idSignature, signature);
    }
    await saisir(
      cle,
      "etat_des_lieux",
      { occurrence: seance.id, moment, constat: degats ? "degats" : "conforme", controles, observations, photos: identifiants, signature: idSignature, signataire, instant: new Date().toISOString() },
      [...identifiants, ...(idSignature ? [idSignature] : [])],
    );
    await onTermine("État des lieux enregistré sur l'appareil : il partira à la prochaine synchronisation.");
  };
  return (
    <form className="carte" onSubmit={(e) => void envoyer(e)}>
      <h1>
        État des lieux — {seance.espace}, {heure(seance.debut)}
      </h1>
      {erreur ? (
        <p className="alerte alerte--erreur" role="alert">
          {erreur}
        </p>
      ) : null}
      <fieldset>
        <legend>Moment</legend>
        <label>
          <input type="radio" name="moment" checked={moment === "entree"} onChange={() => setMoment("entree")} /> Entrée dans les lieux
        </label>
        <label>
          <input type="radio" name="moment" checked={moment === "sortie"} onChange={() => setMoment("sortie")} /> Sortie des lieux
        </label>
      </fieldset>
      <fieldset>
        <legend>Points contrôlés (décochez ce qui ne va pas)</legend>
        {grille.map((g) => (
          <label key={g} className="case">
            <input type="checkbox" checked={controles[g] ?? true} onChange={(e) => setControles({ ...controles, [g]: e.target.checked })} /> {g}
          </label>
        ))}
      </fieldset>
      <div className="champ">
        <label htmlFor="observations">Observations{degats ? " (obligatoires : dégâts constatés)" : ""}</label>
        <textarea id="observations" value={observations} onChange={(e) => setObservations(e.target.value)} rows={4} />
      </div>
      <div className="champ">
        <label htmlFor="photos">Photos (10 au plus)</label>
        <input id="photos" type="file" accept="image/*" capture="environment" multiple onChange={(e) => setPhotos(e.target.files)} />
      </div>
      <Signature onChange={setSignature} />
      <div className="champ">
        <label htmlFor="signataire">Nom du signataire pour l'usager</label>
        <input id="signataire" value={signataire} onChange={(e) => setSignataire(e.target.value)} autoComplete="off" />
      </div>
      <div className="actions">
        <button type="submit" className="bouton bouton--principal bouton--grand">
          Enregistrer l'état des lieux
        </button>
        <button type="button" className="bouton bouton--lien" onClick={onAnnuler}>
          Revenir au planning
        </button>
      </div>
    </form>
  );
}

const NATURES = [
  { valeur: "degradation", libelle: "Dégradation" },
  { valeur: "comportement", libelle: "Comportement" },
  { valeur: "accident", libelle: "Accident ou blessure" },
  { valeur: "technique", libelle: "Problème technique" },
  { valeur: "absence_usager", libelle: "Usager absent" },
  { valeur: "autre", libelle: "Autre" },
];

function FormulaireIncident({ cle, seance, site, onTermine, onAnnuler }: { cle: CryptoKey; seance: Seance | null; site: number; onTermine: (m: string) => Promise<void>; onAnnuler: () => void }) {
  const [nature, setNature] = useState("degradation");
  const [gravite, setGravite] = useState("mineur");
  const [description, setDescription] = useState("");
  const [photos, setPhotos] = useState<FileList | null>(null);
  const envoyer = async (e: FormEvent) => {
    e.preventDefault();
    const identifiants = await enregistrerPhotos(cle, photos);
    await saisir(cle, "incident", { occurrence: seance?.id ?? null, site, nature, gravite, description, photos: identifiants, instant: new Date().toISOString() }, identifiants);
    await onTermine("Incident enregistré sur l'appareil : il partira à la prochaine synchronisation.");
  };
  return (
    <form className="carte" onSubmit={(e) => void envoyer(e)}>
      <h1>Signaler un incident{seance ? ` — ${seance.espace}, ${heure(seance.debut)}` : ""}</h1>
      <div className="champ">
        <label htmlFor="nature">Nature</label>
        <select id="nature" value={nature} onChange={(e) => setNature(e.target.value)}>
          {NATURES.map((n) => (
            <option key={n.valeur} value={n.valeur}>
              {n.libelle}
            </option>
          ))}
        </select>
      </div>
      <div className="champ">
        <label htmlFor="gravite">Gravité</label>
        <select id="gravite" value={gravite} onChange={(e) => setGravite(e.target.value)}>
          <option value="mineur">Mineur</option>
          <option value="majeur">Majeur</option>
          <option value="securite">Sécurité des personnes</option>
        </select>
      </div>
      <div className="champ">
        <label htmlFor="description">Description</label>
        <textarea id="description" required minLength={5} value={description} onChange={(e) => setDescription(e.target.value)} rows={5} />
      </div>
      <div className="champ">
        <label htmlFor="photos-incident">Photos</label>
        <input id="photos-incident" type="file" accept="image/*" capture="environment" multiple onChange={(e) => setPhotos(e.target.files)} />
      </div>
      <div className="actions">
        <button type="submit" className="bouton bouton--principal bouton--grand">
          Enregistrer l'incident
        </button>
        <button type="button" className="bouton bouton--lien" onClick={onAnnuler}>
          Revenir au planning
        </button>
      </div>
    </form>
  );
}
