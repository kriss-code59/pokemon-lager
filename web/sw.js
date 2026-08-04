/* Minimal service worker.
 *
 * To grunner til at den finnes allerede na, for vi har push:
 *   1. iOS gir ikke Web Push til en side som ikke er lagt til pa
 *      hjemskjermen, og en installerbar PWA krever service worker.
 *   2. Skallet (html/css/js) skal apne umiddelbart pa mobil, ogsa pa
 *      darlig nett. Data hentes alltid ferskt fra nettet.
 *
 * Regelen er enkel: skallet fra cache, /api/ ALDRI fra cache.
 */
const CACHE = "pokepuls-skall-v2";
const SKALL = ["/", "/style.css?v=2", "/app.js?v=2", "/ikon.svg", "/manifest.webmanifest"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(SKALL)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((n) => Promise.all(n.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== location.origin) return;
  if (url.pathname.startsWith("/api/")) return;   // data skal alltid vaere ferske

  e.respondWith(
    fetch(e.request)
      .then((svar) => {
        if (svar.ok) {
          const kopi = svar.clone();
          caches.open(CACHE).then((c) => c.put(e.request, kopi));
        }
        return svar;
      })
      .catch(() => caches.match(e.request).then((t) => t || caches.match("/")))
  );
});
