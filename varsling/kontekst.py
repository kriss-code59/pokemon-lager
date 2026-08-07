"""Prisbildet rundt en hendelse.

Ett sporsmaal, to sporringer: hva koster den samme varen andre steder NAA,
og hva var den billigste kjopbare prisen siste uke.

Begge tar produkt-id, ikke oppforings-id. Det er hele poenget med den
kanoniske katalogen: "Prismatic Evolutions Booster Bundle" er ETT produkt
selv om seks butikker kaller den seks forskjellige ting.
"""
from __future__ import annotations

BILLIGST_NA_SQL = """
SELECT l.price_ore, st.name AS store_name
FROM listings l JOIN stores st ON st.id = l.store_id
WHERE l.product_id = %s AND l.in_stock IS TRUE AND l.price_ore >= 500
  -- Bare ekte lager teller som sammenligningsgrunnlag. Et forhaandssalg
  -- til 2 699 kr skal ikke gjore at en vare du kan faa i posten i morgen
  -- til 2 999 kr faar merkelappen «finnes billigere» -- det er ikke det
  -- samme produktet i tid.
  AND l.bestillingstype IS NULL
  AND l.last_seen_at > now() - interval '2 days'
ORDER BY l.price_ore
"""

# Hendelsestabellen er den eneste prishistorikken vi har. Bare hendelser der
# varen faktisk kunne kjopes teller: en "utsolgt"-rad forteller hva prisen
# var da den forsvant, ikke hva du kunne betalt.
BILLIGST_7D_SQL = """
SELECT min(price_ore) AS pris FROM events
WHERE product_id = %s AND kind IN ('ny','restock','prisendring')
  AND price_ore >= 500 AND detected_at > now() - interval '7 days'
"""


def hent(cur, produkt_id: str | None) -> dict:
    """Synkron psycopg-cursor med dict_row inn, kontekst-dict ut."""
    if not produkt_id:
        return {"billigst_na_ore": None, "billigst_butikk": None,
                "billigst_7d_ore": None, "antall_pa_lager": 0}

    cur.execute(BILLIGST_NA_SQL, (produkt_id,))
    inne = cur.fetchall()
    cur.execute(BILLIGST_7D_SQL, (produkt_id,))
    rad = cur.fetchone()

    return {
        "billigst_na_ore": inne[0]["price_ore"] if inne else None,
        "billigst_butikk": inne[0]["store_name"] if inne else None,
        "billigst_7d_ore": (rad or {}).get("pris"),
        "antall_pa_lager": len(inne),
    }
