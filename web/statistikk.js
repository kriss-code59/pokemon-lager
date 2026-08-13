/* Statistikksiden.
 *
 * Egen fil og egen side, ikke enda en fane i appen. Fire faner er alt det
 * som faar plass paa en mobilbunn, og en femte ville gjort de fire andre
 * traengre for noe de fleste aapner én gang i uka.
 *
 * Alt her er premium. Sperren ligger i API-et (402), ikke i at siden er
 * vanskelig aa finne -- denne filen kan hvem som helst laste ned.
 */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const UKEDAG = ["", "mandag", "tirsdag", "onsdag", "torsdag", "fredag",
                "lørdag", "søndag"];

function nar(iso) {
  if (!iso) return "aldri";
  const min = Math.round((Date.now() - new Date(iso)) / 60000);
  if (min < 60) return min + " min siden";
  if (min < 1440) return Math.round(min / 60) + " t siden";
  return Math.round(min / 1440) + " d siden";
}

/* Sooyler i ren HTML. Et diagrambibliotek er hundre kilobyte for noe som
 * her er en bredde i prosent. */
function stolper(rader, merk, verdi, format) {
  const maks = Math.max(...rader.map(verdi), 1);
  return '<div class="stolper">' + rader.map((r) => {
    const v = verdi(r);
    return '<div class="stolpe-rad"><span class="stolpe-merk">' +
      esc(merk(r)) + "</span>" +
      '<span class="stolpe-spor"><span class="stolpe-fyll" style="width:' +
      (v / maks * 100).toFixed(1) + '%"></span></span>' +
      '<span class="stolpe-tall">' + esc(format ? format(r) : v) + "</span></div>";
  }).join("") + "</div>";
}

async function last() {
  const boks = $("innhold");
  let r, d;
  try {
    r = await fetch("/api/statistikk/restock?dager=30", {
      credentials: "same-origin", headers: { Accept: "application/json" },
    });
    const t = await r.text();
    d = t ? JSON.parse(t) : null;
  } catch (e) {
    boks.innerHTML = '<p class="tom">Fikk ikke kontakt med serveren.</p>';
    return;
  }

  if (r.status === 401) {
    boks.innerHTML = '<p class="tom">Logg inn for å se statistikk.<br>' +
      '<a class="hovedknapp smal" href="/">Til forsiden</a></p>';
    return;
  }
  if (r.status === 402) {
    boks.innerHTML = '<div class="varselboks"><h3>Statistikk er en ' +
      "premium-funksjon</h3>" +
      '<p class="hjelp">Se hvilke butikker som fyller på oftest, når på ' +
      "døgnet det skjer, og hvilke varer som kommer inn igjen mest. " +
      "49 kr i måneden.</p>" +
      '<a class="hovedknapp" href="/">Skru på Premium fra kontosiden</a></div>';
    return;
  }
  if (!r.ok) {
    boks.innerHTML = '<p class="tom">' + esc((d && d.detail) || r.status) + "</p>";
    return;
  }

  const totalt = d.butikker.reduce((a, b) => a + Number(b.antall), 0);
  const beste = [...d.per_time].sort((a, b) => b.antall - a.antall)[0];

  boks.innerHTML =
    '<p class="side-under">' + totalt.toLocaleString("nb-NO") +
      " påfyll registrert de siste " + d.dager + " dagene</p>" +

    (beste && beste.antall
      ? '<div class="helsekort ok"><strong>Flest påfyll rundt kl. ' +
        beste.time + "</strong><span>" + beste.antall +
        " av " + totalt + " skjedde i den timen</span></div>"
      : "") +

    "<h2>Butikker som fyller på oftest</h2>" +
    (d.butikker.length
      ? stolper(d.butikker, (b) => b.store_name || b.store_id,
                (b) => Number(b.antall),
                (b) => b.antall + " · " + nar(b.sist))
      : '<p class="hjelp">Ingen påfyll registrert i perioden.</p>') +

    "<h2>Når på døgnet</h2>" +
    stolper(d.per_time, (t) => String(t.time).padStart(2, "0"),
            (t) => t.antall) +

    "<h2>Hvilken ukedag</h2>" +
    stolper(d.per_ukedag, (u) => UKEDAG[u.dag], (u) => u.antall) +

    "<h2>Varer som kommer inn igjen oftest</h2>" +
    (d.varer.length
      ? stolper(d.varer,
                (v) => (v.set_label || "?") + " " + (v.type_label || ""),
                (v) => Number(v.antall),
                (v) => v.antall + " · " + nar(v.sist))
      : '<p class="hjelp">Ingenting ennå.</p>') +

    '<p class="hjelp liten">' + esc(d.forbehold) + "</p>";
}

last();
