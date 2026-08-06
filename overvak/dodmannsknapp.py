#!/usr/bin/env python3
"""Dodmannsknapp: varsler hvis scraperen har sluttet a oppdatere data.

Bakgrunn: 2026-08-02 kl. 14:00 hang en Playwright-kjoring for alltid. Fordi
cron bruker `flock -n`, avsluttet alle 132 pafolgende kjoringer stille uten a
skrive en eneste loggplinje. Ingen oppdaget det pa 44 timer.

Den 2026-08-05 skjedde det igjen -- av en annen grunn (cron kunne ikke
kjore skriptet), og med et annet utfall: dodmannsknappen FYRTE som den
skulle. Inn i et offentlig ntfy-topic ingen fulgte med paa. Scraperen sto
i 28 timer.

Laerdommen er ikke at overvakingen var feil. Den var at KANALEN var feil:
et varsel ingen mottar er ikke et varsel.

Derfor sender denne na Web Push til alle med role='admin' -- den samme
kanalen du allerede har paa telefonen for restock-varsler, og som du merker
med en gang hvis den slutter a virke. ntfy beholdes bare som reserve, og
bare hvis NTFY_TOPIC er satt.

To ting den fortsatt gjor riktig, og som ikke maa endres:

* **Helt uavhengig av scraperen.** Egen cron-jobb, egen prosess, ingen delt
  las. Dor scraperen, skal denne fortsatt leve.
* **Leser sannheten, ikke en mellomstasjon.** Den ser paa scrape_runs i
  Postgres -- det samme /api/health ser paa. Tidligere leste den
  docs/data.json, som fortsatt kan skrives selv om ingesten feiler.

Kjores hvert 15. minutt (se deploy/oppsett-api.sh).
"""
import datetime
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Scraperen gar hvert 20. minutt. 60 min uten oppdatering er derfor tre
# tapte kjoringer -- utvetydig feil, men romslig nok til at en enkelt treg
# kjoring ikke utloser falsk alarm.
MAKS_ALDER_MIN = 60

# Ikke mas: ett varsel per time sa lenge feilen varer.
VARSEL_INTERVALL_MIN = 60

# Scraperen sover 22-04 norsk tid, sa data er lovlig gammelt om natta.
NATT_START, NATT_SLUTT = 22, 4

DSN = os.environ.get("POKEPULS_DSN", "postgresql:///pokepuls")
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


# --------------------------------------------------------------- kanaler

def _push_til_admin(tittel, melding):
    """-> antall enheter som fikk varselet.

    Feiler stille og returnerer 0: klarer vi ikke pushe, skal ntfy-reserven
    fortsatt faa prove. En dodmannsknapp som selv kaster unntak er ingen
    dodmannsknapp.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row

        from varsling import send as sender
        from varsling import vapid

        if not vapid.har_nokler():
            print("VAPID-nokler mangler -- kan ikke pushe", file=sys.stderr)
            return 0

        with psycopg.connect(DSN, row_factory=dict_row) as conn:
            cur = conn.execute(
                "SELECT p.id, p.endpoint, p.p256dh, p.auth FROM push_endpoints p "
                "JOIN users u ON u.id = p.user_id WHERE u.role = 'admin'")
            enheter = cur.fetchall()

        if not enheter:
            print("ingen admin-enheter registrert -- ingen kan motta varselet",
                  file=sys.stderr)
            return 0

        varsel = {"title": "🚨 " + tittel, "body": melding,
                  "url": "https://pokepuls.no/admin.html",
                  "produkt_url": "https://pokepuls.no/admin.html",
                  "tag": "dodmannsknapp", "kind": "restock", "hastig": True}
        ok = 0
        for e in enheter:
            # TTL 0: dette varselet er verdilost hvis det leveres senere.
            # Enten naar det frem naa, eller sa fyrer vi igjen om en time.
            if sender.send(e, varsel, ttl=900)[0]:
                ok += 1
        return ok
    except Exception as e:
        print("push feilet: %s" % e, file=sys.stderr)
        return 0


def _ntfy(tittel, melding):
    """Reserve. Bare hvis NTFY_TOPIC er satt.

    Merk: et ntfy-topic er ikke hemmelig og ikke autentisert -- hvem som
    helst som kjenner navnet kan bade lese og sende falske varsler. Det er
    grunnen til at dette ikke lenger er hovedkanalen.
    """
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return False
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/%s" % topic,
            data=melding.encode("utf-8"),
            method="POST",
            headers={"Title": tittel, "Priority": "urgent",
                     "Tags": "skull,rotating_light"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            r.read()
        return True
    except Exception as e:
        print("ntfy feilet: %s" % e, file=sys.stderr)
        return False


def varsle(tittel, melding):
    n = _push_til_admin(tittel, melding)
    reserve = _ntfy(tittel, melding)
    if n:
        print("varslet %d admin-enhet(er)" % n)
    if not n and not reserve:
        # Siste utvei: skriv det i loggen sa det i det minste finnes et spor.
        print("INGEN KANAL VIRKET. %s: %s" % (tittel, melding), file=sys.stderr)
    return bool(n or reserve)


# ------------------------------------------------------------------ sjekk

def les_siste_kjoring():
    """-> (starttid, ok, feilede_butikker) fra Postgres.

    Faller tilbake pa docs/data.json hvis databasen ikke svarer -- da er
    noe alvorlig galt uansett, og vi vil helst kunne si HVA.
    """
    try:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DSN, row_factory=dict_row, connect_timeout=10) as conn:
            cur = conn.execute(
                "SELECT started_at, ok, failed_stores FROM scrape_runs "
                "ORDER BY started_at DESC LIMIT 1")
            rad = cur.fetchone()
        if rad:
            return rad["started_at"], rad["ok"], rad["failed_stores"] or [], None
        return None, None, [], "ingen kjoringer registrert"
    except Exception as e:
        try:
            with open(DATA, encoding="utf-8") as f:
                sist = json.load(f).get("last_updated")
            t = datetime.datetime.fromisoformat(sist)
            if t.tzinfo is None:
                t = t.replace(tzinfo=datetime.timezone.utc)
            return t, None, [], "databasen svarer ikke (%s)" % type(e).__name__
        except Exception as e2:
            return None, None, [], "verken database eller data.json (%s / %s)" % (e, e2)


def main():
    na = datetime.datetime.now(datetime.timezone.utc)

    if er_natt():
        print("natt i Norge -- hopper over")
        return 0

    tidspunkt, ok, feilede, problem = les_siste_kjoring()

    if tidspunkt is None:
        varsle("POKEPULS: ingen data", problem or "ukjent feil")
        return 2

    alder_min = (na - tidspunkt).total_seconds() / 60
    print("siste kjoring er %.0f min gammel (grense %d)%s"
          % (alder_min, MAKS_ALDER_MIN, "" if not problem else " [%s]" % problem))

    if alder_min <= MAKS_ALDER_MIN:
        # Frisk igjen: nullstill, sa neste feil varsler umiddelbart.
        if les_tilstand().get("sist_varslet"):
            skriv_tilstand({})
            varsle("✅ Pokepuls: scraperen går igjen",
                   "Siste kjøring for %.0f minutter siden." % alder_min)
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
    melding = ("Siste skanning var for %.1f timer siden (%s UTC).\n"
               "Sjekk:  tail -30 ~/scrape.log\n"
               "        grep flock /etc/cron.d/pokepuls"
               % (timer, tidspunkt.strftime("%Y-%m-%d %H:%M")))
    if problem:
        melding = problem + "\n" + melding
    if feilede:
        melding += "\nFeilede butikker sist: " + ", ".join(feilede[:6])

    if varsle("Pokepuls: scraperen står stille", melding):
        tilstand["sist_varslet"] = na.isoformat()
        skriv_tilstand(tilstand)
    return 1


if __name__ == "__main__":
    sys.exit(main())
