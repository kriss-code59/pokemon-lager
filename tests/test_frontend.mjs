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

async function app() {
  const dom = new JSDOM(les("index.html"), {
    url: "https://pokepuls.no/", runScripts: "outside-only", pretendToBeVisual: true,
  });
  const w = dom.window;
  w.fetch = async (url) => {
    const sti = String(url).replace(/^.*\/api/, "");
    let data = null;
    if (sti.startsWith("/snapshot")) data = SNAPSHOT;
    else if (sti.startsWith("/catalog")) data = { sets: [], types: [], stores: [] };
    else if (sti.startsWith("/history")) data = HISTORIKK;
    else if (sti.startsWith("/unmatched")) data = { antall: 0, varer: [] };
    else if (sti.startsWith("/product/")) data = PRODUKT;
    return { ok: true, status: 200, json: async () => data };
  };
  w.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 30));
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
  dom.window.fetch = async (u) => ({ ok: true, status: 200, json: async () =>
    String(u).includes("/snapshot") ? ondt : { sets: [], types: [], stores: [] } });
  dom.window.eval(les("app.js").replace(/if \("serviceWorker"[\s\S]*$/, ""));
  await new Promise((r) => setTimeout(r, 30));
  assert.equal(dom.window.document.querySelectorAll("#liste img").length, 0);
  assert.match($(dom.window, ".sett-tittel").textContent, /<img/);
});
