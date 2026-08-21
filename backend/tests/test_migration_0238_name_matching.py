"""Forma Unicode w dopasowaniu nazwisk korekty BIK (rewizja 0238).

Korekta wskazuje dziewięć osób porównaniem CAŁEGO napisu
(`lower(trim(name) || ' ' || trim(lastname)) IN (...)`), a taki predykat jest
wrażliwy na formę zapisu: „ń" bywa w bazie trzymane jako „n" + U+0301 i wtedy
równość po prostu nie trafia. To już raz kosztowało kontrakt #571 (Robert
Łuszczyński), doaktywowany osobną rewizją 0239 — punktowo, prefiksem `LIKE`,
więc przyczyna została. Na tej samej liście stoi „michał leśniak", gdzie „ś"
rozkłada się dokładnie tak samo.

Regresja jest CICHA: migracja nie raportuje, ilu z dziewięciu ludzi trafiła,
więc częściowe pudło wygląda w logach identycznie jak pełne trafienie —
wychodzi dopiero wtedy, gdy ktoś zauważy, że kontraktor jest szkicem.

Test pilnuje OBU połówek niezmiennika, bo każda z osobna jest bezużyteczna:

* kolumna musi być normalizowana do NFC po stronie SQL-a,
* literały nazwisk muszą być zapisane w NFC — literał wklejony w formie
  rozłożonej nie zrówna się z żadnym znormalizowanym rekordem, czyli
  normalizacja kolumny cicho przestaje działać dla tej jednej osoby.

Zakres: `entrypoint.sh` niesie LUSTRO tego samego SQL-a (prod alembic bywa
osierocony) i nadal porównuje surowy napis — jego poprawka wykracza poza tę
zmianę. Dlatego dla lustra sprawdzamy tylko to, co jest w nim dziś prawdą:
że literały są w NFC.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

import pytest
from sqlalchemy import text

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0238_contract_order_workflows.py"
ENTRYPOINT = BACKEND / "entrypoint.sh"

# Zapisane tutaj w NFC — to jest wzorzec, do którego porównujemy oba źródła.
EXPECTED_NAMES = (
    "aleksander wojdyła",
    "daniel madejski",
    "maciej koc",
    "robert łuszczyński",
    "paweł łaski",
    "konrad teper",
    "michał leśniak",
    "wojciech wojtak",
    "grzegorz wadecki",
)

# Linia zawierająca WYŁĄCZNIE literał (z przecinkiem lub bez). Komentarze SQL
# zaczynają się od `--`, więc nie wpadają tu przypadkiem, mimo że też bywają
# w apostrofach.
_NAME_LITERAL = re.compile(r"^\s*'([^']+)',?\s*$", re.MULTILINE)


def _name_literals(path: Path) -> list[str]:
    """Wytnij listę nazwisk z bloku korekty BIK w danym pliku.

    Kotwice są wspólne dla obu ścieżek mimo różnych wcięć: predykat kończy się
    na `trim(ca.lastname)`, a lista domyka się tuż przed guardem markera.
    """

    body = path.read_text(encoding="utf-8")
    start = body.index("trim(ca.lastname)")
    end = body.index("AND EXISTS (SELECT 1 FROM marker)", start)
    return _NAME_LITERAL.findall(body[start:end])


def test_migration_normalizes_the_candidate_name_before_comparing():
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "lower(normalize(trim(ca.name) || ' ' || trim(ca.lastname), NFC))" in sql, (
        "predykat 0238 wrócił do porównania surowego napisu — nazwiska w formie rozłożonej znów przepadną"
    )
    assert "lower(trim(ca.name) || ' ' || trim(ca.lastname)) IN (" not in sql, (
        "w 0238 został stary, nieznormalizowany wariant porównania"
    )


@pytest.mark.parametrize(
    "source", (MIGRATION, ENTRYPOINT), ids=("migration", "entrypoint")
)
def test_bik_name_literals_are_stored_in_nfc(source: Path):
    literals = _name_literals(source)

    assert tuple(literals) == EXPECTED_NAMES, (
        f"{source.name}: lista nazwisk rozjechała się ze wzorcem"
    )
    for literal in literals:
        assert literal == unicodedata.normalize("NFC", literal), (
            f"{source.name}: literał {literal!r} jest w formie rozłożonej — "
            "porównanie do znormalizowanej kolumny nigdy go nie trafi"
        )


async def test_postgres_normalize_matches_a_decomposed_lastname():
    """Semantyka po stronie silnika, nie po stronie Pythona.

    `normalize(..., NFC)` istnieje dopiero od Postgresa 13, a sam fakt, że
    predykat wygląda poprawnie w źródle, nie dowodzi, że baza go wykona i że
    faktycznie zrówna zapis rozłożony ze złożonym.
    """

    from app.core.database import AsyncSessionLocal

    composed = unicodedata.normalize("NFC", "Michał Leśniak")
    decomposed = unicodedata.normalize("NFD", composed)
    assert composed != decomposed, "test straciłby sens, gdyby obie formy były równe"

    first, last = decomposed.split(" ")
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT "
                    "lower(normalize(trim(:first) || ' ' || trim(:last), NFC)) "
                    "= :expected AS normalized_hit, "
                    "lower(trim(:first) || ' ' || trim(:last)) "
                    "= :expected AS raw_hit"
                ),
                {"first": first, "last": last, "expected": composed.lower()},
            )
        ).one()

    assert row.normalized_hit is True, (
        "Postgres nie zrównał formy rozłożonej ze złożoną mimo normalize(..., NFC)"
    )
    assert row.raw_hit is False, (
        "porównanie surowego napisu nagle trafia — pułapka, którą ten test "
        "opisuje, zniknęła i predykat można uprościć świadomie, nie przypadkiem"
    )
