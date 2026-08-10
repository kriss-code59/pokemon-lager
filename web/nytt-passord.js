/* Egen side, ikke et ark i appen.
 *
 * Lenken i e-posten aapnes ofte i en helt annen nettleser enn den du bruker
 * til vanlig -- e-postklienters innebygde visning, en jobb-PC, en annen
 * telefon. Da skal det ikke kreves at hele appen laster, at et service
 * worker-skall er ferskt, eller at noe javascript-tungt virker. Det eneste
 * som trengs er et felt og en knapp. */
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const token = new URLSearchParams(location.search).get("t");

if (!token) {
  $("innhold").innerHTML =
    '<p class="side-status ute">Lenken mangler koden sin. Åpne lenken fra ' +
    "e-posten på nytt, eller be om en ny.</p>" +
    '<p><a class="side-cta" href="/">Til Pokepuls</a></p>';
} else {
  $("innhold").innerHTML =
    '<form id="skjema" class="skjema">' +
      '<label>Nytt passord<input id="p1" type="password" minlength="8" ' +
        'autocomplete="new-password" required></label>' +
      '<label>Gjenta passordet<input id="p2" type="password" minlength="8" ' +
        'autocomplete="new-password" required></label>' +
      '<p class="hjelp liten">Minst 8 tegn.</p>' +
      '<p class="feil" id="feil" hidden></p>' +
      '<button class="hovedknapp" type="submit">Lagre nytt passord</button>' +
    "</form>";

  $("skjema").addEventListener("submit", async (e) => {
    e.preventDefault();
    const feil = $("feil");
    feil.hidden = true;
    // Sjekkes her og ikke bare av serveren: to like felter er en skrivefeil
    // du vil oppdage FOR du har laast deg ute med et passord du ikke husker.
    if ($("p1").value !== $("p2").value) {
      feil.textContent = "Passordene er ikke like.";
      feil.hidden = false;
      return;
    }
    const knapp = e.target.querySelector("button");
    knapp.disabled = true;
    try {
      const r = await fetch("/api/auth/nytt-passord", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, password: $("p1").value }),
      });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || ("Serveren svarte " + r.status));
      // Serveren logger deg inn med en gang. Aa sende folk til en
      // innloggingsside rett etter at de beviste hvem de er, er et steg
      // for mye -- og et sted til aa skrive feil passord.
      $("innhold").innerHTML =
        '<p class="side-status inne">Passordet er lagret, og du er logget inn.</p>' +
        '<p><a class="side-cta" href="/">Til Pokepuls</a></p>';
    } catch (err) {
      feil.textContent = err.message;
      feil.hidden = false;
      knapp.disabled = false;
    }
  });
}
