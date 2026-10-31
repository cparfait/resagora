import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./App";
import { ajouterSaisie, compterSaisies, creerCoffre, deverrouiller, enregistrerPaquet, marquerSynchronisation } from "./coffre";
import { fauxServeur, PAQUET } from "./test/serveur";

const CODE = "482913";
type Utilisateur = ReturnType<typeof userEvent.setup>;

async function preparer(synchronise: number) {
  const cle = await creerCoffre(CODE, "gardien01", "jeton", synchronise);
  await enregistrerPaquet(cle, PAQUET);
  await marquerSynchronisation(synchronise, 7);
  return cle;
}

async function deverrouillerEcran() {
  const utilisateur = userEvent.setup();
  render(<App />);
  await utilisateur.type(await screen.findByLabelText("Code de déverrouillage"), CODE);
  await utilisateur.click(screen.getByRole("button", { name: "Déverrouiller" }));
  return utilisateur;
}

async function premiereConnexion(utilisateur: Utilisateur) {
  await utilisateur.type(await screen.findByLabelText("Identifiant"), "gardien01");
  await utilisateur.type(screen.getByLabelText("Mot de passe"), "Mot-de-passe-1");
  await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));
}

async function choisirCode(utilisateur: Utilisateur, code = CODE) {
  await utilisateur.type(await screen.findByLabelText("Code de déverrouillage"), code);
  await utilisateur.type(screen.getByLabelText("Confirmez le code"), code);
  await utilisateur.click(screen.getByRole("button", { name: "Enregistrer le code" }));
}

describe("Application des gardiens", () => {
  it("MOB-01 : première connexion, choix du code, planning reçu puis pointage hors ligne mis en file", async () => {
    let enLigne = true;
    const serveur = fauxServeur({ enLigne: () => enLigne });
    vi.stubGlobal("fetch", serveur.f);
    const utilisateur = userEvent.setup();
    render(<App />);
    await premiereConnexion(utilisateur);
    const connexion = serveur.appels.find((a) => a.chemin === "/api/mobile/auth/connexion");
    expect(connexion?.corps).toMatchObject({ appareil_id: expect.stringMatching(/^[0-9a-f-]{36}$/) });
    await choisirCode(utilisateur);
    expect(await screen.findByRole("heading", { name: /Bonjour Camille/ })).toBeInTheDocument();
    expect(screen.getByText(/Club de basket/)).toBeInTheDocument();
    enLigne = false;
    const [arrivee] = screen.getAllByRole("button", { name: /Pointer mon arrivée/ });
    if (!arrivee) throw new Error("bouton absent");
    await utilisateur.click(arrivee);
    await waitFor(async () => expect(await compterSaisies()).toBe(1));
    expect(await screen.findByText(/1 saisie en attente/)).toBeInTheDocument();
  });

  it("MOB-07 : le code de déverrouillage ne peut pas être trop simple", async () => {
    vi.stubGlobal("fetch", fauxServeur().f);
    const utilisateur = userEvent.setup();
    render(<App />);
    await premiereConnexion(utilisateur);
    await choisirCode(utilisateur, "111111");
    expect(await screen.findByRole("alert")).toHaveTextContent("trop simple");
  });

  it("MOB-01 : seconde étape TOTP quand le serveur l'exige", async () => {
    vi.stubGlobal("fetch", fauxServeur({ totp: true }).f);
    const utilisateur = userEvent.setup();
    render(<App />);
    await premiereConnexion(utilisateur);
    await utilisateur.type(await screen.findByLabelText("Code de l'application d'authentification"), "123456");
    await utilisateur.click(screen.getByRole("button", { name: "Valider le code" }));
    await choisirCode(utilisateur);
    expect(await screen.findByRole("heading", { name: /Bonjour Camille/ })).toBeInTheDocument();
  });

  it("MOB-02 : sans réseau, l'application se déverrouille et affiche le planning local, avec alerte de fraîcheur", async () => {
    await preparer(Date.now() - 30 * 3_600_000);
    vi.stubGlobal("fetch", fauxServeur({ enLigne: () => false }).f);
    await deverrouillerEcran();
    expect(await screen.findByText(/Grande salle — Club de basket/)).toBeInTheDocument();
    expect(await screen.findByText(/plus de 24 h/)).toBeInTheDocument();
    expect(await screen.findByText(/Hors ligne/)).toBeInTheDocument();
  });

  it("MOB-08 : à l'ouverture après 7 jours, le planning est effacé mais les saisies restent", async () => {
    const cle = await preparer(Date.now() - 8 * 86_400_000);
    await ajouterSaisie(cle, { uuid: "s-1", type: "pointage", horodatage: "2026-11-10T17:00:00Z", donnees: { vacation: 10, moment: "arrivee" } });
    vi.stubGlobal("fetch", fauxServeur({ enLigne: () => false }).f);
    render(<App />);
    expect(await screen.findByText(/le planning a été effacé de l'appareil/)).toBeInTheDocument();
    expect(await screen.findByText(/1 saisie pas encore transmise/)).toBeInTheDocument();
    expect(await compterSaisies()).toBe(1);
  });

  it("MOB-03 : un état des lieux avec dégâts exige une description puis part en file", async () => {
    await preparer(Date.now());
    vi.stubGlobal("fetch", fauxServeur({ enLigne: () => false }).f);
    const utilisateur = await deverrouillerEcran();
    await utilisateur.click(await screen.findByRole("button", { name: /État des lieux/ }));
    await utilisateur.click(screen.getByLabelText("Filets en place"));
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer l'état des lieux" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Décrivez les dégâts");
    await utilisateur.type(screen.getByLabelText(/Observations/), "Filet de basket arraché");
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer l'état des lieux" }));
    expect(await screen.findByText(/État des lieux enregistré sur l'appareil/)).toBeInTheDocument();
    expect(await compterSaisies()).toBe(1);
  });

  it("MOB-04 : un incident saisi hors ligne part en file", async () => {
    await preparer(Date.now());
    vi.stubGlobal("fetch", fauxServeur({ enLigne: () => false }).f);
    const utilisateur = await deverrouillerEcran();
    await utilisateur.click(await screen.findByRole("button", { name: /Signaler un incident/ }));
    await utilisateur.selectOptions(screen.getByLabelText("Gravité"), "majeur");
    await utilisateur.type(screen.getByLabelText("Description"), "Fuite d'eau vestiaire");
    await utilisateur.click(screen.getByRole("button", { name: "Enregistrer l'incident" }));
    expect(await screen.findByText(/Incident enregistré sur l'appareil/)).toBeInTheDocument();
    expect(await compterSaisies()).toBe(1);
  });

  it("MOB-05 : session expirée, reconnexion par le mot de passe de l'annuaire sans perte des saisies", async () => {
    const cle = await preparer(Date.now());
    await ajouterSaisie(cle, { uuid: "s-1", type: "pointage", horodatage: "2026-11-10T17:00:00Z", donnees: { vacation: 10, moment: "arrivee" } });
    let session = false;
    vi.stubGlobal("fetch", fauxServeur({ session: () => session }).f);
    const utilisateur = await deverrouillerEcran();
    expect(await screen.findByRole("heading", { name: "Reconnexion nécessaire" })).toBeInTheDocument();
    session = true;
    await utilisateur.type(screen.getByLabelText("Mot de passe"), "Nouveau-mot-de-passe-2");
    await utilisateur.click(screen.getByRole("button", { name: "Se connecter" }));
    await waitFor(async () => expect(await compterSaisies()).toBe(0));
    expect((await deverrouiller(CODE)).jeton).toMatch(/^jeton-/);
  });

  it("refuse un code erroné au déverrouillage et indique les essais restants", async () => {
    await creerCoffre(CODE, "gardien01", "jeton");
    vi.stubGlobal("fetch", fauxServeur({ enLigne: () => false }).f);
    const utilisateur = userEvent.setup();
    render(<App />);
    await utilisateur.type(await screen.findByLabelText("Code de déverrouillage"), "000999");
    await utilisateur.click(screen.getByRole("button", { name: "Déverrouiller" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Il reste 9 essais");
  });
});
