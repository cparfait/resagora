import {
  ajouterPhoto,
  ajouterSaisie,
  CodeIncorrect,
  CodeInvalide,
  compterSaisies,
  creerCoffre,
  deverrouiller,
  enregistrerPaquet,
  ESSAIS_MAX,
  identifiantAppareil,
  effacerTout,
  lireMeta,
  lirePaquet,
  lirePhoto,
  listerSaisies,
  marquerSynchronisation,
  ouvrir,
  purgerSiPerime,
  rechiffrer,
  remplacerJeton,
} from "./coffre";

const SAISIE = { uuid: "u-1", type: "pointage" as const, horodatage: "2026-11-10T17:02:00Z", donnees: { vacation: 10, moment: "arrivee" } };
const CODE = "482913";

const texteBrut = async () => {
  const db = await ouvrir();
  const tout = [await db.getAll("file"), await db.get("paquet", "courant"), await db.getAll("photos")];
  return JSON.stringify(tout, (_cle, valeur: unknown) => (valeur instanceof ArrayBuffer ? new TextDecoder().decode(valeur) : valeur));
};

describe("MOB-07 — stockage local chiffré", () => {
  it("chiffre les données au repos et se déverrouille hors ligne avec le seul code", async () => {
    const cle = await creerCoffre(CODE, "gardien01", "jeton-secret");
    await enregistrerPaquet(cle, { agent: "Camille Martin" });
    await ajouterSaisie(cle, SAISIE);
    const brut = await texteBrut();
    expect(brut).not.toContain("Camille");
    expect(brut).not.toContain("arrivee");
    const { cle: rouverte, jeton } = await deverrouiller(CODE);
    expect(jeton).toBe("jeton-secret");
    expect(await lirePaquet(rouverte)).toEqual({ agent: "Camille Martin" });
    expect(await listerSaisies(rouverte)).toEqual([SAISIE]);
  });

  it("refuse un code trop simple ou trop court", async () => {
    await expect(creerCoffre("12345", "gardien01", "jeton")).rejects.toBeInstanceOf(CodeInvalide);
    await expect(creerCoffre("111111", "gardien01", "jeton")).rejects.toBeInstanceOf(CodeInvalide);
    await expect(creerCoffre("123456", "gardien01", "jeton")).rejects.toBeInstanceOf(CodeInvalide);
  });

  it("décompte les codes faux puis efface l'appareil au dixième", async () => {
    const cle = await creerCoffre(CODE, "gardien01", "jeton");
    await ajouterSaisie(cle, SAISIE);
    for (let essai = 1; essai < ESSAIS_MAX; essai++) {
      const refus = await deverrouiller("000999").catch((e: unknown) => e);
      expect(refus).toBeInstanceOf(CodeIncorrect);
      expect((refus as CodeIncorrect).essaisRestants).toBe(ESSAIS_MAX - essai);
    }
    const dernier = (await deverrouiller("000999").catch((e: unknown) => e)) as CodeIncorrect;
    expect(dernier.efface).toBe(true);
    expect(await lireMeta()).toBeUndefined();
    expect(await compterSaisies()).toBe(0);
  });

  it("un bon code remet le compteur d'essais à zéro", async () => {
    await creerCoffre(CODE, "gardien01", "jeton");
    await deverrouiller("000999").catch(() => undefined);
    await deverrouiller(CODE);
    expect((await lireMeta())?.essais_restants).toBe(ESSAIS_MAX);
  });

  it("change de code en rechiffrant tout, sans perdre la file ni les photos", async () => {
    const cle = await creerCoffre(CODE, "gardien01", "ancien");
    await ajouterSaisie(cle, SAISIE);
    await ajouterPhoto(cle, "p-1", new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }));
    await rechiffrer(cle, "730561", "nouveau");
    await expect(deverrouiller(CODE)).rejects.toBeInstanceOf(CodeIncorrect);
    const { cle: nouvelle, jeton } = await deverrouiller("730561");
    expect(jeton).toBe("nouveau");
    expect(await listerSaisies(nouvelle)).toEqual([SAISIE]);
    const photo = await lirePhoto(nouvelle, "p-1");
    if (!photo) throw new Error("photo perdue");
    expect(new Uint8Array(await photo.arrayBuffer())).toEqual(new Uint8Array([1, 2, 3]));
  });

  it("renouvelle la session sans changer le code", async () => {
    const cle = await creerCoffre(CODE, "gardien01", "ancien");
    await remplacerJeton(cle, "renouvele");
    expect((await deverrouiller(CODE)).jeton).toBe("renouvele");
  });

  it("garde l'identifiant de l'appareil au changement de compte (SEC-10)", async () => {
    const identifiant = await identifiantAppareil();
    await creerCoffre(CODE, "gardien01", "jeton");
    await effacerTout();
    expect(await identifiantAppareil()).toBe(identifiant);
  });
});

describe("MOB-08 — purge après 7 jours sans synchronisation", () => {
  it("efface le planning au-delà du délai, garde les saisies non transmises", async () => {
    const synchro = Date.UTC(2026, 10, 1);
    const cle = await creerCoffre(CODE, "gardien01", "jeton", synchro);
    await enregistrerPaquet(cle, { agent: "Camille Martin" });
    await ajouterSaisie(cle, SAISIE);
    await marquerSynchronisation(synchro, 7);
    expect(await purgerSiPerime(synchro + 6 * 86_400_000)).toBe(false);
    expect(await lirePaquet(cle)).not.toBeNull();
    expect(await purgerSiPerime(synchro + 8 * 86_400_000)).toBe(true);
    expect(await lirePaquet(cle)).toBeNull();
    expect(await listerSaisies(cle)).toEqual([SAISIE]);
    expect((await lireMeta())?.planning_efface_le).not.toBeNull();
  });

  it("part de la création du coffre s'il n'a jamais été synchronisé", async () => {
    const creation = Date.UTC(2026, 10, 1);
    const cle = await creerCoffre(CODE, "gardien01", "jeton", creation);
    await enregistrerPaquet(cle, { agent: "Camille Martin" });
    expect(await purgerSiPerime(creation + 8 * 86_400_000)).toBe(true);
    expect(await lirePaquet(cle)).toBeNull();
  });
});
