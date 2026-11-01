import { describe, expect, it } from "vitest";
import { adresseComplete, lienCarte } from "./carte";

const site = { adresse: "12 rue de la Mairie", code_postal: "92320", commune: "Châtillon", latitude: null, longitude: null };

describe("Lien vers la carte d'un site", () => {
  it("POR-03 situe le site par ses coordonnées quand elles sont connues", () => {
    expect(lienCarte({ ...site, latitude: 48.8034, longitude: 2.288 })).toBe(
      "https://www.openstreetmap.org/?mlat=48.803400&mlon=2.288000#map=18/48.803400/2.288000",
    );
  });

  it("POR-03 cherche l'adresse sans coordonnées, et n'invente rien sans adresse", () => {
    expect(lienCarte(site)).toBe("https://www.openstreetmap.org/search?query=12%20rue%20de%20la%20Mairie%2092320%20Ch%C3%A2tillon");
    expect(lienCarte({ ...site, adresse: "" })).toBeNull();
    expect(adresseComplete({ adresse: "", code_postal: "92320", commune: "Châtillon" })).toBe("92320 Châtillon");
  });
});
