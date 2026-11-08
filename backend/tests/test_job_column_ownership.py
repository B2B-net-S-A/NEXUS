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

from pathlib import Path


from app.models.job import Job
from app.services import job_column_ownership as own

BACKEND = Path(__file__).resolve().parents[1]


def test_source_invalidation_does_not_transfer_ownership_to_traffit():
    assert own.SYNC_SOURCE_INVALIDATABLE == {
        "matching_requirements",
        "requirements_reviewed",
    }
    assert own.SYNC_SOURCE_INVALIDATABLE <= own.NEXUS_OWNED
    assert not own.SYNC_SOURCE_INVALIDATABLE & own.SYNC_WRITABLE


def test_managed_in_nexus_belongs_to_nexus():
    for column in ("managed_in_nexus", "managed_in_nexus_at", "managed_in_nexus_by"):
        assert column in own.NEXUS_OWNED
        assert column not in own.SYNC_WRITABLE


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
