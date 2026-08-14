/* Service worker: skall-cache + Web Push.
 *
 * Tre jobber:
 *   1. Skallet (html/css/js) apner umiddelbart pa mobil, ogsa pa darlig
 *      nett. Data hentes alltid ferskt fra nettet.
 *   2. iOS gir ikke Web Push til en side som ikke er lagt til pa
 *      hjemskjermen, og en installerbar PWA krever service worker.
 *   3. Tar imot push og viser varselet.
 *
 * Regelen for cache er enkel: skallet fra cache, /api/ ALDRI fra cache.
 */
const CACHE = "pokepuls-skall-v24";
const SKALL = ["/", "/style.css?v=24", "/app.js?v=24", "/ikon.svg", "/manifest.webmanifest"];

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
  // Serverrendrede produktsider (/p/...) og sidekartet skal heller ikke
  // caches: de har priser i seg, og en gammel pris er verre enn ingen side.
  if (url.pathname.startsWith("/p/") || url.pathname === "/sitemap.xml") return;

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

/* ------------------------------------------------------------ push */

self.addEventListener("push", (e) => {
  /* Uten data er det en "tom" push (noen tjenester sender slike for a holde
   * abonnementet i live). Vi MA likevel vise et varsel: nettleseren trekker
   * tilbake pushtillatelsen hvis vi tar imot en push uten a vise noe. */
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch (_) { d = {}; }

  const tittel = d.title || "Pokepuls";
  const valg = {
    body: d.body || "Noe har endret seg pa noe du følger.",
    icon: "/ikon-192.png",
    badge: "/ikon-badge.png",
    // Samme tag = nyere varsel om samme vare hos samme butikk erstatter det
    // forrige i stedet for a stable seg opp i varslingssenteret.
    tag: d.tag || "pokepuls",
    renotify: true,
    // Bare restock far a vibrere. Alt annet skal kunne komme mens du sover
    // uten a vekke deg -- se ogsa "stille natt" i overvak/varsler.py.
    silent: !d.hastig,
    vibrate: d.hastig ? [80, 40, 80] : undefined,
    timestamp: Date.now(),
    data: { url: d.url, produkt_url: d.produkt_url },
    actions: d.url ? [
      { action: "butikk", title: "Til butikken" },
      { action: "produkt", title: "Se alle priser" },
    ] : [],
  };
  if (d.bilde) valg.image = d.bilde;

  e.waitUntil(self.registration.showNotification(tittel, valg));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const d = e.notification.data || {};
  // Standardklikk gar til BUTIKKEN. Ved en restock er det sekunder som
  // teller, og et mellomledd er sekunder.
  const mal = e.action === "produkt" ? (d.produkt_url || "/") : (d.url || d.produkt_url || "/");

  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true })
    .then((vinduer) => {
      // Er appen alt apen pa denne siden, loft den frem i stedet for a
      // apne enda en fane.
      for (const v of vinduer) {
        if (v.url === mal && "focus" in v) return v.focus();
      }
      return clients.openWindow(mal);
    }));
});

/* Nettleseren kan bytte ut abonnementet pa egen hand (nokkelrotasjon,
 * gjenoppretting). Skjer det uten at vi sender det nye endepunktet til
 * serveren, slutter varslene stille a komme -- den verste feilmodusen et
 * varslingssystem har. */
self.addEventListener("pushsubscriptionchange", (e) => {
  e.waitUntil((async () => {
    try {
      const gammel = e.oldSubscription;
      const svar = await fetch("/api/push/nokkel");
      const { public_key: nokkel } = await svar.json();
      if (!nokkel) return;
      const ny = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: nokkel,
      });
      // En service worker har ingen localStorage. Vi sporr et aapent vindu
      // om installasjons-id-en; finnes ingen, sender vi uten -- da rydder
      // neste sidebesok opp i stedet.
      let inst = null;
      try {
        const vinduer = await self.clients.matchAll({ type: "window" });
        if (vinduer.length) {
          inst = await new Promise((svar) => {
            const kanal = new MessageChannel();
            kanal.port1.onmessage = (e) => svar(e.data && e.data.installasjon);
            vinduer[0].postMessage({ sporr: "installasjon" }, [kanal.port2]);
            setTimeout(() => svar(null), 500);
          });
        }
      } catch (_) { /* uten id virker abonnementet fortsatt */ }

      await fetch("/api/push/abonner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ ...ny.toJSON(), installasjon: inst }),
      });
      if (gammel) {
        await fetch("/api/push/avmeld", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          body: JSON.stringify({ endpoint: gammel.endpoint }),
        });
      }
    } catch (_) { /* neste sidebesok prover igjen */ }
  })());
});
