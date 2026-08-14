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
  // Ingen nattunntak: scraperen gar dognet rundt na, sa gult kl. 02 betyr
  // det samme som gult kl. 14.
  const helse = alder < 45 ? ["ok", "Scraperen går"]
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
  let t = null;
  try { t = await hent("/admin/premium/telling"); } catch (e) { /* eldre server */ }
  $("#admin-innhold").innerHTML =
    (t ? '<div class="tallrad">' + [
      ["Brukere", t.brukere], ["Premium", t.premium],
      ["Betalende", t.betalende], ["Gratis gitt", t.gratis],
      // Kampanjen: 50 gratisplasser. Naar de er brukt opp, skal det staa
      // her og ikke i hodet ditt.
      ["Igjen av 50", Math.max(0, 50 - Number(t.gratis))],
    ].map(([n, v]) => '<div class="talle"><b>' + esc(v) + "</b><span>" +
      esc(n) + "</span></div>").join("") + "</div>" : "") +
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

    // Egen knapp, ikke bare rollen. Rollen alene er ikke nok: er_premium()
    // krever ogsaa at premium_until er NULL eller i framtiden, og en gammel
    // dato fra et utlopt abonnement ville staatt igjen og gjort gaven
    // virkningslos.
    (d.bruker.role === "admin" ? "" :
      '<p class="hjelp">' +
      (d.bruker.role === "premium"
        ? '<button class="chip pa" id="premium-av">Ta bort premium</button>' +
          '<span class="hjelp liten"> ' +
          (d.bruker.premium_until
            ? "Betalt ut " + esc(new Date(d.bruker.premium_until)
                .toLocaleDateString("nb-NO"))
            : "Gratis, uten utløp") + "</span>"
        : '<button class="chip" id="premium-pa">Gi gratis premium</button>') +
      '</p><p class="feil" id="premium-feil" hidden></p>') +

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

  const premium = async (gi, knapp) => {
    knapp.disabled = true;
    const feil = $("#premium-feil");
    feil.hidden = true;
    try {
      const r = await hent("/admin/premium", { method: "POST",
        body: JSON.stringify({ user_id: id, gi }) });
      // Advarselen er ikke en feil -- den er informasjon du trenger. Tar du
      // premium fra noen som BETALER, fortsetter Stripe aa trekke dem, og
      // neste webhook setter rollen tilbake. Da maa abonnementet sies opp
      // hos Stripe, ikke her.
      if (r.advarsel) alert(r.advarsel);
      await tegnBrukere();
      visBruker(id);
    } catch (e) {
      feil.textContent = e.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  };
  const pa = $("#premium-pa");
  if (pa) pa.addEventListener("click", () => premium(true, pa));
  const av = $("#premium-av");
  if (av) av.addEventListener("click", () => premium(false, av));
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

/* ------------------------------------------------------------- feedback */

const FB_STATUS = ["ny", "lest", "gjort", "avvist"];
const FB_SLAG = { feil: "Feil", onske: "Ønske", butikk: "Butikk", annet: "Annet" };

async function tegnFeedback() {
  const d = await hent("/admin/feedback");
  const a = d.antall || {};

  $("#admin-innhold").innerHTML =
    '<div class="tallrad">' + FB_STATUS.map((k) =>
      '<div class="talle"><b>' + esc(a[k] || 0) + "</b><span>" + esc(k) +
      "</span></div>").join("") + "</div>" +
    (d.meldinger.length
      ? d.meldinger.map((m) => fbKort(m)).join("")
      : '<p class="hjelp">Ingen tilbakemeldinger ennå.</p>');

  for (const b of document.querySelectorAll("[data-fb-status]")) {
    b.addEventListener("click", async () => {
      const [id, status] = b.dataset.fbStatus.split(":");
      try {
        await hent("/admin/feedback/" + id, { method: "POST",
          body: JSON.stringify({ status }) });
        await tegnFeedback();
      } catch (e) { alert(e.message); }
    });
  }
  for (const felt of document.querySelectorAll("[data-fb-notat]")) {
    // Lagre naar feltet forlates, ikke ved hvert tastetrykk: ett kall i
    // stedet for femti, og ingen halvskrevne notater i databasen.
    felt.addEventListener("blur", () => {
      hent("/admin/feedback/" + felt.dataset.fbNotat, { method: "POST",
        body: JSON.stringify({ notat: felt.value }) }).catch(() => {});
    });
  }
}

function fbKort(m) {
  return '<div class="umatchet' + (m.status === "ny" ? " ny" : "") + '">' +
    '<div class="fb-topp">' +
      '<span class="merkelapp">' + esc(FB_SLAG[m.slag] || m.slag) + "</span>" +
      "<b>" + esc(m.epost || "ukjent") + "</b>" +
      (m.slettet_konto ? ' <span class="hjelp liten">(slettet konto)</span>' : "") +
      '<span class="hjelp liten"> · ' + esc(nar(m.created_at)) +
      (m.side ? " · fra «" + esc(m.side) + "»" : "") + "</span>" +
    "</div>" +
    // pre-wrap, ikke innerHTML-formatering: teksten kommer fra en bruker og
    // skal vises som tekst, med linjeskiftene deres i behold.
    '<p class="fb-tekst">' + esc(m.tekst) + "</p>" +
    '<div class="koble-treff">' + FB_STATUS.map((k) =>
      '<button class="chip' + (m.status === k ? " pa" : "") +
      '" data-fb-status="' + m.id + ":" + k + '">' + k + "</button>").join("") +
    "</div>" +
    '<input class="koble-sok" style="margin-top:8px" placeholder="Notat til deg selv…" ' +
      'data-fb-notat="' + m.id + '" value="' + esc(m.notat || "") + '">' +
    "</div>";
}

/* ------------------------------------------------------------------ bruk */

/* Ett spoersmaal, ikke en analysepakke: VIRKER DET AA BE FOLK INSTALLERE?
 *
 * Derfor staar andelen installert stoerst og forst, og resten er en tabell
 * du kan la vaere aa lese. Andelen regnes over 30 dager samlet fordi en
 * dagsandel er stoy naar trafikken er liten -- to iPhone-brukere fra eller
 * til flytter den ti prosentpoeng.
 *
 * Tallet er aapninger, ikke mennesker. Frontenden melder én gang per
 * fane-oekt, saa den som aapner appen tre ganger om dagen teller tre. Det
 * staar i teksten under fordi et tall uten enhet blir husket feil. */
const apning = (n) => (n === 1 ? "åpning" : "åpninger");

async function tegnBruk() {
  const d = await hent("/admin/bruk");
  const alle = Number(d.sum30.alle) || 0;
  const inst = Number(d.sum30.installert) || 0;
  const andel = alle ? Math.round((inst / alle) * 100) : 0;

  // Dagene slaas sammen paa tvers av sider, men holdes delt paa standalone
  // -- det er hele skillet fanen finnes for.
  const dager = new Map();
  for (const r of d.rader) {
    const rad = dager.get(r.dag) || { installert: 0, nett: 0 };
    rad[r.standalone ? "installert" : "nett"] += Number(r.antall) || 0;
    dager.set(r.dag, rad);
  }

  // Under 50 aapninger far kortet ingen farge. En andel regnet paa fem
  // besok er stoy, og et rodt kort som egentlig betyr «for lite data» er
  // verre enn ingen farge: det larer deg aa overse kortet.
  const nok = alle >= 50;
  const farge = !nok ? "" : andel >= 25 ? " ok" : andel >= 10 ? " gammel" : " nede";

  $("#admin-innhold").innerHTML =
    (alle
      ? '<div class="helsekort' + farge + '"><strong>' + andel +
        " % åpner fra hjemskjermen</strong>" +
        "<span>" + inst.toLocaleString("nb-NO") + " av " +
        alle.toLocaleString("nb-NO") + " " + apning(alle) + " siste 30 dager" +
        (nok ? "" : " · for lite til å si noe ennå") + "</span></div>"
      : '<p class="tom">Ingen åpninger registrert ennå. Tabellen fylles fra ' +
        "første besøk etter at dette ble deployet.</p>") +

    '<p class="hjelp">Én åpning per fane-økt, ikke per menneske: den som ' +
    "åpner appen tre ganger om dagen teller tre. Ingen IP, ingen bruker-id, " +
    "ingen informasjonskapsel — bare dato, side og om den lå på " +
    "hjemskjermen.</p>" +

    (dager.size
      ? "<h2>Per dag</h2><div class=\"tabell\">" +
        [...dager.entries()].map(([dag, r]) => {
          const sum = r.installert + r.nett;
          return '<div class="rad"><span><b>' + esc(dag) + "</b></span>" +
            "<span>" + esc(sum) + " " + apning(sum) + "</span>" +
            "<span>" + esc(r.installert) + " installert</span>" +
            "<span>" + esc(r.nett) + " i nettleser</span>" +
            "<span>" + (sum ? Math.round((r.installert / sum) * 100) : 0) +
            " %</span></div>";
        }).join("") + "</div>"
      : "");
}

/* ---------------------------------------------------------------- faner */

async function tegn() {
  const boks = $("#admin-innhold");
  boks.innerHTML = '<p class="hjelp">Laster…</p>';
  try {
    if (state.fane === "drift") await tegnDrift();
    else if (state.fane === "brukere") await tegnBrukere();
    else if (state.fane === "feedback") await tegnFeedback();
    else if (state.fane === "bruk") await tegnBruk();
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
