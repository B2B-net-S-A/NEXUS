"""Kto dostaje który dzwonek i mail — wzorzec zapisany w repo (bez bazy).

Powiadomienia trafiały do złych ludzi: 02.11.2026 „Podsumowanie Rady”
z przychodem i marżą firmy dostało 11 osób, w tym 5 z Finansów; dzwonki
z czatu rekrutacji szły do nieprzypisanych (18.11.2026); ruchy etapu do
prowadzących o cudzych kandydatach (10.11 i 18.11.2026). Każdy z tych
błędów był rozszerzeniem odbiorców, którego nikt nie zobaczył w PR-ze.

Ten test liczy odbiorców kodem produkcyjnym dla każdej persony z
``tests/_authz_matrix.py`` i porównuje z ``tests/data/notify_golden/``.
Zmiana = czerwony test z listą „rodzaj: ±persona (było/jest)”. Zamierzoną
zmianę przegeneruj i dołącz diff wzorca do PR-a:

    cd backend && NOTIFY_GOLDEN_WRITE=1 python -m pytest \\
        tests/test_notify_golden.py tests/test_notify_golden_db.py

Warstwy i pliki: ``tests/_notify_matrix.py``. Wybór odbiorców zapytaniami
do bazy (Rada, czat rekrutacji, ruch etapu, alerty klienta…):
``tests/test_notify_golden_db.py``. Reguła:
``docs/claude/powiadomienia/odbiorcy-golden.md``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.models.notification import NotificationType
from tests._authz_matrix import PERSONAS, Persona, build_user
from tests._notify_matrix import (
    CONTEXT_VARIANTS,
    WRITE_ENV,
    bell_matrix,
    check_or_write,
    failure_message,
    kind,
    load_golden,
    mail_matrix,
    persona_users,
)

pytestmark = pytest.mark.static

_WRITE = os.environ.get(WRITE_ENV) == "1"

# Fikcyjne id w regule „rekruter rekrutacji” (czysta funkcja, bez bazy).
_OWNER, _PAIR = 1, 2
_STAGE_LABELS = {_OWNER: "prowadzący rekrutację", _PAIR: "rekruter kandydata"}


@pytest.fixture(scope="module")
def users():
    return persona_users()


@pytest.fixture(scope="module")
def bells(users) -> dict[str, list[str]]:
    return bell_matrix(users)


@pytest.fixture(scope="module")
def mails(users):
    from app.core.config import settings

    patch = pytest.MonkeyPatch()
    # Program „Ludzie” działa na produkcji (HR_PROGRAM_ENABLED=true).
    patch.setattr(settings, "HR_PROGRAM_ENABLED", True)
    try:
        return mail_matrix(users)
    finally:
        patch.undo()


def _board_report_cast(users) -> list[tuple[str, object]]:
    """Persony plus admin z imiennym „mail Rady” (``users.receives_board_report``)."""

    named = build_user(Persona("admin", PERSONAS[0].role), user_id=919_999)
    named.receives_board_report = True
    return [(persona.key, user) for persona, user in users] + [
        ("admin+receives_board_report", named)
    ]


@pytest.fixture(scope="module")
def relations(users) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """``(rodzaje, obsady)`` — wybór odbiorców liczony czystymi funkcjami."""

    from app.services import announcements
    from app.services.stage_notification_resolver import job_recruiter_ids
    from app.tasks.kpi_email_reports import _board_readers

    out: dict[str, dict] = {}
    labels = {user.id: persona.key for persona, user in users}

    cast = _board_report_cast(users)
    board_labels = {user.id: label for label, user in cast}
    readers = _board_readers([user for _, user in cast])
    out["board_monthly_report [nadawca: Podsumowanie Rady]"] = kind(
        _board_readers,
        "persony + admin z nadaniem",
        board_labels,
        (u.id for u in readers),
    ).as_json()

    stage_cases = {
        "kandydat innego rekrutera": (_OWNER, _PAIR, False),
        "własny kandydat prowadzącego": (_OWNER, _OWNER, False),
        "kandydat bez rekrutera, ruch bez osoby": (_OWNER, None, False),
        "prowadzący wybrał wszystkie ruchy": (_OWNER, _PAIR, True),
    }
    for label, (owner, pair, wants_all) in stage_cases.items():
        ids = job_recruiter_ids(owner_id=owner, pair_id=pair, owner_wants_all=wants_all)
        out[f"stage_rule [reguła „rekruter rekrutacji”: {label}]"] = kind(
            job_recruiter_ids, "reguła etapu", _STAGE_LABELS, ids
        ).as_json()

    plain = [user for _, user in users]
    for label, roles in {
        "do wszystkich": [],
        "do Rady": ["board"],
        "do rekruterów": ["recruiter"],
    }.items():
        announcement = SimpleNamespace(audience_roles=roles)
        out[f"announcement_important [{label}]"] = kind(
            announcements._recipients,
            "persony",
            labels,
            announcements._recipients(announcement, plain),
        ).as_json()

    casts = {
        "persony": sorted(labels.values()),
        "persony + admin z nadaniem": sorted(board_labels.values()),
        "reguła etapu": sorted(_STAGE_LABELS.values()),
    }
    return out, casts


# ── Wzorce ───────────────────────────────────────────────────────────────────


def test_bell_gate_matches_golden(bells) -> None:
    lines = check_or_write(
        "bell_roles",
        bells,
        write=_WRITE,
        description=(
            "Brama dzwonka: persony, które notification_access."
            "user_can_receive_notification przepuszcza dla każdego "
            "NotificationType (bez wyciszeń osoby i roli). Producent wybiera "
            "spośród nich — patrz relations*.json."
        ),
        extra={"personas": [persona.key for persona in PERSONAS]},
    )
    assert not lines, failure_message(lines)


def test_mail_gate_matches_golden(mails) -> None:
    matrix, outside = mails
    lines = check_or_write(
        "mail_roles",
        matrix,
        write=_WRITE,
        description=(
            "Brama maila: persony, do których mail z CATALOG może trafić "
            "(notification_email_prefs.APPLIES, moduły „Ludzi” włączone)."
        ),
        extra={
            "personas": [persona.key for persona in PERSONAS],
            "poza_regula_konta": outside,
        },
    )
    assert not lines, failure_message(lines)


def test_pure_relations_match_golden(relations) -> None:
    kinds, casts = relations
    lines = check_or_write(
        "relations",
        kinds,
        write=_WRITE,
        description=(
            "Wybór odbiorców liczony czystymi funkcjami producentów (bez bazy). "
            "„obsada” = konta scenariusza (lista w „obsady”), „odbiorcy” = kogo "
            "wybiera kod; reszta obsady nie dostaje."
        ),
        extra={"obsady": casts},
    )
    assert not lines, failure_message(lines)


def test_golden_covers_every_type_and_mail_kind() -> None:
    """Nowy typ albo mail bez wpisu = świadoma decyzja o odbiorcach w PR-ze."""

    from app.services.notification_access import CONTEXTUAL_NOTIFICATION_TYPES
    from app.services.notification_delivery import CATALOG, SECURITY_CATALOG

    assert CONTEXTUAL_NOTIFICATION_TYPES <= CONTEXT_VARIANTS.keys(), (
        "Typ kontekstowy bez wariantów w tests/_notify_matrix.CONTEXT_VARIANTS"
    )
    bell_keys = set(load_golden("bell_roles")["rodzaje"])
    bell_types = {key.split(" [", 1)[0] for key in bell_keys}
    assert bell_types == {ntype.value for ntype in NotificationType}
    mail = load_golden("mail_roles")
    mail_keys = set(mail["rodzaje"]) | set(mail["poza_regula_konta"])
    assert mail_keys == {spec["id"] for spec in (*CATALOG, *SECURITY_CATALOG)}


def test_matrix_tells_the_roles_apart(bells, mails) -> None:
    """Wzorzec, który każdemu daje to samo, niczego nie pilnuje."""

    assert bells["ai_spend_alert"] == ["admin"]
    assert set(bells["candidate_data_access_alert"]) == {
        "admin",
        "head_of_recruitment",
        "head_of_recruitment+delivery_lead",
        "head_of_recruitment+recruiter",
    }
    # Kadry i ogłoszenia: odbiorcę wybiera moduł, więc brama wpuszcza każdego.
    assert len(bells["announcement_important"]) == len(PERSONAS)
    assert "employee" not in bells["stage_rule"]
    assert "recruiter" in bells["stage_rule"]
    matrix, _ = mails
    assert matrix["system_failure"] == ["admin"]
    assert matrix["month_check_report"] == ["finance", "finance-finance_module"]


# ── Przypadki z historii (warstwa bez bazy; z bazą: test_notify_golden_db) ──


def test_historia_rada_podsumowanie_tylko_rada_i_imienne_nadanie(relations) -> None:
    """02.11.2026: „Podsumowanie Rady” (przychód i marża firmy) dostało 11
    osób, w tym 5 z Finansów. Od tej daty: Rada i osoba z imiennym nadaniem
    ``receives_board_report`` — ani rola admin, ani „Moduł Finanse”."""

    kinds, _ = relations
    got = set(kinds["board_monthly_report [nadawca: Podsumowanie Rady]"]["odbiorcy"])
    assert got == {"board", "admin+receives_board_report"}
    for outsider in (
        "finance",
        "admin",
        "head_of_recruitment",
        "recruiter+finance_module",
    ):
        assert outsider not in got


def test_historia_rada_mail_brama_tylko_rada(mails) -> None:
    matrix, _ = mails
    # Brama maila (lustro nadawcy): Rada z odczytem Insights; admin dopiero
    # z imiennym nadaniem, którego persony nie mają.
    assert matrix["board_monthly_report"] == ["board"]
    assert matrix["board_placement_alert"] == ["board"]


def test_historia_ruch_etapu_regula_wskazuje_rekrutera_kandydata(relations) -> None:
    """10.11 i 18.11.2026: prowadzący rekrutację dostawał ruchy cudzych
    kandydatów (49%, potem 61% dzwonków ruchu). Reguła „rekruter rekrutacji”
    wskazuje rekrutera kandydata; prowadzący tylko na własne życzenie."""

    kinds, _ = relations
    other = kinds[
        "stage_rule [reguła „rekruter rekrutacji”: kandydat innego rekrutera]"
    ]
    assert other["odbiorcy"] == ["rekruter kandydata"]
