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
  sok: "", kunLager: true, region: null, type: null,
  hendelseKinds: new Set(["restock"]),
  andre: [], andreVist: 0,
  fane: "produkter",
  bruker: null,        // null = ikke innlogget
  folger: new Map(),   // product_id -> abonnement-id
  folgerAlt: false,    // «foelg alt»: én rad uten product_id og set_id
  maksPerTime: 5,      // brukerens timeskvote, hentet fra serveren
  apentProdukt: null,
};

/* ------------------------------------------------------------- verktoy */

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
    '<rect width="64" height="64" rx="10" fill="#1b2027"/>' +
    '<g fill="none" stroke="' + farge + '" stroke-width="2.4" stroke-linejoin="round" opacity="0.85">' +
    form + "</g></svg>";
  return "data:image/svg+xml;utf8," + encodeURIComponent(svg);
}

function bildeHtml(p, klasse) {
  const reserve = reservebilde(p);
  const src = p.bilde || reserve;
  return '<img class="' + klasse + '" loading="lazy" decoding="async" alt="" ' +
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
    ? treff.length + " produkter" + (state.kunLager ? " på lager" : "") +
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
function grupperHtml(treff) {
  const grupper = new Map();
  for (const p of treff) {
    const nokkel = p.set_id + ":" + p.region;
    if (!grupper.has(nokkel)) grupper.set(nokkel, []);
    grupper.get(nokkel).push(p);
  }

  const bolker = [...grupper.values()].map((produkter, i) => ({
    produkter,
    // Ferskeste hendelse i bolken. 0 = ingen aktivitet vi vet om.
    tid: Math.max(...produkter.map((p) =>
      p.sist_hendelse ? new Date(p.sist_hendelse).getTime() : 0)),
    i,
  }));
  // Stabil sortering: like verdier beholder opprinnelig rekkefolge (som er
  // alfabetisk fra API-et). Array.prototype.sort er stabil i alle nettlesere
  // vi bryr oss om, men vi tar med `i` sa det ikke er noe a lure pa.
  bolker.sort((a, b) => (b.tid - a.tid) || (a.i - b.i));

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

function kortHtml(p) {
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
      (bilde ? '<img class="ark-bilde" src="' + esc(bilde.image_url) + '" alt="" ' +
               "onerror=\"this.onerror=null;this.src='" + reservebilde(iSnapshot) + "'\">"
             : '<img class="ark-bilde" src="' + reservebilde(iSnapshot) + '" alt="">') +
      '<div class="ark-tekst"><h2>' + esc(p.set_label) + "</h2>" +
      '<div class="ark-under"><span>' + esc(p.type_label) + "</span>" +
      '<span class="merkelapp ' + p.region + '">' + esc(REGION[p.region] || p.region) + "</span></div>" +
      '<button class="folg-knapp" id="folg-knapp" type="button"></button>' +
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
    if (state.produkter.length) tegnProdukter();
  }
}

async function lastFolger() {
  try {
    const d = await hent("/watchlist");
    state.folger = new Map(d.folger.filter((f) => f.product_id).map((f) => [f.product_id, f.id]));
    // Serveren sier selv om «alt» er paa; vi utleder det ikke av radene.
    state.folgerAlt = !!d.alt;
    // Faller tilbake til 5 hvis feltet mangler -- en eldre server skal ikke
    // gi «du faar maks undefined varsler i timen».
    state.maksPerTime = d.maks_per_time || 5;
  } catch (e) {
    state.folger = new Map();
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
    await hent("/push/abonner", { method: "POST", body: JSON.stringify(ab.toJSON()) });
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
    "Skriv det her — det går rett til Kristian.</p>" +
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
    folgAltHtml() +
    feedbackHtml() +
    (state.bruker.role === "admin"
      ? '<a class="lenkeknapp" href="/admin.html">Åpne admin</a>' : "") +
    '<button class="hovedknapp" id="logg-ut" type="button">Logg ut</button>' +
    '<p class="hjelp liten" style="margin-top:18px">' +
      '<a href="/personvern.html">Personvern</a> · ' +
      '<button class="lenkeknapp" id="slett-konto" type="button" ' +
        'style="margin:0;color:var(--tekst-svak)">Slett kontoen min</button></p>');

  koblFeedback();
  koblFolgAlt();
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
  if (navn === "nytt") lastHendelser();
  if (navn === "folger") tegnFolgerFane();
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

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
