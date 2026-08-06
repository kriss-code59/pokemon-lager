"""E-post via Resend.

Bare tre e-poster finnes, og alle tre er noe brukeren nettopp ba om:
glemt passord, verifiser adressen, og bekreftelse paa sletting. Ingen
nyhetsbrev, ingen "vi savner deg". Varsler gaar via push, ikke e-post --
en restock-beskjed som kommer som e-post er allerede for sen.

Oppsett (Kristian gjor dette selv, jeg rorer ikke API-nokler):

    1. Lag konto pa resend.com, legg til domenet pokepuls.no og folg
       DNS-oppskriften deres (tre poster i cPanel hos Domene AS).
       MX-posten deres skal IKKE roeres -- Resend trenger bare TXT/CNAME
       for DKIM og SPF, og e-post TIL deg skal fortsatt til Domene.
    2. Lag en API-nokkel med «Sending access».
    3. Paa serveren:

           sudo sh -c 'echo "RESEND_API_KEY=re_din_nokkel" >> /etc/pokepuls.env'
           sudo systemctl restart pokepuls-api

Uten nokkelen er alt annet uendret -- send() returnerer (False, grunn), og
API-et svarer at e-post ikke er satt opp. Ingenting kraesjer.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API = "https://api.resend.com/emails"

# Avsender maa ligge paa et domene som er verifisert hos Resend. Fram til
# domenet er verifisert kan du bruke "onboarding@resend.dev", som bare kan
# sende til din egen adresse -- nok til aa teste at koden virker.
AVSENDER = os.environ.get("POKEPULS_EPOST_FRA", "Pokepuls <ikke-svar@pokepuls.no>")
SVAR_TIL = os.environ.get("POKEPULS_EPOST_SVAR", "norgekriss@gmail.com")


def er_satt_opp() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def send(til: str, emne: str, tekst: str, html: str | None = None) -> tuple[bool, str | None]:
    """-> (ok, feil). Kaster aldri."""
    nokkel = os.environ.get("RESEND_API_KEY")
    if not nokkel:
        return False, "RESEND_API_KEY mangler"

    kropp = json.dumps({
        "from": AVSENDER,
        "to": [til],
        "reply_to": SVAR_TIL,
        "subject": emne,
        "text": tekst,
        **({"html": html} if html else {}),
    }).encode("utf-8")

    req = urllib.request.Request(
        API, data=kropp, method="POST",
        headers={"Authorization": f"Bearer {nokkel}",
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            r.read()
        return True, None
    except urllib.error.HTTPError as e:
        # Resend forteller HVA som er galt i kroppen. Uten den staar man
        # igjen med "400 Bad Request" og ingen anelse.
        detalj = ""
        try:
            detalj = e.read().decode()[:300]
        except Exception:
            pass
        return False, f"Resend svarte {e.code}: {detalj}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- maler
#
# Ren tekst forst, HTML som pynt. En e-post som BARE er HTML havner oftere
# i soppelposten, og lenken skal kunne kopieres ut av teksten hvis knappen
# ikke virker i et rart e-postprogram.

def _ramme(overskrift: str, avsnitt: str, knapp_tekst: str, lenke: str) -> str:
    return f"""<!DOCTYPE html><html><body style="margin:0;padding:24px;
background:#0b0d10;color:#e8ecf1;font:15px/1.5 -apple-system,Segoe UI,Roboto,sans-serif">
<div style="max-width:520px;margin:0 auto">
<p style="font-size:20px;font-weight:800;margin:0 0 20px">
<span style="color:#e8ecf1">poke</span><span style="color:#ffcb05">puls</span></p>
<h1 style="font-size:19px;margin:0 0 12px">{overskrift}</h1>
<p style="color:#c7ced7;margin:0 0 20px">{avsnitt}</p>
<p><a href="{lenke}" style="display:inline-block;padding:12px 20px;
background:#ffcb05;color:#1a1400;font-weight:700;border-radius:10px;
text-decoration:none">{knapp_tekst}</a></p>
<p style="color:#8b95a3;font-size:12.5px;margin-top:24px">
Virker ikke knappen, lim inn denne i nettleseren:<br>
<span style="color:#4c9aff;word-break:break-all">{lenke}</span></p>
</div></body></html>"""


def send_passordlenke(til: str, lenke: str) -> tuple[bool, str | None]:
    tekst = (
        "Noen ba om et nytt passord til Pokepuls-kontoen din.\n\n"
        f"Lag nytt passord her (lenken varer i 1 time):\n{lenke}\n\n"
        "Var det ikke deg, kan du se bort fra denne e-posten. "
        "Passordet ditt er uendret.\n")
    return send(til, "Nytt passord til Pokepuls", tekst,
                _ramme("Lag nytt passord",
                       "Lenken varer i én time. Var det ikke du som ba om "
                       "dette, kan du se bort fra e-posten — passordet ditt "
                       "er uendret.", "Lag nytt passord", lenke))


def send_verifisering(til: str, lenke: str) -> tuple[bool, str | None]:
    tekst = (
        "Velkommen til Pokepuls.\n\n"
        f"Bekreft e-postadressen din her (lenken varer i 3 døgn):\n{lenke}\n\n"
        "Da kan du få nytt passord hvis du glemmer det.\n")
    return send(til, "Bekreft e-posten din hos Pokepuls", tekst,
                _ramme("Bekreft e-posten din",
                       "Da kan du få tilsendt nytt passord hvis du glemmer "
                       "det. Lenken varer i tre døgn.", "Bekreft e-posten", lenke))
