# Drift

## Hva som kjorer hvor

Scraperen kjorer pa en server (i dag EC2 `pokemon-lager-scraper`, eu-north-1),
styrt av to cron-jobber:

```cron
# Skanning hvert 20. minutt. timeout dreper en hengende kjoring etter 15 min;
# uten den blokkerer flock -n alle senere kjoringer for alltid (se hendelsen
# 2026-08-02). python3 -u gir ubufret output, ellers viser loggen ingenting
# nar en kjoring dor.
*/20 * * * * PATH=/home/ubuntu/.local/bin:/usr/bin:/bin timeout -k 60 1200 flock -n /tmp/pokemon-lager-scrape.lock /home/ubuntu/pokemon-lager/deploy/ec2-cron-scrape.sh >> /home/ubuntu/scrape-cron.log 2>&1

# Dodmannsknapp hvert 15. minutt. MA vaere en egen jobb uten delt las, slik at
# den fortsatt lever selv om scraperen henger.
*/15 * * * * NTFY_TOPIC=<topic> /usr/bin/python3 /home/ubuntu/pokemon-lager/overvak/dodmannsknapp.py >> /home/ubuntu/dodmannsknapp.log 2>&1
```

## Hendelse 2026-08-02: 44 timer uten data

**Symptom:** siste commit 2026-08-02 13:59. Ingen feilmeldinger noe sted.

**Arsak:** en kjoring startet 14:00:01 og hang. Playwright har ingen
standard-timeout, sa da Chromium mistet forbindelsen til en butikk uten a
rapportere det, la `python3` seg i `epoll_wait` og ventet i det uendelige.
Prosessen holdt `/tmp/pokemon-lager-scrape.lock`, og fordi cron bruker
`flock -n`, avsluttet hver eneste pafolgende kjoring umiddelbart -- uten
output. 132 tapte kjoringer, null spor i loggen.

**Retting:**
1. `context.set_default_timeout()` og `set_default_navigation_timeout()` i
   `scrape.py`, sa en hengende side kaster TimeoutError
2. try/except per butikk, sa en butikk som feiler ikke river med seg resten
3. `timeout -k 60 1200` i cron som ytre sikkerhetsnett
4. `python3 -u` sa loggen viser hvor kjoringen faktisk star
5. `overvak/dodmannsknapp.py` som varsler hvis data blir eldre enn 60 min

**Lardom:** et system som overvaker butikker, men ikke seg selv, er blindt.
