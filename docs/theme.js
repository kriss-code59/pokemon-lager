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
