"""Sync Traffita nie przejmuje treści należących do NEXUSA.

Tabela `jobs` ma dwóch piszących i do 09.2026 nie było między nimi granicy:
`_UPSERT_JOB` wymieniał `title` i `status` w `DO UPDATE SET` bezwarunkowo, więc
rekrutacja opublikowana ręcznie w NEXUSIE wracała do `draft` przy najbliższym
dotknięciu wiersza przez nocny sync. Bez śladu i bez powiadomienia — objaw był
widoczny dopiero jako liczba na dashboardzie.

Podział w `app/services/job_column_ownership.py` jest deklaracją; nic go nie
egzekwuje w runtime. Egzekwuje go ten plik. Testy czytają ŹRÓDŁO, a nie
zachowanie jednej ścieżki, bo chroniona własność dotyczy każdego przyszłego
zapisu, nie tego jednego, który akurat pokryjemy testem wykonaniowym.
"""

import re
import sqlite3
from pathlib import Path

import pytest

from app.models.job import Job
from app.services import job_column_ownership as own

BACKEND = Path(__file__).resolve().parents[1]
IMPORTER = BACKEND / "app/services/traffit/importer.py"


def _do_update_set_columns() -> set[str]:
    """Kolumny wymienione w `DO UPDATE SET` w `_UPSERT_JOB`."""
    source = IMPORTER.read_text(encoding="utf-8")
    start = source.index("_UPSERT_JOB = text(")
    end = source.index("RETURNING id, (xmax = 0) AS was_insert", start)
    statement = source[start:end]

    clause = statement[statement.index("DO UPDATE SET") :]
    # `kolumna = ...` na początku przypisania; nazwy po prawej stronie
    # (`EXCLUDED.x`, `jobs.x`) mają kropkę i nie wpadają w ten wzorzec.
    return set(re.findall(r"^\s{4,}(\w+)\s*=", clause, flags=re.MULTILINE))


def test_sync_updates_exactly_the_columns_it_owns_or_may_invalidate():
    """Dokładna lista zapisów oraz ograniczonych unieważnień źródła.

    Rozjazd w którąkolwiek stronę jest błędem: kolumna w UPSERT-cie, a nie
    w zbiorze, to ciche nadpisywanie pracy z NEXUSA; kolumna w zbiorze, a nie
    w UPSERT-cie, to deklaracja, że sync coś prowadzi, czego nie prowadzi.
    """
    updated = _do_update_set_columns()
    permitted = own.SYNC_WRITABLE | own.SYNC_SOURCE_INVALIDATABLE

    assert updated == permitted, (
        "rozjazd `_UPSERT_JOB` z dozwolonymi zapisami/unieważnieniami; "
        f"tylko w UPSERT: {sorted(updated - permitted)}; "
        f"tylko w zbiorze: {sorted(permitted - updated)}"
    )


def test_sync_never_writes_unapproved_nexus_owned_columns():
    """Osobno od testu wyżej, bo to on nazywa SKUTEK naruszenia.

    Równość zbiorów pada z komunikatem o rozjeździe list. Ten test pada
    z komunikatem o tym, co się realnie stanie na produkcji, i to jest
    informacja, której szuka ktoś czytający czerwone CI.
    """
    trespassing = (
        _do_update_set_columns() & own.NEXUS_OWNED
    ) - own.SYNC_SOURCE_INVALIDATABLE

    assert not trespassing, (
        "sync Traffita nadpisałby kolumny prowadzone w NEXUSIE — praca "
        f"użytkownika zniknie przy najbliższym nocnym biegu: {sorted(trespassing)}"
    )


def test_source_invalidation_does_not_transfer_ownership_to_traffit():
    assert own.SYNC_SOURCE_INVALIDATABLE == {
        "matching_requirements",
        "requirements_reviewed",
    }
    assert own.SYNC_SOURCE_INVALIDATABLE <= own.NEXUS_OWNED
    assert not own.SYNC_SOURCE_INVALIDATABLE & own.SYNC_WRITABLE


@pytest.mark.parametrize(
    "column,stored,reset",
    [
        ("matching_requirements", '{"all_of": []}', None),
        ("matching_requirements", '{"all_of": [{"any_of": ["python"]}]}', None),
        ("matching_requirements", None, None),
        ("requirements_reviewed", 1, 0),
        ("requirements_reviewed", 0, 0),
    ],
)
@pytest.mark.parametrize("incoming_title", ["Python Developer", "Java Developer"])
def test_source_invalidation_only_resets_on_changed_title(
    column, stored, reset, incoming_title
):
    """Run the actual CASE: preserve NEXUS work, never import external criteria."""
    source = IMPORTER.read_text()
    expression = re.search(rf"{column}\s*=\s*(CASE.*?END),", source, re.S).group(1)
    query = (
        f"SELECT {expression} FROM (SELECT ? AS title, ? AS {column}) jobs "
        f"CROSS JOIN (SELECT ? AS title, ? AS {column}) EXCLUDED"
    )
    expected = stored if incoming_title == "Python Developer" else reset
    with sqlite3.connect(":memory:") as db:
        result = db.execute(
            query, ("Python Developer", stored, incoming_title, "external overwrite")
        ).fetchone()[0]
    assert result == expected


def test_every_column_has_an_owner():
    """Nowa kolumna bez decyzji „czyja jest" nie przechodzi.

    Czytamy `Job.__table__`, nie źródło, bo `created_at`/`updated_at`
    przychodzą z `TimestampMixin` i w ciele klasy ich nie widać.
    """
    model_columns = {c.key for c in Job.__table__.columns}
    classified = set(own.ALL_CLASSIFIED)

    assert model_columns == classified, (
        "każda kolumna `jobs` musi należeć do dokładnie jednego zbioru "
        "w `job_column_ownership.py`; "
        f"bez właściciela: {sorted(model_columns - classified)}; "
        f"sklasyfikowane, ale nieistniejące: {sorted(classified - model_columns)}"
    )


def test_owner_sets_do_not_overlap():
    """Kolumna w dwóch kubełkach czyni podział bezużytecznym."""
    buckets = {
        "TRAFFIT_OWNED": own.TRAFFIT_OWNED,
        "SYNC_IDENTITY": own.SYNC_IDENTITY,
        "SHARED_NEXUS_WINS": own.SHARED_NEXUS_WINS,
        "SYNC_BOOKKEEPING": own.SYNC_BOOKKEEPING,
        "NEXUS_OWNED": own.NEXUS_OWNED,
    }
    names = list(buckets)
    for i, left in enumerate(names):
        for right in names[i + 1 :]:
            shared = buckets[left] & buckets[right]
            assert not shared, f"{left} i {right} dzielą kolumny: {sorted(shared)}"


def test_is_open_belongs_to_nexus():
    """Kotwica na decyzję, nie na implementację.

    `is_open` istnieje po to, żeby „czy MY to prowadzimy" przestało zależeć od
    statusu z Traffita. Gdyby kiedykolwiek trafiło pod sync, wróciłby dokładnie
    problem, dla którego tę kolumnę dodano.
    """
    assert "is_open" in own.NEXUS_OWNED
    assert "is_open" not in own.SYNC_WRITABLE


def test_import_preserves_owner_and_pending_automatic_handoff():
    """Execute the import's real owner expression with both systems' values."""
    source = IMPORTER.read_text()
    expression = re.search(r"recruiter_id\s*=\s*(CASE.*?END),", source, re.S).group(1)
    query = f"SELECT {expression} FROM (SELECT ? AS recruiter_id, ? AS is_open) jobs CROSS JOIN (SELECT ? AS recruiter_id) EXCLUDED"
    with sqlite3.connect(":memory:") as db:
        for owner, opened, external, expected in [
            (7, 1, 8, 7),
            (None, 1, 8, None),
            (7, 0, 8, 7),
            (None, 0, 8, 8),
        ]:
            assert (
                db.execute(query, (owner, opened, external)).fetchone()[0] == expected
            )
