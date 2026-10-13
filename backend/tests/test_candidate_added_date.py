"""„W bazie od” — reguła daty wejścia do bazy, „skąd” i zapis daty z Traffita (bez bazy).

Prośba rekrutera 13.10.2026: przy osobie ma być widać, od kiedy jest w bazie.
`candidates.created_at` osób z Traffita to dzień importu, więc data musi
pochodzić z Traffita (`source_created_at`), a gdy jej nie ma — ekran mówi
uczciwie „przed …” zamiast pokazać dzień importu jako prawdę.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.candidate_added_date import (
    FIRST_IMPORT_DAY,
    added_to_base,
    added_via_label,
)
from app.services.candidate_quick_view import resolve_source
from app.services.traffit.importer import candidate_payload_sha
from app.services.traffit.mappers import traffit_employee_to_candidate

UTC = timezone.utc
IMPORT_DAY = datetime(2026, 4, 16, 10, 0, tzinfo=UTC)
LATER_IMPORT = datetime(2026, 9, 17, 3, 0, tzinfo=UTC)
NEXUS_DAY = datetime(2026, 10, 3, 9, 30, tzinfo=UTC)
IN_TRAFFIT = datetime(2019, 5, 11, 22, 0, tzinfo=UTC)


def test_source_date_wins_when_older_and_is_exact() -> None:
    added = added_to_base(IMPORT_DAY, IN_TRAFFIT, "traffit")
    assert added.at == IN_TRAFFIT
    assert added.exact is True


def test_earlier_of_two_dates_for_an_adopted_row() -> None:
    """Osoba założona w NEXUSIE, później dopasowana do kartoteki z Traffita."""
    later_in_traffit = datetime(2026, 10, 10, 8, 0, tzinfo=UTC)
    added = added_to_base(NEXUS_DAY, later_in_traffit, "traffit")
    assert added.at == NEXUS_DAY
    assert added.exact is True


def test_person_added_in_nexus_is_exact() -> None:
    added = added_to_base(NEXUS_DAY, None, "manual")
    assert added.at == NEXUS_DAY
    assert added.exact is True


def test_traffit_row_without_source_date_is_not_exact() -> None:
    """Dzień importu z nocnej delty (17.09) — wiemy tylko „przed”."""
    added = added_to_base(LATER_IMPORT, None, "traffit")
    assert added.at == LATER_IMPORT
    assert added.exact is False
    assert added_to_base(IMPORT_DAY, None, "tr_legacy").exact is False


def test_rows_from_the_first_import_day_are_not_exact() -> None:
    """Wiersze ze startu (np. LinkedIn, Pracuj z 15–16.04) nie mają prawdziwej daty."""
    late_evening_warsaw = datetime(2026, 4, 16, 21, 30, tzinfo=UTC)  # 23:30 w Warszawie
    assert added_to_base(late_evening_warsaw, None, "manual").exact is False
    # 22:30 UTC 16.04 to już 17.04 w Warszawie.
    next_day_warsaw = datetime(2026, 4, 16, 22, 30, tzinfo=UTC)
    assert FIRST_IMPORT_DAY.isoformat() == "2026-04-16"
    assert added_to_base(next_day_warsaw, None, "manual").exact is True


def test_missing_dates() -> None:
    added = added_to_base(None, None, "traffit")
    assert added.at is None
    assert added.exact is False


def test_added_via_prefers_the_traffit_source_name_from_domain() -> None:
    """Import zapisuje nazwę źródła w `domain`, `value` przychodzi pusty."""
    tags = [
        {"type": "skill", "value": "Java"},
        {"type": "traffit_source", "value": None, "domain": "Aktywny Search"},
        {"type": "traffit_source", "value": None, "domain": "career_page"},
    ]
    assert added_via_label(tags, "traffit", "traffit") == "Traffit · Aktywny Search"
    career = [{"type": "traffit_source", "value": None, "domain": "career_page"}]
    assert added_via_label(career, "traffit", "traffit") == "Traffit · Strona kariery"


def test_added_via_for_people_added_in_nexus() -> None:
    assert added_via_label([], "cv_upload", "manual") == "CV upload"
    assert added_via_label(None, "email", "manual") == "E-mail"
    assert added_via_label([], "invite_link:anna-k", "manual") == "Formularz aplikacyjny"
    assert added_via_label([], None, "manual") is None


def test_added_via_for_traffit_without_source_tag() -> None:
    assert added_via_label([], "traffit", "traffit") == "Traffit"
    assert added_via_label([], None, "traffit") == "Traffit"


def test_quick_view_source_reads_the_domain_too() -> None:
    candidate = type(
        "C",
        (),
        {
            "tags": [{"type": "traffit_source", "value": None, "domain": "CV upload"}],
            "source": "traffit",
            "external_source": "traffit",
            "creator": None,
        },
    )()
    assert resolve_source(candidate)["acquisition_source"] == "CV upload"


def _employee(**over) -> dict:
    base = {
        "id": 6708,
        "name": "Jan",
        "lastname": "Kowalski",
        "email": "jan@example.test",
        "created_at": "2019-05-12 00:00:00",
        "updated_at": "2022-07-19 06:59:26",
    }
    base.update(over)
    return base


def test_mapper_keeps_the_traffit_added_date_in_utc() -> None:
    payload = traffit_employee_to_candidate(_employee())
    # Czas Traffita bez strefy = Europe/Warsaw (maj: +02:00).
    assert payload["source_created_at"] == IN_TRAFFIT.isoformat()


def test_mapper_without_date_gives_none() -> None:
    assert traffit_employee_to_candidate(_employee(created_at=None))["source_created_at"] is None
    assert traffit_employee_to_candidate(_employee(created_at=""))["source_created_at"] is None


def test_payload_hash_ignores_the_added_date() -> None:
    """Nowe pole nie może zmienić skrótu 57 tys. kartotek — pełny bieg przepisałby każdą."""
    payload = traffit_employee_to_candidate(_employee())
    without = {k: v for k, v in payload.items() if k != "source_created_at"}
    assert candidate_payload_sha(payload) == candidate_payload_sha(without)
    other_date = {**payload, "source_created_at": "2020-01-01T00:00:00+00:00"}
    assert candidate_payload_sha(other_date) == candidate_payload_sha(payload)
