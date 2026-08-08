"""Syntakssjekk av all SQL i repoet, uten en database.

pglast bruker Postgres sin egen parser (libpg_query). En SQL-setning som
gar gjennom her, gar gjennom pa serveren. Poenget er a fange skrivefeil i
en sporring som ellers forst smeller nar en bruker treffer endepunktet.

Kjor: python3 -m pytest tests/test_sql.py -q
"""
import ast
import os
import re

import pytest

pglast = pytest.importorskip("pglast")

ROT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KILDER = [os.path.join(ROT, "api", "main.py"),
          os.path.join(ROT, "api", "auth.py"),
          os.path.join(ROT, "ingest", "ingest.py")]

START = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH)\s+\S", re.I)

# En streng som slutter midt i en klausul er en halvdel som limes sammen med
# noe annet ved kjoretid (se /api/history). Den kan ikke parses alene, og
# daekkes i stedet av test_api_bygger_gyldig_history_sporring.
FRAGMENT = re.compile(r"(WHERE|AND|OR|,|\(|=|JOIN|BY|SET)\s*$", re.I)


def sql_strenger(sti):
    """Hent ut alle strengkonstanter som ser ut som SQL.

    Spissfindighet: psycopg bruker %s som plassholder, og det er ikke gyldig
    SQL. Vi bytter dem til NULL for parsing -- syntaksen rundt er det vi vil
    sjekke, ikke parameterne.
    """
    with open(sti, encoding="utf-8") as f:
        tre = ast.parse(f.read(), filename=sti)
    ut = []
    for node in ast.walk(tre):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if START.match(node.value) and not FRAGMENT.search(node.value):
                ut.append((sti, node.lineno, node.value))
        # "SELECT ..." "fortsettelse" limt sammen av Python skjer implisitt og
        # fanges av Constant over. Eksplisitt + fanges her:
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            try:
                verdi = ast.literal_eval(node)
            except Exception:
                continue
            if isinstance(verdi, str) and START.match(verdi) and not FRAGMENT.search(verdi):
                ut.append((sti, node.lineno, verdi))
    return ut


ALLE = [s for k in KILDER for s in sql_strenger(k)]


def test_fant_sporringer():
    assert len(ALLE) >= 12, "fant bare %d sporringer - har filene flyttet seg?" % len(ALLE)


@pytest.mark.parametrize("sti,linje,sql", ALLE,
                         ids=[f"{os.path.basename(s)}:{l}" for s, l, _ in ALLE])
def test_sql_parser(sti, linje, sql):
    pglast.parse_sql(sql.replace("%s", "NULL"))


def test_skjemaet_parser():
    with open(os.path.join(ROT, "db", "001_skjema.sql"), encoding="utf-8") as f:
        pglast.parse_sql(f.read())


def test_api_bygger_gyldig_history_sporring():
    """/api/history limer sammen WHERE-vilkar. Sjekk begge grenene."""
    grunn = ("SELECT e.kind FROM events e WHERE %s ORDER BY e.detected_at DESC LIMIT NULL")
    for vilkar in [
        "e.detected_at > now() - make_interval(hours => NULL)",
        "e.detected_at > now() - make_interval(hours => NULL) AND e.kind = ANY(NULL)",
    ]:
        pglast.parse_sql(grunn % vilkar)
