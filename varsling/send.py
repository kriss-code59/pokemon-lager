"""Sender Web Push til en enkelt enhet, og rydder opp etter dode enheter.

Skilt fra tekst.py fordi dette er den eneste delen som snakker med
nettverket -- og dermed den eneste delen som kan feile pa maater vi ikke
kontrollerer.
"""
from __future__ import annotations

import json
import logging

from . import vapid

log = logging.getLogger("varsling")

# Pushtjenesten skal ikke holde meldingen lenger enn den er relevant. En
# restock-beskjed som dukker opp fire timer senere er verre enn ingen:
# du gaar til butikken og varen er borte igjen.
TTL_SEKUNDER = {"restock": 1800, "ny": 1800, "prisendring": 7200, "utsolgt": 3600}

# 404/410 = abonnementet finnes ikke lenger. Alt annet kan vaere midlertidig
# (telefonen er av, tjenesten har hikke) og skal ikke slette enheten.
DODE_KODER = (404, 410)


class IkkeKonfigurert(RuntimeError):
    pass


def send(endepunkt: dict, varsel: dict, ttl: int | None = None) -> tuple[bool, str | None, int | None]:
    """-> (ok, feilmelding, http_status)

    `endepunkt` = {'endpoint', 'p256dh', 'auth'} fra push_endpoints.
    `varsel`   = resultatet fra varsling.tekst.bygg().
    """
    if not vapid.har_nokler():
        raise IkkeKonfigurert(
            "POKEPULS_VAPID_PRIVATE/PUBLIC mangler. Kjor: python -m varsling.vapid")

    from pywebpush import WebPushException, webpush

    kropp = json.dumps({
        "title": varsel["title"],
        "body": varsel["body"],
        "url": varsel.get("url"),
        "produkt_url": varsel.get("produkt_url"),
        "bilde": varsel.get("bilde"),
        "tag": varsel.get("tag"),
        "hastig": varsel.get("hastig", False),
    }, ensure_ascii=False)

    try:
        svar = webpush(
            subscription_info={
                "endpoint": endepunkt["endpoint"],
                "keys": {"p256dh": endepunkt["p256dh"], "auth": endepunkt["auth"]},
            },
            data=kropp,
            vapid_private_key=vapid.privat_nokkel(),
            vapid_claims=dict(vapid.vapid_krav()),
            ttl=ttl if ttl is not None else TTL_SEKUNDER.get(varsel.get("kind"), 3600),
            headers={"Urgency": "high" if varsel.get("hastig") else "normal"},
            timeout=10,
        )
        return True, None, getattr(svar, "status_code", 201)
    except WebPushException as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return False, str(e)[:300], status
    except Exception as e:  # nettverk, DNS, tidsavbrudd
        return False, f"{type(e).__name__}: {e}"[:300], None


def er_dod(status: int | None) -> bool:
    return status in DODE_KODER
