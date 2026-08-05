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
  ],
};

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

/* Frontenden leser svaret med r.text() slik at et tomt svar (204) ikke
 * kaster. Testdobbelen ma derfor tilby text(), ikke bare json(). */
function svar(url, valg, innlogget) {
  const sti = String(url).replace(/^.*\/api/, "");
  let data = null;
  if (sti.startsWith("/snapshot")) data = SNAPSHOT;
  else if (sti.startsWith("/catalog")) data = { sets: [], types: [], stores: [] };
  else if (sti.startsWith("/history")) data = HISTORIKK;
  else if (sti.startsWith("/unmatched")) data = { antall: 0, varer: [] };
  else if (sti.startsWith("/product/")) data = PRODUKT;
  else if (sti.startsWith("/auth/me")) data = innlogget
    ? { innlogget: true, email: "kris@example.no", role: "free" } : { innlogget: false };
  else if (sti.startsWith("/watchlist/snapshot")) data = { produkter: [SNAPSHOT.produkter[0]] };
  else if (sti.startsWith("/watchlist")) {
    if (valg && valg.method === "POST") data = { id: 7 };
    else if (valg && valg.method === "DELETE") data = { ok: true };
    else data = { folger: innlogget ? [{ id: 7, product_id: "pitch-black:booster-box:en" }] : [] };
  } else if (sti.startsWith("/auth/")) data = { email: "kris@example.no", role: "free" };
  const kropp = JSON.stringify(data);
  return { ok: data !== null, status: data ? 200 : 404,
           text: async () => kropp, json: async () => data };
}

async function app(innlogget = false) {
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const w = dom.window;
  w.fetch = async (url, valg) => svar(url, valg, innlogget);
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
  assert.match($(w, "#teller").textContent, /2 produkter pa lager/);
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
  assert.equal(alle(w, "#liste .kort").length, 3);
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
  assert.match($(w, "#ark").textContent, /Pa lager/);
  assert.match($(w, "#ark").textContent, /Cardcenter/);
});

test("hendelsesfanen viser gammel og ny pris ved prisendring", async () => {
  const w = await app();
  alle(w, ".fane-knapp").find((b) => b.dataset.fane === "nytt")
    .dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 20));
  const tekst = $(w, "#hendelser").textContent;
  assert.match(tekst, /pa lager igjen/);
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
  assert.match(knapp.textContent, /Folg denne/);
  knapp.dispatchEvent(new w.Event("click", { bubbles: true }));
  await new Promise((r) => setTimeout(r, 25));
  assert.match($(w, "#folg-knapp").textContent, /Folger/);
});
