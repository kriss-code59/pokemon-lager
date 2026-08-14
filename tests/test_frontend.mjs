/* Frontend-test uten nettleser.
 *
 * Kjorer web/index.html + web/app.js i jsdom mot et falskt API og sjekker at
 * det som faktisk havner i DOM-en stemmer. Poenget er ikke a teste jsdom,
 * men a fange de feilene som ellers forst dukker opp pa mobilen til noen
 * andre: feil felt fra API-et, filtre som ikke filtrerer, priser som vises
 * som ore.
 *
 * Kjor:  node --test tests/test_frontend.mjs
 *        (krever: npm install jsdom)
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const ROT = join(dirname(fileURLToPath(import.meta.url)), "..");
const les = (n) => readFileSync(join(ROT, "web", n), "utf8");

const SNAPSHOT = {
  sist_skannet: new Date(Date.now() - 6 * 60000).toISOString(),
  skanning_ok: true,
  felt: ["butikk", "pris_ore", "pa_lager"],
  produkter: [
    { id: "pitch-black:booster-box:en", set_id: "pitch-black", type_id: "booster-box",
      region: "en", set_label: "Pitch Black", type_label: "Booster Box",
      tilbud: [["cardcenter", 179900, 1], ["outland", 189900, 0]],
      min_pris: 179900, antall_pa_lager: 1 },
    { id: "pitch-black:etb:en", set_id: "pitch-black", type_id: "etb", region: "en",
      set_label: "Pitch Black", type_label: "Elite Trainer Box",
      tilbud: [["outland", 64900, 0]], min_pris: null, antall_pa_lager: 0 },
    { id: "mega-dream:booster-box:jp", set_id: "mega-dream", type_id: "booster-box",
      region: "jp", set_label: "Mega Dream", type_label: "Booster Box",
      tilbud: [["neo-tokyo", 149950, 1]], min_pris: 149950, antall_pa_lager: 1 },
    // Ikke sluppet enna: tilbud finnes, men hvert eneste ett er
    // forhaandssalg. Det er nettopp denne kombinasjonen standardfilteret
    // skjuler, og som slippboksen finnes for aa redde.
    { id: "30th-celebration:etb:en", set_id: "30th-celebration", type_id: "etb",
      region: "en", set_label: "30th Anniversary Celebration",
      type_label: "Elite Trainer Box",
      tilbud: [["cardcenter", 89900, 1, "forhandssalg"],
               ["outland", 94900, 1, "forhandssalg"]],
      min_pris: null, antall_pa_lager: 0, antall_forhandssalg: 2 },
  ],
};

// Slippdato ~40 dager fram, regnet ut i stedet for skrevet inn: en fast dato
// i en test slutter aa vaere «i framtiden» en dag, og da feiler den av en
// grunn som ikke er kodens.
const SLIPP = new Date(Date.now() + 40 * 86400000).toISOString().slice(0, 10);

const PRODUKT = {
  produkt: { id: "pitch-black:booster-box:en", set_id: "pitch-black",
             type_id: "booster-box", region: "en", set_label: "Pitch Black",
             type_label: "Booster Box" },
  tilbud: [
    { store_id: "cardcenter", store_name: "Cardcenter", title: "Pitch Black Display",
      price_ore: 179900, in_stock: true, url: "https://cardcenter.no/a" },
    { store_id: "outland", store_name: "Outland", title: "Pitch Black BB",
      price_ore: 189900, in_stock: false, url: "https://outland.no/b" },
  ],
  hendelser: [{ kind: "restock", store_id: "cardcenter", price_ore: 179900,
                detected_at: new Date(Date.now() - 3600000).toISOString() }],
};

const HISTORIKK = {
  hendelser: [
    { kind: "restock", detected_at: new Date(Date.now() - 600000).toISOString(),
      price_ore: 179900, prev_price_ore: null, store_id: "cardcenter",
      store_name: "Cardcenter", product_id: "pitch-black:booster-box:en",
      title: "Pitch Black Display", url: "https://cardcenter.no/a",
      set_label: "Pitch Black", type_label: "Booster Box" },
    { kind: "prisendring", detected_at: new Date(Date.now() - 900000).toISOString(),
      price_ore: 169900, prev_price_ore: 189900, store_id: "outland",
      store_name: "Outland", product_id: "pitch-black:etb:en",
      title: "ETB", url: "https://outland.no/b",
      set_label: "Pitch Black", type_label: "Elite Trainer Box" },
  ],
};

/* «Foelg alt» holdes som ekte tilstand i testdobbelen, ikke som et fast
 * svar. Knappen leser tilstanden tilbake fra serveren etter hvert trykk, og
 * en dobbel som alltid svarer det samme ville sagt at knappen virker selv om
 * den aldri sendte noe. KALL gjor det mulig aa se HVA den sendte. */
let ALT_PAA = false;
const KALL = [];

/* Det frontenden meldte inn til /api/bruk. Kroppen er poenget: standalone
 * er hele grunnen til at endepunktet finnes. */
const BRUK = [];

/* Varsler som appen lukket. Se «rydd varselsenteret»-testene nederst. */
const LUKKET = [];

/* Frontenden leser svaret med r.text() slik at et tomt svar (204) ikke
 * kaster. Testdobbelen ma derfor tilby text(), ikke bare json(). */
function svar(url, valg, innlogget) {
  const sti = String(url).replace(/^.*\/api/, "");
  let data = null;
  if (sti.startsWith("/snapshot")) data = SNAPSHOT;
  else if (sti.startsWith("/catalog")) data = {
    sets: [{ id: "30th-celebration", label: "30th Anniversary Celebration",
             region: "en", release_date: SLIPP },
           { id: "pitch-black", label: "Pitch Black", region: "en",
             release_date: null }],
    types: [], stores: [] };
  else if (sti.startsWith("/history")) data = HISTORIKK;
  else if (sti.startsWith("/unmatched")) data = { antall: 0, varer: [] };
  else if (sti.startsWith("/product/")) data = PRODUKT;
  else if (sti.startsWith("/feedback")) data = { ok: true, id: 1 };
  else if (sti.startsWith("/push/nokkel")) data = { paa: false, public_key: null };
  else if (sti.startsWith("/push/status")) data = {
    enheter: [], antall: 0, stille_natt: true, maks_pris_ore: null,
    sendt_7d: 0, vapid_paa: false };
  else if (sti.startsWith("/auth/me")) data = innlogget
    ? { innlogget: true, email: "kris@example.no", role: "free",
        epost_bekreftet: true } : { innlogget: false };
  else if (sti.startsWith("/bruk")) {
    BRUK.push(JSON.parse((valg && valg.body) || "null"));
    data = {};
  }
  else if (sti.startsWith("/watchlist/snapshot")) data = { produkter: [SNAPSHOT.produkter[0]] };
  else if (sti.startsWith("/watchlist/alt")) {
    KALL.push({ sti, metode: (valg && valg.method) || "GET" });
    if (valg && valg.method === "POST") { ALT_PAA = true; data = { id: 9, paa: true }; }
    else if (valg && valg.method === "DELETE") { ALT_PAA = false; data = { ok: true, paa: false }; }
    else data = { paa: ALT_PAA };
  }
  else if (sti.startsWith("/watchlist")) {
    if (valg && valg.method === "POST") data = { id: 7 };
    else if (valg && valg.method === "DELETE") data = { ok: true };
    else data = {
      folger: innlogget ? [{ id: 7, product_id: "pitch-black:booster-box:en" }] : [],
      alt: innlogget ? ALT_PAA : false,
      maks_per_time: 5,
    };
  } else if (sti.startsWith("/auth/")) data = { email: "kris@example.no", role: "free" };
  const kropp = JSON.stringify(data);
  return { ok: data !== null, status: data ? 200 : 404,
           text: async () => kropp, json: async () => data };
}

async function app(innlogget = false) {
  ALT_PAA = false;
  KALL.length = 0;
  BRUK.length = 0;
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const w = dom.window;
  // jsdom implementerer ikke matchMedia. Alle ekte nettlesere gjor det, saa
  // uten denne tester vi et miljo som ikke finnes noe sted.
  w.matchMedia = w.matchMedia || ((q) => ({ matches: false, media: q,
                                            addListener() {}, removeListener() {} }));
  // jsdom har ingen serviceWorker. Uten denne kan vi ikke teste at appen
  // rydder varselsenteret naar den aapnes.
  LUKKET.length = 0;
  const varsler = [{ close() { LUKKET.push("a"); } }, { close() { LUKKET.push("b"); } }];
  Object.defineProperty(w.navigator, "serviceWorker", {
    configurable: true,
    value: {
      getRegistration: async () => ({ getNotifications: async () => varsler }),
      ready: Promise.resolve({ getNotifications: async () => varsler }),
      register: async () => ({}),
    },
  });
  w.fetch = async (url, valg) => svar(url, valg, innlogget);
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  return w;
}

/* Som app(), men med et eget snapshot. Brukes av sorteringstestene, der
 * poenget nettopp er hvilke data som kommer inn. */
async function appMed(snapshot, innlogget = false) {
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const w = dom.window;
  w.matchMedia = w.matchMedia || ((q) => ({ matches: false, media: q,
                                            addListener() {}, removeListener() {} }));
  w.fetch = async (url, valg) => {
    if (String(url).includes("/snapshot") && !String(url).includes("watchlist")) {
      const kropp = JSON.stringify(snapshot);
      return { ok: true, status: 200, text: async () => kropp,
               json: async () => snapshot };
    }
    return svar(url, valg, innlogget);
  };
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  return w;
}

const $ = (w, s) => w.document.querySelector(s);
const alle = (w, s) => [...w.document.querySelectorAll(s)];

test("viser bare produkter pa lager som standard", async () => {
  const w = await app();
  const kort = alle(w, "#liste .kort");
  assert.equal(kort.length, 2, "ETB-en uten lager skal vaere filtrert bort");
  assert.match($(w, "#teller").textContent, /2 produkter på lager/);
});

test("priser vises i kroner, ikke ore", async () => {
  const w = await app();
  const tekst = $(w, "#liste").textContent;
  assert.match(tekst, /1\s?799 kr/, "1799 kr forventet, fikk: " + tekst.slice(0, 200));
  assert.match(tekst, /1\s?499,50 kr/, "desimaler skal beholdes");
  assert.doesNotMatch(tekst, /179900/);
});

test("grupperer etter sett og merker ikke-vestlige regioner", async () => {
  const w = await app();
  const titler = alle(w, ".sett-tittel").map((e) => e.textContent.trim());
  assert.deepEqual(titler, ["Pitch Black", "Mega Dream Japansk"]);
  assert.equal(alle(w, ".sett-tittel .merkelapp.jp").length, 1);
});

test("samme sett i to regioner blir to bolker", async () => {
  // Regresjon: 151 (vestlig), 151 (japansk) og 151 (kinesisk) havnet i én
  // bolk, som sa ut som "Booster Box" gjentatt tre ganger uten forklaring.
  const to = { ...SNAPSHOT, produkter: [
    { id: "151:booster-box:en", set_id: "151", type_id: "booster-box", region: "en",
      set_label: "151", type_label: "Booster Box", tilbud: [["a", 129900, 1]],
      min_pris: 129900, antall_pa_lager: 1 },
    { id: "151:booster-box:jp", set_id: "151", type_id: "booster-box", region: "jp",
      set_label: "151", type_label: "Booster Box", tilbud: [["b", 99900, 1]],
      min_pris: 99900, antall_pa_lager: 1 },
  ] };
  const dom = new JSDOM(les("index.html"), { url: "https://pokepuls.no/",
    runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.fetch = async (u) => {
    const d = String(u).includes("/snapshot") ? to : { sets: [], types: [], stores: [] };
    const k = JSON.stringify(d);
    return { ok: true, status: 200, text: async () => k, json: async () => d };
  };
  dom.window.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 30));
  const titler = alle(dom.window, ".sett-tittel").map((e) => e.textContent.trim());
  assert.deepEqual(titler, ["151", "151 Japansk"]);
});

test("filteret 'kun pa lager' kan slas av og viser da alt", async () => {
  const w = await app();
  $(w, '[data-filter="lager"]').dispatchEvent(new w.Event("click", { bubbles: true }));
  assert.equal(alle(w, "#liste .kort").length, 4);
});

test("regionfilter begrenser listen", async () => {
  const w = await app();
  $(w, '[data-verdi="jp"]').dispatchEvent(new w.Event("click", { bubbles: true }));
  const kort = alle(w, "#liste .kort");
  assert.equal(kort.length, 1);
  assert.match($(w, "#liste").textContent, /Mega Dream/);
});

test("sok treffer bade settnavn og butikk", async () => {
  const w = await app();
  const sok = $(w, "#sok");
  for (const [ord, antall] of [["pitch", 1], ["neo tokyo", 1], ["xyzzy", 0]]) {
    sok.value = ord;
    sok.dispatchEvent(new w.Event("input", { bubbles: true }));
    assert.equal(alle(w, "#liste .kort").length, antall, "sok: " + ord);
  }
  assert.equal($(w, "#tom-liste").hidden, false, "tomt-melding skal vises");
});

test("apner produktark med tilbud sortert og lenker som gar ut", async () => {
  const w = await app();
  $(w, "#liste .kort").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  assert.equal($(w, "#ark").hidden, false);
  const lenker = alle(w, "#ark .tilbud");
  assert.equal(lenker.length, 2);
  assert.equal(lenker[0].getAttribute("rel"), "noopener nofollow");
  assert.match($(w, "#ark").textContent, /På lager/);
  assert.match($(w, "#ark").textContent, /Cardcenter/);
});

test("hendelsesfanen viser gammel og ny pris ved prisendring", async () => {
  const w = await app();
  alle(w, ".fane-knapp").find((b) => b.dataset.fane === "nytt")
    .dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  const tekst = $(w, "#hendelser").textContent;
  assert.match(tekst, /på lager igjen/);
  assert.match(tekst, /1\s?899 kr/, "gammel pris skal vises");
  assert.match(tekst, /1\s?699 kr/, "ny pris skal vises");
  assert.equal(alle(w, "#hendelser .gjennomstreket").length, 1);
});

test("ferskhetsprikken lyser gront pa fersk skanning", async () => {
  const w = await app();
  assert.ok($(w, "#prikk").className.includes("ok"));
  assert.match($(w, "#ferskhet-tekst").textContent, /min siden/);
});

test("brukerdata slipper aldri ut som rå HTML", async () => {
  const w = await app();
  // Et butikknavn med HTML i seg skal vises som tekst, ikke tolkes.
  const ondt = { ...SNAPSHOT, produkter: [{ ...SNAPSHOT.produkter[0],
    set_label: '<img src=x onerror=alert(1)>', tilbud: [["a", 1000, 1]] }] };
  const dom = new JSDOM(les("index.html"), { url: "https://pokepuls.no/",
    runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.fetch = async (u) => {
    const d = String(u).includes("/snapshot") ? ondt : { sets: [], types: [], stores: [] };
    const k = JSON.stringify(d);
    return { ok: true, status: 200, text: async () => k, json: async () => d };
  };
  dom.window.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 30));
  // Miniatyrbildene vare er ekte <img>, sa vi kan ikke telle alle. Poenget er
  // at det INJISERTE bildet ikke ble til et element, og at teksten star
  // ordrett i overskriften.
  const injisert = [...dom.window.document.querySelectorAll("#liste img")]
    .filter((el) => el.getAttribute("src") === "x" || el.hasAttribute("onerror") &&
                    /alert/.test(el.getAttribute("onerror")));
  assert.equal(injisert.length, 0, "payloaden ble tolket som HTML");
  assert.match($(dom.window, ".sett-tittel").textContent, /<img/);
});


test("produktkort far miniatyrbilde, med reservegrafikk uten foto", async () => {
  const w = await app();
  const bilder = alle(w, "#liste .miniatyr");
  assert.equal(bilder.length, 2, "ett bilde per kort");
  // Ingen av produktene i testdataene har bilde, sa begge skal ha reserven.
  for (const b of bilder) {
    assert.match(b.getAttribute("src"), /^data:image\/svg\+xml/);
    assert.equal(b.getAttribute("loading"), "lazy");
  }
});

test("reservegrafikken skiller pa varetype", async () => {
  const w = await app();
  const [boks, ] = alle(w, "#liste .miniatyr").map((b) => b.getAttribute("src"));
  const jp = alle(w, "#liste .miniatyr")[1].getAttribute("src");
  // Booster box (vestlig, bla) og booster box (japansk, rod) skal ikke vaere
  // samme bilde -- regionen farger silhuetten.
  assert.notEqual(boks, jp);
});

test("butikkens bilde brukes nar det finnes", async () => {
  const med = { ...SNAPSHOT, produkter: [{ ...SNAPSHOT.produkter[0],
    bilde: "https://cdn.example.no/pitch.jpg" }] };
  const dom = new JSDOM(les("index.html"), { url: "https://pokepuls.no/",
    runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.fetch = async (u) => {
    const d = String(u).includes("/snapshot") ? med : { sets: [], types: [], stores: [] };
    const k = JSON.stringify(d);
    return { ok: true, status: 200, text: async () => k, json: async () => d };
  };
  dom.window.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 30));
  const img = $(dom.window, "#liste .miniatyr");
  assert.equal(img.getAttribute("src"), "https://cdn.example.no/pitch.jpg");
  // Faller bildet, skal reserven ta over i stedet for et odelagt ikon.
  assert.match(img.getAttribute("onerror"), /data:image\/svg\+xml/);
});

test("utlogget bruker blir bedt om a logge inn i folger-fanen", async () => {
  const w = await app(false);
  alle(w, ".fane-knapp").find((b) => b.dataset.fane === "folger")
    .dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  assert.match($(w, "#folger-innhold").textContent, /Logg inn for a folge/);
  assert.equal($(w, ".konto-knapp").classList.contains("innlogget"), false);
});

test("innlogget bruker ser folgelisten og merket pa kortet", async () => {
  const w = await app(true);
  assert.equal($(w, ".konto-knapp").classList.contains("innlogget"), true);
  assert.equal(alle(w, "#liste .folge-merke").length, 1, "det fulgte produktet skal merkes");
  alle(w, ".fane-knapp").find((b) => b.dataset.fane === "folger")
    .dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 25));
  assert.match($(w, "#folger-innhold").textContent, /1 fulgte produkter/);
});

test("innloggingsskjemaet kan bytte mellom logg inn og registrer", async () => {
  const w = await app(false);
  $(w, "#konto-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 15));
  assert.equal($(w, "#ark").hidden, false);
  assert.match($(w, "#ark-innhold").textContent, /Logg inn/);
  $(w, "#bytt-modus").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 15));
  assert.match($(w, "#ark-innhold").textContent, /Lag konto/);
  assert.equal($(w, "#k-passord").getAttribute("minlength"), "8");
});

test("folg-knappen i produktarket krever innlogging", async () => {
  const w = await app(false);
  $(w, "#liste .kort").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 25));
  assert.match($(w, "#folg-knapp").textContent, /Logg inn/);
});

test("innlogget bruker kan folge og slutte a folge fra produktarket", async () => {
  const w = await app(true);
  // Apne et produkt brukeren IKKE folger fra for.
  alle(w, "#liste .kort")[1].dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 25));
  const knapp = $(w, "#folg-knapp");
  assert.match(knapp.textContent, /Følg denne/);
  knapp.dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 25));
  assert.match($(w, "#folg-knapp").textContent, /Følger/);
});


/* ------------------------------------------------------ nytt i v6 */

test("nyeste aktivitet havner overst, ikke alfabetisk", async () => {
  // Regresjon mot den gamle sorteringen: «Ascended Heroes» laa alltid
  // overst uansett hva som hadde skjedd, og det du apnet appen for a se
  // -- hva som er nytt -- laa langt nede.
  const na = new Date().toISOString();
  const data = { ...SNAPSHOT, produkter: [
    { id: "aaa:booster-box:en", set_id: "aaa", type_id: "booster-box", region: "en",
      set_label: "Aaa Forst Alfabetisk", type_label: "Booster Box",
      tilbud: [["butikk-a", 100000, 1]], min_pris: 100000, antall_pa_lager: 1,
      sist_hendelse: null },
    { id: "zzz:booster-box:en", set_id: "zzz", type_id: "booster-box", region: "en",
      set_label: "Zzz Sist Alfabetisk", type_label: "Booster Box",
      tilbud: [["butikk-b", 200000, 1]], min_pris: 200000, antall_pa_lager: 1,
      sist_hendelse: na },
  ] };
  const w = await appMed(data);
  const titler = alle(w, ".sett-tittel").map((e) => e.textContent.trim());
  assert.deepEqual(titler, ["Zzz Sist Alfabetisk", "Aaa Forst Alfabetisk"]);
});

test("sett uten aktivitet beholder rekkefolgen fra API-et", async () => {
  const w = await app();
  const titler = alle(w, ".sett-tittel").map((e) => e.textContent.trim());
  assert.deepEqual(titler, ["Pitch Black", "Mega Dream Japansk"]);
});

test("kortet viser hvilken butikk som er billigst, ikke antall tilbud", async () => {
  const w = await app();
  const tekst = $(w, "#liste").textContent;
  assert.match(tekst, /billigst hos Cardcenter/);
  assert.doesNotMatch(tekst, /2 tilbud/);
});

test("fersk hendelse gir tidsmerke pa kortet", async () => {
  const data = { ...SNAPSHOT, produkter: [
    { ...SNAPSHOT.produkter[0],
      sist_hendelse: new Date(Date.now() - 12 * 60000).toISOString() },
  ] };
  const w = await appMed(data);
  assert.equal(alle(w, ".nylig").length, 1);
  assert.match($(w, ".nylig").textContent, /12 min siden/);
});

test("gammel hendelse gir IKKE tidsmerke", async () => {
  const data = { ...SNAPSHOT, produkter: [
    { ...SNAPSHOT.produkter[0],
      sist_hendelse: new Date(Date.now() - 40 * 3600 * 1000).toISOString() },
  ] };
  const w = await appMed(data);
  assert.equal(alle(w, ".nylig").length, 0);
});

test("regionfilteret heter Engelsk, ikke Vestlig", async () => {
  const w = await app();
  const chip = $(w, '[data-filter="region"][data-verdi="en"]');
  assert.equal(chip.textContent.trim(), "Engelsk");
  assert.doesNotMatch(w.document.body.textContent, /Vestlig/);
});

test("kontosiden sier fra nar varsler ikke er slatt pa pa serveren", async () => {
  // vapid_paa: false i testdobbelen. Da skal det sta hvorfor, ikke en
  // knapp som ikke kan virke.
  const w = await app(true);
  $(w, "#konto-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  const tekst = $(w, "#ark-innhold").textContent;
  assert.match(tekst, /Varsler/);
  assert.equal($(w, "#varsel-knapp"), null, "ingen knapp uten VAPID-nokler");
});


/* ------------------------------------------- deling: feedback og konto */

const konto = async (w) => {
  $(w, "#konto-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  return w;
};

test("innlogget bruker far et felt for a si fra", async () => {
  const w = await konto(await app(true));
  assert.ok($(w, "#fb-skjema"), "feedback-skjemaet skal finnes");
  assert.match($(w, "#ark-innhold").textContent, /Si fra/);
});

test("feedback kan sendes og kvitteres ut", async () => {
  const w = await konto(await app(true));
  $(w, "#fb-tekst").value = "Dere mangler Pokemadness";
  $(w, "#fb-skjema").dispatchEvent(new w.Event("submit", { bubbles: true, cancelable: true }));
  await new Promise((r) => setTimeout(r, 40));
  assert.match($(w, "#fb-skjema").textContent, /Takk/);
});

test("tom feedback sendes ikke", async () => {
  // Regresjon: uten required-attributtet gikk en tom melding rett inn, og
  // admin fikk en rad uten innhold og uten mate a vite hvem som mente hva.
  const w = await konto(await app(true));
  assert.equal($(w, "#fb-tekst").required, true);
});

test("innloggingsskjemaet har vei ut for den som har glemt passordet", async () => {
  const w = await app();
  $(w, "#konto-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  const lenke = $(w, "#glemt-lenke");
  assert.ok(lenke, "glemt-passord-lenken skal finnes pa innlogging");
  lenke.dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  assert.ok($(w, "#glemt-skjema"));
});

test("registrering peker pa personvern", async () => {
  const w = await app();
  $(w, "#konto-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  $(w, "#bytt-modus").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  assert.ok($(w, '#ark-innhold a[href="/personvern.html"]'),
            "den som lager konto skal se hva vi lagrer");
});

test("sletting av konto krever passord", async () => {
  const w = await konto(await app(true));
  $(w, "#slett-konto").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  const felt = $(w, "#s-passord");
  assert.ok(felt, "passordfeltet skal finnes");
  assert.equal(felt.type, "password");
  assert.equal(felt.required, true);
  assert.match($(w, "#ark-innhold").textContent, /kan ikke angres/);
});

test("ubekreftet e-post gir en synlig oppfordring", async () => {
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const w = dom.window;
  w.fetch = async (url, valg) => {
    if (String(url).includes("/auth/me")) {
      const d = { innlogget: true, email: "kris@example.no", role: "free",
                  epost_bekreftet: false };
      const k = JSON.stringify(d);
      return { ok: true, status: 200, text: async () => k, json: async () => d };
    }
    return svar(url, valg, true);
  };
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  await konto(w);
  assert.ok($(w, "#send-verifisering"),
            "uten bekreftet e-post kan du ikke fa nytt passord -- si fra om det");
});


/* --------------------------------------- forhandssalg vs ekte lager */

test("forhandssalg teller ikke som pa lager, men skjules heller ikke", async () => {
  // Regresjon: produktsiden viste tre butikker under «Pa lager» der alle
  // tre var forhandsbestillinger. Da er varselet en logn.
  const data = { ...SNAPSHOT, produkter: [
    { id: "ah:etb:en", set_id: "ah", type_id: "etb", region: "en",
      set_label: "Ascended Heroes", type_label: "Elite Trainer Box",
      // [butikk, pris, pa_lager, bestillingstype]
      tilbud: [["boosterkongen", 269900, 1, "forhandssalg"]],
      min_pris: null, antall_pa_lager: 0, sist_hendelse: null },
  ] };
  const w = await appMed(data);
  // Kun-pa-lager-filteret er pa som standard, sa den skal vaere borte.
  assert.equal(alle(w, "#liste .kort").length, 0, "forhandssalg er ikke pa lager");

  // Men sla av filteret, og den skal vises -- med merkelapp, ikke som utsolgt.
  $(w, '[data-filter="lager"]').dispatchEvent(new w.Event("click", { bubbles: true }));
  const tekst = $(w, "#liste").textContent;
  assert.equal(alle(w, "#liste .kort").length, 1);
  assert.match(tekst, /Forhåndssalg/);
  assert.match(tekst, /2\s?699 kr/, "prisen skal vises, ikke skjules");
  assert.doesNotMatch(tekst, /billigst hos/, "et forhandssalg er ikke «billigst pa lager»");
});

test("ekte lager slar forhandssalg i «billigst hos»", async () => {
  const data = { ...SNAPSHOT, produkter: [
    { id: "ah:etb:en", set_id: "ah", type_id: "etb", region: "en",
      set_label: "Ascended Heroes", type_label: "Elite Trainer Box",
      tilbud: [["cardcenter", 289900, 1, null],
               ["boosterkongen", 269900, 1, "forhandssalg"]],
      min_pris: 289900, antall_pa_lager: 1, sist_hendelse: null },
  ] };
  const w = await appMed(data);
  const tekst = $(w, "#liste").textContent;
  // 2 699 er billigere, men kan ikke sendes. Da er 2 899 hos Cardcenter
  // riktig svar pa «hvor far jeg den na».
  assert.match(tekst, /billigst hos Cardcenter/);
  assert.match(tekst, /2\s?899 kr/);
});

/* ------------------------------------------------------------ folg alt */

/* Backend og API for «foelg alt» har vaert ferdig siden bolk 3. Det som
 * manglet var knappen -- og en funksjon uten inngang finnes ikke for noen
 * andre enn den som kan skrive en POST for haand. Testene her handler
 * derfor mest om at loftet i teksten stemmer med det systemet faktisk
 * gjor, for det er der en slik knapp mister tillit. */

test("kontosiden har en knapp for a folge alt", async () => {
  const w = await konto(await app(true));
  const knapp = $(w, "#folg-alt-knapp");
  assert.ok(knapp, "knappen skal finnes for innloggede");
  assert.equal(knapp.textContent.trim(), "Følg alt");
});

test("dempingen staar i teksten FOR du trykker", async () => {
  // Det viktigste i hele boksen. En bruker som tror «alt» betyr alt, far
  // 300-500 varsler i dognet og skrur av varsler for godt samme kveld.
  // Da har du mistet ham, ikke bare funksjonen.
  const w = await konto(await app(true));
  const boks = $(w, "#folg-alt-knapp").closest(".varselboks").textContent;
  assert.match(boks, /Maks 5 varsler i timen/);
  assert.match(boks, /samles i ett/i);
  assert.match(boks, /enkeltvis går alltid gjennom/i);
});

test("teksten viser brukerens egen kvote, ikke tallet 5 hardkodet", async () => {
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true });
  dom.window.fetch = async (url, valg) => {
    const sti = String(url).replace(/^.*\/api/, "");
    if (sti === "/watchlist") {
      const d = { folger: [], alt: false, maks_per_time: 12 };
      const k = JSON.stringify(d);
      return { ok: true, status: 200, text: async () => k, json: async () => d };
    }
    return svar(url, valg, true);
  };
  dom.window.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  await konto(dom.window);
  assert.match($(dom.window, "#folg-alt-knapp").closest(".varselboks").textContent,
               /Maks 12 varsler i timen/);
});

test("knappen sender POST /watchlist/alt og bytter til av-tilstand", async () => {
  const w = await konto(await app(true));
  $(w, "#folg-alt-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(KALL, [{ sti: "/watchlist/alt", metode: "POST" }]);
  const knapp = $(w, "#folg-alt-knapp");
  assert.equal(knapp.textContent.trim(), "Slutt å følge alt");
  assert.ok(knapp.classList.contains("av"));
});

test("trykk nummer to skrur det av igjen", async () => {
  const w = await konto(await app(true));
  $(w, "#folg-alt-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  $(w, "#folg-alt-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  assert.deepEqual(KALL.map((k) => k.metode), ["POST", "DELETE"]);
  assert.equal($(w, "#folg-alt-knapp").textContent.trim(), "Følg alt");
});

test("naar du folger alt sier kontosiden det, ikke 'du folger 1 produkt'", async () => {
  const w = await konto(await app(true));
  $(w, "#folg-alt-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  const tekst = $(w, "#ark-innhold").textContent;
  assert.match(tekst, /Du følger hele katalogen/);
  assert.doesNotMatch(tekst, /Du følger 1 produkt/);
});

test("boksen overlever at nettleseren ikke stotter push", async () => {
  // jsdom har ingen serviceWorker, sa push.stottes() er alltid false her --
  // varselseksjonen returnerer tidlig med «stotter ikke varsler». Ligger
  // «folg alt» inni den seksjonen, forsvinner den samtidig. Den skal ikke:
  // abonnementet ditt er ikke Safaris ansvar.
  const w = await konto(await app(true));
  assert.match($(w, "#varsel-seksjon").textContent, /støtter ikke varsler/,
               "forutsetningen: push er ikke tilgjengelig i denne testen");
  assert.ok($(w, "#folg-alt-knapp"), "knappen skal staa likevel");
});

test("en feil fra serveren vises, og knappen kan proves igjen", async () => {
  const w = await konto(await app(true));
  w.fetch = async (url, valg) => {
    if (String(url).includes("/watchlist/alt")) {
      const k = JSON.stringify({ detail: "Ikke innlogget" });
      return { ok: false, status: 401, text: async () => k,
               json: async () => JSON.parse(k) };
    }
    return svar(url, valg, true);
  };
  $(w, "#folg-alt-knapp").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 60));
  assert.equal($(w, "#folg-alt-feil").hidden, false);
  assert.match($(w, "#folg-alt-feil").textContent, /Ikke innlogget/);
  assert.equal($(w, "#folg-alt-knapp").disabled, false, "skal kunne proves igjen");
});

/* ---------------------------------------------------- sidevisninger */

/* Ett spoersmaal: virker det aa be folk installere? Testene her passer paa
 * de to maatene svaret kan bli feil paa -- at tallet blaases opp av
 * omlastinger, og at iPhone-installasjoner teller som null. */

/* Som app(), men med kontroll over de to tingene som avgjor om nettleseren
 * ser seg selv som installert. */
async function appSom({ standalone = false, ios = false } = {}) {
  BRUK.length = 0;
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.fetch = async (url, valg) => svar(url, valg, false);
  w.matchMedia = (q) => ({ matches: standalone && /standalone/.test(q),
                           media: q, addListener() {}, removeListener() {} });
  if (ios) Object.defineProperty(w.navigator, "standalone", { value: true,
                                                              configurable: true });
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  return w;
}

test("melder fra én gang naar appen aapnes", async () => {
  await app();
  assert.equal(BRUK.length, 1);
  assert.deepEqual(BRUK[0], { side: "hjem", standalone: false });
});

test("samme fane teller ikke to ganger", async () => {
  // Uten dette ser én person som laster siden tjue ganger ut som tjue
  // aapninger, og da er andelen installert det eneste brukbare tallet
  // igjen. sessionStorage doer med fanen, saa neste oekt teller igjen.
  const w = await app();
  assert.equal(BRUK.length, 1);
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(BRUK.length, 1, "andre lasting i samme fane skal ikke telles");
});

test("display-mode standalone teller som installert", async () => {
  await appSom({ standalone: true });
  assert.equal(BRUK[0].standalone, true);
});

test("iPhone teller som installert via navigator.standalone", async () => {
  // Apple-spesifikk og finnes bare paa iOS. Uten denne sjekken teller du
  // NULL iPhone-installasjoner -- og iOS er den ene plattformen der
  // varsler ikke virker i det hele tatt uten installasjon, altsaa nettopp
  // der du trenger tallet.
  await appSom({ ios: true });
  assert.equal(BRUK[0].standalone, true);
});

test("nettleser uten installasjon teller som ikke installert", async () => {
  await appSom({});
  assert.equal(BRUK[0].standalone, false);
});

test("meldingen sender ingenting som kan identifisere noen", async () => {
  // Personvernerklaeringen lover «ingen sporing». Bryter noen det, skjer
  // det ved at et felt sniker seg inn her.
  await app();
  assert.deepEqual(Object.keys(BRUK[0]).sort(), ["side", "standalone"]);
});

/* ------------------------------------------ forhandssalg og slippboks */

/* Bakgrunnen: 30th Celebration laa i katalogen med tilbud fra flere
 * butikker, men var USYNLIG paa forsiden. Alle tilbudene var forhaandssalg,
 * standardfilteret er «kun paa lager», og da faller settet ut. Det mest
 * etterspurte slippet i aaret ville dukket opp forste gang paa slippdagen
 * -- presis for sent, siden hele poenget med forhaandssalg er aa sikre seg
 * FOR alle andre. */

test("forhandssalg er skjult som standard", async () => {
  // Regresjonsvern for det motsatte: at noen «fikser» synligheten ved aa la
  // forhaandssalg telle som paa lager. Da lyver restock-varselet igjen.
  const w = await app();
  assert.doesNotMatch($(w, "#liste").textContent, /30th/);
});

test("forhandssalg-filteret viser dem, og bare dem", async () => {
  const w = await app();
  $(w, '[data-filter="forhandssalg"]').dispatchEvent(new w.Event("click", { bubbles: true }));
  const kort = alle(w, "#liste .kort");
  assert.equal(kort.length, 1);
  assert.match($(w, "#liste").textContent, /30th Anniversary Celebration/);
  assert.match($(w, "#teller").textContent, /til forhåndsbestilling/);
});

test("forhandssalg-filteret gjor ikke varen til «pa lager»", async () => {
  const w = await app();
  $(w, '[data-filter="forhandssalg"]').dispatchEvent(new w.Event("click", { bubbles: true }));
  assert.doesNotMatch($(w, "#teller").textContent, /på lager/);
});

test("slippboksen teller ned og staar utenfor filteret", async () => {
  const w = await app();
  const boks = $(w, "#slipp-boks");
  assert.equal(boks.hidden, false, "boksen skal vises selv om settet ikke er inne");
  const tekst = boks.textContent;
  assert.match(tekst, /40\s*dager til/);
  assert.match(tekst, /30th Anniversary Celebration/);
  assert.match(tekst, /2 butikker tar forhåndsbestilling nå/);
  assert.match(tekst, /fra 899 kr/, "billigste forhandssalg, ikke billigste noe");
});

test("slippboksen skiller «har lagt ut» fra «tar bestilling»", async () => {
  // Rett for et slipp er dette den viktigste setningen paa siden. Butikker
  // som har lagt ut varen men ikke selger den enna, staar KLARE -- det kan
  // skje naar som helst. Slaas de sammen med «ingen har den», sier teksten
  // «ingenting skjer» paa akkurat det tidspunktet det er mest som skjer.
  const lagt_ut = { ...SNAPSHOT, produkter: SNAPSHOT.produkter.map((p) =>
    p.set_id === "30th-celebration"
      ? { ...p, tilbud: [["cardcenter", null, 0, null], ["outland", null, 0, null]],
          antall_forhandssalg: 0 } : p) };
  const a = await appMed(lagt_ut);
  assert.match($(a, "#slipp-boks").textContent,
               /2 butikker har lagt ut varene, men ingen tar bestilling akkurat nå/);

  const ingenting = { ...SNAPSHOT, produkter: SNAPSHOT.produkter.map((p) =>
    p.set_id === "30th-celebration"
      ? { ...p, tilbud: [], antall_forhandssalg: 0 } : p) };
  const b = await appMed(ingenting);
  assert.match($(b, "#slipp-boks").textContent,
               /Ingen norske butikker har lagt ut settet ennå/);
});

test("slippboksen vises ikke for et sett som allerede er ute", async () => {
  // Nedtelling til noe som skjedde i fjor er stoy, og stoy over listen er
  // dyrere enn stoy under den.
  const dom = new JSDOM(les("index.html"), { url: "https://pokepuls.no/",
    runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.matchMedia = (q) => ({ matches: false, media: q, addListener() {}, removeListener() {} });
  w.fetch = async (url, valg) => {
    if (String(url).includes("/catalog")) {
      const d = { sets: [{ id: "30th-celebration", label: "30th Anniversary Celebration",
                           region: "en", release_date: "2020-01-01" }],
                  types: [], stores: [] };
      const k = JSON.stringify(d);
      return { ok: true, status: 200, text: async () => k, json: async () => d };
    }
    return svar(url, valg, false);
  };
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 60));
  assert.equal($(w, "#slipp-boks").hidden, true);
});

test("folg-knappen vises bare for innloggede", async () => {
  const ute = await app(false);
  assert.equal($(ute, "#folg-sett"), null);
  const inne = await app(true);
  await new Promise((r) => setTimeout(r, 60));
  assert.ok($(inne, "#folg-sett"), "innlogget skal kunne folge settet");
});

test("folg-knappen lager et abonnement paa SETTET, ikke paa ett produkt", async () => {
  // Det er hele poenget: du vet ikke hvilken butikk som apner forhaandssalg
  // forst, eller om det blir ETB-en eller boksen. Folger du settet, treffer
  // du uansett.
  const w = await app(true);
  await new Promise((r) => setTimeout(r, 60));
  const sendt = [];
  const gammelFetch = w.fetch;
  w.fetch = async (url, valg) => {
    if (String(url).endsWith("/watchlist") && valg && valg.method === "POST")
      sendt.push(JSON.parse(valg.body));
    return gammelFetch(url, valg);
  };
  $(w, "#folg-sett").dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 80));
  assert.equal(sendt.length, 1);
  assert.equal(sendt[0].set_id, "30th-celebration");
  assert.equal(sendt[0].product_id, undefined, "skal ikke sende product_id");
  // Begge trengs: «ny» naar butikken legger ut forhaandssalget, «restock»
  // naar det gaar over til ekte lager paa slippdagen.
  assert.deepEqual(sendt[0].kinds.sort(), ["ny", "restock"]);
});

/* --------------------------------------------- rydd varselsenteret */

/* «Vi far alle varslene paa nytt hver gang vi oppdaterer siden.»
 *
 * De kom aldri paa nytt. De hadde ligget der hele tiden: et varsel du ikke
 * sveiper bort blir staaende i varslingssenteret, og paa iOS leveres i
 * tillegg alt som kom mens appen var lukket, samlet, i det du aapner den.
 *
 * Staar du INNE i appen, har varselet gjort jobben sin. */

test("varselsenteret ryddes naar appen aapnes", async () => {
  await app();
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(LUKKET, ["a", "b"]);
});

test("ryddes ogsaa naar fanen blir synlig igjen", async () => {
  // Paa mobil byttes det mellom apper langt oftere enn sider lastes. Uten
  // dette ville varslene blitt liggende gjennom en hel dags bruk.
  const w = await app();
  await new Promise((r) => setTimeout(r, 30));
  LUKKET.length = 0;
  w.document.dispatchEvent(new w.Event("visibilitychange"));
  await new Promise((r) => setTimeout(r, 30));
  assert.deepEqual(LUKKET, ["a", "b"]);
});

test("en nettleser uten serviceWorker skal ikke kaste", async () => {
  // Safari uten hjemskjerm, eldre Android. Ryddingen er en bekvemmelighet;
  // den skal aldri vaere grunnen til at appen ikke laster.
  const dom = new JSDOM(les("index.html"), { url: "https://pokepuls.no/",
    runScripts: "outside-only", pretendToBeVisual: true });
  const w = dom.window;
  w.matchMedia = (q) => ({ matches: false, media: q, addListener() {}, removeListener() {} });
  w.fetch = async (url, valg) => svar(url, valg, false);
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 40));
  assert.equal(alle(w, "#liste .kort").length, 2, "appen skal virke som vanlig");
});

/* ------------------------------------------------ tekst som gaar utenfor */

/* Andre-fanen viser RAA butikktitler -- «2025 Pokemon Chinese Gem Pack
 * Volume 3 Houndoom Master Ball Rare #050...» -- og de la seg tvers over
 * prisen.
 *
 * Aarsaken hadde ligget der hele tiden: .kort-navn har text-overflow og
 * white-space, men staar paa et <span>, og de reglene virker IKKE paa et
 * inline-element. Paa produktlista merkes det aldri, fordi navnene der er
 * korte. Derfor testes CSS-en direkte -- jsdom regner ikke layout, saa en
 * DOM-test ville sagt at alt var i orden. */

const CSS = readFileSync(join(ROT, "web", "style.css"), "utf8");

function regel(velger) {
  const i = CSS.indexOf("\n" + velger + " {");
  if (i < 0) return "";
  return CSS.slice(i, CSS.indexOf("}", i));
}

test("kort-navn kan faktisk kortes av", () => {
  const r = regel(".kort-navn");
  assert.match(r, /text-overflow:\s*ellipsis/);
  assert.match(r, /white-space:\s*nowrap/);
  assert.match(r, /display:\s*block/,
               "ellipsis virker ikke paa et inline-element -- <span> ma blokkeres");
});

test("flex-elementet kan krympe under innholdet sitt", () => {
  // Uten min-width: 0 nekter et flex-element aa bli smalere enn innholdet,
  // og da hjelper ingen ellipsis.
  assert.match(regel(".kort-venstre"), /min-width:\s*0/);
});

test("prisen klemmes ikke av en lang tittel", () => {
  assert.match(regel(".kort-hoyre"), /flex:\s*0 0 auto/);
});

test("kort som er lenker ser ikke ut som lenker", () => {
  // Andre-fanen bruker <a class="kort">. Uten dette tar nettleseren over
  // med blaatt og understrek midt i en ellers mork side.
  const i = CSS.indexOf("a.kort {");
  assert.ok(i > 0, "a.kort mangler");
  const r = CSS.slice(i, CSS.indexOf("}", i));
  assert.match(r, /color:\s*inherit/);
  assert.match(r, /text-decoration:\s*none/);
});

test("Andre-fanen tegner kort med de klassene CSS-en gjelder for", () => {
  // Bindeleddet: virker CSS-en, men markupen bruker andre klasser, er
  // testene over verdilose.
  const js = les("app.js");
  const i = js.indexOf("function visMerAndre");
  const kropp = js.slice(i, i + 900);
  for (const klasse of ["kort", "kort-venstre", "kort-navn", "kort-hoyre"]) {
    assert.ok(kropp.includes('"' + klasse) || kropp.includes(klasse + '"'),
              "visMerAndre bruker ikke ." + klasse);
  }
});

/* ------------------------------------------------- oppdagbarhet
 *
 * Kristian spurte om slippkalenderen og statistikken var «litt gjemt».
 * De laa bare i bunnteksten -- kalenderen er en av de sterkeste grunnene
 * til aa komme tilbake, og statistikken er en av tre ting folk betaler
 * for. Begge var ett klikk unna aa aldri bli funnet.
 */

test("slippboksen lenker videre til hele kalenderen", () => {
  // Boksen viser ETT sett, det naermeste. Den som bryr seg om slipp,
  // bryr seg som regel om de neste ogsaa.
  const kilde = les("app.js");
  const i = kilde.indexOf("function slippBoksHtml");
  const kropp = kilde.slice(i, kilde.indexOf("function nyNorskDato"));
  assert.ok(kropp.includes('href="/kalender"'),
            "slippboksen har ingen vei til kalenderen");
});

test("premium selger paa alle tre funksjonene, ikke bare én", () => {
  // Vi bygde prisgrense, prishistorikk OG restock-statistikk. Boksen
  // listet bare den forste -- de to andre var usynlige for den som
  // skulle bestemme seg for aa betale 49 kr i maaneden.
  const kilde = les("app.js");
  const i = kilde.indexOf("async function tegnPremium");
  const kropp = kilde.slice(i, i + 3500);
  assert.match(kropp, /Prisgrense per vare/);
  assert.match(kropp, /Prishistorikk/);
  assert.match(kropp, /Restock-statistikk/);
  // Veien til siden maa finnes begge veier: for den som vurderer aa
  // betale, og for den som allerede har betalt og skal finne den igjen.
  const treff = kropp.match(/href="\/statistikk\.html"/g) || [];
  assert.ok(treff.length >= 2,
            `statistikk lenkes bare ${treff.length} sted(er) i premium-boksen`);
});

test("cacheversjonen er bumpet overalt samtidig", () => {
  // Glemmer vi én, serverer tjeneren gammel app.js mot ny style.css --
  // og det er den slags feil som bare vises hos brukeren.
  const sw = les("sw.js");
  const v = sw.match(/pokepuls-skall-v(\d+)/)?.[1];
  assert.ok(v, "fant ingen cacheversjon i sw.js");
  assert.ok(sw.includes(`/app.js?v=${v}`), "SKALL-listen i sw.js henger etter");
  assert.ok(sw.includes(`/style.css?v=${v}`), "SKALL-listen i sw.js henger etter");
  assert.ok(les("index.html").includes(`app.js?v=${v}`),
            "index.html henger etter sw.js");
});

test("vilkaarene sier ikke hvor mange som staar bak", () => {
  // Kristian ba om at navnet hans skulle bort. Setningen «Pokepuls driftes
  // av én person» ble staaende og sa fortsatt at det er en enmannsjobb.
  //
  // Forbeholdet den baerer -- at tjenesten kan vaere nede og varsler kan
  // utebli -- er det viktige, og det staar fortsatt. Bemanningen er ikke
  // noe kunden trenger aa vite for aa forstaa det.
  const v = les("vilkar.html");
  assert.ok(!/av én person/.test(v), "bemanningen staar fortsatt i vilkaarene");
  assert.match(v, /kan være nede, varsler kan/,
               "forbeholdet forsvant sammen med setningen");
  for (const fil of ["vilkar.html", "personvern.html", "om.html"]) {
    assert.ok(!/Kristian|privatperson/.test(les(fil)), fil);
  }
});
