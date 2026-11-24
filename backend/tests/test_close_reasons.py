"""Jeden słownik powodów zamknięcia procesu (0745, decyzja Artura 19.11.2026).

Każdy powód słownika ma własny klucz w szablonie, więc powód dla systemu
przechodzi na powód z szablonu 1:1, a historia i raporty mają jedną nazwę.
Źródła czytane jako tekst, bez wykonania heredocu.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

from app.services import close_reasons as cr
from app.services.autofill_feedback import REASON_LABELS, bucket_for
from app.services.autofill_feedback_schema import REASONS
from app.services.rejection_reason_labels import (
    is_rate_too_high,
    needs_description,
    rejection_reason_label,
)

pytestmark = pytest.mark.static

_BACKEND = Path(__file__).resolve().parents[1]
_ENTRYPOINT = (_BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
_VERSIONS = _BACKEND / "alembic" / "versions"
_FRONT_AUTOFILL = (
    _BACKEND.parent / "frontend" / "src" / "lib" / "autofill-feedback.ts"
).read_text(encoding="utf-8")

# Nazwy, które szablon domyślny miał przed 0745 (0006, 0068, 0442, 0484,
# 0646, 0740) — słownik może ich używać bez nowego wiersza.
_SEEDED_BEFORE = {
    "rejected": {
        "Brak doświadczenia",
        "Za wysokie oczekiwania finansowe",
        "Nie spełnia wymagań technicznych",
        "Nie pasuje kulturowo",
        "Zatrudniony gdzie indziej",
        "work_mode_mismatch",
        "hm_already_interviewed",
        "not_looking_for_work",
        "contract_form",
        "no_contact",
        "client_no_reason",
        "client_chose_other",
        "client_other_vendor",
        "client_interview_weak",
        "Inne (rejected)",
    },
    "withdrawn": {
        "accepted_other_offer",
        "counter_offer",
        "personal_reasons",
        "lost_interest",
        "salary_mismatch",
        "work_mode_mismatch",
        "Inne (withdrawn)",
    },
}


def _migration(name: str = "0745_one_close_reason_dictionary"):
    path = _VERSIONS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"m{name[:4]}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _shape(text: str) -> str:
    glued = re.sub(r"[\"']\s*\n\s*[\"']", "", text)
    return " ".join(glued.replace('\\"', '"').split())


def test_entrypoint_mirrors_the_migration_seed_verbatim():
    seed = " ".join(_migration().SEED_CLOSE_REASON_DICTIONARY.split())
    assert seed in _shape(_ENTRYPOINT)


def test_entrypoint_mirrors_the_outside_poland_seed_verbatim():
    seed = _migration("0768_outside_poland_reason").SEED_OUTSIDE_POLAND_REASON
    assert " ".join(seed.split()) in _shape(_ENTRYPOINT)
    assert "outside_poland_reason_seeded" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    # Sytuacja, nie werdykt o osobie: bez weta hiring managera.
    assert "TRUE, FALSE, 'manual'" in seed
    assert cr.LATER_REJECTED == (("outside_poland", False),)


def test_seed_is_one_shot_and_never_rewires_old_rows():
    seed = _migration().SEED_CLOSE_REASON_DICTIONARY
    assert "ON CONFLICT (key) DO NOTHING RETURNING key" in seed
    assert "WHERE EXISTS (SELECT 1 FROM marker)" in seed
    assert "ON CONFLICT (template_id, name, category) DO NOTHING" in seed
    assert "UPDATE " not in seed.upper()


def test_seed_rows_match_the_dictionary():
    seed = _migration().SEED_CLOSE_REASON_DICTIONARY
    rows = re.findall(r"\(\d+, '([^']+)', '(rejected|withdrawn)', (TRUE|FALSE)\)", seed)
    rejected = {
        (name, verdict == "TRUE") for name, cat, verdict in rows if cat == "rejected"
    }
    withdrawn = {name for name, cat, _ in rows if cat == "withdrawn"}
    assert rejected == set(cr.NEW_REJECTED)
    assert withdrawn == set(cr.NEW_WITHDRAWN)
    assert set(_migration().REJECTED_KEYS) == {name for name, _ in cr.NEW_REJECTED}
    assert set(_migration().WITHDRAWN_KEYS) == set(cr.NEW_WITHDRAWN)


def test_only_language_reasons_veto_the_hiring_manager():
    verdicts = {name for name, verdict in cr.NEW_REJECTED if verdict}
    assert verdicts == {"no_polish", "weak_english"}


@pytest.mark.parametrize("reason", cr.CLOSE_REASONS, ids=lambda r: r.key)
def test_every_side_that_may_pick_a_reason_has_a_template_row(reason):
    new = {
        "rejected": {n for n, _ in (*cr.NEW_REJECTED, *cr.LATER_REJECTED)},
        "withdrawn": set(cr.NEW_WITHDRAWN),
    }
    if cr.RECRUITER in reason.who or cr.CLIENT in reason.who:
        assert reason.rejected in _SEEDED_BEFORE["rejected"] | new["rejected"]
    else:
        assert reason.rejected is None
    if cr.CANDIDATE in reason.who:
        assert reason.withdrawn in _SEEDED_BEFORE["withdrawn"] | new["withdrawn"]
    else:
        assert reason.withdrawn is None


def test_keys_are_unique_and_early_only_is_ours_alone():
    keys = [r.key for r in cr.CLOSE_REASONS]
    assert len(keys) == len(set(keys))
    early = {r.key for r in cr.CLOSE_REASONS if r.early_only}
    assert early == {"outdated_cv", "profile_mismatch", "wrong_phone"}
    assert all(cr.BY_KEY[k].who == {cr.RECRUITER} for k in early)


def test_client_group_is_client_only_and_candidate_reasons_never_reach_us():
    client_group = dict(cr.CLOSE_REASON_GROUPS)["Klient"]
    assert all(r.who == {cr.CLIENT} for r in client_group)
    for key in ("counter_offer", "lost_interest", "personal_reasons"):
        assert cr.BY_KEY[key].who == {cr.CANDIDATE}
        assert cr.template_name(key, withdrawn=False) is None


@pytest.mark.parametrize(
    "reason",
    [r for r in cr.CLOSE_REASONS if cr.RECRUITER in r.who or cr.CLIENT in r.who],
    ids=lambda r: r.key,
)
def test_every_rejection_reason_is_a_reason_for_the_system(reason):
    # Osoba od systemu w „Nowych”/„Screeningu” odrzucana jest powodem dla
    # systemu — każdy powód odrzucenia ze słownika musi przejść walidację.
    assert reason.key in REASONS
    assert REASON_LABELS[reason.key]


def test_front_maps_every_reason_for_the_system_one_to_one():
    block = _FRONT_AUTOFILL[
        _FRONT_AUTOFILL.index("export const AUTOFILL_TEMPLATE_REASON") :
    ]
    block = block[: block.index("};")]
    pairs = dict(re.findall(r"^\s+(\w+): (?:\"([^\"]+)\"|null),", block, re.M))
    for reason in cr.CLOSE_REASONS:
        if reason.rejected is None or reason.key == "other":
            continue
        assert pairs.get(reason.key) == reason.rejected, reason.key
    assert set(pairs) == set(REASONS)


@pytest.mark.parametrize(
    "name,label",
    [
        ("Nie spełnia wymagań technicznych", "Brak kluczowej umiejętności"),
        ("Brak doświadczenia", "Za mało doświadczenia"),
        ("Za wysokie oczekiwania finansowe", "Za droga"),
        ("salary_mismatch", "Za droga"),
        ("work_mode_mismatch", "Lokalizacja lub tryb pracy"),
        ("Zatrudniony gdzie indziej", "Przyjęła inną ofertę"),
        ("accepted_other_offer", "Przyjęła inną ofertę"),
        ("client_other_vendor", "Pracuje u klienta / zgłoszona przez inną firmę"),
        ("client_project_closed", "Klient zamknął projekt / przetarg przegrany"),
        ("available_too_late", "Dostępna za późno / wypowiedzenie"),
        ("outside_poland", "Mieszka poza Polską"),
        # Stare nazwy i dopisane przez admina — ta sama etykieta co powód
        # słownika, więc raporty liczące po etykiecie sumują je razem.
        ("process_too_long", "Straciła zainteresowanie / za długi proces"),
        ("Brak odpowiedzi", "Nie odbiera / brak kontaktu"),
        ("Kandydat nieosiągalny", "Nie odbiera / brak kontaktu"),
        ("client_conflict", "Pracuje u klienta lub nie chce do klienta"),
        ("Kandydat się wycofał", "Kandydat się wycofał"),
    ],
)
def test_history_reads_old_and_new_names_in_dictionary_words(name, label):
    assert rejection_reason_label(name) == label


def test_other_still_needs_a_description_and_rate_reasons_still_ask():
    assert needs_description("Inne (rejected)")
    assert needs_description("Inne (withdrawn)")
    assert not needs_description("client_project_closed")
    assert is_rate_too_high("Za wysokie oczekiwania finansowe")
    assert is_rate_too_high("salary_mismatch")


@pytest.mark.parametrize(
    "reason,bucket",
    [
        ("culture", "person"),
        ("available_too_late", "person"),
        ("accepted_other_offer", "person"),
        ("hm_already_interviewed", "data"),
        ("outside_poland", "data"),
        ("client_project_closed", "other"),
        ("client_interview_weak", "other"),
    ],
)
def test_new_reasons_for_the_system_land_in_their_buckets(reason, bucket):
    assert bucket_for(reason, snapshot=None, budget_hourly=None) == bucket


def test_template_name_for_unknown_key_is_none():
    assert cr.template_name("nie_ma_takiego", withdrawn=False) is None
    assert cr.template_name("too_expensive", withdrawn=True) == "salary_mismatch"
    assert cr.template_name("other", withdrawn=True) == "Inne (withdrawn)"


_FRONT_DICTIONARY = (
    _BACKEND.parent / "frontend" / "src" / "lib" / "close-reasons.ts"
).read_text(encoding="utf-8")
_FRONT_WHO = {
    "ALL": {cr.RECRUITER, cr.CLIENT, cr.CANDIDATE},
    "US_CLIENT": {cr.RECRUITER, cr.CLIENT},
    "US_CANDIDATE": {cr.RECRUITER, cr.CANDIDATE},
    "CLIENT": {cr.CLIENT},
    "CANDIDATE": {cr.CANDIDATE},
    '["recruiter"]': {cr.RECRUITER},
}


def _front_entries() -> dict[str, dict]:
    entries = {}
    for line in _FRONT_DICTIONARY.splitlines():
        found = re.match(
            r'\s*\{ key: "(\w+)", label: "[^"]+", who: ([^,]+),(.*)\},?$', line
        )
        if not found:
            continue
        key, who, rest = found.groups()
        rejected = re.search(r'rejected: "([^"]+)"', rest)
        withdrawn = re.search(r'withdrawn: "([^"]+)"', rest)
        entries[key] = {
            "who": _FRONT_WHO[who.strip()],
            "rejected": rejected.group(1) if rejected else None,
            "withdrawn": withdrawn.group(1) if withdrawn else None,
            "early_only": "earlyOnly: true" in rest,
        }
    return entries


def test_front_dictionary_mirrors_the_backend_one():
    front = _front_entries()
    back = {r.key: r for r in cr.CLOSE_REASONS if r.key != "other"}
    assert set(front) == set(back)
    for key, reason in back.items():
        assert front[key] == {
            "who": set(reason.who),
            "rejected": reason.rejected,
            "withdrawn": reason.withdrawn,
            "early_only": reason.early_only,
        }, key
