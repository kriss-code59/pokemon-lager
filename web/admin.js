/* Pokepuls admin.
 *
 * Samme regler som resten av frontenden: ingen rammeverk, ingen byggesteg.
 * Filen som ligger pa serveren er filen som kjorer.
 *
 * Autorisasjonen ligger IKKE her. Denne filen kan hvem som helst laste ned
 * og lese -- den er bare et grensesnitt. /api/admin/* svarer 404 til alle
 * som ikke har role='admin', og det er der sperren faktisk er.
 */

const API = "/api";
const $ = (s) => document.querySelector(s);

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const kr = (ore) => ore == null ? "–" :
  (ore / 100).toLocaleString("nb-NO", { maximumFractionDigits: 2 }) + " kr";

function nar(iso) {
  if (!iso) return "aldri";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 60) return min + " min siden";
  if (min < 1440) return Math.round(min / 60) + " t siden";
  return Math.round(min / 1440) + " d siden";
}

async function hent(sti, valg) {
  const r = await fetch(API + sti, {
    credentials: "same-origin",
    headers: { Accept: "application/json",
               ...(valg && valg.body ? { "Content-Type": "application/json" } : {}) },
    ...valg,
  });
  const t = await r.text();
  const d = t ? JSON.parse(t) : null;
  if (!r.ok) throw new Error((d && d.detail) || (sti + " svarte " + r.status));
  return d;
}

const state = { fane: "drift", produkter: [], valgtTittel: null };

/* ---------------------------------------------------------------- drift */

async function tegnDrift() {
  const d = await hent("/admin/drift");
  const t = d.tall;
  const siste = d.kjoringer[0];
  const alder = siste ? (Date.now() - new Date(siste.started_at)) / 60000 : Infinity;

  // Det viktigste tallet forst og storst: gaar scraperen? Alt annet pa
  // siden er meningslost hvis svaret er nei.
  //
  // Nattpausen ma med. Scraperen sover 22-04 norsk tid (se
  // deploy/pokepuls-cron-scrape.sh), og uten dette unntaket lyser siden
  // rodt hver eneste natt. En overvaking som roper ulv seks timer i dognet
  // er en overvaking du slutter a se pa -- det var nettopp slik den forrige
  // dodmannsknappen ble ignorert.
  const oslo = Number(new Intl.DateTimeFormat("no", {
    timeZone: "Europe/Oslo", hour: "numeric", hour12: false }).format(new Date()));
  const natt = oslo >= 22 || oslo < 4;

  const helse = natt ? ["ok", "Nattpause (22–04)"]
    : alder < 45 ? ["ok", "Scraperen går"]
    : alder < 180 ? ["gammel", "Scraperen henger etter"]
    : ["nede", "SCRAPEREN STÅR"];

  $("#admin-innhold").innerHTML =
    '<div class="helsekort ' + helse[0] + '"><strong>' + helse[1] + "</strong>" +
      "<span>Siste kjøring " + esc(nar(siste && siste.started_at)) +
      (siste && siste.sekunder ? " · brukte " + Math.round(siste.sekunder / 60) + " min" : "") +
      "</span></div>" +

    '<div class="tallrad">' + [
      ["Brukere", t.brukere], ["Abonnementer", t.abonnementer],
      ["Push-enheter", t.enheter],
      ["Varsler 24t", (d.varsler_24t && d.varsler_24t.sendt) || 0],
      ["Oppføringer", t.oppforinger], ["Umatchet", t.umatchet],
      ["Med bilde", t.med_bilde],
    ].map(([n, v]) => '<div class="talle"><b>' + esc(v) + "</b><span>" +
      esc(n) + "</span></div>").join("") + "</div>" +

    "<h2>Hendelser siste døgn</h2><div class=\"tallrad\">" +
      ["restock", "ny", "prisendring", "utsolgt"].map((k) =>
        '<div class="talle"><b>' + esc(d.hendelser_24t[k] || 0) + "</b><span>" +
        esc(k) + "</span></div>").join("") + "</div>" +

    "<h2>Kjøringer</h2><div class=\"tabell\">" +
      d.kjoringer.map((k) =>
        '<div class="rad' + (k.ok ? "" : " feil") + '">' +
        "<span>" + esc(nar(k.started_at)) + "</span>" +
        "<span>" + esc(k.product_count ?? "–") + " varer</span>" +
        "<span>" + esc(k.store_count ?? "–") + " butikker</span>" +
        "<span>" + (k.sekunder ? Math.round(k.sekunder / 60) + " min" : "uferdig") + "</span>" +
        "<span>" + ((k.failed_stores || []).length
          ? "feilet: " + esc((k.failed_stores || []).join(", "))
          : (k.carried_stores || []).length
            ? "fremført: " + esc((k.carried_stores || []).join(", "))
            : "ok") + "</span></div>").join("") + "</div>" +

    "<h2>Butikker</h2><div class=\"tabell\">" +
      d.butikker.map((b) =>
        '<div class="rad' + (b.oppforinger ? "" : " feil") + '">' +
        "<span><b>" + esc(b.name) + "</b></span>" +
        "<span>" + esc(b.oppforinger) + " varer</span>" +
        "<span>" + esc(b.pa_lager) + " inne</span>" +
        "<span>" + esc(b.umatchet) + " umatchet</span>" +
        "<span>" + esc(nar(b.sist_ok)) + "</span></div>").join("") + "</div>";
}

/* -------------------------------------------------------------- brukere */

async function tegnBrukere() {
  const d = await hent("/admin/users");
  $("#admin-innhold").innerHTML =
    '<p class="hjelp">' + d.brukere.length + " registrerte brukere. " +
    "Klikk en rad for å se hva de følger.</p>" +
    '<div class="tabell">' + d.brukere.map((u) =>
      '<div class="rad klikkbar" data-bruker="' + esc(u.id) + '">' +
      "<span><b>" + esc(u.email) + "</b>" +
        (u.role !== "free" ? ' <span class="merkelapp">' + esc(u.role) + "</span>" : "") +
      "</span>" +
      "<span>" + esc(u.folger) + " følger</span>" +
      "<span>" + esc(u.enheter) + " enheter</span>" +
      "<span>" + esc(u.varsler_30d) + " varsler/30d</span>" +
      "<span>sist inne " + esc(nar(u.last_login_at)) + "</span></div>").join("") + "</div>" +
    '<div id="bruker-detalj"></div>';

  for (const rad of document.querySelectorAll("[data-bruker]")) {
    rad.addEventListener("click", () => visBruker(rad.dataset.bruker));
  }
}

async function visBruker(id) {
  const boks = $("#bruker-detalj");
  boks.innerHTML = '<p class="hjelp">Laster…</p>';
  const d = await hent("/admin/users/" + encodeURIComponent(id));
  boks.innerHTML =
    "<h2>" + esc(d.bruker.email) + "</h2>" +
    '<p class="hjelp">Rolle: ' +
      ["free", "premium", "admin"].map((r) =>
        '<button class="chip' + (d.bruker.role === r ? " pa" : "") +
        '" data-rolle="' + r + '">' + r + "</button>").join(" ") + "</p>" +

    "<h3>Følger (" + d.folger.length + ")</h3>" +
    (d.folger.length ? '<div class="tabell">' + d.folger.map((f) =>
        '<div class="rad"><span>' + esc(f.set_label || f.set_id || "?") + "</span>" +
        "<span>" + esc(f.type_label || "hele settet") + "</span>" +
        "<span>" + esc(f.region || "") + "</span>" +
        "<span>" + esc((f.kinds || []).join(", ")) + "</span></div>").join("") + "</div>"
      : '<p class="hjelp">Ingenting.</p>') +

    "<h3>Enheter (" + d.enheter.length + ")</h3>" +
    (d.enheter.length ? '<div class="tabell">' + d.enheter.map((e) =>
        '<div class="rad' + (e.feil_pa_rad ? " feil" : "") + '">' +
        '<span class="ua">' + esc((e.user_agent || "").slice(0, 60)) + "</span>" +
        "<span>lagt til " + esc(nar(e.created_at)) + "</span>" +
        "<span>sist ok " + esc(nar(e.last_ok_at)) + "</span>" +
        "<span>" + (e.feil_pa_rad ? esc(e.feil_pa_rad) + " feil" : "") + "</span></div>")
        .join("") + "</div>"
      : '<p class="hjelp">Ingen push-enheter — brukeren får ingen varsler.</p>') +

    "<h3>Siste varsler</h3>" +
    (d.varsler.length ? '<div class="tabell">' + d.varsler.map((v) =>
        '<div class="rad' + (v.ok ? "" : " feil") + '">' +
        "<span>" + esc(nar(v.sendt_at)) + "</span>" +
        "<span>" + esc(v.kind) + "</span>" +
        "<span>" + esc(v.store_id) + "</span>" +
        "<span>" + esc(kr(v.price_ore)) + "</span>" +
        "<span>" + esc(v.ok ? "" : v.feil || "feilet") + "</span></div>").join("") + "</div>"
      : '<p class="hjelp">Ingen sendt ennå.</p>');

  for (const b of boks.querySelectorAll("[data-rolle]")) {
    b.addEventListener("click", async () => {
      try {
        await hent("/admin/role", { method: "POST",
          body: JSON.stringify({ user_id: id, role: b.dataset.rolle }) });
        await tegnBrukere();
        visBruker(id);
      } catch (e) { alert(e.message); }
    });
  }
  boks.scrollIntoView({ behavior: "smooth", block: "start" });
}

/* -------------------------------------------------------------- katalog */

async function tegnKatalog() {
  $("#admin-innhold").innerHTML =
    '<p class="hjelp">Umatchede varer, gruppert på tittel og sortert på hvor ' +
    "mange butikker som selger den. Øverst i listen ligger det som gir mest " +
    "dekning per kobling.</p>" +
    '<input id="sok-umatchet" class="admin-sok" type="search" placeholder="Filtrer titler…">' +
    '<div id="umatchet-liste"><p class="hjelp">Laster…</p></div>';

  if (!state.produkter.length) {
    state.produkter = (await hent("/admin/produkter")).produkter;
  }
  $("#sok-umatchet").addEventListener("input", (e) => lastUmatchet(e.target.value));
  await lastUmatchet("");
}

async function lastUmatchet(q) {
  const d = await hent("/admin/umatchet?limit=300" + (q ? "&q=" + encodeURIComponent(q) : ""));
  $("#umatchet-liste").innerHTML = d.varer.length
    ? d.varer.map((v, i) =>
        '<div class="umatchet" data-i="' + i + '">' +
          '<div class="umatchet-topp">' +
            (v.bilde ? '<img src="' + esc(v.bilde) + '" alt="" loading="lazy">' : "") +
            "<div><b>" + esc(v.title) + "</b>" +
            '<span class="hjelp liten">' + esc(v.butikker) + " butikk" +
              (v.butikker > 1 ? "er" : "") + " · fra " + esc(kr(v.min_pris)) +
              (v.noen_inne ? " · på lager" : "") + "</span></div>" +
          "</div>" +
          '<div class="umatchet-verktoy">' +
            '<input class="koble-sok" placeholder="Søk etter produkt…" ' +
              'data-tittel="' + esc(v.title) + '">' +
            '<div class="koble-treff"></div>' +
          "</div></div>").join("")
    : '<p class="hjelp">Ingen umatchede varer. Det er en god dag.</p>';

  for (const felt of document.querySelectorAll(".koble-sok")) {
    felt.addEventListener("input", () => visTreff(felt));
  }
}

function visTreff(felt) {
  const q = felt.value.trim().toLowerCase();
  const boks = felt.parentElement.querySelector(".koble-treff");
  if (q.length < 2) return (boks.innerHTML = "");
  const ord = q.split(/\s+/);
  const treff = state.produkter.filter((p) => {
    const s = (p.set_label + " " + p.type_label + " " + p.region).toLowerCase();
    return ord.every((o) => s.includes(o));
  }).slice(0, 8);

  boks.innerHTML = treff.length
    ? treff.map((p) => '<button class="chip" data-produkt="' + esc(p.id) + '">' +
        esc(p.set_label) + " · " + esc(p.type_label) +
        (p.region !== "en" ? " · " + esc(p.region) : "") + "</button>").join("")
    : '<span class="hjelp liten">Ingen treff.</span>';

  for (const b of boks.querySelectorAll("[data-produkt]")) {
    b.addEventListener("click", async () => {
      b.disabled = true;
      try {
        const svar = await hent("/admin/koble", { method: "POST",
          body: JSON.stringify({ title: felt.dataset.tittel,
                                 product_id: b.dataset.produkt }) });
        const kort = felt.closest(".umatchet");
        kort.classList.add("koblet");
        kort.querySelector(".umatchet-verktoy").innerHTML =
          '<span class="ok">✓ Koblet ' + esc(svar.koblet) + " oppføringer</span>";
      } catch (e) {
        alert(e.message);
        b.disabled = false;
      }
    });
  }
}

/* ---------------------------------------------------------------- faner */

async function tegn() {
  const boks = $("#admin-innhold");
  boks.innerHTML = '<p class="hjelp">Laster…</p>';
  try {
    if (state.fane === "drift") await tegnDrift();
    else if (state.fane === "brukere") await tegnBrukere();
    else await tegnKatalog();
  } catch (e) {
    // 404 fra /api/admin/* betyr «du er ikke admin» -- endepunktene later
    // som de ikke finnes for alle andre. Si det rett ut her, ellers ser det
    // ut som en feil i siden.
    boks.innerHTML = /404|401/.test(e.message)
      ? '<p class="tom">Du må være logget inn som admin.<br>' +
        '<a class="hovedknapp smal" href="/">Til forsiden</a></p>'
      : '<p class="tom">' + esc(e.message) + "</p>";
  }
}

for (const b of document.querySelectorAll("#admin-faner .chip")) {
  b.addEventListener("click", () => {
    state.fane = b.dataset.fane;
    for (const x of document.querySelectorAll("#admin-faner .chip"))
      x.classList.toggle("pa", x === b);
    tegn();
  });
}
$("#oppdater").addEventListener("click", tegn);
tegn();
