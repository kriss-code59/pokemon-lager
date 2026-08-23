/* Pokepuls frontend.
 *
 * Henter ETT lite snapshot (kanoniske produkter med tilbud under seg) i
 * stedet for 5,8 MB data.json. Alt filtrering skjer i minnet -- 460
 * produkter er ingenting, og det gjor soket umiddelbart.
 *
 * Ingen rammeverk, ingen byggesteg: filen som ligger pa serveren er filen
 * som kjorer. Det er det som gjor at neste okt kan endre den uten a sette
 * opp en verktoykjede forst.
 */

const API = location.hostname === "localhost" || location.hostname === "127.0.0.1"
  ? "http://127.0.0.1:8001/api" : "/api";

const $ = (id) => document.getElementById(id);

/* «Engelsk», ikke «Vestlig». Butikkene, Facebook-gruppene og folk flest sier
 * engelsk om denne utgaven -- «vestlig» er et ord fra samlermiljoet som en
 * ny kjoper ma oversette i hodet for a bruke filteret. */
const REGION = { en: "Engelsk", jp: "Japansk", cn: "Kinesisk", ko: "Koreansk" };
const HENDELSE = {
  restock: { ikon: "↑", ord: "på lager igjen" },
  ny: { ikon: "✦", ord: "ny vare" },
  prisendring: { ikon: "kr", ord: "ny pris" },
  utsolgt: { ikon: "↓", ord: "utsolgt" },
};

/* Hvor lenge en hendelse regnes som «nylig». 24 timer er valgt fordi det er
 * omtrent sa lenge en restock er interessant: er den fortsatt inne dagen
 * etter, var det ikke en restock det hastet med. */
const NYLIG_MS = 24 * 3600 * 1000;

/* Forhandssalg og bestillingsvarer er IKKE «pa lager», men de er heller
 * ikke utsolgt. Butikkene setter available=true pa begge, sa uten dette
 * skillet sto varer du ikke kunne fa i hus som «Pa lager» -- og utloste
 * restock-varsel. Se katalog/tilgjengelighet.py. */
const BESTILLING = {
  forhandssalg: { kort: "Forhåndssalg", lang: "Kan forhåndsbestilles" },
  bestillingsvare: { kort: "Bestilles", lang: "Butikken skaffer den" },
};

const state = {
  produkter: [], typer: new Map(),
  sok: "", kunLager: true, forhandssalg: false, region: null, type: null,
  hendelseKinds: new Set(["restock"]),
  andre: [], andreVist: 0,
  fane: "produkter",
  bruker: null,        // null = ikke innlogget
  folger: new Map(),   // product_id -> abonnement-id
  folgerAlt: false,    // «foelg alt»: én rad uten product_id og set_id
  folgerSett: new Map(),  // set_id -> abonnement-id
  grenser: new Map(),     // product_id -> maks_pris_ore (null = ingen grense)
  premium: false,
  slipp: new Map(),    // set_id -> slippdato, for sett som ikke er ute enna
  // Sortering av bolkene. Huskes mellom besok -- den som har valgt
  // slippdato én gang, mener som regel det neste gang ogsaa.
  sortering: localStorage.getItem("pokepuls-sortering") || "nytt",
  // Liste eller rutenett. Huskes -- den som liker store bilder liker dem
  // ogsaa i morgen.
  visning: localStorage.getItem("pokepuls-visning") || "liste",
  maksPerTime: 5,      // brukerens timeskvote, hentet fra serveren
  apentProdukt: null,
};

/* ------------------------------------------------------------- verktoy */

/* TESTOMRAADE.
 *
 * /ny serverer NOYAKTIG samme fil som forsiden. Forskjellen er dette
 * flagget: funksjoner som ikke er godkjent enna er paa der og av her.
 *
 * Hvorfor ikke en kopi av appen: denne filen er over 2000 linjer. En fork
 * ville blitt to forsider aa holde i takt, og den ene ville blitt glemt
 * neste gang noen rettet en feil. Aa skipe en funksjon betyr aa fjerne én
 * if-setning -- ikke aa flytte kode mellom to filer og haape.
 */
/* /ny er testomraadet.
 *
 * Flagget gjaldt fem funksjoner. Fire av dem er godkjent og staar naa paa
 * forsiden for alle -- restock-stripen, filterknappen, veien ut av en tom
 * liste og rutenettet. Aa skipe dem betyr aa fjerne en if-setning, og det
 * er nettopp det som skjedde her.
 *
 * Igjen staar butikkartet. Det bygger paa lagerdata vi enna ikke har
 * ordentlig -- bare Outland oppgir noe, og bare et antall -- saa det blir
 * paa /ny til kjedene er kartlagt.
 */
const KART_PAA_PROVE = location.pathname === "/ny";

const kr = (ore) => ore == null ? null :
  (ore % 100 === 0 ? (ore / 100).toLocaleString("nb-NO")
                   : (ore / 100).toLocaleString("nb-NO", { minimumFractionDigits: 2 })) + " kr";

function siden(iso) {
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "nå";
  if (min < 60) return min + " min siden";
  const t = Math.round(min / 60);
  if (t < 24) return t + " t siden";
  return Math.round(t / 24) + " d siden";
}

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* Butikknavn fra butikk-id.
 *
 * /snapshot sender bare id-en ("pokenordic") -- a sende navnet med hver
 * eneste tilbudsrad ville lagt pa flere kilobyte for informasjon som er den
 * samme overalt. /catalog har de ekte navnene, og lastes samtidig.
 *
 * Reserven under er en ren slug-oppdeling, og den tar feil av navn med
 * indre stor bokstav: "pokenordic" blir "Pokenordic", ikke "PokeNordic".
 * Derfor er den bare en reserve, ikke hovedveien. */
const butikkNavn = new Map();
const butikknavn = (id) => butikkNavn.get(id) ||
  (id || "").split("-").map((d) => d.charAt(0).toUpperCase() + d.slice(1)).join(" ");

/* ------------------------------------------------------------- bilder */

/* Butikkene har ikke bilde pa alt. I stedet for et tomt hull tegner vi en
 * enkel silhuett av varetypen i regionens farge -- da ser listen hel ut,
 * og du ser hva slags produkt det er selv uten foto. */
const REGIONFARGE = { en: "#4c9aff", jp: "#ff8a8a", cn: "#ffd479", ko: "#9ec1ff" };

const FORM = {
  "booster-box": '<rect x="14" y="22" width="36" height="26" rx="3"/><path d="M14 30h36M32 22v26"/>',
  "jumbo-booster-box": '<rect x="10" y="18" width="44" height="32" rx="3"/><path d="M10 28h44M32 18v32"/>',
  etb: '<rect x="16" y="18" width="32" height="30" rx="3"/><path d="M16 27h32"/><circle cx="32" cy="37" r="4"/>',
  "premium-collection": '<rect x="12" y="20" width="40" height="28" rx="3"/><path d="M12 29h40"/><circle cx="32" cy="38" r="5"/>',
  "collection-box": '<rect x="14" y="20" width="36" height="28" rx="3"/><path d="M14 29h36"/>',
  bundle: '<rect x="18" y="16" width="12" height="32" rx="2"/><rect x="34" y="16" width="12" height="32" rx="2"/>',
  blister: '<rect x="20" y="14" width="24" height="36" rx="4"/><path d="M20 24h24"/>',
  tin: '<rect x="16" y="22" width="32" height="24" rx="6"/><path d="M16 30h32"/>',
  "mini-tin": '<rect x="22" y="26" width="20" height="18" rx="5"/><path d="M22 32h20"/>',
  "booster-pack": '<rect x="22" y="14" width="20" height="36" rx="2"/><path d="M22 22h20"/>',
  "jumbo-booster-pack": '<rect x="18" y="12" width="28" height="40" rx="2"/><path d="M18 22h28"/>',
  "league-battle-deck": '<rect x="16" y="22" width="32" height="22" rx="3"/><path d="M24 22v22"/>',
};

function reservebilde(p) {
  const farge = REGIONFARGE[p.region] || "#8b95a3";
  const form = FORM[p.type_id] || '<rect x="16" y="20" width="32" height="26" rx="3"/>';
  const svg =
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">' +
    // Fyllet var #1b2027 -- noyaktig samme farge som rammen bak i
    // rutenettet. Et bilde som feilet saa da ut som en tom boks, og det
    // var umulig aa se forskjell paa «mangler bilde» og «her er det
    // ingenting». Litt lysere, saa silhuetten leses.
    '<rect width="64" height="64" rx="10" fill="#232a33"/>' +
    '<g fill="none" stroke="' + farge + '" stroke-width="2.4" stroke-linejoin="round" opacity="0.85">' +
    form + "</g></svg>";
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function bildeHtml(p, klasse) {
  const reserve = reservebilde(p);
  const src = p.bilde || reserve;
  // referrerpolicy="no-referrer" -- MAALT, IKKE GJETTET.
  //
  // Bildene laa der (97 % dekning), URL-ene svarte 200 fra serveren, og
  // likevel var rutene tomme i nettleseren. Forskjellen er Referer:
  // curl sender ingen, nettleseren sender «https://pokepuls.no».
  // Flere Shopify-butikker avviser fremmede henvisere paa bilde-CDN-en.
  //
  // Uten henviser ser CDN-en et helt vanlig bildekall. Vi ber ikke om noe
  // vi ikke har lov til -- vi slutter aa fortelle hvem som spor.
  return '<img class="' + klasse + '" loading="lazy" decoding="async" ' +
    'referrerpolicy="no-referrer" alt="" ' +
    'src="' + esc(src) + '" onerror="this.onerror=null;this.src=\'' + reserve + '\'">';
}

/* ---------------------------------------------------------------- data */

async function hent(sti, valg) {
  const r = await fetch(API + sti, {
    credentials: "same-origin",
    headers: { Accept: "application/json", ...(valg && valg.body ? { "Content-Type": "application/json" } : {}) },
    ...valg,
  });
  const tekst = await r.text();
  const data = tekst ? JSON.parse(tekst) : null;
  if (!r.ok) throw new Error((data && data.detail) || (sti + " svarte " + r.status));
  return data;
}

async function last() {
  try {
    const [snap, kat] = await Promise.all([hent("/snapshot"), hent("/catalog")]);
    kat.types.forEach((t) => state.typer.set(t.id, t.label));
    // Ma fylles for _sok bygges under: ellers indekseres "Pokenordic" og
    // et sok pa "pokenordic" gir treff mens "PokeNordic" i listen ikke gjor.
    (kat.stores || []).forEach((b) => butikkNavn.set(b.id, b.name));
    // Slippdato kommer fra katalogen, ikke fra en dato skrevet inn i denne
    // filen. Neste sett som skal telles ned til krever da én rad i
    // katalog.json og ingen endring her.
    (kat.sets || []).forEach((s) => {
      if (s.release_date) state.slipp.set(s.id, s.release_date);
    });
    state.produkter = snap.produkter.map((p) => ({
      ...p,
      _sok: (p.set_label + " " + p.type_label + " " + REGION[p.region] + " " +
             p.tilbud.map((t) => butikknavn(t[0])).join(" ")).toLowerCase(),
    }));
    ferskhet(snap.sist_skannet, snap.skanning_ok);
    tegnProdukter();
    tegnSlippBoks();
    tegnRestockStripe();
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

/* «INGEN TREFF» ER EN BLINDVEI.
 *
 * Slaar du paa tre filtre og treffer null, sto det bare «Ingen treff. Prov
 * et annet sok, eller slaa av filtrene» -- og saa maatte du selv gjette
 * HVILKET filter som var for strengt.
 *
 * Naa regner vi ut hva hvert enkelt filter koster: fjern ett om gangen, se
 * hvor mange som da dukker opp, og tilby det som gir flest. Det er billig
 * -- listen er noen tusen rader -- og det er forskjellen paa en vegg og en
 * dor.
 */
function tegnTomListe() {
  const boks = $("tom-liste");
  if (!boks) return;
  const aktive = aktiveFiltre();
  if (!aktive.length) {
    boks.textContent = state.sok
      ? "Ingen treff på «" + state.sok + "»."
      : "Ingen treff.";
    return;
  }

  // Prov aa fjerne ett filter om gangen og se hva som da ville matchet.
  const sikkerhetskopi = {
    kunLager: state.kunLager, forhandssalg: state.forhandssalg,
    region: state.region, type: state.type,
  };
  let best = null;
  for (const [navn, tekst] of aktive) {
    nullstillFilter(navn);
    const antall = filtrert().length;
    Object.assign(state, sikkerhetskopi);
    if (antall && (!best || antall > best.antall)) best = { navn, tekst, antall };
  }
  Object.assign(state, sikkerhetskopi);

  boks.innerHTML = "Ingen treff med filtrene du har på." +
    (best ? '<button class="lenkeknapp" type="button" data-fjern="' + best.navn +
      '">Vis ' + best.antall + " produkter uten «" + esc(best.tekst) + "»</button>"
          : "");
}

/* RESTOCK-STRIPEN -- det eneste som haster paa siden.
 *
 * Forsiden hadde ingen hastegrad: alt saa like viktig ut, og det som
 * nettopp kom inn laa begravd i listen. Nytt-fanen finnes, men den maa man
 * oppsoke -- og den som skal rekke en booster box rekker ikke aa lete.
 *
 * Bare siste time. En restock fra i gaar er ikke haster, den er historikk,
 * og den hoerer hjemme i Nytt-fanen.
 *
 * Er ingenting kommet inn, kollapser den til én stille linje. En tom
 * fremhevet blokk roper like hoyt som en full, og da slutter folk aa se
 * paa den.
 */
const STRIPE_VINDU_MS = 60 * 60 * 1000;

function restockNylig() {
  const na = Date.now();
  return state.produkter
    .filter((p) => Number(p.antall_pa_lager) && p.sist_hendelse)
    .map((p) => ({ p, t: new Date(p.sist_hendelse).getTime() }))
    .filter((x) => na - x.t < STRIPE_VINDU_MS)
    .sort((a, b) => b.t - a.t)
    .slice(0, 3);
}

function tegnRestockStripe() {
  const boks = $("restock-stripe");
  if (!boks) return;
  const nylig = restockNylig();
  boks.hidden = false;

  if (!nylig.length) {
    boks.className = "stripe-stille";
    boks.textContent = "Ingenting nytt inn den siste timen.";
    return;
  }

  boks.className = "stripe";
  boks.innerHTML =
    '<div class="stripe-topp"><span class="stripe-merke">På lager nå</span>' +
    '<span class="stripe-antall">' + nylig.length + " siste time</span></div>" +
    nylig.map(({ p }) => {
      // billigsteButikk() gir NAVNET, ikke tuppelen. Den detaljen kostet
      // meg en runde -- b[0] ville gitt forste bokstav i butikknavnet.
      const butikk = billigsteButikk(p);
      return '<button class="stripe-rad" type="button" data-produkt="' + esc(p.id) + '">' +
        '<img class="stripe-bilde" referrerpolicy="no-referrer" src="' +
          esc(p.bilde || reservebilde(p)) + '" alt="">' +
        '<span class="stripe-tekst"><span class="stripe-navn">' +
          esc(p.set_label) + " " + esc(p.type_label) + "</span>" +
        '<span class="stripe-meta">' + esc(butikk || "") +
          " · " + esc(siden(p.sist_hendelse)) + "</span></span>" +
        '<span class="stripe-pris">' + esc(kr(p.min_pris) || "") + "</span></button>";
    }).join("");
}

/* ----------------------------------------------------------- produkter */

function filtrert() {
  const q = state.sok.trim().toLowerCase();
  const ord = q ? q.split(/\s+/) : [];
  return state.produkter.filter((p) => {
    // Forhaandssalg er et EGET filter, ikke en oppmyking av «kun paa lager».
    // De to spor om helt ulike ting: «hva kan jeg kjope na» og «hva kan jeg
    // sikre meg for alle andre». Blander man dem, mister «paa lager» sin
    // betydning -- og det er den betydningen restock-varselet hviler paa.
    if (state.forhandssalg && !Number(p.antall_forhandssalg)) return false;
    if (state.kunLager && !state.forhandssalg && !p.antall_pa_lager) return false;
    if (state.region && p.region !== state.region) return false;
    if (state.type && p.type_id !== state.type) return false;
    return ord.every((o) => p._sok.includes(o));
  });
}

/* Nedtelling til et sett som ikke er ute enna.
 *
 * Staar UTENFOR den filtrerte listen med vilje. Et sett som ikke er sluppet
 * har null varer paa lager, og standardfilteret er «kun paa lager» -- saa
 * det mest etterspurte settet i aaret ville vaert usynlig helt fram til
 * slippdagen. Det er presis feil dag aa bli synlig paa: hele poenget er aa
 * sikre seg FOR alle andre.
 *
 * Boksen viser bare det ene settet som er naermest slipp. Tre nedtellinger
 * over hverandre er ingen nedtelling.
 */
function slippBoksHtml() {
  const naa = Date.now();
  const kommende = [...state.slipp.entries()]
    .map(([id, dato]) => ({ id, dato, tid: new Date(dato + "T00:00:00+02:00").getTime() }))
    .filter((s) => s.tid > naa)
    .sort((a, b) => a.tid - b.tid);
  if (!kommende.length) return "";

  const s = kommende[0];
  const produkter = state.produkter.filter((p) => p.set_id === s.id);
  if (!produkter.length) return "";

  const navn = produkter[0].set_label;
  const dager = Math.ceil((s.tid - naa) / 86400000);
  // TRE tilstander, ikke to. Skillet mellom «ingen butikk har varen» og
  // «butikkene har lagt den ut, men ingen selger den akkurat na» er hele
  // poenget rett for et slipp: det siste betyr at butikkene staar klare, og
  // at det kan skje naar som helst. Sa dem i samme sekk, og teksten sier
  // «ingenting skjer» pa akkurat det tidspunktet det er mest som skjer.
  const apne = new Set();      // tar bestilling NA
  const klare = new Set();     // har lagt ut varen, men ikke kjopbar
  let billigst = null;
  for (const p of produkter) {
    for (const t of p.tilbud || []) {
      klare.add(t[0]);
      if (t[2] === 1 && t[3] === "forhandssalg") {
        apne.add(t[0]);
        if (t[1] && (billigst === null || t[1] < billigst)) billigst = t[1];
      }
    }
  }
  const butikkord = (n) => n + (n === 1 ? " butikk" : " butikker");

  return '<div class="slipp">' +
    '<div class="slipp-topp"><span class="slipp-dager">' + dager + "</span>" +
    '<span class="slipp-tekst">' + (dager === 1 ? "dag" : "dager") + " til<br><strong>" +
      esc(navn) + "</strong></span></div>" +
    '<p class="hjelp">Slippes ' + esc(nyNorskDato(s.dato)) + ", samtidig i hele verden. " +
    (apne.size
      ? butikkord(apne.size) + " tar forhåndsbestilling nå" +
        (billigst ? ", fra " + kr(billigst) : "") + "."
      : klare.size
        ? butikkord(klare.size) + " har lagt ut varene, men ingen tar " +
          "bestilling akkurat nå."
        : "Ingen norske butikker har lagt ut settet ennå.") + "</p>" +
    '<p class="hjelp liten">Følg settet, så får du beskjed i det en butikk ' +
    "åpner forhåndssalg — og igjen når varen faktisk kommer på lager.</p>" +
    settFolgesHtml(s.id, navn) +
    '<p class="feil" id="slipp-feil" hidden></p>' +
    '<button class="lenkeknapp" id="slipp-vis" type="button">' +
      (produkter.length === 1 ? "Vis produktet"
                              : "Vis alle " + produkter.length + " produktene") +
      "</button>" +
    // Boksen viser ETT sett -- det naermeste. Den som bryr seg om slipp,
    // bryr seg som regel om de neste ogsaa, og fram til naa fantes veien
    // dit bare i bunnteksten.
    '<a class="lenkeknapp" href="/kalender">Hele slippkalenderen</a>' +
    "</div>";
}

function nyNorskDato(iso) {
  const m = ["januar", "februar", "mars", "april", "mai", "juni", "juli",
             "august", "september", "oktober", "november", "desember"];
  const d = new Date(iso + "T00:00:00+02:00");
  return d.getDate() + ". " + m[d.getMonth()] + " " + d.getFullYear();
}

function tegnSlippBoks() {
  const boks = $("slipp-boks");
  if (!boks) return;
  const html = slippBoksHtml();
  boks.innerHTML = html;
  boks.hidden = !html;
  if (!html) return;

  const knapp = $("folg-sett");
  if (knapp) knapp.addEventListener("click", async () => {
    knapp.disabled = true;
    const feil = $("slipp-feil");
    feil.hidden = true;
    try {
      await vekslFolgSett(knapp.dataset.sett);
      tegnSlippBoks();
      tegnProdukter();
    } catch (e) {
      feil.textContent = e.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  });

  const vis = $("slipp-vis");
  if (vis) vis.addEventListener("click", () => {
    // Sok pa settnavnet og slipp lagerfilteret: settet er ikke ute enna, sa
    // «kun paa lager» ville gitt null treff og sett ut som en feil.
    const navn = $("slipp-boks").querySelector("strong").textContent;
    $("sok").value = navn;
    state.sok = navn.toLowerCase();
    state.kunLager = false;
    for (const el of $("chips").children) {
      if (el.dataset.filter === "lager") {
        el.classList.remove("pa");
        el.classList.add("chip-av");
      }
    }
    $("tom-sok").hidden = false;
    tegnProdukter();
  });
}

/* AKTIVE FILTRE SOM FJERNBARE CHIPS.
 *
 * Radene med filterknapper tok mesteparten av mobilskjermen for forste
 * produkt kom til syne -- to varer over folden. Én knapp med teller, og de
 * valgte filtrene som chips du kan trykke bort.
 *
 * Filtrene selv er UENDRET: dette leser og skriver samme state som
 * chip-radene, og chip-radene ligger fortsatt i panelet bak knappen. Vi
 * bygget ikke et nytt filtersystem, vi flyttet inngangen til det.
 */
function aktiveFiltre() {
  const ut = [];
  if (state.kunLager) ut.push(["lager", "På lager"]);
  if (state.forhandssalg) ut.push(["forhandssalg", "Forhåndssalg"]);
  if (state.region) ut.push(["region", REGION[state.region] || state.region]);
  if (state.type) ut.push(["type", state.typer.get(state.type) || state.type]);
  return ut;
}

function nullstillFilter(navn) {
  if (navn === "lager") state.kunLager = false;
  else if (navn === "forhandssalg") state.forhandssalg = false;
  else if (navn === "region") state.region = null;
  else if (navn === "type") state.type = null;
  // Chip-radene bak panelet maa foelge med, ellers staar de og lyser paa
  // et filter som ikke lenger gjelder.
  for (const el of $("chips").children) {
    const f = el.dataset.filter;
    const paa = f === "lager" ? state.kunLager
      : f === "forhandssalg" ? state.forhandssalg
      : f === "region" ? state.region === el.dataset.verdi
      : f === "type" ? state.type === el.dataset.verdi : false;
    el.classList.toggle("chip-av", !paa);
  }
}

function tegnFilterlinje() {
  const linje = $("filterlinje");
  if (!linje) return;
  linje.hidden = state.fane !== "produkter";
  const aktive = aktiveFiltre();
  $("filterteller").hidden = !aktive.length;
  $("filterteller").textContent = aktive.length;
  $("aktive-filtre").innerHTML = aktive.map(([navn, tekst]) =>
    '<span class="aktiv-chip">' + esc(tekst) +
    '<button type="button" data-fjern="' + navn + '" aria-label="Fjern ' +
    esc(tekst) + '">&times;</button></span>').join("");
}

function tegnProdukter() {
  const treff = filtrert();
  const liste = $("liste");
  // RUTENETT MED STORE BILDER.
  //
  // Vi har bilde paa 487 av 496 produkter -- 98 %. De ble vist som 46
  // piksler brede miniatyrer, og da spiller det ingen rolle at vi har
  // dem. Konkurrenten viser pakkeskuddet stort, og DET er grunnen til at
  // deres side ser bedre ut -- ikke farger, ikke typografi.
  //
  // Listen beholdes: den viser «billigst hos X», som rutenettet ikke har
  // plass til. To maater aa se det samme paa, for to ulike sporsmaal.
  liste.classList.toggle("rutenett", state.visning === "rutenett");
  $("tom-liste").hidden = treff.length > 0;
  tegnFilterlinje();
  if (!treff.length) tegnTomListe();
  $("teller").textContent = treff.length
    ? treff.length + " produkter" +
      (state.forhandssalg ? " til forhåndsbestilling" : state.kunLager ? " på lager" : "") +
      " · " + new Set(treff.map((p) => p.set_id + p.region)).size + " sett"
    : "";
  liste.innerHTML = grupperHtml(treff);
}

/* Grupper pa sett OG region. Uten regionen havner den engelske, japanske
 * og kinesiske utgaven av samme sett i samme bolk, og listen ser ut til a
 * vise "Booster Box" tre ganger uten forklaring.
 *
 * Bolkene sorteres pa NYESTE HENDELSE, ikke alfabetisk. Alfabetisk er en
 * sortering for et arkiv: den setter «Ascended Heroes» overst hver eneste
 * dag uansett hva som har skjedd. Det du apner appen for a se, er hva som
 * er nytt -- sa det ligger overst. Sett uten aktivitet beholder sin
 * innbyrdes rekkefolge under. */
/* Slippdato for en bolk, som tall. Sett uten dato havner sist -- ikke
 * oeverst med tiden 0, som ville gjort ukjente sett til de nyeste. */
function slippTid(bolk) {
  const d = state.slipp.get(bolk.produkter[0].set_id);
  return d ? new Date(d).getTime() : -Infinity;
}

function grupperHtml(treff) {
  const grupper = new Map();
  for (const p of treff) {
    const nokkel = p.set_id + ":" + p.region;
    if (!grupper.has(nokkel)) grupper.set(nokkel, []);
    grupper.get(nokkel).push(p);
  }

  const NYLIG = 7 * 24 * 3600 * 1000;
  const na = Date.now();

  const bolker = [...grupper.values()].map((produkter, i) => {
    const tid = Math.max(...produkter.map((p) =>
      p.sist_hendelse ? new Date(p.sist_hendelse).getTime() : 0));
    return {
      produkter,
      tid,
      // TRE NIVAAER, IKKE ÉN TIDSSTEMPEL.
      //
      // For sorterte bolkene bare paa ferskeste hendelse. Da kunne et doedt
      // sett med én prisendring paa én obskur vare ligge over et sett med
      // tjue varer inne hos ti butikker. Du apner appen for aa se hva du
      // kan kjope -- et sett du ikke kan kjope noe fra er ikke svaret,
      // uansett hvor nylig noe skjedde med det.
      //
      // 2 = noe er paa lager naa
      // 1 = kan forhaandsbestilles
      // 0 = ingenting aa faa
      niva: produkter.some((p) => Number(p.antall_pa_lager)) ? 2
          : produkter.some((p) => Number(p.antall_forhandssalg)) ? 1 : 0,
      // Aktivitet teller bare hvis den er fersk. En restock fra i mars sier
      // ingenting om i dag, og lot gamle sett ligge oeverst i maanedsvis.
      fersk: tid && (na - tid) < NYLIG ? tid : 0,
      i,
    };
  });
  // Stabil sortering: like verdier beholder opprinnelig rekkefolge (som er
  // alfabetisk fra API-et). Array.prototype.sort er stabil i alle nettlesere
  // vi bryr oss om, men vi tar med `i` sa det ikke er noe a lure pa.
  if (state.sortering === "slipp") {
    // NYESTE SETT FORST. Et sett uten slippdato i katalogen havner sist --
    // ikke overst med tiden 0, som ville gitt en liste der ukjente sett
    // fortrengte dem vi faktisk vet naar kom.
    bolker.sort((a, b) => (slippTid(b) - slippTid(a)) || (a.i - b.i));
  } else if (state.sortering === "navn") {
    bolker.sort((a, b) =>
      a.produkter[0].set_label.localeCompare(b.produkter[0].set_label, "nb") ||
      (a.i - b.i));
  } else {
    // Kan du faa tak i det? Skjedde det noe nylig? Er settet nytt?
    // -- i den rekkefolgen. Siste ledd (a.i - b.i) holder alfabetisk
    // rekkefolge fra API-et for alt som ellers er likt.
    bolker.sort((a, b) =>
      (b.niva - a.niva) ||
      (b.fersk - a.fersk) ||
      (slippTid(b) - slippTid(a)) ||
      (a.i - b.i));
  }

  let html = "";
  for (const { produkter } of bolker) {
    const f = produkter[0];
    html += '<div class="sett-tittel">' + esc(f.set_label) +
      (f.region !== "en" ? ' <span class="merkelapp ' + f.region + '">' +
        esc(REGION[f.region] || f.region) + "</span>" : "") + "</div>";
    for (const p of produkter) html += kortHtml(p);
  }
  return html;
}

/* Billigste butikk med varen inne.
 *
 * tilbud er allerede sortert av API-et: pa lager forst, sa stigende pris.
 * Forste rad med pa_lager=1 er derfor den billigste kjopbare. */
function billigsteButikk(p) {
  // t[3] = bestillingstype. Et forhandssalg teller ikke som «billigst pa
  // lager» -- det er ikke det samme produktet i tid.
  const t = (p.tilbud || []).find((x) => x[2] === 1 && x[1] && !x[3]);
  return t ? butikknavn(t[0]) : null;
}

/* Billigste forhandssalg/bestilling, brukt nar ingen har varen inne. */
function billigsteBestilling(p) {
  const t = (p.tilbud || []).find((x) => x[2] === 1 && x[1] && x[3]);
  return t ? { butikk: butikknavn(t[0]), pris: t[1], type: t[3] } : null;
}

function rutenettKortHtml(p) {
  const antall = Number(p.antall_pa_lager) || 0;
  const pris = kr(p.min_pris);
  const best = antall ? null : billigsteBestilling(p);
  const folges = state.folger.has(p.id);
  const status = antall ? "inne" : best ? "forhand" : "ute";
  return '<button class="rutekort" data-produkt="' + esc(p.id) + '">' +
    '<span class="rutebilde">' + bildeHtml(p, "rutefoto") +
      (folges ? '<span class="rute-folges" title="Du følger denne">♥</span>' : "") +
    "</span>" +
    '<span class="rutenavn">' + esc(p.set_label) + " " + esc(p.type_label) + "</span>" +
    '<span class="rutebunn"><span class="ruteprikk ' + status + '"></span>' +
      '<span class="rutepris">' + (pris || (best ? kr(best.pris) : "–")) +
    "</span></span></button>";
}

function kortHtml(p) {
  if (state.visning === "rutenett") return rutenettKortHtml(p);
  const antall = Number(p.antall_pa_lager) || 0;
  const pris = kr(p.min_pris);
  const folges = state.folger.has(p.id);
  const hos = billigsteButikk(p);
  const best = antall ? null : billigsteBestilling(p);
  const tid = p.sist_hendelse ? new Date(p.sist_hendelse).getTime() : 0;
  const nylig = tid && Date.now() - tid < NYLIG_MS;

  return '<button class="kort" data-produkt="' + esc(p.id) + '">' +
    bildeHtml(p, "miniatyr") +
    '<span class="kort-venstre">' +
      '<span class="kort-navn">' + esc(p.type_label) +
        (folges ? ' <span class="folge-merke" title="Du følger denne">♥</span>' : "") +
        (nylig ? ' <span class="nylig">' + esc(siden(p.sist_hendelse)) + "</span>" : "") +
      "</span>" +
      // Under navnet star det som faktisk avgjor om du klikker: hvor den er
      // billigst. «6 tilbud» er et tall om databasen, ikke om varen.
      '<span class="kort-under">' +
        (hos ? "billigst hos " + esc(hos)
             : best ? esc(BESTILLING[best.type].lang) + " hos " + esc(best.butikk)
             : p.tilbud.length + " butikker følges") +
      "</span>" +
    "</span>" +
    '<span class="kort-hoyre">' +
      (pris ? '<span class="pris">' + pris + "</span>"
            : best ? '<span class="pris bestilling">' + kr(best.pris) + "</span>"
            : '<span class="pris ingen">ikke på lager</span>') +
      '<div class="lager ' + (antall ? "inne" : best ? "bestilling" : "ute") + '">' +
        (antall ? antall + " butikk" + (antall > 1 ? "er" : "") + " inne"
                : best ? esc(BESTILLING[best.type].kort) : "–") +
      "</div>" +
    "</span></button>";
}

/* ---------------------------------------------------------------- ark */

async function apneProdukt(id) {
  state.apentProdukt = id;
  visArk('<p class="hjelp">Laster…</p>');
  try {
    const d = await hent("/product/" + encodeURIComponent(id));
    const p = d.produkt;
    const iSnapshot = state.produkter.find((x) => x.id === id) || p;
    const bilde = d.tilbud.find((t) => t.image_url);
    let h = '<div class="ark-topp">' +
      (bilde ? '<img class="ark-bilde" referrerpolicy="no-referrer" ' +
               'src="' + esc(bilde.image_url) + '" alt="" ' +
               "onerror=\"this.onerror=null;this.src='" + reservebilde(iSnapshot) + "'\">"
             : '<img class="ark-bilde" src="' + reservebilde(iSnapshot) + '" alt="">') +
      '<div class="ark-tekst"><h2>' + esc(p.set_label) + "</h2>" +
      '<div class="ark-under"><span>' + esc(p.type_label) + "</span>" +
      '<span class="merkelapp ' + p.region + '">' + esc(REGION[p.region] || p.region) + "</span></div>" +
      '<button class="folg-knapp" id="folg-knapp" type="button"></button>' +
      '<div id="grense-boks"></div>' +
      '<div id="pris-historikk"></div>' +
      "</div></div>";

    // Tre bolker, ikke to. «Pa lager» skal bety at du kan fa den i posten;
    // et forhandssalg hoerer hjemme i sin egen bolk, ikke oeverst blant dem
    // som faktisk har varen.
    const inne = d.tilbud.filter((t) => t.in_stock === true && !t.bestillingstype);
    const bestill = d.tilbud.filter((t) => t.in_stock === true && t.bestillingstype);
    const ute = d.tilbud.filter((t) => t.in_stock !== true);
    if (inne.length) h += "<h3>På lager</h3>" + inne.map(tilbudHtml).join("");
    if (bestill.length) h += "<h3>Forhåndssalg og bestillingsvarer</h3>" +
      '<p class="hjelp liten">Kan legges i handlekurven, men sendes ikke nå.</p>' +
      bestill.map(tilbudHtml).join("");
    if (ute.length) h += "<h3>Ikke på lager</h3>" + ute.map(tilbudHtml).join("");

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
    tegnFolgKnapp();
  } catch (e) {
    $("ark-innhold").innerHTML = '<p class="tom">Klarte ikke a hente produktet.</p>';
  }
}

function tegnFolgKnapp() {
  const knapp = $("folg-knapp");
  if (!knapp) return;
  if (!state.bruker) {
    knapp.textContent = "Logg inn for å følge";
    knapp.className = "folg-knapp";
    knapp.onclick = apneKonto;
    return;
  }
  const folges = state.folger.has(state.apentProdukt);
  knapp.textContent = folges ? "♥ Følger" : "♡ Følg denne";
  knapp.className = "folg-knapp" + (folges ? " pa" : "");
  knapp.onclick = () => vekslFolg(state.apentProdukt);
  tegnGrense();
  tegnPrishistorikk();
}

/* «Varsle bare naar den er under X kr» -- per vare.
 *
 * Den globale grensen (hele kontoen) har ligget i databasen lenge og er
 * nesten ubrukelig: foelger du boosterpakker til 119 og bokser til 6 000,
 * finnes det ingen enkelt verdi som gir mening. Setter du 1 000, hoerer du
 * aldri om en boks igjen.
 *
 * Feltet vises bare naar du allerede foelger varen. Aa sette en grense paa
 * noe du ikke foelger er en innstilling uten virkning, og en innstilling
 * uten virkning er verre enn ingen. */
function tegnGrense() {
  const boks = $("grense-boks");
  if (!boks) return;
  const id = state.apentProdukt;
  if (!state.bruker || !state.folger.has(id)) { boks.innerHTML = ""; return; }

  if (!state.premium) {
    boks.innerHTML = '<p class="hjelp liten">Vil du bare varsles under en ' +
      'viss pris? <a href="/vilkar.html">Premium</a> lar deg sette en ' +
      "grense per vare.</p>";
    return;
  }

  const ore = state.grenser.get(id);
  boks.innerHTML =
    '<label class="grense">Varsle bare under ' +
    '<input id="grense-felt" type="number" inputmode="numeric" min="1" ' +
      'step="1" placeholder="ingen grense"' +
      (ore ? ' value="' + Math.round(ore / 100) + '"' : "") + "> kr</label>" +
    '<p class="feil" id="grense-feil" hidden></p>';

  const felt = $("grense-felt");
  felt.addEventListener("change", async () => {
    const feil = $("grense-feil");
    feil.hidden = true;
    const abonnement = state.folger.get(id);
    const kr = felt.value.trim() === "" ? null : Number(felt.value);
    try {
      const d = await hent("/watchlist/" + abonnement + "/grense", {
        method: "POST", body: JSON.stringify({ maks_pris_kr: kr }),
      });
      state.grenser.set(id, d.maks_pris_ore);
    } catch (e) {
      feil.textContent = e.message;
      feil.hidden = false;
    }
  });
}

/* Prishistorikk.
 *
 * En sparkline, ikke et diagrambibliotek. 180 punkter i en SVG er noen
 * hundre byte; et bibliotek er hundre kilobyte og et byggesteg vi ikke
 * har. Formen er det som betyr noe -- ikke aksene.
 *
 * Det viktigste tallet er ikke grafen, det er LAVESTE REGISTRERT. Det er
 * det som gjor at «3 999» blir til «3 999, og den har vaert nede i 3 199».
 * Uten den setningen er en pris bare et tall.
 */
function sparkline(punkter) {
  const v = punkter.map((p) => p.laveste);
  if (v.length < 2) return "";
  const lav = Math.min(...v), hoy = Math.max(...v);
  const spenn = hoy - lav || 1;
  const B = 280, H = 48;
  const d = v.map((y, i) =>
    (i ? "L" : "M") + (i / (v.length - 1) * B).toFixed(1) + " " +
    (H - (y - lav) / spenn * (H - 6) - 3).toFixed(1)).join(" ");
  return '<svg class="spark" viewBox="0 0 ' + B + " " + H + '" ' +
    'preserveAspectRatio="none" aria-hidden="true">' +
    '<path d="' + d + '" fill="none" stroke="currentColor" stroke-width="1.6" ' +
    'stroke-linejoin="round" stroke-linecap="round"/></svg>';
}

async function tegnPrishistorikk() {
  const boks = $("pris-historikk");
  if (!boks) return;
  boks.innerHTML = "";
  if (!state.bruker) return;

  const id = state.apentProdukt;
  let d;
  try {
    d = await hent("/statistikk/pris/" + encodeURIComponent(id));
  } catch (e) {
    // 402 = ikke betalt. Vis hva de gaar glipp av, ikke en feilmelding.
    if (/402/.test(e.message) || /premium/i.test(e.message)) {
      boks.innerHTML = '<p class="hjelp liten">Se prishistorikk og laveste ' +
        'registrerte pris med <a href="/om.html">Premium</a>.</p>';
    }
    return;
  }
  if (!d.laveste_ore) {
    boks.innerHTML = '<p class="hjelp liten">Ingen prishistorikk registrert ' +
      "for denne varen ennå.</p>";
    return;
  }
  const nar = d.laveste_nar
    ? new Date(d.laveste_nar).toLocaleDateString("nb-NO",
        { day: "numeric", month: "short", year: "numeric" })
    : null;
  boks.innerHTML = '<div class="historikk">' +
    '<div class="historikk-topp"><span>Laveste registrert</span>' +
    "<strong>" + kr(d.laveste_ore) + "</strong></div>" +
    sparkline(d.punkter) +
    '<p class="hjelp liten">' +
      (d.laveste_hos ? esc(d.laveste_hos) + (nar ? ", " + esc(nar) : "") + ". " : "") +
      "Laveste vi har <em>registrert</em> — historikken starter da vi begynte " +
      "å måle varen.</p></div>";
}

function tilbudHtml(t) {
  return '<a class="tilbud" href="' + esc(t.url) + '" target="_blank" rel="noopener nofollow">' +
    (t.image_url ? '<img class="tilbud-bilde" loading="lazy" src="' + esc(t.image_url) + '" alt="">' : "") +
    '<span class="tilbud-venstre"><span class="tilbud-butikk">' +
      esc(t.store_name || butikknavn(t.store_id)) + "</span>" +
    '<span class="tilbud-tittel">' + esc(t.title) + "</span></span>" +
    (t.bestillingstype
      ? '<span class="merkelapp bestilling">' +
        esc((BESTILLING[t.bestillingstype] || {}).kort || t.bestillingstype) + "</span>"
      : "") +
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
  state.apentProdukt = null;
}

/* ---------------------------------------------------------- konto */

async function lastBruker() {
  try {
    const d = await hent("/auth/me");
    state.bruker = d.innlogget ? d : null;
  } catch (e) {
    state.bruker = null;
  }
  $("konto-knapp").classList.toggle("innlogget", !!state.bruker);
  if (state.bruker) {
    await lastFolger();
    // Folgelisten kommer etter forste tegning. Uten denne omtegningen ser du
    // ingen hjerter for du tilfeldigvis rorer et filter.
    if (state.produkter.length) { tegnProdukter(); tegnSlippBoks(); }
  }
}

async function lastFolger() {
  try {
    const d = await hent("/watchlist");
    state.folger = new Map(d.folger.filter((f) => f.product_id).map((f) => [f.product_id, f.id]));
    state.folgerSett = new Map(
      d.folger.filter((f) => f.set_id && !f.product_id).map((f) => [f.set_id, f.id]));
    state.grenser = new Map(
      d.folger.filter((f) => f.product_id).map((f) => [f.product_id, f.maks_pris_ore]));
    // Serveren avgjor hva som er premium. Frontenden viser bare -- den
    // sperrer ikke, for et skjult felt er ingen sperre.
    state.premium = !!d.premium;
    // Serveren sier selv om «alt» er paa; vi utleder det ikke av radene.
    state.folgerAlt = !!d.alt;
    // Faller tilbake til 5 hvis feltet mangler -- en eldre server skal ikke
    // gi «du faar maks undefined varsler i timen».
    state.maksPerTime = d.maks_per_time || 5;
  } catch (e) {
    state.folger = new Map();
    state.folgerSett = new Map();
    state.grenser = new Map();
    state.premium = false;
    state.folgerAlt = false;
  }
}

async function vekslFolg(produktId) {
  try {
    if (state.folger.has(produktId)) {
      await hent("/watchlist/" + state.folger.get(produktId), { method: "DELETE" });
      state.folger.delete(produktId);
    } else {
      const d = await hent("/watchlist", {
        method: "POST",
        body: JSON.stringify({ product_id: produktId, kinds: ["restock", "ny"] }),
      });
      state.folger.set(produktId, d.id);
    }
    tegnFolgKnapp();
    tegnProdukter();
  } catch (e) {
    alert("Klarte ikke å lagre: " + e.message);
  }
}

/* «Foelg hele settet».
 *
 * API-et har stottet abonnement paa set_id siden dag én, men det har aldri
 * hatt en knapp -- noyaktig samme hull som «foelg alt» hadde. Uten den ma
 * du hake av ni produkttyper hver for seg for aa dekke ett sett, og da gjor
 * du det ikke.
 *
 * Det er dette som gjor forhaandssalg brukbart: du vet ikke HVILKEN
 * butikk som apner forst, eller om det blir ETB-en eller boksen. Foelger
 * du settet, treffer du uansett.
 */
function settFolgesHtml(settId, settNavn) {
  if (!state.bruker) return "";
  const paa = state.folgerSett.has(settId);
  return '<button class="hovedknapp' + (paa ? " av" : "") + '" ' +
    'id="folg-sett" type="button" data-sett="' + esc(settId) + '">' +
    (paa ? "Slutt å følge " + esc(settNavn) : "🔔 Følg hele " + esc(settNavn)) +
    "</button>";
}

async function vekslFolgSett(settId) {
  if (state.folgerSett.has(settId)) {
    await hent("/watchlist/" + state.folgerSett.get(settId), { method: "DELETE" });
  } else {
    await hent("/watchlist", {
      method: "POST",
      // Forhaandssalg kommer inn som «ny» naar butikken legger ut varen, og
      // som «restock» naar den gaar fra forhaandssalg til ekte lager. Begge
      // ma vaere med, ellers gaar du glipp av den ene halvparten.
      body: JSON.stringify({ set_id: settId, kinds: ["restock", "ny"] }),
    });
  }
  await lastFolger();
}

/* Premium.
 *
 * Boksen etterfylles, som varselseksjonen: den maa spore serveren om
 * betaling i det hele tatt er satt opp. Er den ikke det, staar det
 * ingenting her -- en halvkonfigurert betalingsloype skal ikke se ut som
 * en fungerende en.
 *
 * All logikk om HVEM som er premium ligger paa serveren. Denne filen kan
 * hvem som helst laste ned og endre. */
async function tegnPremium() {
  const boks = $("premium-boks");
  if (!boks) return;
  let d = null;
  try { d = await hent("/betaling/status"); } catch (e) { return; }
  if (!d || !d.paa) { boks.innerHTML = ""; return; }

  if (d.premium) {
    const til = d.gjelder_til
      ? new Date(d.gjelder_til).toLocaleDateString("nb-NO",
          { day: "numeric", month: "long", year: "numeric" })
      : null;
    boks.innerHTML = '<div class="varselboks"><h3>Premium</h3>' +
      '<p class="hjelp">Du har Pokepuls Premium' +
        (til ? ", betalt ut " + esc(til) : "") + ". Takk.</p>" +
      '<p class="hjelp liten">Du kan sette en prisgrense per vare: åpne en ' +
      "vare du følger, og skriv inn hva den må under for at vi skal si fra.</p>" +
      '<p class="hjelp liten"><a href="/statistikk.html">Restock-statistikk</a>' +
      " — hvilke butikker fyller på oftest, og når på døgnet.</p>" +
      '<button class="lenkeknapp" id="premium-portal" type="button">' +
      "Administrer eller si opp</button>" +
      '<p class="feil" id="premium-feil" hidden></p></div>';
  } else {
    boks.innerHTML = '<div class="varselboks"><h3>Pokepuls Premium</h3>' +
      '<p class="hjelp">' + d.pris_kr + " kr i måneden. Alt du bruker i dag " +
      "forblir gratis — Premium er bare i tillegg.</p>" +
      // Boksen listet ÉN ting. Vi bygde tre, og de to andre var usynlige
      // for den som skulle bestemme seg for aa betale.
      '<ul class="side-liste-tekst liten">' +
      "<li><strong>Prisgrense per vare.</strong> " +
      "«Si fra bare når denne boksen er under 3 999.»</li>" +
      "<li><strong>Prishistorikk.</strong> Se hva en vare har kostet før, " +
      "og hva som er det laveste vi har registrert — så du vet om " +
      "dagens pris faktisk er et kupp.</li>" +
      "<li><strong>Restock-statistikk.</strong> Hvilke butikker fyller på " +
      "oftest, og når på døgnet det pleier å skje.</li></ul>" +
      '<p class="hjelp liten"><a href="/statistikk.html">Se statistikken</a></p>' +
      '<button class="hovedknapp" id="premium-kjop" type="button">' +
      "Prøv Premium — " + d.pris_kr + " kr/mnd</button>" +
      '<p class="hjelp liten">Fornyes automatisk. Si opp når som helst. ' +
      '<a href="/vilkar.html">Vilkår</a>.</p>' +
      '<p class="feil" id="premium-feil" hidden></p></div>';
  }

  const vis = (e) => {
    const f = $("premium-feil");
    if (f) { f.textContent = e; f.hidden = !e; }
  };
  const gaaTil = async (sti, knapp) => {
    knapp.disabled = true;
    vis("");
    try {
      const r = await hent(sti, { method: "POST" });
      location.href = r.url;    // videre til Stripe -- vi ser aldri kortet
    } catch (e) {
      vis(e.message);
      knapp.disabled = false;
    }
  };
  const kjop = $("premium-kjop");
  if (kjop) kjop.addEventListener("click", () => gaaTil("/betaling/start", kjop));
  const portal = $("premium-portal");
  if (portal) portal.addEventListener("click", () => gaaTil("/betaling/portal", portal));
}

function apneKonto() {
  if (state.bruker) return visKontoSide();
  visArk(skjemaHtml("logg-inn"));
  koblSkjema();
}

function skjemaHtml(modus) {
  const erNy = modus === "registrer";
  return '<h2>' + (erNy ? "Lag konto" : "Logg inn") + "</h2>" +
    '<p class="hjelp">' + (erNy
      ? "Med konto kan du følge produkter og få push-varsel på telefonen i det de kommer på lager."
      : "Velkommen tilbake.") + "</p>" +
    '<form id="konto-skjema" class="skjema" novalidate>' +
      '<label>E-post<input id="k-epost" type="email" autocomplete="email" required></label>' +
      '<label>Passord<input id="k-passord" type="password" ' +
        'autocomplete="' + (erNy ? "new-password" : "current-password") + '" ' +
        'minlength="' + (erNy ? 8 : 1) + '" required></label>' +
      (erNy ? '<p class="hjelp liten">Minst 8 tegn.</p>' : "") +
      '<p class="feil" id="k-feil" hidden></p>' +
      '<button class="hovedknapp" type="submit">' + (erNy ? "Lag konto" : "Logg inn") + "</button>" +
    "</form>" +
    '<button class="lenkeknapp" id="bytt-modus" type="button" data-modus="' +
      (erNy ? "logg-inn" : "registrer") + '">' +
      (erNy ? "Har du konto? Logg inn" : "Ny her? Lag konto") + "</button>" +
    (erNy ? '<p class="hjelp liten">Ved å lage konto godtar du at vi lagrer ' +
            'e-postadressen din. <a href="/personvern.html">Slik behandler vi den.</a></p>'
          : '<button class="lenkeknapp" id="glemt-lenke" type="button">Glemt passord?</button>');
}

/* Glemt passord.
 *
 * Svaret er alltid det samme, uansett om adressen finnes -- se
 * /api/auth/glemt. Teksten her ma derfor ogsa vaere noytral: sier UI-et
 * «sjekk innboksen», mens serveren ikke sendte noe, er det ikke en lognn --
 * det er den eneste maaten a la vaere a rope ut hvem som har konto her. */
function glemtHtml() {
  return "<h2>Glemt passord</h2>" +
    '<p class="hjelp">Skriv e-posten din, så sender vi en lenke du kan lage ' +
    "nytt passord med. Lenken varer i én time.</p>" +
    '<form id="glemt-skjema" class="skjema" novalidate>' +
      '<label>E-post<input id="g-epost" type="email" autocomplete="email" required></label>' +
      '<p class="feil" id="g-feil" hidden></p>' +
      '<p class="hjelp" id="g-ok" hidden></p>' +
      '<button class="hovedknapp" type="submit">Send lenke</button>' +
    "</form>" +
    '<button class="lenkeknapp" id="tilbake-innlogging" type="button">Tilbake til innlogging</button>';
}

function koblGlemt() {
  const skjema = $("glemt-skjema");
  if (!skjema) return;
  skjema.addEventListener("submit", async (e) => {
    e.preventDefault();
    const knapp = skjema.querySelector("button[type=submit]");
    const feil = $("g-feil");
    const ok = $("g-ok");
    feil.hidden = true;
    knapp.disabled = true;
    try {
      const d = await hent("/auth/glemt", { method: "POST",
        body: JSON.stringify({ email: $("g-epost").value.trim() }) });
      ok.textContent = d.melding;
      ok.hidden = false;
      skjema.querySelector("label").hidden = true;
      knapp.hidden = true;
    } catch (err) {
      feil.textContent = err.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  });
  $("tilbake-innlogging").addEventListener("click", () => {
    visArk(skjemaHtml("logg-inn"));
    koblSkjema();
  });
}

function koblSkjema() {
  const skjema = $("konto-skjema");
  if (!skjema) return;
  skjema.addEventListener("submit", async (e) => {
    e.preventDefault();
    const erNy = skjema.parentElement.querySelector("#bytt-modus").dataset.modus === "logg-inn";
    const feil = $("k-feil");
    feil.hidden = true;
    const knapp = skjema.querySelector("button[type=submit]");
    knapp.disabled = true;
    try {
      await hent("/auth/" + (erNy ? "register" : "login"), {
        method: "POST",
        body: JSON.stringify({ email: $("k-epost").value.trim(), password: $("k-passord").value }),
      });
      await lastBruker();
      lukkArk();
      tegnProdukter();
      if (state.fane === "folger") tegnFolgerFane();
    } catch (err) {
      feil.textContent = err.message;
      feil.hidden = false;
    } finally {
      knapp.disabled = false;
    }
  });
  $("bytt-modus").addEventListener("click", (e) => {
    visArk(skjemaHtml(e.target.dataset.modus));
    koblSkjema();
  });
  const glemt = $("glemt-lenke");
  if (glemt) glemt.addEventListener("click", () => { visArk(glemtHtml()); koblGlemt(); });
}

/* --------------------------------------------------------- web push */

/* Hele poenget med appen er dette varselet. Alt annet -- katalogen,
 * prissammenligningen, folgelisten -- er forarbeid til at telefonen din
 * piper i det sekundet en vare du vil ha kommer inn.
 *
 * Tre ting gjor dette vanskeligere enn det ser ut:
 *
 * 1. **iOS.** Safari gir bare Web Push til sider som er lagt til pa
 *    hjemskjermen. Er den ikke det, finnes ikke `PushManager` i det hele
 *    tatt -- og en knapp som ikke gjor noe er verre enn ingen knapp. Vi
 *    oppdager tilfellet og forklarer det i stedet.
 * 2. **Tillatelse kan bare spørres om én gang.** Sier brukeren nei, kan vi
 *    aldri spørre igjen fra kode; det ma gjores i nettleserinnstillingene.
 *    Derfor spor vi ALDRI automatisk ved sidelasting -- bare etter et
 *    bevisst trykk.
 * 3. **Abonnementet er per nettleser, ikke per konto.** Vi lagrer det mot
 *    brukeren, og sw.js sender inn et nytt hvis nettleseren bytter det ut.
 */
/* Nettleserens egen id, husket paa tvers av service worker-bytter.
 *
 * Uten den samler det seg ETT push-endepunkt per service worker-generasjon.
 * Alle er levende, saa den vanlige oppryddingen (som sletter DODE
 * endepunkter) fjerner dem aldri -- og hvert varsel gaar ut i like mange
 * kopier. Malt i drift 14. august: én bruker hadde tre, opprettet 7., 9. og
 * 13. august. Tolv deployer paa én dag ga tre nye abonnementer.
 *
 * Dette er ikke sporing. Id-en lages her i nettleseren, sendes bare til oss,
 * og brukes bare til aa kjenne igjen en enhet som allerede er innlogget.
 * localStorage er valgt fremfor sessionStorage nettopp fordi den maa
 * overleve at fanen lukkes -- det er hele poenget. */
function installasjonsId() {
  try {
    let id = localStorage.getItem("pokepuls-installasjon");
    if (!id) {
      id = (crypto.randomUUID && crypto.randomUUID()) ||
           String(Date.now()) + Math.random().toString(36).slice(2);
      localStorage.setItem("pokepuls-installasjon", id);
    }
    return id;
  } catch (e) {
    // Privat modus. Da faar vi ikke ryddet, men abonnementet virker.
    return null;
  }
}

const push = {
  stottes() {
    return "serviceWorker" in navigator && "PushManager" in window &&
           "Notification" in window;
  },
  erIos() {
    return /iPad|iPhone|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  },
  paaHjemskjerm() {
    return window.matchMedia("(display-mode: standalone)").matches ||
           navigator.standalone === true;
  },

  /* base64url -> Uint8Array. applicationServerKey godtar ikke strengen
   * direkte i alle nettlesere, og feilen den gir er «InvalidCharacterError»
   * uten flere ord. */
  nokkelTilBytes(base64) {
    const pad = "=".repeat((4 - (base64.length % 4)) % 4);
    const raa = atob((base64 + pad).replace(/-/g, "+").replace(/_/g, "/"));
    return Uint8Array.from([...raa].map((c) => c.charCodeAt(0)));
  },

  async abonnement() {
    if (!this.stottes()) return null;
    const reg = await navigator.serviceWorker.ready;
    return reg.pushManager.getSubscription();
  },

  async slaPaa() {
    const { public_key: nokkel } = await hent("/push/nokkel");
    if (!nokkel) throw new Error("Varsler er ikke satt opp på serveren ennå.");

    const tillatelse = await Notification.requestPermission();
    if (tillatelse !== "granted") {
      throw new Error(tillatelse === "denied"
        ? "Varsler er blokkert for pokepuls.no. Du må slå dem på igjen i nettleserinnstillingene."
        : "Du må godta varsler for at dette skal virke.");
    }

    const reg = await navigator.serviceWorker.ready;
    const ab = await reg.pushManager.getSubscription() ||
      await reg.pushManager.subscribe({
        // Kreves av alle nettlesere: vi lover at hver push blir et synlig
        // varsel. Bryter vi lovnaden, trekkes tillatelsen tilbake.
        userVisibleOnly: true,
        applicationServerKey: this.nokkelTilBytes(nokkel),
      });
    await hent("/push/abonner", {
      method: "POST",
      body: JSON.stringify({ ...ab.toJSON(), installasjon: installasjonsId() }),
    });
    return ab;
  },

  async slaAv() {
    const ab = await this.abonnement();
    if (!ab) return;
    await hent("/push/avmeld", { method: "POST",
      body: JSON.stringify({ endpoint: ab.endpoint }) });
    await ab.unsubscribe();
  },
};

/* Installasjonshjelp.
 *
 * Ordene "PWA", "progressive web app" og "service worker" skal ALDRI staa i
 * denne teksten. Folk som trenger den vet ikke hva det betyr, og de som vet
 * hva det betyr trenger den ikke. Teksten sier én ting: legg Pokepuls paa
 * hjemskjermen, saa virker varsler.
 *
 * Paa iPhone er dette ikke et tips, det er et krav. Safari nekter aa sende
 * push til vanlige nettsider. Staar ikke det rett ut, tror folk at varslene
 * er odelagte. */
function installerHjelpHtml() {
  const paa = push.paaHjemskjerm();
  return "<h2>Slik får du varsler på telefonen</h2>" +
    (paa
      ? '<p class="side-status inne">Pokepuls ligger allerede på hjemskjermen ' +
        "din. Da er du klar — varsler virker herfra.</p>"
      : '<p class="hjelp">Pokepuls må ligge på hjemskjermen for å kunne sende ' +
        "deg varsler. Det tar et halvt minutt, og du laster ikke ned noe.</p>") +

    "<h3>iPhone og iPad</h3><ol class=\"side-liste-tekst\">" +
    "<li>Åpne pokepuls.no i <strong>Safari</strong>. Chrome på iPhone kan " +
      "ikke gjøre dette.</li>" +
    "<li>Trykk <strong>Del</strong> nederst på skjermen — firkanten med en " +
      "pil opp.</li>" +
    "<li>Bla nedover i lista og velg <strong>Legg til på Hjem-skjerm</strong>.</li>" +
    "<li>Trykk <strong>Legg til</strong> øverst til høyre.</li>" +
    "<li>Åpne Pokepuls fra det nye ikonet, logg inn, og trykk " +
      "<strong>Slå på varsler</strong>.</li></ol>" +
    '<p class="hjelp liten">Dette er Apples regel, ikke vår. Safari sender ' +
    "ikke varsler til vanlige nettsider uansett hva vi gjør.</p>" +

    "<h3>Android</h3><ol class=\"side-liste-tekst\">" +
    "<li>Åpne pokepuls.no i Chrome.</li>" +
    "<li>Kommer det opp et felt nederst som sier <strong>Installer</strong>, " +
      "trykk på det.</li>" +
    "<li>Skjer ikke det: trykk de tre prikkene øverst til høyre, og velg " +
      "<strong>Installer app</strong> eller <strong>Legg til på " +
      "startskjerm</strong>.</li></ol>" +

    "<h3>PC og Mac</h3>" +
    '<p class="hjelp">I Chrome eller Edge kommer det et lite ikon helt til ' +
    "høyre i adresselinjen — en skjerm med en pil ned. Trykk det og velg " +
    "<strong>Installer</strong>. I Safari på Mac: <strong>Arkiv</strong> → " +
    "<strong>Legg til i Dock</strong>.</p>" +

    "<h3>Hvordan vet jeg at det ble riktig?</h3>" +
    '<p class="hjelp">Åpne Pokepuls fra det nye ikonet. Ser du ingen ' +
    "adresselinje øverst, ligger den riktig.</p>";
}

async function varselSeksjonHtml() {
  if (!push.stottes()) {
    if (push.erIos() && !push.paaHjemskjerm()) {
      return '<div class="varselboks"><h3>Varsler på iPhone</h3>' +
        '<p class="hjelp">Safari gir bare varsler til sider som ligger på ' +
        "hjemskjermen. Det tar et halvt minutt.</p>" +
        '<button class="hovedknapp" id="installer-hjelp" type="button">' +
        "Vis meg hvordan</button></div>";
    }
    return '<div class="varselboks"><h3>Varsler</h3>' +
      '<p class="hjelp">Denne nettleseren støtter ikke varsler.</p></div>';
  }

  let status = null;
  try { status = await hent("/push/status"); } catch (e) { /* ikke innlogget */ }
  if (status && !status.vapid_paa) {
    return '<div class="varselboks"><h3>Varsler</h3>' +
      '<p class="hjelp">Varsler er ikke slått på på serveren ennå.</p></div>';
  }

  const ab = await push.abonnement();
  const paa = !!ab && !!status && status.antall > 0;
  return '<div class="varselboks"><h3>Varsler</h3>' +
    '<p class="hjelp">' + (paa
      ? "Du får push-varsel når noe du følger kommer på lager. " +
        (status.sendt_7d ? status.sendt_7d + " varsler siste uke." : "Ingen varsler ennå.")
      : "Slå på for å få beskjed på telefonen i det en vare du følger kommer inn.") +
    "</p>" +
    '<button class="hovedknapp' + (paa ? " av" : "") + '" id="varsel-knapp" type="button">' +
      (paa ? "Slå av varsler" : "🔔 Slå på varsler") + "</button>" +
    (paa ? '<button class="lenkeknapp" id="varsel-test" type="button">Send et testvarsel</button>' +
           '<label class="bryter"><input type="checkbox" id="varsel-natt"' +
             (status.stille_natt ? " checked" : "") + "> Ikke varsle mellom 23 og 07</label>"
         : "") +
    (push.paaHjemskjerm() ? "" :
      '<p class="hjelp liten"><button class="lenkeknapp" id="installer-hjelp" ' +
      'type="button" style="margin:0">Får du ikke varsler? Legg Pokepuls på ' +
      "hjemskjermen</button></p>") +
    '<p class="feil" id="varsel-feil" hidden></p></div>';
}

/* «Foelg alt».
 *
 * Backend har hatt dette siden bolk 3, men uten knapp fantes det ikke for
 * noen andre enn den som kan skrive en POST for haand.
 *
 * Teksten maa si dempingen HOYT, foer trykket. Katalogen ga 433 restock,
 * 105 prisendringer og 202 utsolgt paa ett doegn. En bruker som tror han
 * skrur paa «alt» og faar alt, skrur av varsler for godt samme kveld --
 * og da har du mistet ham, ikke bare denne funksjonen. Lover vi taket
 * paa forhaand, er 5 i timen en funksjon i stedet for et loftebrudd.
 *
 * Boksen staar utenfor varselSeksjonHtml() med vilje: den seksjonen
 * returnerer tidlig naar nettleseren ikke stotter push eller VAPID mangler,
 * og abonnementet ditt skal ikke forsvinne fordi Safari er Safari. */
function folgAltHtml() {
  const paa = state.folgerAlt;
  const maks = state.maksPerTime;
  return '<div class="varselboks"><h3>Følg alt</h3>' +
    '<p class="hjelp">' + (paa
      ? "Du følger hele katalogen. Du trenger ikke følge produkter enkeltvis " +
        "i tillegg — de kommer uansett."
      : "Slipp å hake av vare for vare. Du får beskjed om alt som kommer på " +
        "lager, og om nye varer.") + "</p>" +
    '<p class="hjelp liten">Maks ' + maks + " varsler i timen. Resten samles i " +
      "ett: «14 andre varer kom på lager». Prisendringer og utsolgt varsler " +
      "vi ikke om her — det ville vært bakgrunnsstøy. Varer du følger " +
      "enkeltvis går alltid gjennom, uansett kvote.</p>" +
    '<button class="hovedknapp' + (paa ? " av" : "") + '" id="folg-alt-knapp" type="button">' +
      (paa ? "Slutt å følge alt" : "Følg alt") + "</button>" +
    '<p class="feil" id="folg-alt-feil" hidden></p></div>';
}

function koblFolgAlt() {
  const knapp = $("folg-alt-knapp");
  if (!knapp) return;
  knapp.addEventListener("click", async () => {
    knapp.disabled = true;
    const feil = $("folg-alt-feil");
    feil.hidden = true;
    try {
      await hent("/watchlist/alt", { method: state.folgerAlt ? "DELETE" : "POST" });
      // Les tilstanden tilbake fra serveren i stedet for aa anta at den ble
      // som vi ba om. Knappen skal aldri kunne staa og lyve om hva du foelger.
      await lastFolger();
      await visKontoSide();
    } catch (e) {
      feil.textContent = e.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  });
}

function koblVarselKnapper() {
  const knapp = $("varsel-knapp");
  const feil = $("varsel-feil");
  const vis = (e) => { feil.textContent = e; feil.hidden = !e; };

  if (knapp) knapp.addEventListener("click", async () => {
    knapp.disabled = true;
    vis("");
    try {
      const ab = await push.abonnement();
      if (ab) await push.slaAv(); else await push.slaPaa();
      await visKontoSide();
    } catch (e) {
      vis(e.message);
      knapp.disabled = false;
    }
  });

  const hjelp = $("installer-hjelp");
  if (hjelp) hjelp.addEventListener("click", () => visArk(installerHjelpHtml()));

  const test = $("varsel-test");
  if (test) test.addEventListener("click", async () => {
    test.disabled = true;
    vis("");
    try {
      await hent("/push/test", { method: "POST" });
      test.textContent = "Sendt. Se på telefonen.";
    } catch (e) {
      vis(e.message);
    } finally {
      setTimeout(() => { test.disabled = false; test.textContent = "Send et testvarsel"; }, 4000);
    }
  });

  const natt = $("varsel-natt");
  if (natt) natt.addEventListener("change", () => {
    hent("/push/innstillinger", { method: "POST",
      body: JSON.stringify({ stille_natt: natt.checked }) }).catch(() => {});
  });
}

/* ------------------------------------------------------------ feedback */

/* Hvorfor dette er verdt plassen: den eneste maaten aa vite hvorfor folk
 * IKKE bruker noe, er at de sier det. En e-postadresse i bunnteksten faar
 * omtrent ingen svar -- den krever at du bytter app, formulerer en hel
 * e-post og vet hva du skal skrive i emnefeltet. Et felt der du allerede
 * staar faar svar.
 *
 * Kun for innloggede: da vet vi alltid hvem som sa det og kan svare. */
const FEEDBACK_SLAG = [
  ["feil", "Noe er feil"],
  ["onske", "Ønske"],
  ["butikk", "Butikk mangler"],
  ["annet", "Annet"],
];

function feedbackHtml() {
  return '<div class="varselboks"><h3>Si fra</h3>' +
    '<p class="hjelp">Mangler en butikk? Er en pris feil? Savner du noe? ' +
    "Skriv det her — vi leser alt som kommer inn.</p>" +
    '<form id="fb-skjema" class="skjema">' +
      '<div class="chips chips-under" id="fb-slag">' +
        FEEDBACK_SLAG.map(([v, t], i) =>
          '<button type="button" class="chip' + (i === 0 ? " pa" : "") +
          '" data-slag="' + v + '">' + t + "</button>").join("") +
      "</div>" +
      '<label><textarea id="fb-tekst" rows="4" maxlength="4000" required ' +
        'placeholder="Skriv her…"></textarea></label>' +
      '<p class="feil" id="fb-feil" hidden></p>' +
      '<button class="hovedknapp" type="submit">Send</button>' +
    "</form></div>";
}

function koblFeedback() {
  const skjema = $("fb-skjema");
  if (!skjema) return;
  let valgt = "feil";
  $("fb-slag").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    valgt = c.dataset.slag;
    for (const x of $("fb-slag").children) x.classList.toggle("pa", x === c);
  });
  skjema.addEventListener("submit", async (e) => {
    e.preventDefault();
    const knapp = skjema.querySelector("button[type=submit]");
    const feil = $("fb-feil");
    feil.hidden = true;
    knapp.disabled = true;
    try {
      await hent("/feedback", { method: "POST", body: JSON.stringify({
        tekst: $("fb-tekst").value.trim(), slag: valgt, side: state.fane }) });
      skjema.innerHTML = '<p class="hjelp">Takk — den er mottatt.</p>';
    } catch (err) {
      feil.textContent = err.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  });
}

async function visKontoSide() {
  const ubekreftet = state.bruker.epost_bekreftet === false;
  visArk('<h2>Konto</h2>' +
    '<p class="hjelp">Innlogget som <strong>' + esc(state.bruker.email) + "</strong>" +
    (state.bruker.role !== "free" ? " · " + esc(state.bruker.role) : "") + "</p>" +
    '<p class="hjelp liten">' + (state.folgerAlt
      ? "Du følger hele katalogen."
      : "Du følger " + state.folger.size + " produkt" +
        (state.folger.size === 1 ? "" : "er") + ".") + "</p>" +
    // Ubekreftet e-post er ikke et kosmetisk problem: uten den kan du ikke
    // faa nytt passord, og da er kontoen tapt hvis du glemmer det.
    (ubekreftet
      ? '<div class="varselboks"><h3>Bekreft e-posten din</h3>' +
        '<p class="hjelp">Uten en bekreftet adresse kan du ikke få nytt ' +
        "passord hvis du glemmer det.</p>" +
        '<button class="hovedknapp" id="send-verifisering" type="button">' +
        "Send bekreftelseslenke</button>" +
        '<p class="feil" id="ver-feil" hidden></p></div>'
      : "") +
    '<div id="varsel-seksjon"><p class="hjelp liten">Sjekker varsler…</p></div>' +
    '<div id="premium-boks"></div>' +
    folgAltHtml() +
    feedbackHtml() +
    (state.bruker.role === "admin"
      ? '<a class="lenkeknapp" href="/admin.html">Åpne admin</a>' : "") +
    '<button class="hovedknapp" id="logg-ut" type="button">Logg ut</button>' +
    '<p class="hjelp liten" style="margin-top:18px">' +
      '<a href="/personvern.html">Personvern</a> · ' +
      '<a href="/vilkar.html">Vilkår</a> · ' +
      '<button class="lenkeknapp" id="slett-konto" type="button" ' +
        'style="margin:0;color:var(--tekst-svak)">Slett kontoen min</button></p>');

  koblFeedback();
  koblFolgAlt();
  tegnPremium();
  const ver = $("send-verifisering");
  if (ver) ver.addEventListener("click", async () => {
    ver.disabled = true;
    try {
      await hent("/auth/send-verifisering", { method: "POST" });
      ver.textContent = "Sendt — se i innboksen";
    } catch (e) {
      $("ver-feil").textContent = e.message;
      $("ver-feil").hidden = false;
      ver.disabled = false;
    }
  });
  $("slett-konto").addEventListener("click", visSlettKonto);

  // Varselseksjonen etterfylles: den ma sporre bade serveren og nettleserens
  // pushManager, og arket skal ikke stå tomt mens den venter.
  varselSeksjonHtml().then((h) => {
    const boks = $("varsel-seksjon");
    if (boks) { boks.innerHTML = h; koblVarselKnapper(); }
  });

  $("logg-ut").addEventListener("click", async () => {
    await hent("/auth/logout", { method: "POST" });
    state.bruker = null;
    state.folger = new Map();
    $("konto-knapp").classList.remove("innlogget");
    lukkArk();
    tegnProdukter();
    if (state.fane === "folger") tegnFolgerFane();
  });
}

/* Sletting krever passord selv om du allerede er innlogget. En ulaast
 * telefon som ligger paa bordet skal ikke vaere nok til aa slette kontoen
 * til noen andre -- og handlingen kan ikke angres. */
function visSlettKonto() {
  visArk("<h2>Slett kontoen</h2>" +
    '<p class="hjelp">Dette sletter e-posten din, følgelisten, ' +
    "varselinnstillingene og alle registrerte enheter. Det kan ikke angres, " +
    "og vi har ingen kopi å hente den tilbake fra.</p>" +
    '<form id="slett-skjema" class="skjema">' +
      '<label>Bekreft med passordet ditt' +
        '<input id="s-passord" type="password" autocomplete="current-password" required></label>' +
      '<label>Hvorfor slutter du? <span class="hjelp liten">(frivillig, ' +
        "lagres uten navn)</span>" +
        '<input id="s-grunn" type="text" maxlength="500"></label>' +
      '<p class="feil" id="s-feil" hidden></p>' +
      '<button class="hovedknapp av" type="submit">Slett kontoen for godt</button>' +
    "</form>" +
    '<button class="lenkeknapp" id="s-avbryt" type="button">Avbryt</button>');

  $("s-avbryt").addEventListener("click", visKontoSide);
  $("slett-skjema").addEventListener("submit", async (e) => {
    e.preventDefault();
    const knapp = e.target.querySelector("button[type=submit]");
    knapp.disabled = true;
    try {
      await hent("/auth/slett-meg", { method: "POST", body: JSON.stringify({
        password: $("s-passord").value, grunn: $("s-grunn").value.trim() || null }) });
      state.bruker = null;
      state.folger = new Map();
      $("konto-knapp").classList.remove("innlogget");
      visArk('<h2>Kontoen er slettet</h2><p class="hjelp">Takk for at du ' +
             "prøvde Pokepuls. Du er alltid velkommen tilbake.</p>");
      tegnProdukter();
    } catch (err) {
      $("s-feil").textContent = err.message;
      $("s-feil").hidden = false;
      knapp.disabled = false;
    }
  });
}

/* --------------------------------------------------------- folger-fane */

async function tegnFolgerFane() {
  const boks = $("folger-innhold");
  if (!state.bruker) {
    boks.innerHTML = '<p class="tom">Logg inn for a folge produkter.<br>' +
      '<button class="hovedknapp smal" id="folger-logg-inn" type="button">Logg inn eller lag konto</button></p>';
    $("folger-logg-inn").addEventListener("click", apneKonto);
    return;
  }
  boks.innerHTML = '<p class="hjelp">Laster…</p>';
  try {
    const d = await hent("/watchlist/snapshot");
    if (!d.produkter.length) {
      boks.innerHTML = '<p class="tom">Du folger ingen produkter enna.<br>' +
        "Åpne et produkt og trykk «Følg denne».</p>";
      return;
    }
    const pa = d.produkter.filter((p) => p.antall_pa_lager).length;
    boks.innerHTML = '<p class="teller">' + d.produkter.length + " fulgte produkter · " +
      pa + " på lager nå</p>" + '<div class="liste">' + grupperHtml(d.produkter) + "</div>";
  } catch (e) {
    boks.innerHTML = '<p class="tom">Klarte ikke a hente folgelisten.</p>';
  }
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
    (v.image_url ? '<img class="miniatyr" loading="lazy" src="' + esc(v.image_url) + '" alt="">' : "") +
    '<span class="kort-venstre"><span class="kort-navn">' + esc(v.title) + "</span>" +
    '<span class="kort-under">' + esc(butikknavn(v.store_id)) + "</span></span>" +
    '<span class="kort-hoyre"><span class="pris">' + (kr(v.price_ore) || "–") + "</span>" +
    '<div class="lager ' + (v.in_stock ? "inne" : "ute") + '">' +
    (v.in_stock ? "på lager" : "–") + "</div></span></a>").join(""));
  state.andreVist += bit.length;
  $("mer-andre").hidden = state.andreVist >= state.andre.length;
}

/* --------------------------------------------------------------- faner */

function byttFane(navn) {
  state.fane = navn;
  for (const el of document.querySelectorAll(".fane-knapp")) {
    const p = el.dataset.fane === navn;
    el.classList.toggle("valgt", p);
    el.setAttribute("aria-selected", String(p));
  }
  $("fane-produkter").hidden = navn !== "produkter";
  $("fane-nytt").hidden = navn !== "nytt";
  $("fane-folger").hidden = navn !== "folger";
  $("fane-andre").hidden = navn !== "andre";
  document.querySelector(".sok-rad").hidden = navn !== "produkter";
  $("chips").hidden = navn !== "produkter";
  const l = $("filterlinje");
  if (l) l.hidden = navn !== "produkter";
  const st = $("restock-stripe");
  if (st) st.hidden = navn !== "produkter";
  if (navn === "nytt") lastHendelser();
  if (navn === "folger") tegnFolgerFane();
  if (navn === "andre") lastAndre();
  scrollTo({ top: 0 });
}

function koble() {
  // Sorteringen settes FOR vi lytter, ellers viser nedtrekket «Nytt forst»
  // mens listen er sortert paa slippdato fra forrige besok.
  const sortValg = $("sortering");
  if (sortValg) {
    sortValg.value = state.sortering;
    sortValg.addEventListener("change", (e) => {
      state.sortering = e.target.value;
      localStorage.setItem("pokepuls-sortering", state.sortering);
      tegnProdukter();
    });
  }

  $("sok").addEventListener("input", (e) => {
    state.sok = e.target.value;
    $("tom-sok").hidden = !state.sok;
    tegnProdukter();
  });
  $("tom-sok").addEventListener("click", () => {
    $("sok").value = ""; state.sok = ""; $("tom-sok").hidden = true; tegnProdukter();
  });

  // Filterknappen, chipsene, restock-stripen og rutenettet -- godkjent
  // og live for alle.
  const filterKnapp = $("knapp-filtre");
  filterKnapp.addEventListener("click", () => {
    const panel = $("filterpanel");
    const apent = panel.classList.toggle("apent");
    filterKnapp.setAttribute("aria-expanded", apent ? "true" : "false");
  });

  // Ett sted for aa fjerne et filter, uansett om trykket kom fra chipsen
  // i filterlinjen eller fra knappen i tom-listen.
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-fjern]");
    if (!b) return;
    nullstillFilter(b.dataset.fjern);
    tegnProdukter();
  });

  const visKnapp = $("knapp-visning");
  const settVisning = () => {
    visKnapp.textContent = state.visning === "rutenett" ? "Liste" : "Rutenett";
  };
  settVisning();
  visKnapp.addEventListener("click", () => {
    state.visning = state.visning === "rutenett" ? "liste" : "rutenett";
    localStorage.setItem("pokepuls-visning", state.visning);
    settVisning();
    tegnProdukter();
  });

  $("restock-stripe").addEventListener("click", (e) => {
    const rad = e.target.closest("[data-produkt]");
    if (rad) apneProdukt(rad.dataset.produkt);
  });

  // Butikkartet er det ENESTE som fortsatt bare finnes paa /ny. Det
  // hviler paa lagerdata vi ikke har ordentlig enna.
  // Null-sjekken er ikke pynt: uten den kaster koble() hvis knappen ikke
  // finnes, og DA kobles ingenting -- ikke soket, ikke filtrene, ikke
  // fanene. En manglende knapp ville tatt ned hele appen.
  const kartKnapp = $("knapp-kart");
  if (kartKnapp) {
    if (KART_PAA_PROVE) {
      kartKnapp.hidden = false;
      kartKnapp.addEventListener("click", apneKart);
    } else {
      kartKnapp.remove();
    }
  }

  $("chips").addEventListener("click", (e) => {
    const c = e.target.closest(".chip");
    if (!c) return;
    const { filter, verdi } = c.dataset;
    if (filter === "lager") state.kunLager = !state.kunLager;
    else if (filter === "forhandssalg") state.forhandssalg = !state.forhandssalg;
    else state[filter] = state[filter] === verdi ? null : verdi;
    for (const el of $("chips").children) {
      const f = el.dataset.filter;
      const pa = f === "lager" ? state.kunLager
        : f === "forhandssalg" ? state.forhandssalg
        : state[f] === el.dataset.verdi;
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

  $("konto-knapp").addEventListener("click", apneKonto);
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
lastBruker();

/* Dyplenke fra de serverrendrede produktsidene: /p/<id> lenker hit med
 * ?produkt=<id>. Uten dette lander alle som kommer fra Google pa forsiden
 * og ma sokte seg frem til varen de nettopp leste om. */
/* Bekreftelseslenken fra e-posten lander her. Vi tar imot tokenet, rydder
 * det ut av adresselinjen (det skal ikke bli liggende i historikken eller
 * i en delt lenke) og sier fra at det gikk bra. */
(function verifiserEpost() {
  const t = new URLSearchParams(location.search).get("verifiser");
  if (!t) return;
  // Tokenet ryddes ut av adresselinjen FORST etter at vi har svar. Gjor vi
  // det for, og kallet feiler paa et daarlig nett, er tokenet borte fra
  // skjermen og lenken kan ikke provess om igjen -- brukeren sitter igjen
  // med en feilmelding og ingen vei videre.
  const rydd = () => history.replaceState(null, "", location.pathname);
  hent("/auth/verifiser", { method: "POST", body: JSON.stringify({ token: t }) })
    .then(() => {
      rydd();
      if (state.bruker) state.bruker.epost_bekreftet = true;
      visArk('<h2>E-posten er bekreftet</h2><p class="hjelp">Takk. Nå kan du ' +
             "få nytt passord hvis du skulle glemme det.</p>");
    })
    .catch((e) => {
      rydd();
      visArk('<h2>Lenken virket ikke</h2><p class="hjelp">' + esc(e.message) +
        '</p><p class="hjelp liten">Ba du om flere lenker, er det bare den ' +
        "siste som virker. De eldre slås av med vilje, slik at en lenke på " +
        "avveie ikke kan brukes.</p>" +
        '<button class="hovedknapp" id="ny-ver-lenke" type="button">' +
        "Send meg en ny lenke</button>" +
        '<p class="feil" id="ny-ver-feil" hidden></p>');
      // En blindvei er ikke en feilmelding. Herfra skal du komme videre
      // uten aa lete deg fram til kontosiden.
      const k = $("ny-ver-lenke");
      if (!k) return;
      k.addEventListener("click", async () => {
        k.disabled = true;
        const f = $("ny-ver-feil");
        try {
          await hent("/auth/send-verifisering", { method: "POST" });
          k.textContent = "Sendt — se i innboksen";
        } catch (err) {
          f.textContent = state.bruker
            ? err.message
            : "Du må være logget inn for å få en ny lenke.";
          f.hidden = false;
          k.disabled = false;
        }
      });
    });
})();

(function dyplenke() {
  const id = new URLSearchParams(location.search).get("produkt");
  if (!id) return;
  history.replaceState(null, "", location.pathname);
  // Vent til snapshot er lastet, sa arket kan vise reservebilde og folge-
  // knappen med riktig tilstand.
  const prov = (forsok = 0) => {
    if (state.produkter.length || forsok > 40) apneProdukt(id);
    else setTimeout(() => prov(forsok + 1), 100);
  };
  prov();
})();

/* Sidevisninger.
 *
 * Ett kall, én gang per fane-oekt. Ingen id, ingen kapsel, ingenting som
 * folger deg mellom oekter -- serveren lagrer bare dato, side, standalone
 * og et antall. Se api/bruk.py og db/006_bruk.sql.
 *
 * Hvorfor sessionStorage og ikke bare telle hver lasting: uten det ser én
 * person som laster siden tjue ganger ut som tjue aapninger, og da er
 * tallet ubrukelig til det eneste det skal svare paa -- virker det aa be
 * folk installere? sessionStorage doer med fanen, saa neste gang du aapner
 * appen teller du igjen. Det er nettopp det vi vil.
 *
 * `navigator.standalone` er Apple-spesifikk og finnes bare paa iOS. Uten
 * den andre sjekken teller du NULL iPhone-installasjoner -- og det er
 * nettopp der du helst vil vite det, siden iOS er den ene plattformen der
 * varsler ikke virker uten installasjon. */
(function meldBruk() {
  // HELE kroppen ligger i try. En teller som kaster under lasting stopper
  // alt som star etter den i filen -- da har du byttet et tall du savner
  // mot en app som ikke virker. Det er feil vei.
  try {
    try {
      if (sessionStorage.getItem("pokepuls-meldt")) return;
      sessionStorage.setItem("pokepuls-meldt", "1");
    } catch (e) {
      // Privat modus kaster paa sessionStorage. Da teller vi heller én gang
      // for mye enn aa miste hele gruppen -- de som surfer privat er ikke
      // en gruppe vi vil ha et systematisk hull i.
    }
    const standalone =
      (window.matchMedia
        ? window.matchMedia("(display-mode: standalone)").matches : false) ||
      window.navigator.standalone === true;
    hent("/bruk", {
      method: "POST",
      body: JSON.stringify({ side: "hjem", standalone }),
    }).catch(() => {});   // en tapt telling er ikke verdt en feil hos brukeren
  } catch (e) { /* se over */ }
})();

/* Rydd varselsenteret naar appen aapnes.
 *
 * Dette er grunnen til at det foles som om «alle varslene kommer paa nytt
 * hver gang du oppdaterer siden». De kommer ikke paa nytt -- de har ligget
 * der hele tiden. Et varsel du ikke sveiper bort blir liggende i
 * varslingssenteret, og paa iOS leveres i tillegg alt som kom mens appen
 * var lukket, samlet, i det du aapner den.
 *
 * Naar du staar INNE i appen har varselet gjort jobben sin. Det skal ikke
 * ligge igjen og be om oppmerksomhet for noe du allerede ser paa.
 *
 * Vi rydder ogsaa naar fanen blir synlig igjen, ikke bare ved lasting:
 * paa mobil byttes det mellom apper langt oftere enn sider lastes.
 */
function ryddVarsler() {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.getRegistration()
    .then((reg) => {
      if (!reg || !reg.getNotifications) return;
      return reg.getNotifications().then((varsler) => {
        for (const v of varsler) v.close();
      });
    })
    .catch(() => {});   // en opprydding som feiler skal aldri vises
}

document.addEventListener("visibilitychange", () => {
  if (!document.hidden) ryddVarsler();
});

// Ved lasting. Funksjonen sjekker selv om serviceWorker finnes, saa den kan
// kalles fritt -- den skal aldri vaere grunnen til at appen ikke starter.
ryddVarsler();

if ("serviceWorker" in navigator) {
  // Service workeren har ingen localStorage. Naar den bytter push-abonnement
  // spor den oss om installasjons-id-en, saa serveren kan rydde bort den
  // forrige registreringen fra samme nettleser.
  navigator.serviceWorker.addEventListener("message", (e) => {
    if (e.data && e.data.sporr === "installasjon" && e.ports && e.ports[0]) {
      e.ports[0].postMessage({ installasjon: installasjonsId() });
    }
  });
  navigator.serviceWorker.register("/sw.js").catch(() => {});
  // Én gang til naar registreringen er aktiv: paa aller forste besok finnes
  // det ingen registrering enna naar linja over kjorer.
  navigator.serviceWorker.ready.then(ryddVarsler).catch(() => {});
}

/* =====================================================================
   FYSISKE BUTIKKER PAA KART  (testomraadet)
   =====================================================================

   HVA KARTET SVARER PAA

   «Finnes det en butikk i naerheten min» -- ja. «Har DEN butikken varen»
   -- nei.

   Vi undersokte alle 46 butikkene. Bare Outland oppgir lager i fysisk
   butikk i det hele tatt, og bare som et ANTALL: «Tilgjengelig i 4
   butikker», ikke hvilke fire. Ingen norsk kjede vi leser rekker ut med
   lager per filial.

   Et kart faar folk til aa tro paa presisjon. Hadde vi tegnet en gronn
   prikk paa Bergen for en vare som finnes i «4 av 15», ville noen kjort
   dit. Derfor viser kartet hvor kjedene ER, og sier det rett ut.

   HVORFOR INGEN KYSTLINJE

   Et Norges-omriss tegnet etter hukommelsen ville sett omtrent riktig ut
   og vaert feil -- og et kart som ser presist ut, blir trodd. Prikkene
   ligger paa ekte koordinater i ekte projeksjon; det er alt vi kan
   staa inne for uten en ordentlig kartkilde.
   ===================================================================== */

/* EKTE KART -- Leaflet med OpenStreetMap-fliser.
 *
 * Forste forsok var prikker paa breddegradslinjer. Andre forsok var et
 * tegnet Norges-omriss. Begge var «kart» i den forstand at de viste hvor
 * ting laa, og ingen av dem var det folk mener med et kart: du kunne ikke
 * zoome inn og se hvilken gate butikken ligger i.
 *
 * Leaflet ligger i web/vendor/ og lastes LOKALT. CSP-en tillater bare
 * egne skript, og den skal ikke myknes opp for et kartbibliotek.
 *
 * Biblioteket er 148 kB og lastes forst naar noen aapner kartet. Forsiden
 * skal ikke betale for en funksjon de fleste aldri trykker paa.
 *
 * FLISENE
 *
 * OpenStreetMap sine egne. De er lyse, og appen er mork -- derfor
 * CSS-filteret i style.css, som er den vanlige maaten aa gjore OSM morkt
 * paa uten aa binde seg til en betalt leverandor.
 *
 * OSM krever navngiving, og den staar nede i hjornet. Bruksvilkaarene
 * deres gjelder volum: blir dette en side med mye trafikk, maa vi over paa
 * en egen flisleverandor. Det er en regning, ikke en teknisk hindring, og
 * den kommer forst naar tjenesten er stor nok til aa taale den.
 */
const LEAFLET_JS = "/vendor/leaflet/leaflet.js";
const LEAFLET_CSS = "/vendor/leaflet/leaflet.css";
let leafletLastet = null;

function lastLeaflet() {
  if (leafletLastet) return leafletLastet;
  leafletLastet = new Promise((ok, nei) => {
    const css = document.createElement("link");
    css.rel = "stylesheet";
    css.href = LEAFLET_CSS;
    document.head.appendChild(css);
    const js = document.createElement("script");
    js.src = LEAFLET_JS;
    js.onload = ok;
    js.onerror = () => nei(new Error("fikk ikke lastet kartet"));
    document.head.appendChild(js);
  });
  return leafletLastet;
}

/* POSTNUMMER I STEDET FOR POSISJONSTILGANG.
 *
 * Forste versjon spurte nettleseren om posisjon. Det virker, men det
 * koster en tillatelsesboks for du har sett noe som helst, det virker
 * daarlig paa desktop, og det er en personopplysning vi egentlig ikke
 * trenger. Konkurrenten bruker postnummer, og de har rett.
 *
 * Et postnummer holder. Vi skal svare paa «hvilken butikk er naermest»,
 * ikke navigere deg dit -- og til det er en by noyaktig nok.
 *
 * Tabellen er postnummerSERIER, ikke enkeltnumre. Norge har rundt 5 000
 * postnumre; alle i frontenden ville vaert hundrevis av kilobyte for en
 * presisjon ingen merker. Her er det 89 rader uten hull, og treffet er
 * byen eller distriktet du bor i.
 *
 * Vi sier det ogsaa rett ut i grensesnittet: avstanden er omtrentlig.
 */
const POSTSTEDER = [
  [1, 1299, "Oslo", 59.913, 10.739], [1300, 1379, "Bærum", 59.891, 10.527],
  [1380, 1399, "Asker", 59.833, 10.435], [1400, 1499, "Follo", 59.720, 10.836],
  [1500, 1599, "Moss", 59.435, 10.664], [1600, 1699, "Fredrikstad", 59.221, 10.934],
  [1700, 1799, "Sarpsborg", 59.284, 11.109], [1800, 1899, "Indre Østfold", 59.583, 11.166],
  [1900, 1999, "Nedre Romerike", 59.940, 11.170], [2000, 2099, "Lillestrøm", 59.956, 11.049],
  [2100, 2199, "Sør-Odal", 60.253, 11.688], [2200, 2299, "Kongsvinger", 60.190, 11.994],
  [2300, 2399, "Hamar", 60.795, 11.068], [2400, 2499, "Elverum", 60.881, 11.562],
  [2500, 2599, "Tynset", 62.276, 10.777], [2600, 2699, "Lillehammer", 61.115, 10.466],
  [2700, 2799, "Hadeland", 60.373, 10.556], [2800, 2899, "Gjøvik", 60.795, 10.692],
  [2900, 2999, "Valdres", 60.987, 9.234], [3000, 3099, "Drammen", 59.744, 10.204],
  [3100, 3199, "Tønsberg", 59.267, 10.408], [3200, 3299, "Sandefjord", 59.131, 10.225],
  [3300, 3399, "Hokksund", 59.774, 9.909], [3400, 3499, "Lier", 59.792, 10.243],
  [3500, 3599, "Hønefoss", 60.169, 10.257], [3600, 3699, "Kongsberg", 59.665, 9.650],
  [3700, 3799, "Skien", 59.209, 9.609], [3800, 3899, "Midt-Telemark", 59.412, 9.062],
  [3900, 3999, "Porsgrunn", 59.141, 9.656], [4000, 4099, "Stavanger", 58.970, 5.733],
  [4100, 4199, "Strand", 59.021, 6.043], [4200, 4299, "Sauda", 59.650, 6.359],
  [4300, 4399, "Sandnes", 58.852, 5.735], [4400, 4499, "Flekkefjord", 58.297, 6.661],
  [4500, 4599, "Mandal", 58.028, 7.457], [4600, 4699, "Kristiansand", 58.146, 7.995],
  [4700, 4799, "Vennesla", 58.297, 7.977], [4800, 4899, "Arendal", 58.461, 8.772],
  [4900, 4999, "Risør", 58.622, 9.070], [5000, 5099, "Bergen", 60.393, 5.324],
  [5100, 5199, "Nordhordland", 60.545, 5.288], [5200, 5299, "Bjørnafjorden", 60.183, 5.466],
  [5300, 5399, "Askøy", 60.400, 5.180], [5400, 5499, "Stord", 59.783, 5.500],
  [5500, 5599, "Haugesund", 59.413, 5.268], [5600, 5699, "Kvam", 60.370, 6.144],
  [5700, 5799, "Voss", 60.630, 6.416], [5800, 5899, "Sogndal", 61.230, 7.100],
  [5900, 5999, "Austrheim", 60.780, 4.930], [6000, 6099, "Ålesund", 62.472, 6.155],
  [6100, 6199, "Volda", 62.147, 6.070], [6200, 6299, "Stranda", 62.310, 6.940],
  [6300, 6399, "Åndalsnes", 62.567, 7.688], [6400, 6499, "Molde", 62.737, 7.159],
  [6500, 6599, "Kristiansund", 63.110, 7.728], [6600, 6699, "Sunndal", 62.675, 8.563],
  [6700, 6799, "Måløy", 61.937, 5.113], [6800, 6899, "Førde", 61.452, 5.856],
  [6900, 6999, "Florø", 61.599, 5.032], [7000, 7099, "Trondheim", 63.430, 10.395],
  [7100, 7199, "Indre Fosen", 63.585, 9.968], [7200, 7299, "Hitra", 63.290, 9.100],
  [7300, 7399, "Orkland", 63.300, 9.850], [7400, 7499, "Heimdal", 63.360, 10.350],
  [7500, 7599, "Stjørdal", 63.470, 10.919], [7600, 7699, "Levanger", 63.746, 11.300],
  [7700, 7799, "Steinkjer", 64.015, 11.495], [7800, 7899, "Namsos", 64.466, 11.496],
  [7900, 7999, "Rørvik", 64.862, 11.240], [8000, 8099, "Bodø", 67.280, 14.405],
  [8100, 8199, "Fauske", 67.259, 15.393], [8200, 8299, "Rognan", 67.098, 15.394],
  [8300, 8399, "Svolvær", 68.234, 14.567], [8400, 8499, "Sortland", 68.696, 15.412],
  [8500, 8599, "Narvik", 68.438, 17.427], [8600, 8699, "Mo i Rana", 66.313, 14.142],
  [8700, 8799, "Nesna", 66.196, 13.023], [8800, 8899, "Sandnessjøen", 66.021, 12.632],
  [8900, 8999, "Brønnøysund", 65.474, 12.212], [9000, 9099, "Tromsø", 69.649, 18.955],
  [9100, 9199, "Kvaløya", 69.680, 18.800], [9200, 9299, "Balsfjord", 69.220, 19.550],
  [9300, 9399, "Finnsnes", 69.230, 17.980], [9400, 9499, "Harstad", 68.798, 16.541],
  [9500, 9599, "Alta", 69.968, 23.271], [9600, 9699, "Hammerfest", 70.663, 23.682],
  [9700, 9799, "Lakselv", 70.050, 24.970], [9800, 9899, "Vadsø", 70.074, 29.749],
  [9900, 9999, "Kirkenes", 69.727, 30.045],
];

function stedFraPostnummer(tekst) {
  const n = parseInt(String(tekst).trim(), 10);
  if (!Number.isInteger(n) || n < 1 || n > 9999) return null;
  const rad = POSTSTEDER.find(([fra, til]) => n >= fra && n <= til);
  return rad ? { navn: rad[2], lat: rad[3], lon: rad[4] } : null;
}

/* Luftlinje i kilometer. Haversine -- Norge er langt nok nord til at
 * «bare regn med rette linjer» bommer med titalls kilometer. */
function avstandKm(lat1, lon1, lat2, lon2) {
  const R = 6371, rad = (g) => g * Math.PI / 180;
  const dLat = rad(lat2 - lat1), dLon = rad(lon2 - lon1);
  const a = Math.sin(dLat / 2) ** 2 +
    Math.cos(rad(lat1)) * Math.cos(rad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

/* Klyng butikker per by.
 *
 * Outland har tre butikker i Oslo. Tre markorer oppa hverandre ser ut som
 * en klatt, ikke som informasjon -- og zoomer du inn, skiller de seg. */
function byklynger(steder) {
  const byer = new Map();
  for (const s of steder) {
    const n = byer.get(s.poststed) ||
      { poststed: s.poststed, lat: s.lat, lon: s.lon, butikker: [] };
    n.butikker.push(s);
    byer.set(s.poststed, n);
  }
  return [...byer.values()];
}

let kartet = null;

function tegnKart(steder, meg) {
  const boks = $("kart-boks");
  if (!boks || !window.L) return;

  // Rydd et gammelt kart bort for vi lager et nytt. Uten dette klager
  // Leaflet paa at beholderen allerede er i bruk, og kartet blir tomt.
  if (kartet) { kartet.remove(); kartet = null; }

  kartet = L.map(boks, { scrollWheelZoom: false, attributionControl: true })
    .setView([64.5, 13.0], 4);

  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: "&copy; OpenStreetMap-bidragsytere",
  }).addTo(kartet);

  const punkter = [];
  for (const by of byklynger(steder)) {
    const aapne = by.butikker.filter((b) => b.aapnet);
    const merke = L.circleMarker([by.lat, by.lon], {
      radius: 7 + Math.min(by.butikker.length - 1, 3) * 2,
      className: aapne.length ? "kart-merke" : "kart-merke kommer",
    }).addTo(kartet);

    merke.bindPopup(
      "<strong>" + esc(by.poststed) + "</strong><br>" +
      by.butikker.map((b) =>
        esc(b.navn) + "<br><span class='popup-adresse'>" +
        esc(b.adresse) + (b.merknad ? " · " + esc(b.merknad) : "") +
        (b.aapnet ? "" : " · åpner snart") + "</span>").join("<br>"));
    punkter.push([by.lat, by.lon]);
  }

  if (meg) {
    L.circleMarker([meg.lat, meg.lon], { radius: 7, className: "kart-meg" })
      .addTo(kartet).bindPopup("Her er du");
    punkter.push([meg.lat, meg.lon]);
  }

  // Er posisjonen kjent, ram inn deg og de tre naermeste. Hele Norge er
  // riktig naar man ikke vet hvor du er, og unyttig naar man vet det.
  if (meg && punkter.length > 1) {
    const naer = byklynger(steder)
      .map((b) => ({ b, km: avstandKm(meg.lat, meg.lon, b.lat, b.lon) }))
      .sort((a, b) => a.km - b.km).slice(0, 3)
      .map((x) => [x.b.lat, x.b.lon]);
    kartet.fitBounds([[meg.lat, meg.lon], ...naer], { padding: [30, 30] });
  }
  // Leaflet maaler beholderen ved oppstart. Aapnes kartet i et ark som
  // fortsatt glir inn, er hoyden feil og flisene legger seg skjevt.
  setTimeout(() => kartet && kartet.invalidateSize(), 120);
}

function stedslisteHtml(steder, meg) {
  const med = steder.map((s) => ({
    ...s,
    km: meg ? avstandKm(meg.lat, meg.lon, s.lat, s.lon) : null,
  }));
  if (meg) med.sort((a, b) => a.km - b.km);

  return '<ul class="stedliste">' + med.map((s) =>
    "<li><span><strong>" + esc(s.navn) + "</strong>" +
    '<span class="hjelp liten">' + esc(s.adresse) + ", " + esc(s.poststed) +
      (s.merknad ? " · " + esc(s.merknad) : "") + "</span></span>" +
    (s.km != null
      ? '<span class="stedavstand">' + Math.round(s.km) + " km</span>"
      : s.aapnet ? "" : '<span class="stedavstand">kommer</span>') +
    "</li>").join("") + "</ul>";
}

async function apneKart() {
  visArk('<p class="hjelp">Laster kart…</p>');
  let d;
  try {
    [d] = await Promise.all([hent("/steder"), lastLeaflet()]);
  } catch (e) {
    visArk('<p class="feil">Fikk ikke lastet kartet.</p>');
    return;
  }

  const husket = localStorage.getItem("pokepuls-postnummer") || "";

  const tegn = (meg, post) => {
    visArk("<h2>Butikk nær deg</h2>" +
      '<p class="hjelp">' + esc(d.forbehold) + "</p>" +
      '<div class="postrad"><label for="postnr">Postnummer</label>' +
        '<input id="postnr" type="text" inputmode="numeric" maxlength="4" ' +
        'autocomplete="postal-code" placeholder="0150" value="' +
        esc(post || "") + '"></div>' +
      (meg ? '<p class="hjelp liten">Avstand fra ' + esc(meg.navn) +
             ". Omtrentlig — vi regner fra midten av området, ikke fra døra di.</p>"
           : "") +
      '<p class="feil" id="kart-feil" hidden></p>' +
      '<div id="kart-boks" class="kart-boks"></div>' +
      stedslisteHtml(d.steder, meg));

    tegnKart(d.steder, meg);

    const felt = $("postnr");
    const sok = () => {
      const verdi = felt.value.trim();
      if (!verdi) { localStorage.removeItem("pokepuls-postnummer"); tegn(null, ""); return; }
      const sted = stedFraPostnummer(verdi);
      if (!sted) {
        const feil = $("kart-feil");
        feil.textContent = "Fant ikke postnummeret. Skriv fire siffer.";
        feil.hidden = false;
        return;
      }
      localStorage.setItem("pokepuls-postnummer", verdi);
      tegn(sted, verdi);
    };
    felt.addEventListener("change", sok);
    felt.addEventListener("keydown", (e) => { if (e.key === "Enter") felt.blur(); });
  };

  // Har vi et postnummer fra forrige besok, bruk det med én gang. Da ser
  // du din egen naerhet forst, ikke hele Norge.
  tegn(husket ? stedFraPostnummer(husket) : null, husket);
}
