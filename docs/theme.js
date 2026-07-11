// Bestemmer om vi er i "rolig periode" (22:00-04:00 norsk tid), da automatisk
// oppdatering skal pause siden butikkene uansett ikke skannes om natten (se
// .github/workflows/scrape.yml). Bruker Intl med Europe/Oslo som tidssone i
// stedet for a regne pa UTC-offset manuelt, sa sommertid/vintertid (CEST/CET)
// haandteres riktig automatisk uten a hardkode et offset som blir feil halve
// aaret.
function isNorwegianQuietHours() {
  var osloHour = parseInt(
    new Intl.DateTimeFormat('en-GB', {
      timeZone: 'Europe/Oslo',
      hour: '2-digit',
      hour12: false,
    }).format(new Date()),
    10
  );
  return osloHour >= 22 || osloHour < 4;
}

// Felles auto-oppdatering for alle sider. Ren setInterval er ikke nok: de
// fleste nettlesere strupe/pauser timere i bakgrunnsfaner (spesielt pa
// mobil, eller nar fanen ikke er aktiv), sa en side som har staett urort i
// bakgrunnen en stund kan fremstaa som at den "ikke oppdaterer seg selv"
// naar brukeren kommer tilbake til den. Vi dekker derfor to tilfeller: et
// vanlig intervall (for aktive faner), OG en umiddelbar oppdatering nar
// fanen blir synlig igjen etter aa ha vaert skjult.
function registerAutoRefresh(loadFn, intervalMs) {
  intervalMs = intervalMs || 5 * 60 * 1000;
  var lastRun = Date.now();
  loadFn();

  function maybeRun() {
    if (isNorwegianQuietHours()) return;
    lastRun = Date.now();
    loadFn();
  }

  setInterval(maybeRun, intervalMs);

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && Date.now() - lastRun > 30 * 1000) {
      maybeRun();
    }
  });
}

// Delt tema-logikk (mork/lys modus) for alle sider i dashboardet.
(function () {
  var stored = localStorage.getItem('theme');
  var theme = stored || 'dark';
  document.documentElement.setAttribute('data-theme', theme);

  document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('themeToggle');
    if (!btn) return;
    var current = document.documentElement.getAttribute('data-theme');
    btn.textContent = current === 'dark' ? '☀️' : '🌙';
    btn.addEventListener('click', function () {
      var now = document.documentElement.getAttribute('data-theme');
      var next = now === 'dark' ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
      btn.textContent = next === 'dark' ? '☀️' : '🌙';
    });
  });
})();
