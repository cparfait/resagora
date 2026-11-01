#!/usr/bin/env node
/**
 * Extraction des données d'exemple de CityResa (prisma/seed-demo.ts) vers le jeu de démonstration de la plateforme,
 * pour comparer les deux applications avec les mêmes données.
 *
 *   node outils/cityresa/extraire.mjs C:/tmp/__DEV__/cityresa
 *
 * Seules les parties « données » du script de CityResa sont exécutées (sites, espaces, tarifs, matériel, usagers,
 * générateur de réservations) dans un dossier temporaire : ni base de données, ni réseau, ni fichier .env. Le dépôt
 * de CityResa n'est que lu.
 *
 * Données personnelles (CLAUDE.md, règle 7) : les associations de CityResa viennent du guide des sports de la Ville
 * et nomment de vraies personnes (présidents, courriels, téléphones). Pour elles, seuls la structure et ses lieux sont
 * repris (nom, activité, site web) ; les personnes, courriels, téléphones et adresses de siège sont retirés et seront
 * remplacés par des contacts fictifs au chargement. Les messages des dossiers (prénoms) sont retirés.
 *
 * Sortie : backend/apps/noyau/demo/cityresa.json
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const depot = resolve(process.argv[2] ?? "../cityresa");
const ici = dirname(fileURLToPath(import.meta.url));
const sortie = resolve(ici, "../../backend/apps/noyau/demo/cityresa.json");

const lire = (chemin) => readFileSync(join(depot, chemin), "utf8");
const relocaliser = (source) => source.replaceAll(/from "@\/lib\/([\w-]+)"/g, 'from "./$1.ts"');

const travail = mkdtempSync(join(tmpdir(), "cityresa-"));
try {
  for (const module of ["date-utc", "paris-time", "creneaux", "constantes", "libelles"]) {
    writeFileSync(join(travail, `${module}.ts`), relocaliser(lire(`src/lib/${module}.ts`)));
  }
  writeFileSync(join(travail, "seed-associations.ts"), lire("prisma/seed-associations.ts"));

  // Parties « données » de seed-demo.ts, repérées par leurs titres de section.
  const lignes = lire("prisma/seed-demo.ts").split("\n");
  const indice = (motif) => {
    const i = lignes.findIndex((l) => l.startsWith(motif));
    if (i < 0) throw new Error(`Section introuvable dans seed-demo.ts : ${motif}`);
    return i;
  };
  const outils = lignes.slice(indice("const MOT_DE_PASSE"), indice("// ── Photos"));
  const donnees = lignes.slice(indice("// ── Sites et espaces ──"), indice("// ── Chargement ──"));
  const programme = [
    'import type { ReservationStatus } from "./constantes.ts";',
    'import type { Recurrence } from "./creneaux.ts";',
    'import { montant, plage } from "./libelles.ts";',
    'import { addParisDays, minutesDe, parisMidnight, parisParts, parisWallToInstant, todayParisISO, toParisWall } from "./paris-time.ts";',
    'import { ASSOCIATIONS_SPORTIVES, type OrgSpec } from "./seed-associations.ts";',
    ...outils,
    ...donnees,
    "process.stdout.write(JSON.stringify({",
    "  reference: todayParisISO(now),",
    "  sites: SITES, espaces: ESPACES, options: OPTIONS_GLOBALES, materiels: MATERIELS,",
    "  usagers: ORGS, associationsDuGuide: ASSOCIATIONS_SPORTIVES.map((o) => o.cle),",
    "  reservations: reservations().map((r) => ({ ...r, ymd: ymd(r.jour) })),",
    "}));",
  ].join("\n");
  writeFileSync(join(travail, "donnees.ts"), programme);
  const brut = JSON.parse(
    execFileSync(process.execPath, ["--no-warnings", join(travail, "donnees.ts")], {
      cwd: travail,
      env: { PATH: process.env.PATH, TZ: "Europe/Paris" },
      maxBuffer: 64 * 1024 * 1024,
    }).toString("utf8"),
  );

  // ── Nettoyage des données personnelles ──
  const duGuide = new Set(brut.associationsDuGuide);
  const adressesPubliques = new Set(brut.sites.map((s) => s.address));
  const telephoneFictif = (rang) => `01 99 ${String(10 + (rang % 90)).padStart(2, "0")} ${String((rang * 7) % 100).padStart(2, "0")} ${String((rang * 13) % 100).padStart(2, "0")}`;
  const usagers = brut.usagers.map((o, rang) => {
    const base = { cle: o.cle, type: o.type, nom: o.name, codePostal: o.postalCode, commune: o.city, valide: o.valide };
    if (duGuide.has(o.cle)) {
      // Personnes réelles : rien n'est repris d'elles. Adresse gardée seulement si c'est un lieu public de la Ville.
      return {
        ...base,
        rna: o.rna ?? "",
        siteWeb: o.website ?? "",
        adresse: adressesPubliques.has(o.address) ? o.address : "",
        contactFictif: true,
      };
    }
    // Usagers inventés par CityResa (domaine exemple.fr) : noms gardés, courriels en .test, téléphones fictifs.
    const courriel = (adresse) => (adresse ?? "").replace(/@[\w.-]+$/, "@exemple.test");
    return {
      ...base,
      siret: (o.siret ?? "").replaceAll(" ", ""),
      rna: o.rna ?? "",
      siteWeb: (o.website ?? "").includes("exemple") ? "" : (o.website ?? ""),
      adresse: o.address ?? "",
      notes: o.notes ?? "",
      contactFictif: false,
      contact: { prenom: o.user.prenom, nom: o.user.nom, courriel: courriel(o.user.email), telephone: telephoneFictif(rang), fonction: o.user.fonction ?? "" },
    };
  });
  const reservations = brut.reservations.map(({ messages, ...r }) => r);

  const resultat = {
    source: "CityResa — prisma/seed-demo.ts et prisma/seed-associations.ts",
    reference: brut.reference,
    sites: brut.sites.map(({ email, phone, ...s }) => s),
    espaces: brut.espaces,
    options: brut.options,
    materiels: brut.materiels,
    usagers,
    reservations,
  };
  writeFileSync(sortie, `${JSON.stringify(resultat, null, 1)}\n`, "utf8");
  console.log(
    `${resultat.sites.length} sites, ${resultat.espaces.length} espaces, ${usagers.length} usagers (dont ${duGuide.size} associations du guide, contacts fictifs), ${reservations.length} réservations → ${sortie}`,
  );
} finally {
  rmSync(travail, { recursive: true, force: true });
}
