/* Pokepuls frontend.
 *
 * Henter ETT lite snapshot (kanoniske produkter med tilbud under seg) i
 * stedet for 5,8 MB data.json. Alt filtrering skjer i minnet -- 427
 * produkter er ingenting, og det gjor soket umiddelbart.
 *
 * Ingen rammeverk, ingen byggesteg: filen som ligger pa serveren er filen
 * som kjorer. Det er det som gjor at neste okt kan endre den uten a sette
 * opp en verktoykjede forst.
 */

const API = location.hostname === "localhost" || location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:8001/api" : "/api";

const $ = (id) => document.getElementById(id);

const REGION = { en: "Vestlig", jp: "Japansk", cn: "Kinesisk", ko: "Koreansk" };
const HENDELSE = {
  restock: { ikon: "↑", ord: "pa lager igjen" },
  ny: { ikon: "✦", ord: "ny vare" },
  prisendring: { ikon: "kr", ord: "ny pris" },
  utsolgt: { ikon: "↓", ord: "utsolgt" },
};

const state = {
  produkter: [], typer: new Map(),
  sok: "", kunLager: true, region: null, type: null,
  hendelseKinds: new Set(["restock"]),
  andre: [], andreVist: 0,
  fane: "produkter",
};

/* ------------------------------------------------------------- verktoy */

const kr = (ore) => ore == null ? null :
  (ore % 100 === 0 ? (ore / 100).toLocaleString("nb-NO")
                   : (ore / 100).toLocaleString("nb-NO", { minimumFractionDigits: 2 })) + " kr";

function siden(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "na";
  if (min < 60) return min + " min siden";
  const t = Math.round(min / 60);
  if (t < 24) return t + " t siden";
  return Math.round(t / 24) + " d siden";
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* Butikk-id er en slug ("neo-tokyo"); vis den som butikknavn ("Neo Tokyo"). */
const butikknavn = (id) => (id || "").split("-")
  .map((d) => d.charAt(0).toUpperCase() + d.slice(1)).join(" ");

/* ---------------------------------------------------------------- data */

async function hent(sti) {
  const r = await fetch(API + sti, { headers: { Accept: "application/json" } });
  if (!r.ok) throw new Error(sti + " svarte " + r.status);
  return r.json();
}

async function last() {
  try {
    const [snap, kat] = await Promise.all([hent("/snapshot"), hent("/catalog")]);
    kat.types.forEach((t) => state.typer.set(t.id, t.label));
    state.produkter = snap.produkter.map((p) => ({
      ...p,
      _sok: (p.set_label + " " + p.type_label + " " + REGION[p.region] + " " +
             p.tilbud.map((t) => butikknavn(t[0])).join(" ")).toLowerCase(),
    }));
    ferskhet(snap.sist_skannet, snap.skanning_ok);
    tegnProdukter();
  } catch (e) {
    $("liste").innerHTML =
      '<p class="tom">Fikk ikke kontakt med API-et.<br><small>' + esc(e.message) + "</small></p>";
    prikkstatus("nede", "ingen kontakt");
  }
}

function prikkstatus(klasse, tekst) {
  $("prikk").className = "prikk " + klasse;
  $("ferskhet-tekst").textContent = tekst;
}

function ferskhet(iso, ok) {
  if (!iso) return prikkstatus("nede", "ukjent");
  const min = (Date.now() - new Date(iso)) / 60000;
  prikkstatus(min < 45 && ok !== false ? "ok" : min < 180 ? "gammel" : "nede", siden(iso));
}

/* ----------------------------------------------------------- produkter */

function filtrert() {
  const q = state.sok.trim().toLowerCase();
  const ord = q ? q.split(/\s+/) : [];
  return state.produkter.filter((p) => {
    if (state.kunLager && !p.antall_pa_lager) return false;
    if (state.region && p.region !== state.region) return false;
    if (state.type && p.type_id !== state.type) return false;
    return ord.every((o) => p._sok.includes(o));
  });
}

function tegnProdukter() {
  const treff = filtrert();
  const liste = $("liste");
  $("tom-liste").hidden = treff.length > 0;
  $("teller").textContent = treff.length
    ? treff.length + " produkter" + (state.kunLager ? " pa lager" : "") +
      " · " + new Set(treff.map((p) => p.set_id)).size + " sett"
    : "";

  const grupper = new Map();
  for (const p of treff) {
    if (!grupper.has(p.set_id)) grupper.set(p.set_id, []);
    grupper.get(p.set_id).push(p);
  }

  let html = "";
  for (const [, produkter] of grupper) {
    const f = produkter[0];
    html += '<div class="sett-tittel">' + esc(f.set_label) +
      (f.region !== "en" ? ' <span class="merkelapp ' + f.region + '">' +
        esc(REGION[f.region] || f.region) + "</span>" : "") + "</div>";
    for (const p of produkter) html += kortHtml(p);
  }
  liste.innerHTML = html;
}

function kortHtml(p) {
  const antall = Number(p.antall_pa_lager) || 0;
  const pris = kr(p.min_pris);
  return '<button class="kort" data-produkt="' + esc(p.id) + '">' +
    '<span class="kort-venstre">' +
      '<span class="kort-navn">' + esc(p.type_label) + "</span>" +
      '<span class="kort-under">' + p.tilbud.length + " tilbud</span>" +
    "</span>" +
    '<span class="kort-hoyre">' +
      (pris ? '<span class="pris">' + pris + "</span>"
            : '<span class="pris ingen">ikke pa lager</span>') +
      '<div class="lager ' + (antall ? "inne" : "ute") + '">' +
        (antall ? antall + " butikk" + (antall > 1 ? "er" : "") + " inne" : "–") +
      "</div>" +
    "</span></button>";
}

/* ---------------------------------------------------------------- ark */

async function apneProdukt(id) {
  visArk('<p class="hjelp">Laster…</p>');
  try {
    const d = await hent("/product/" + encodeURIComponent(id));
    const p = d.produkt;
    let h = "<h2>" + esc(p.set_label) + " — " + esc(p.type_label) + "</h2>" +
      '<div class="ark-under"><span class="merkelapp ' + p.region + '">' +
      esc(REGION[p.region] || p.region) + "</span><span>" + d.tilbud.length +
      " tilbud hos " + new Set(d.tilbud.map((t) => t.store_id)).size + " butikker</span></div>";

    const inne = d.tilbud.filter((t) => t.in_stock === true);
    const ute = d.tilbud.filter((t) => t.in_stock !== true);
    if (inne.length) h += "<h3>Pa lager</h3>" + inne.map(tilbudHtml).join("");
    if (ute.length) h += "<h3>Ikke pa lager</h3>" + ute.map(tilbudHtml).join("");

    if (d.hendelser.length) {
      h += "<h3>Historikk</h3>" + d.hendelser.slice(0, 20).map((e) => {
        const m = HENDELSE[e.kind] || { ikon: "?", ord: e.kind };
        return '<div class="hendelse"><span class="hendelse-ikon k-' + e.kind + '">' +
          m.ikon + '</span><span class="kort-venstre"><span class="kort-navn">' +
          esc(butikknavn(e.store_id)) + " · " + m.ord + '</span><span class="hendelse-tid">' +
          siden(e.detected_at) + (e.price_ore ? " · " + kr(e.price_ore) : "") +
          "</span></span></div>";
      }).join("");
    }
    $("ark-innhold").innerHTML = h;
  } catch (e) {
    $("ark-innhold").innerHTML = '<p class="tom">Klarte ikke a hente produktet.</p>';
  }
}

function tilbudHtml(t) {
  return '<a class="tilbud" href="' + esc(t.url) + '" target="_blank" rel="noopener nofollow">' +
    '<span class="tilbud-venstre"><span class="tilbud-butikk">' +
      esc(t.store_name || butikknavn(t.store_id)) + "</span>" +
    '<span class="tilbud-tittel">' + esc(t.title) + "</span></span>" +
    '<span class="pris">' + (kr(t.price_ore) || "–") + '</span><span class="pil">›</span></a>';
}

function visArk(html) {
  $("ark-innhold").innerHTML = html;
  $("ark").hidden = false;
  $("ark-bakgrunn").hidden = false;
  document.body.style.overflow = "hidden";
}

function lukkArk() {
  $("ark").hidden = true;
  $("ark-bakgrunn").hidden = true;
  document.body.style.overflow = "";
}

/* ----------------------------------------------------------- hendelser */

async function lastHendelser() {
  const kinds = [...state.hendelseKinds];
  const boks = $("hendelser");
  boks.innerHTML = '<p class="hjelp">Laster…</p>';
  try {
    const d = await hent("/history?limit=150&timer=336" +
      (kinds.length ? "&kind=" + kinds.join(",") : ""));
    if (!d.hendelser.length) {
      boks.innerHTML = '<p class="tom">Ingen hendelser i denne perioden enna.</p>';
      return;
    }
    boks.innerHTML = d.hendelser.map((e) => {
      const m = HENDELSE[e.kind] || { ikon: "?", ord: e.kind };
      const navn = e.set_label ? e.set_label + " — " + e.type_label : (e.title || "Ukjent vare");
      const pris = e.kind === "prisendring" && e.prev_price_ore
        ? '<span class="gjennomstreket">' + kr(e.prev_price_ore) + "</span> " + kr(e.price_ore)
        : (kr(e.price_ore) || "");
      return '<div class="kort"' + (e.url ? ' data-lenke="' + esc(e.url) + '"' : "") + ">" +
        '<span class="hendelse-ikon k-' + e.kind + '">' + m.ikon + "</span>" +
        '<span class="kort-venstre"><span class="kort-navn">' + esc(navn) + "</span>" +
        '<span class="kort-under">' + esc(e.store_name || butikknavn(e.store_id)) +
        " · " + m.ord + " · " + siden(e.detected_at) + "</span></span>" +
        '<span class="kort-hoyre"><span class="pris">' + pris + "</span></span></div>";
    }).join("");
  } catch (e) {
    boks.innerHTML = '<p class="tom">Klarte ikke a hente hendelser.</p>';
  }
}

/* -------------------------------------------------------- andre varer */

async function lastAndre() {
  if (state.andre.length) return;
  $("andre").innerHTML = '<p class="hjelp">Laster…</p>';
  try {
    const d = await hent("/unmatched?limit=3000");
    state.andre = d.varer;
    state.andreVist = 0;
    $("andre").innerHTML = "";
    visMerAndre();
  } catch (e) {
    $("andre").innerHTML = '<p class="tom">Klarte ikke a hente varene.</p>';
  }
}

function visMerAndre() {
  const bit = state.andre.slice(state.andreVist, state.andreVist + 60);
  $("andre").insertAdjacentHTML("beforeend", bit.map((v) =>
    '<a class="kort" href="' + esc(v.url) + '" target="_blank" rel="noopener nofollow">' +
    '<span class="kort-venstre"><span class="kort-navn">' + esc(v.title) + "</span>" +
    '<span class="kort-under">' + esc(butikknavn(v.store_id)) + "</span></span>" +
    '<span class="kort-hoyre"><span class="pris">' + (kr(v.price_ore) || "–") + "</span>" +
    '<div class="lager ' + (v.in_stock ? "inne" : "ute") + '">' +
    (v.in_stock ? "pa lager" : "–") + "</div></span></a>").join(""));
  state.andreVist += bit.length;
  $("mer-andre").hidden = state.andreVist >= state.andre.length;
}

/* ------------------------------------------------------------- hendel. */

function byttFane(navn) {
  state.fane = navn;
  for (const el of document.querySelectorAll(".fane-knapp")) {
    const p = el.dataset.fane === navn;
    el.classList.toggle("valgt", p);
    el.setAttribute("aria-selected", String(p));
  }
  $("fane-produkter").hidden = navn !== "produkter";
  $("fane-nytt").hidden = navn !== "nytt";
  $("fane-andre").hidden = navn !== "andre";
  document.querySelector(".sok-rad").hidden = navn !== "produkter";
  $("chips").hidden = navn !== "produkter";
  if (navn === "nytt") lastHendelser();
  if (navn === "andre") lastAndre();
  scrollTo({ top: 0 });
}

function koble() {
  $("sok").addEventListener("input", (e) => {
    state.sok = e.target.value;
    $("tom-sok").hidden = !state.sok;
    tegnProdukter();
  });
  $("tom-sok").addEventListener("click", () => {
    $("sok").value = ""; state.sok = ""; $("tom-sok").hidden = true; tegnProdukter();
  });

  $("chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    const { filter, verdi } = c.dataset;
    if (filter === "lager") state.kunLager = !state.kunLager;
    else state[filter] = state[filter] === verdi ? null : verdi;
    for (const el of $("chips").children) {
      const f = el.dataset.filter;
      const pa = f === "lager" ? state.kunLager : state[f] === el.dataset.verdi;
      el.classList.toggle("pa", pa);
      el.classList.toggle("chip-av", !pa);
    }
    tegnProdukter();
  });

  $("hendelse-chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    const k = c.dataset.kind;
    state.hendelseKinds.has(k) ? state.hendelseKinds.delete(k) : state.hendelseKinds.add(k);
    c.classList.toggle("pa", state.hendelseKinds.has(k));
    lastHendelser();
  });

  document.addEventListener("click", (e) => {
    const kort = e.target.closest("[data-produkt]");
    if (kort) return apneProdukt(kort.dataset.produkt);
    const lenke = e.target.closest("[data-lenke]");
    if (lenke) window.open(lenke.dataset.lenke, "_blank", "noopener");
  });

  for (const b of document.querySelectorAll(".fane-knapp"))
    b.addEventListener("click", () => byttFane(b.dataset.fane));

  $("ark-lukk").addEventListener("click", lukkArk);
  $("ark-bakgrunn").addEventListener("click", lukkArk);
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") lukkArk(); });
  $("mer-andre").addEventListener("click", visMerAndre);
  $("ferskhet").addEventListener("click", () => last());

  // Marker startfiltrene som pa.
  for (const el of $("chips").children)
    if (el.dataset.filter === "lager") el.classList.add("pa");
  for (const el of $("hendelse-chips").children)
    if (state.hendelseKinds.has(el.dataset.kind)) el.classList.add("pa");

  // Hent friske data nar fanen kommer tilbake i forgrunnen, men ikke oftere
  // enn hvert minutt -- scraperen kjorer uansett bare hvert 20.
  let sistLastet = Date.now();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - sistLastet > 60000) {
      sistLastet = Date.now();
      last();
    }
  });
}

koble();
last();

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
