/* Pokepuls — nytt design, forhandsvisning.
 *
 * Egen fil, egen CSS, egen adresse. Rorer ikke app.js.
 *
 * ALT ER EKTE DATA. Den henter /api/snapshot, /api/catalog og
 * /api/product/<id> -- de samme endepunktene dagens app bruker. Skulle
 * dette vaert vurdert paa oppdiktede tall, ville vi vurdert en tegning og
 * ikke et produkt: det er nettopp naar en butikk heter «CollectorsCorner»
 * og prisen er «12 999 kr» at man ser om designet holder.
 *
 * Foelging krever konto, som i dag. Designet viste ett trykk uten konto,
 * men det er push-abonnementet som henger sammen med brukeren, og den
 * loypa har betalende kunder i seg. Utseendet kan vurderes uten aa rore
 * den.
 */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const REGION = { en: "engelsk", jp: "japansk", cn: "kinesisk", ko: "koreansk" };

const state = {
  produkter: [],
  butikker: new Map(),
  typer: new Map(),
  sok: "",
  status: null,      // «inne» | «forhand» | null
  sprak: null,
  type: null,
  tetthet: localStorage.getItem("pokepuls-ny-tetthet") || "luftig",
  sist: null,
};

/* Priser i nb-NO med tynt mellomrom, som handoffen ber om: «1 649 kr». */
const kr = (ore) => ore == null ? "–"
  : Math.round(ore / 100).toLocaleString("nb-NO").replace(/ /g, " ") + " kr";

function siden(iso) {
  if (!iso) return "ukjent";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 1) return "nå";
  if (min < 60) return min + " min siden";
  if (min < 1440) return Math.round(min / 60) + " t siden";
  return Math.round(min / 1440) + " d siden";
}

async function hent(sti) {
  const r = await fetch("/api" + sti, {
    credentials: "same-origin", headers: { Accept: "application/json" },
  });
  if (!r.ok) throw new Error(r.status);
  return r.json();
}

/* Statusen en vare har. Tre verdier, aldri en fjerde -- det er regelen i
 * handoffen, og den er grunnen til at siden er lett aa lese. */
function status(p) {
  if (Number(p.antall_pa_lager)) return "inne";
  if (Number(p.antall_forhandssalg) || Number(p.antall_bestilling)) return "forhand";
  return "ute";
}
const STATUSORD = { inne: "På lager", forhand: "Forhåndssalg", ute: "Utsolgt" };

function pris(p) {
  return Number(p.antall_pa_lager) ? p.min_pris : p.min_pris_bestilling ?? p.min_pris;
}

function bilde(p) {
  return p.bilde
    ? '<img class="kort-bilde" src="' + esc(p.bilde) + '" alt="" loading="lazy">'
    : '<div class="kort-bilde"></div>';
}

/* ------------------------------------------------------------- stripen */

/* «Pa lager na» -- det eneste som haster paa siden.
 *
 * Handoffen er tydelig: er ingenting nytt inne, skal den kollapse til én
 * stille linje. En tom mork blokk ville ropt like hoyt som en full. */
function tegnStripe() {
  const boks = $("stripe");
  const nylig = state.produkter
    .filter((p) => Number(p.antall_pa_lager) && p.sist_hendelse)
    .map((p) => ({ p, t: new Date(p.sist_hendelse).getTime() }))
    .filter((x) => Date.now() - x.t < 60 * 60 * 1000)
    .sort((a, b) => b.t - a.t)
    .slice(0, 3);

  boks.hidden = false;
  if (!nylig.length) {
    boks.className = "stripe stille";
    boks.textContent = "Ingenting nytt inn den siste timen.";
    return;
  }
  boks.className = "stripe";
  boks.innerHTML =
    '<div class="stripe-topp"><span class="stripe-etikett">På lager nå</span>' +
    '<span class="stripe-antall">' + nylig.length +
    (nylig.length === 1 ? " funn" : " funn") + " siste time</span></div>" +
    '<div class="stripe-rader">' + nylig.map(({ p, t }) =>
      '<a class="stripe-rad" href="#" data-id="' + esc(p.id) + '">' +
      (p.bilde ? '<img class="stripe-bilde" src="' + esc(p.bilde) + '" alt="">'
               : '<div class="stripe-bilde"></div>') +
      '<span class="stripe-tekst">' +
        '<span class="stripe-navn">' + esc(p.set_label) + " " + esc(p.type_label) + "</span>" +
        '<span class="stripe-meta">' + esc(butikknavn(p)) + " · " + siden(p.sist_hendelse) + "</span>" +
      "</span>" +
      '<span class="stripe-hoyre"><span class="stripe-pris">' + kr(p.min_pris) + "</span>" +
      '<span class="pille">Kjøp</span></span></a>').join("") + "</div>";
}

function butikknavn(p) {
  const t = (p.tilbud || []).find((x) => x[2] === 1);
  return t ? (state.butikker.get(t[0]) || t[0]) : "";
}

/* --------------------------------------------------------------- listen */

function treff() {
  const s = state.sok.trim().toLowerCase();
  return state.produkter.filter((p) => {
    if (state.status && status(p) !== state.status) return false;
    if (state.sprak && p.region !== state.sprak) return false;
    if (state.type && p.type_id !== state.type) return false;
    if (s && !(p.set_label + " " + p.type_label).toLowerCase().includes(s)) return false;
    return true;
  });
}

function kortHtml(p) {
  const st = status(p);
  const navn = esc(p.set_label) + " " + esc(p.type_label);
  const meta = esc(p.type_label) + " · " + esc(REGION[p.region] || p.region);
  const butikker = Number(p.antall_pa_lager) || Number(p.antall_forhandssalg) || 0;

  if (state.tetthet === "kompakt") {
    return '<a class="kort" href="#" data-id="' + esc(p.id) + '">' +
      '<span class="prikk ' + st + '"></span>' +
      '<span class="kort-tekst"><span class="kort-navn">' + navn + "</span>" +
      '<span class="kort-meta">' + meta + " · " + butikker + " butikker</span></span>" +
      '<span class="kort-hoyre"><span class="kort-pris">' + kr(pris(p)) + "</span>" +
      '<span class="kort-status">' + STATUSORD[st] + "</span></span></a>";
  }
  return '<a class="kort" href="#" data-id="' + esc(p.id) + '">' +
    bilde(p) +
    '<span class="kort-tekst"><span class="kort-navn">' + navn + "</span>" +
    '<span class="kort-meta">' + meta + "</span>" +
    '<span class="kort-bunn"><span class="kort-pris">' + kr(pris(p)) + "</span>" +
    '<span class="kort-butikker">' + butikker + " butikker</span>" +
    '<span class="merke-status ' + st + '">' + STATUSORD[st] + "</span></span></span>" +
    '<button class="folg" type="button" aria-label="Følg" data-folg="' + esc(p.id) + '">+</button>' +
    "</a>";
}

function tegn() {
  const t = treff();
  $("liste").className = "liste " + state.tetthet;
  $("resultat").textContent = t.length + " produkter";
  $("tom").hidden = t.length > 0;
  $("liste").innerHTML = t.slice(0, 300).map(kortHtml).join("");

  if (!t.length) {
    // Handoffen: vis hva som VILLE matchet med ett filter borte, og tilby
    // aa fjerne det. En tom liste uten vei videre er en blindvei.
    const uten = { ...state, status: null };
    const antall = state.produkter.filter((p) =>
      (!uten.sprak || p.region === uten.sprak) &&
      (!uten.type || p.type_id === uten.type)).length;
    $("tom").innerHTML = "Ingen treff." +
      (state.status ? '<button type="button" id="fjern-status">Vis alle ' +
        antall + " produkter i stedet</button>" : "");
    const f = $("fjern-status");
    if (f) f.onclick = () => { state.status = null; oppdaterFiltre(); tegn(); };
  }

  const n = [state.status, state.sprak, state.type].filter(Boolean).length;
  $("filterteller").hidden = !n;
  $("filterteller").textContent = n;
  $("aktive-filtre").innerHTML = [
    state.status && ["status", STATUSORD[state.status]],
    state.sprak && ["sprak", REGION[state.sprak]],
    state.type && ["type", state.typer.get(state.type)],
  ].filter(Boolean).map(([n2, tekst]) =>
    '<span class="chip">' + esc(tekst) +
    '<button type="button" data-fjern="' + n2 + '" aria-label="Fjern">×</button></span>').join("");
}

/* -------------------------------------------------------------- filtre */

function knapp(verdi, tekst, felt) {
  return '<button type="button" data-felt="' + felt + '" data-verdi="' + esc(verdi) +
    '" aria-pressed="' + (state[felt] === verdi) + '">' + esc(tekst) + "</button>";
}

function oppdaterFiltre() {
  $("valg-status").innerHTML =
    ["inne", "forhand", "ute"].map((v) => knapp(v, STATUSORD[v], "status")).join("");
  $("valg-sprak").innerHTML =
    Object.keys(REGION).map((v) => knapp(v, REGION[v], "sprak")).join("");
  $("valg-type").innerHTML =
    [...state.typer].slice(0, 8).map(([id, l]) => knapp(id, l, "type")).join("");
  $("valg-tetthet").innerHTML =
    '<button type="button" data-tetthet="luftig" aria-pressed="' +
      (state.tetthet === "luftig") + '">Luftige kort</button>' +
    '<button type="button" data-tetthet="kompakt" aria-pressed="' +
      (state.tetthet === "kompakt") + '">Kompakte rader</button>';
}

/* ---------------------------------------------------------- produktarket */

async function apneProdukt(id) {
  $("ark-bak").hidden = false;
  $("ark").hidden = false;
  $("ark").innerHTML = '<div class="ark-hank"></div><div class="skjelett"></div>';
  document.body.style.overflow = "hidden";

  let d;
  try { d = await hent("/product/" + encodeURIComponent(id)); }
  catch (e) { $("ark").innerHTML = '<div class="ark-hank"></div><p>Fikk ikke kontakt.</p>'; return; }

  const p = d.produkt;
  const inne = d.tilbud.filter((t) => t.in_stock === true && !t.bestillingstype);
  const forhand = d.tilbud.filter((t) => t.in_stock === true && t.bestillingstype);
  const ute = d.tilbud.filter((t) => !inne.includes(t) && !forhand.includes(t));
  const bld = d.tilbud.find((t) => t.image_url);
  const laveste = inne.length ? Math.min(...inne.map((t) => t.price_ore).filter(Boolean)) : null;

  const rad = (t) => {
    const st = t.bestillingstype ? "forhand" : t.in_stock ? "inne" : "ute";
    const handling = t.in_stock ? "Kjøp" : "Varsle";
    return '<a class="butikkrad" href="' + esc(t.url) + '" target="_blank" rel="nofollow noopener">' +
      '<span class="prikk ' + st + '"></span>' +
      '<span class="butikkrad-tekst"><span class="butikk-navn">' + esc(t.store_name) + "</span>" +
      '<span class="butikk-note">sjekket ' + siden(t.last_seen_at) + "</span></span>" +
      '<span class="butikk-pris">' + kr(t.price_ore) + "</span>" +
      '<span class="pille' + (t.in_stock ? "" : " sekundaer") + '">' + handling + "</span></a>";
  };

  $("ark").innerHTML =
    '<div class="ark-hank"></div>' +
    '<div class="ark-topp">' +
      (bld ? '<img class="ark-bilde" src="' + esc(bld.image_url) + '" alt="">'
           : '<div class="ark-bilde"></div>') +
      '<div><h2 class="ark-tittel">' + esc(p.set_label) + " " + esc(p.type_label) + "</h2>" +
      '<p class="ark-meta">' + esc(p.type_label) + " · " + esc(REGION[p.region] || p.region) + "</p>" +
      '<div class="ark-piller">' +
        '<span class="merke-status inne">' + inne.length + " på lager</span>" +
        (forhand.length ? '<span class="merke-status forhand">' + forhand.length + " forhåndssalg</span>" : "") +
        '<span class="merke-status ute">' + ute.length + " utsolgt</span>" +
      "</div></div></div>" +

    '<div class="statkort-rad">' +
      '<div class="statkort"><p class="etikett">Laveste nå</p>' +
        '<div class="statkort-tall">' + kr(laveste) + "</div>" +
        '<p class="statkort-under">' + inne.length + " butikker inne</p></div>" +
      '<div class="statkort"><p class="etikett">Butikker</p>' +
        '<div class="statkort-tall">' + d.tilbud.length + "</div>" +
        '<p class="statkort-under">vi følger med på</p></div>' +
    "</div>" +

    '<div class="tabellkort"><div class="tabell-topp"><h3>Butikker</h3>' +
      '<span class="tabell-sort">pris</span></div>' +
      inne.map(rad).join("") + forhand.map(rad).join("") + ute.map(rad).join("") +
    "</div>" +

    '<p class="ark-forbehold">Prisene hentes automatisk og kan være opptil 20 ' +
    "minutter gamle. Bekreft alltid hos butikken før du kjøper. Frakt er " +
    "ikke med i prisen — den leser vi ikke ennå.</p>" +
    '<a class="hovedknapp" href="/?produkt=' + encodeURIComponent(p.id) + '">' +
    "Varsle meg ved restock</a>";
}

function lukkArk() {
  $("ark").hidden = true;
  $("ark-bak").hidden = true;
  document.body.style.overflow = "";
}

/* ------------------------------------------------------------- oppstart */

function koble() {
  $("knapp-sok").onclick = () => {
    const r = $("sok-rad");
    r.hidden = !r.hidden;
    if (!r.hidden) $("sok").focus();
  };
  $("sok").addEventListener("input", (e) => { state.sok = e.target.value; tegn(); });
  $("knapp-filtre").onclick = () => { $("filterpanel").hidden = !$("filterpanel").hidden; };
  $("knapp-folger").onclick = () => { location.href = "/"; };
  $("knapp-sort").onclick = () => { location.href = "/"; };

  $("filterpanel").addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.tetthet) {
      state.tetthet = b.dataset.tetthet;
      localStorage.setItem("pokepuls-ny-tetthet", state.tetthet);
    } else if (b.dataset.felt) {
      const f = b.dataset.felt;
      state[f] = state[f] === b.dataset.verdi ? null : b.dataset.verdi;
    }
    oppdaterFiltre();
    tegn();
  });

  $("aktive-filtre").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-fjern]");
    if (!b) return;
    state[b.dataset.fjern] = null;
    oppdaterFiltre();
    tegn();
  });

  document.addEventListener("click", (e) => {
    const folg = e.target.closest("[data-folg]");
    if (folg) {
      e.preventDefault();
      // Foelging krever konto, som i dag. Designet viste ett trykk uten,
      // men det er push-abonnementet som henger sammen med brukeren.
      location.href = "/?produkt=" + encodeURIComponent(folg.dataset.folg);
      return;
    }
    const kort = e.target.closest("[data-id]");
    if (kort) { e.preventDefault(); apneProdukt(kort.dataset.id); }
  });

  $("ark-bak").onclick = lukkArk;
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") lukkArk(); });
}

async function start() {
  $("liste").innerHTML = '<div class="skjelett"></div>'.repeat(5);
  koble();
  try {
    const [snap, kat] = await Promise.all([hent("/snapshot"), hent("/catalog")]);
    (kat.stores || []).forEach((b) => state.butikker.set(b.id, b.name));
    (kat.types || []).forEach((t) => state.typer.set(t.id, t.label));
    state.produkter = snap.produkter;
    state.sist = snap.sist_skannet;
    $("friskhet").innerHTML = "oppdatert " + esc(siden(snap.sist_skannet)) +
      " · <b>" + state.butikker.size + " butikker</b>";
    oppdaterFiltre();
    tegnStripe();
    tegn();
    // Friskheten tikker. Den er produktets hovedargument -- da skal den
    // ikke staa og lyve om at det er fire minutter siden i en time.
    setInterval(() => {
      $("friskhet").innerHTML = "oppdatert " + esc(siden(state.sist)) +
        " · <b>" + state.butikker.size + " butikker</b>";
    }, 30000);
  } catch (e) {
    $("liste").innerHTML = "";
    $("friskhet").textContent = "fikk ikke kontakt med serveren";
  }
}

start();
