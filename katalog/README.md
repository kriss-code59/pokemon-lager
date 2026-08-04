# Kanonisk katalog

Gjor 18 228 ra butikkrader om til ~420 kanoniske produkter.

## Hvorfor

Uten dette er dataene bare en liste med butikklenker. Med det kan vi:

- vise "Destined Rivals Boosterpakke - 17 butikker har den" i stedet for 17 separate rader
- sammenligne pris pa tvers av butikker for samme vare
- la brukere folge ET PRODUKT, ikke en enkelt butikklenke som kan forsvinne
- sende ett restock-varsel per produkt i stedet for ett per butikk

Et kanonisk produkt er `sett x type x region`, f.eks. `pitch-black:booster-box:en`.

## Filer

| Fil | Innhold |
|---|---|
| `katalog.json` | Sett, produkttyper og regioner med aliaser |
| `matcher.py` | Klassifisering (sealed/single/merch) og matching mot katalogen |

## Bruk

```python
from katalog.matcher import Katalog
k = Katalog()
k.match("Maks 1 per pers. Pokemon Ascended Heroes Elite Trainer Box")
# {'set_id': 'ascended-heroes', 'type_id': 'etb', 'region': 'en',
#  'product_id': 'ascended-heroes:etb:en'}
```

## Vedlikehold

Nye sett kommer flere ganger i aret. Nar et sett mangler, dukker det opp som
gjentatte ordpar blant bommene. Kjor dekningsanalysen for a finne dem:

```
python3 katalog/dekning.py
```

Legg sa settet inn i `katalog.json` med riktig region og aliaser.

## Bevisste avgrensninger

- **Loskort droppes.** LABOGE og Pokesingles er rene loskort-butikker og
  hentes ikke i det hele tatt (de sto for 10 598 av 18 228 rader).
- **Merch droppes** (plysj, figurer, sleeves, portfolios).
- **Katalogen dekker sett folk faktisk jakter pa**, ikke hele Pokemons
  historie. Et produkt fra 2011 blir sjelden restocket, og en fullstendig
  katalog ville kostet mye vedlikehold for lite verdi.
