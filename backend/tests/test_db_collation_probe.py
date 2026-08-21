"""Kolacja bazy musi być FAKTEM w `/api/health/deep`, nie domysłem.

Regresja tutaj jest maksymalnie cicha: porządek sortowania całego tekstu
wybiera niejawnie tag obrazu w `docker-compose.yml`, a podmiana tego tagu na
istniejącym wolumenie przestawia porządek każdego btree na kolumnie tekstowej
BEZ ostrzeżenia (pod musl `datcollversion` jest pusty, więc wbudowany
bezpiecznik PostgreSQL nie może wystrzelić). Skutek: skan po indeksie zaczyna
gubić wiersze, a UNIQUE na tekście przestaje łapać duplikaty — przy zielonym
`/api/health` i zielonym deployu.

Dlatego test pilnuje dwóch rzeczy naraz: logiki porównania odcisku palca ORAZ
tego, że żywa baza faktycznie odpowiada na to zapytanie (kolumny
`datlocprovider`/`datcollversion` istnieją dopiero od PG 15 — sonda, która
tylko rzuca wyjątkiem, jest gorsza niż jej brak, bo zapala deploy na czerwono
z niewłaściwego powodu).
"""

from __future__ import annotations

import pytest

from app.core import db_collation

_ALPINE_ROW = {
    "datcollate": "en_US.utf8",
    "datctype": "en_US.utf8",
    "datlocprovider": "c",
    "datcollversion": "",
    "polish_order_ok": False,
}


def test_baseline_row_is_healthy():
    matches, report = db_collation.evaluate(dict(_ALPINE_ROW))
    assert matches is True
    assert report["matches_baseline"] is True
    assert report["polish_order_ok"] is False
    assert report["collation_version"] is None


def test_glibc_image_is_drift_even_though_datcollate_is_identical():
    """Sedno sprawy: `datcollate` jest TAKI SAM na obu obrazach.

    Sonda oparta o samą nazwę kolacji zwracałaby „bez zmian" dokładnie w tym
    momencie, w którym porządek indeksów już się rozjechał.
    """
    glibc = dict(_ALPINE_ROW)
    glibc.update(datcollversion="2.41", polish_order_ok=True)

    matches, report = db_collation.evaluate(glibc)

    assert glibc["datcollate"] == _ALPINE_ROW["datcollate"]
    assert matches is False
    assert report["matches_baseline"] is False


def test_icu_provider_is_drift():
    icu = dict(_ALPINE_ROW)
    icu.update(datlocprovider="i", datcollversion="153.136.48", polish_order_ok=True)
    matches, _ = db_collation.evaluate(icu)
    assert matches is False


def test_null_collation_version_is_treated_as_empty():
    """musl zwraca NULL, nie pusty string — obie postacie znaczą to samo."""
    row = dict(_ALPINE_ROW, datcollversion=None)
    matches, report = db_collation.evaluate(row)
    assert matches is True
    assert report["collation_version"] is None


@pytest.mark.asyncio
async def test_probe_sql_runs_against_the_live_database():
    """Zapytanie musi wykonać się na realnym Postgresie i zwrócić komplet pól."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        result = await session.execute(db_collation.COLLATION_PROBE_SQL)
        row = dict(result.mappings().one())

    assert set(row) == {
        "datcollate",
        "datctype",
        "datlocprovider",
        "datcollversion",
        "polish_order_ok",
    }
    matches, report = db_collation.evaluate(row)
    # Nie asertujemy `matches is True`: gdy ktoś ŚWIADOMIE zmieni obraz bazy,
    # ma zaktualizować baseline w `db_collation.py`, a nie zmagać się z testem.
    # Asertujemy to, co musi być prawdą zawsze — sonda dała odpowiedź.
    assert isinstance(matches, bool)
    assert report["baseline"] == db_collation.BASELINE_FINGERPRINT
