"""VAPID-nokler for Web Push.

VAPID er hvordan pushtjenesten (Apple, Google, Mozilla) vet at det er VI som
sender, uten at vi har en konto hos dem. Noklene lages en gang og maa aldri
byttes: bytter du dem, blir hver eneste eksisterende abonnement ugyldig og
alle maa trykke "Slaa paa varsler" paa nytt.

Derfor ligger de i /etc/pokepuls.env og ikke i repoet.

Lage nokler:
    python -m varsling.vapid
"""
from __future__ import annotations

import base64
import os

PRIVAT = "POKEPULS_VAPID_PRIVATE"
OFFENTLIG = "POKEPULS_VAPID_PUBLIC"
# mailto: kreves av spesifikasjonen -- det er adressen pushtjenesten bruker
# hvis de maa kontakte oss om misbruk.
SUBJECT = os.environ.get("POKEPULS_VAPID_SUBJECT", "mailto:norgekriss@gmail.com")


def _b64(raa: bytes) -> str:
    return base64.urlsafe_b64encode(raa).decode().rstrip("=")


def har_nokler() -> bool:
    return bool(os.environ.get(PRIVAT) and os.environ.get(OFFENTLIG))


def offentlig_nokkel() -> str | None:
    """Den nettleseren trenger for aa lage et abonnement."""
    return os.environ.get(OFFENTLIG) or None


def privat_nokkel() -> str | None:
    return os.environ.get(PRIVAT) or None


def vapid_krav() -> dict:
    """Argumentene pywebpush trenger."""
    return {"sub": SUBJECT}


def generer() -> tuple[str, str]:
    """-> (privat, offentlig), begge base64url uten padding.

    Formatet er det py_vapid og nettleseren forventer: raa 32-byte privat
    skalar, og 65-byte ukomprimert offentlig punkt.
    """
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    nokkel = ec.generate_private_key(ec.SECP256R1())
    privat = nokkel.private_numbers().private_value.to_bytes(32, "big")
    offentlig = nokkel.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    return _b64(privat), _b64(offentlig)


if __name__ == "__main__":
    p, o = generer()
    print(f"{PRIVAT}={p}")
    print(f"{OFFENTLIG}={o}")
