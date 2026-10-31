/* Service worker de l'application des gardiens (MOB-01) : l'application s'ouvre sans réseau (mode avion).
 * Écrit à la main (D-011) : coquille mise en cache à l'installation, ressources de l'application mises en cache
 * à la première ouverture, jamais l'API (les données passent par le stockage chiffré de l'application). */
const VERSION = "gardiens-v1";
const COQUILLE = ["/", "/index.html", "/manifest.webmanifest", "/icone.svg"];

// La coquille et les ressources qu'elle référence (scripts et styles construits) sont mises en cache dès
// l'installation : l'application s'ouvre hors ligne même si le gardien perd le réseau juste après l'installation.
async function installer() {
  const cache = await caches.open(VERSION);
  await cache.addAll(COQUILLE);
  const page = await (await fetch("/index.html", { cache: "no-store" })).text();
  const ressources = [...page.matchAll(/(?:src|href)="(\/assets\/[^"]+)"/g)].map((m) => m[1]);
  await cache.addAll(ressources);
}

self.addEventListener("install", (evenement) => {
  evenement.waitUntil(installer());
});

self.addEventListener("activate", (evenement) => {
  evenement.waitUntil(
    caches
      .keys()
      .then((cles) => Promise.all(cles.filter((cle) => cle !== VERSION).map((cle) => caches.delete(cle))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener("message", (evenement) => {
  if (evenement.data === "activer") self.skipWaiting();
});

self.addEventListener("fetch", (evenement) => {
  const requete = evenement.request;
  const url = new URL(requete.url);
  if (requete.method !== "GET" || url.origin !== self.location.origin || url.pathname.startsWith("/api/")) return;
  if (requete.mode === "navigate") {
    // Navigation : réseau d'abord (mise à jour), coquille en cache sans réseau.
    evenement.respondWith(fetch(requete).catch(() => caches.match("/index.html")));
    return;
  }
  // Ressources : cache d'abord, rafraîchies en arrière-plan quand le réseau revient.
  evenement.respondWith(
    caches.match(requete).then((enCache) => {
      const reseau = fetch(requete)
        .then((reponse) => {
          if (reponse.ok) {
            const copie = reponse.clone();
            caches.open(VERSION).then((cache) => cache.put(requete, copie));
          }
          return reponse;
        })
        .catch(() => enCache);
      return enCache || reseau;
    }),
  );
});
