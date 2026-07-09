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
