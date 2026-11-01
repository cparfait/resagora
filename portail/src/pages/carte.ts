/**
 * REF-01, POR-03 : lien vers la carte OpenStreetMap d'un site. Aucune carte n'est chargée dans le portail
 * (pas de ressource tierce, CSP stricte) : l'usager choisit d'ouvrir le service de cartographie.
 */
interface Situation {
  adresse: string;
  code_postal: string;
  commune: string;
  latitude: number | null;
  longitude: number | null;
}

const OSM = "https://www.openstreetmap.org";

export function adresseComplete(s: Pick<Situation, "adresse" | "code_postal" | "commune">): string {
  return [s.adresse, s.code_postal, s.commune].filter(Boolean).join(" ").trim();
}

export function lienCarte(s: Situation): string | null {
  if (s.latitude !== null && s.longitude !== null && Number.isFinite(s.latitude) && Number.isFinite(s.longitude)) {
    const lat = s.latitude.toFixed(6);
    const lon = s.longitude.toFixed(6);
    return `${OSM}/?mlat=${lat}&mlon=${lon}#map=18/${lat}/${lon}`;
  }
  const adresse = adresseComplete(s);
  return s.adresse ? `${OSM}/search?query=${encodeURIComponent(adresse)}` : null;
}
