import { ajouterPhoto, compterSaisies, creerCoffre, lireMeta, lirePaquet } from "./coffre";
import { ReseauIndisponible, saisir, SessionExpiree, synchroniser } from "./synchro";
import { fauxServeur, PAQUET } from "./test/serveur";

describe("MOB-05 — file d'envoi et synchronisation", () => {
  it("envoie les photos puis les saisies, vide la file après accusé et rafraîchit le paquet", async () => {
    const cle = await creerCoffre("482913", "gardien01", "jeton-1");
    await ajouterPhoto(cle, "photo-1", new Blob([new Uint8Array([9])], { type: "image/jpeg" }));
    const etat = await saisir(cle, "etat_des_lieux", { occurrence: 100, constat: "degats" }, ["photo-1"]);
    await saisir(cle, "pointage", { vacation: 10, moment: "arrivee" });
    const serveur = fauxServeur({
      accuse: (uuid) => (uuid === etat.uuid ? { uuid, statut: "conflit", message: "Séance annulée entre-temps." } : { uuid, statut: "acceptee", message: "" }),
    });
    const bilan = await synchroniser(cle, "jeton-1", serveur.f);
    const chemins = serveur.appels.map((a) => a.chemin);
    expect(chemins.indexOf("/api/mobile/photos")).toBeLessThan(chemins.indexOf("/api/mobile/saisies"));
    expect(serveur.appels.filter((a) => a.chemin !== "/api/mobile/sante").every((a) => a.autorisation === "Appareil jeton-1")).toBe(true);
    const envoi = serveur.appels.find((a) => a.chemin === "/api/mobile/saisies")?.corps as { saisies: { uuid: string }[] };
    expect(envoi.saisies.map((s) => s.uuid)).toContain(etat.uuid);
    expect(envoi.saisies[0]).not.toHaveProperty("photos");
    expect(bilan.envoyees).toBe(2);
    expect(bilan.conflits.map((c) => c.message)).toEqual(["Séance annulée entre-temps."]);
    expect(await compterSaisies()).toBe(0);
    expect(await lirePaquet(cle)).toEqual(PAQUET);
    expect((await lireMeta())?.derniere_synchronisation).not.toBeNull();
  });

  it("garde la file intacte sans réseau", async () => {
    const cle = await creerCoffre("482913", "gardien01", "jeton-1");
    await saisir(cle, "pointage", { vacation: 10, moment: "depart" });
    const serveur = fauxServeur({ enLigne: () => false });
    await expect(synchroniser(cle, "jeton-1", serveur.f)).rejects.toBeInstanceOf(ReseauIndisponible);
    expect(await compterSaisies()).toBe(1);
  });

  it("garde la file intacte si la session a expiré", async () => {
    const cle = await creerCoffre("482913", "gardien01", "jeton-1");
    await saisir(cle, "incident", { site: 1, description: "Vitre fissurée" });
    const serveur = fauxServeur({ session: () => false });
    await expect(synchroniser(cle, "jeton-1", serveur.f)).rejects.toBeInstanceOf(SessionExpiree);
    expect(await compterSaisies()).toBe(1);
  });
});

describe("MOB-05 — photo refusée", () => {
  it("écarte la photo refusée et envoie quand même la saisie", async () => {
    const cle = await creerCoffre("482913", "gardien01", "jeton-1");
    await ajouterPhoto(cle, "photo-refusee", new Blob([new Uint8Array([1])], { type: "image/jpeg" }));
    await saisir(cle, "incident", { site: 1, description: "Vitre fissurée" }, ["photo-refusee"]);
    const serveur = fauxServeur();
    const refus: typeof fetch = async (entree, init) =>
      String(entree) === "/api/mobile/photos" ? new Response(JSON.stringify({ code: "format_refuse" }), { status: 422 }) : serveur.f(entree, init);
    const bilan = await synchroniser(cle, "jeton-1", refus);
    expect(bilan.envoyees).toBe(1);
    expect(bilan.rejets.some((r) => r.message.includes("photo"))).toBe(true);
    expect(await compterSaisies()).toBe(0);
  });
});
