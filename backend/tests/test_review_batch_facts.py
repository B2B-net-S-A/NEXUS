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

import re

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


# ── Wzmianka w CV bez regexa po całym tekście (loop_stall 25.11.2026) ──────


def _regex_text_hit(text, variants):
    """``_text_hit`` sprzed 25.11.2026 — wzorzec porównawczy."""
    for variant in variants:
        if not variant:
            continue
        if re.search(rf"(?<![\w+#.]){re.escape(variant)}(?![\w+#])", text):
            return True
    return False


_CV_TEXTS = (
    "",
    "java",
    "javascript developer, typescript",
    "javascript i java 17",
    "c++11, c++ i c#; objective-c",
    "asp.net mvc oraz .net core 8",
    "node.js, nodejs; express",
    "mssql, ms sql i sql server (t-sql)",
    "go, golang, google cloud, django",
    "r&d, r, rust, (r) studio",
    "łódź: aws.lambda, aws, terraform.",
    "spring-boot spring_boot springboot spring.",
    "f# i f#.net, #c, c#8",
)
_VARIANTS = (
    "java",
    "javascript",
    "c",
    "c++",
    "c#",
    "f#",
    ".net",
    "net",
    "node.js",
    "sql",
    "sql server",
    "ms sql",
    "go",
    "r",
    "aws",
    "spring",
    "boot",
    "łódź",
    "t-sql",
    "(r)",
    "",
)


@pytest.mark.parametrize("text", _CV_TEXTS)
def test_text_hit_matches_whole_text_regex(text):
    for variant in _VARIANTS:
        assert facts._text_hit(text, [variant]) is _regex_text_hit(text, [variant]), (
            text,
            variant,
        )
    assert facts._text_hit(text, _VARIANTS) is _regex_text_hit(text, _VARIANTS)


class _CountingRe:
    """``re`` modułu faktów, który liczy uruchomienia wyrażeń regularnych."""

    def __init__(self):
        self.calls = 0

    def __getattr__(self, name):
        attr = getattr(re, name)
        if name not in {"compile", "search", "match", "fullmatch", "finditer"}:
            return attr

        def counted(*args, **kwargs):
            self.calls += 1
            return attr(*args, **kwargs)

        return counted


def test_text_hit_runs_no_regex_when_no_word_is_in_the_cv(monkeypatch):
    """Na Tablicach większości słów nie ma w CV osoby: ``str.find`` (w C)
    wystarcza, regex tylko rozstrzyga granicę słowa przy trafieniu."""
    counting = _CountingRe()
    monkeypatch.setattr(facts, "re", counting)
    cv = "doświadczenie: python, django, postgresql, docker, kubernetes " * 200
    assert facts._text_hit(cv, ["kafka", "spark", "scala", "hadoop"]) is False
    assert counting.calls == 0
