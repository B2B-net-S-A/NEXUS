"""„Kluczowe w tej rekrutacji” na karcie porcji (R2 + R4, decyzje Artura 12.11.2026).

Raport: https://claude.ai/artifact/PqmctW9taWS8mXwmGfrFSM. Kontrakty:

- krytyczna ma trzy stany dowodu: doświadczenie (oś technologii z CV ma przy niej
  miesiące stanowisk), wzmianka (jest w CV albo w umiejętnościach, bez dat), brak;
- dowód tylko informuje: od 15.10 wzmianka wysyłała do klienta tak samo dobrze
  jak doświadczenie (10,8% wobec 10,7%), więc nikt nie wypada z porcji;
- polski: ojczysty z profilu, z CV po polsku albo z polskiego imienia i nazwiska;
  imię i nazwisko tylko podnosi status, nigdy nie daje „nie zna”; „nie zna”
  tylko po odrzuceniu „Brak polskiego”;
- osoba odrzucona za „Brak polskiego” nie wraca do porcji, chyba że rekrutacja
  wprost mówi, że polski nie jest potrzebny.
"""

from __future__ import annotations

import pytest

from app.services import review_batch_facts as facts


@pytest.mark.parametrize(
    ("name", "lastname", "expected"),
    [
        ("Marta", "Mikołajczyk", True),
        ("Jan", "Kowalski", True),
        ("Anna", "Nowak", True),
        ("Łukasz", "Smith", True),
        ("Aliaksei", "Ivanou", False),
        ("John", "Smith", False),
        (None, None, False),
    ],
)
def test_polish_name_only_raises(name, lastname, expected):
    assert facts.polish_name(name, lastname) is expected


def test_polish_status_order_of_sources():
    native = facts.polish_status(
        native=True, level=None, cv_polish=False, name_polish=False, refused_at=None
    )
    assert native == {"state": "native", "detail": "ojczysty w profilu"}
    level = facts.polish_status(
        native=False, level="B2", cv_polish=False, name_polish=False, refused_at=None
    )
    assert level == {"state": "level", "detail": "B2 w profilu"}
    cv = facts.polish_status(
        native=False, level=None, cv_polish=True, name_polish=False, refused_at=None
    )
    assert cv["state"] == "native" and "CV po polsku" in cv["detail"]
    name = facts.polish_status(
        native=False, level=None, cv_polish=False, name_polish=True, refused_at=None
    )
    assert name["state"] == "native" and "imię i nazwisko" in name["detail"]
    unknown = facts.polish_status(
        native=False, level=None, cv_polish=False, name_polish=False, refused_at=None
    )
    assert unknown == {"state": "unknown", "detail": "brak danych — sprawdź"}


def test_refusal_wins_over_name_but_not_over_profile():
    """Odrzucenie „Brak polskiego” to wiedza z rozmowy albo CV: wygrywa z samym
    imieniem i nazwiskiem, ale nie z polskim zapisanym w profilu."""
    by_name = facts.polish_status(
        native=False,
        level=None,
        cv_polish=False,
        name_polish=True,
        refused_at="2026-11-10",
    )
    assert by_name == {
        "state": "no",
        "detail": "odrzucona za brak polskiego 2026-11-10",
    }
    in_profile = facts.polish_status(
        native=True,
        level=None,
        cv_polish=False,
        name_polish=False,
        refused_at="2026-11-10",
    )
    assert in_profile["state"] == "native"


@pytest.mark.parametrize(
    ("months", "text_hit", "skill_hit", "state"),
    [
        (30, False, False, "experience"),
        (0, True, False, "mention"),
        (None, False, True, "mention"),
        (None, False, False, "none"),
    ],
)
def test_critical_evidence_states(months, text_hit, skill_hit, state):
    assert (
        facts.evidence_state(months=months, text_hit=text_hit, skill_hit=skill_hit)
        == state
    )


def test_evidence_detail_reads_like_a_person():
    assert facts.evidence_detail("experience", 30) == "2 lata 6 mies. w stanowiskach"
    assert facts.evidence_detail("experience", 8) == "8 mies. w stanowiskach"
    assert facts.evidence_detail("experience", 12) == "1 rok w stanowiskach"
    assert facts.evidence_detail("experience", 72) == "6 lat w stanowiskach"
    assert (
        facts.evidence_detail("mention", None) == "w CV albo umiejętnościach, bez dat"
    )
    assert facts.evidence_detail("none", None) == "brak w CV i profilu"


@pytest.mark.parametrize(
    ("language", "needs"),
    [
        (None, True),
        ("", True),
        ("PL, EN B2+", True),
        ("Angielski", True),
        ("English only", False),
        ("polski nie jest wymagany", False),
        ("bez polskiego, EN C1", False),
        ("Polish not required", False),
    ],
)
def test_job_needs_polish_unless_it_says_otherwise(language, needs):
    assert facts.job_needs_polish(language) is needs
