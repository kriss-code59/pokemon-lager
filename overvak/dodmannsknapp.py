#!/usr/bin/env python3
"""Dodmannsknapp: varsler hvis scraperen har sluttet a oppdatere data.

Bakgrunn: 2026-08-02 kl. 14:00 hang en Playwright-kjoring for alltid. Fordi
cron bruker `flock -n`, avsluttet alle 132 pafolgende kjoringer stille uten a
skrive en eneste loggplinje. Ingen oppdaget det pa 44 timer.

Denne sjekken ma derfor vaere HELT UAVHENGIG av scraperen: egen cron-jobb,
egen prosess, ingen delt las. Dor scraperen, skal denne fortsatt leve.

Kjores hvert 15. minutt:
    */15 * * * * /usr/bin/python3 /home/ubuntu/pokemon-lager/overvak/dodmannsknapp.py
"""
import datetime
import json
import os
import sys
import urllib.request

# Scraperen gar hvert 20. minutt og bruker ~19 min. 60 min uten oppdatering
# er derfor tre tapte kjoringer -- utvetydig feil, men romslig nok til at en
# enkelt treg kjoring ikke utloser falskt alarm.
MAKS_ALDER_MIN = 60

# Ikke mas: ett varsel per time sa lenge feilen varer.
VARSEL_INTERVALL_MIN = 60

# Scraperen sover 22-04 norsk tid, sa data er lovlig gammelt om natta.
NATT_START, NATT_SLUTT = 22, 4

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROT, "docs", "data.json")
TILSTAND = "/tmp/pokemon-lager-dodmannsknapp.json"


def oslo_time():
    """Norsk lokaltid. ZoneInfo handterer sommer-/vintertid riktig; faller
    tilbake til UTC+1 hvis tzdata mangler pa maskinen."""
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(ZoneInfo("Europe/Oslo"))
    except Exception:
        return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=1)))


def er_natt():
    t = oslo_time().hour
    return t >= NATT_START or t < NATT_SLUTT


def les_tilstand():
    try:
        with open(TILSTAND, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def skriv_tilstand(d):
    try:
        with open(TILSTAND, "w", encoding="utf-8") as f:
            json.dump(d, f)
    except Exception as e:
        print("kunne ikke skrive tilstand: %s" % e, file=sys.stderr)


def varsle(tittel, melding):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        print("NTFY_TOPIC mangler -- kan ikke varsle. %s: %s" % (tittel, melding),
              file=sys.stderr)
        return False
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/%s" % topic,
            data=melding.encode("utf-8"),
            method="POST",
            headers={"Title": tittel, "Priority": "urgent", "Tags": "skull,rotating_light"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        print("varsling feilet: %s" % e, file=sys.stderr)
        return False


def main():
    na = datetime.datetime.now(datetime.timezone.utc)

    if er_natt():
        print("natt i Norge -- hopper over")
        return 0

    try:
        with open(DATA, encoding="utf-8") as f:
            sist = json.load(f).get("last_updated")
        tidspunkt = datetime.datetime.fromisoformat(sist)
        if tidspunkt.tzinfo is None:
            tidspunkt = tidspunkt.replace(tzinfo=datetime.timezone.utc)
    except Exception as e:
        # Kan vi ikke lese data.json i det hele tatt, er noe alvorlig galt.
        varsle("SCRAPER: kan ikke lese data.json", "Feil: %s" % e)
        return 2

    alder_min = (na - tidspunkt).total_seconds() / 60
    print("data.json er %.0f min gammel (grense %d)" % (alder_min, MAKS_ALDER_MIN))

    if alder_min <= MAKS_ALDER_MIN:
        # Frisk igjen: nullstill, sa neste feil varsler umiddelbart.
        if les_tilstand().get("sist_varslet"):
            skriv_tilstand({})
            print("scraperen er frisk igjen")
        return 0

    tilstand = les_tilstand()
    sist_varslet = tilstand.get("sist_varslet")
    if sist_varslet:
        siden = (na - datetime.datetime.fromisoformat(sist_varslet)).total_seconds() / 60
        if siden < VARSEL_INTERVALL_MIN:
            print("allerede varslet for %.0f min siden -- venter" % siden)
            return 1

    timer = alder_min / 60
    if varsle(
        "SCRAPER STAR STILLE",
        "docs/data.json er %.1f timer gammel (siste oppdatering %s UTC).\n"
        "Scraperen har sannsynligvis hengt seg opp. Sjekk:\n"
        "  tail -20 ~/scrape-cron.log\n"
        "  ps -eo pid,lstart,comm | grep -E 'chrome|flock'"
        % (timer, tidspunkt.strftime("%Y-%m-%d %H:%M")),
    ):
        tilstand["sist_varslet"] = na.isoformat()
        skriv_tilstand(tilstand)
    return 1


if __name__ == "__main__":
    sys.exit(main())
