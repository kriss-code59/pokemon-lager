/* Kontaktskjemaet paa /om.html.
 *
 * Egen fil, ikke innebygd skript: CSP-en setter script-src 'self' uten
 * unsafe-inline. Et innebygd <script> ville sluttet aa kjore stille.
 *
 * Ingen innlogging. Den som vurderer aa lage konto, den som ikke kommer
 * inn, og den som vil klage, maa alle naa fram -- og ingen av dem har en
 * konto aa logge inn med.
 */
const $ = (id) => document.getElementById(id);

$("kontakt-skjema").addEventListener("submit", async (e) => {
  e.preventDefault();
  const knapp = e.target.querySelector("button[type=submit]");
  const feil = $("k-feil");
  const ok = $("k-ok");
  feil.hidden = true;
  ok.hidden = true;
  knapp.disabled = true;
  try {
    const r = await fetch("/api/feedback/apen", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      body: JSON.stringify({
        tekst: $("k-tekst").value,
        epost: $("k-epost").value.trim() || null,
        nettsted: $("k-nettsted").value || null,
      }),
    });
    const t = await r.text();
    const d = t ? JSON.parse(t) : null;
    if (!r.ok) throw new Error((d && d.detail) || ("Serveren svarte " + r.status));
    e.target.querySelector("textarea").value = "";
    ok.textContent = $("k-epost").value.trim()
      ? "Takk. Vi svarer på e-posten du oppga."
      : "Takk, meldingen er mottatt.";
    ok.hidden = false;
  } catch (err) {
    feil.textContent = err.message;
    feil.hidden = false;
  } finally {
    knapp.disabled = false;
  }
});
