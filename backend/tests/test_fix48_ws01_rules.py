"""Audyt 48 h (13.10.2026), obszar WS01 — reguły bez bazy.

* pkt 5: arkusz z samymi sprawdzeniami doświadczenia (albo z pustymi
  odpowiedziami, które front wysyła dla każdego pytania) spełniał bramkę
  „Zweryfikowany”, bo `sheet_filled` liczył pozycje listy;
* pkt 6: „Pomiń brakujące” pilnował tylko ekran — zapis przyjmował
  `skipped` bez powodu pominięcia;
* Nordea: para zamknięta z kolejki Cpro wracała do kolejki bez akceptacji
  Delivery Leada (`arrives_from_before_client_send`);
* `/my-next-steps`: reguła „czyj przegląd” pytała bazę osobno dla każdej
  tablicy.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.models.user import User, UserRole
from app.schemas.champion import ScreeningAnswerItem
from app.services import move_requirements
from app.services import pipeline_move_rules as move_rules
from app.services import screening_form
from app.services import screening_form_rules as form_rules


def _answer(question_id: str, response: str = "", **extra) -> dict:
    return {"question_id": question_id, "response": response, **extra}


# Kształt, który zapisywał formularz: każde pytanie, odpowiedzi puste,
# jedno sprawdzenie doświadczenia „potwierdził”.
EXPERIENCE_ONLY = {
    "answers": [_answer("q1"), _answer("q2", "   ")],
    "experience_checks": [
        {"kind": "domains", "name": "Bankowość", "status": "confirmed", "note": ""}
    ],
    "overall_fit": "fit",
    "notes": "",
}


# ── pkt 5: bramka liczy odpowiedzi z treścią ─────────────────────────────────


def test_experience_check_alone_does_not_answer_the_sheet() -> None:
    # Arkusz jest zapisany (formularz go pokazuje) …
    assert move_requirements.sheet_filled(EXPERIENCE_ONLY) is True
    # … ale nie ma ani jednej odpowiedzi z rozmowy.
    assert move_requirements.sheet_answered(EXPERIENCE_ONLY) is False


@pytest.mark.parametrize(
    "item",
    [
        _answer("q1", "5 lat z Javą"),
        _answer("q1", skipped=True),
        _answer("q1", deal_breaker_hit=True),
    ],
)
def test_text_skip_or_deal_breaker_answers_the_sheet(item: dict) -> None:
    sheet = {"answers": [_answer("q2"), item], "overall_fit": "uncertain"}
    assert move_requirements.sheet_answered(sheet) is True


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {},
        "tekst",
        {"answers": [], "overall_fit": "fit", "notes": "stara notatka"},
        {"answers": [_answer("q1"), "nie-słownik"], "overall_fit": "fit"},
    ],
)
def test_empty_and_malformed_sheets_do_not_answer(payload) -> None:
    assert move_requirements.sheet_answered(payload) is False


def test_gate_and_form_share_one_answer_rule() -> None:
    """Zapis formularza (`sheet_has_content`) i bramka liczą odpowiedź tak samo."""
    assert form_rules.answer_has_content is move_requirements.answer_has_content


def test_screening_requirement_with_questions_needs_an_answer() -> None:
    facts = move_requirements.PairFacts(
        from_column="screening",
        screening_done=move_requirements.sheet_answered(EXPERIENCE_ONLY),
    )
    assert move_requirements.screening_requirement(facts) == ("screening_sheet", False)


# ── pkt 6: „Pomiń brakujące” tylko z powodem ─────────────────────────────────


def test_skip_needs_a_reason_unless_the_pair_already_skipped() -> None:
    skipped = [ScreeningAnswerItem(question_id="q1", skipped=True)]
    answered = [ScreeningAnswerItem(question_id="q1", response="tak")]
    assert form_rules.skips_need_reason(skipped, None) is True
    assert form_rules.skips_need_reason(skipped, {"answers": [_answer("q1", "x")]})
    assert form_rules.skips_need_reason(answered, None) is False
    assert form_rules.skips_need_reason([], None) is False
    # Pominięcie zapisane wcześniej nie blokuje ponownego zapisu.
    earlier = {"answers": [_answer("q1", skipped=True), _answer("q2", "tak")]}
    assert form_rules.skips_need_reason(skipped, earlier) is False
    # Słowniki (stara trasa arkusza) — ta sama reguła.
    assert form_rules.skips_need_reason([_answer("q1", skipped=True)], None) is True


def _user() -> User:
    return User(id=7, role=UserRole.recruiter, is_active=True)


async def test_save_refuses_skips_without_a_reason(monkeypatch) -> None:
    from app.services import screening_reassign

    async def no_context(db, *, candidate_id, job_id, user):
        return None

    async def no_reason(db, *, candidate_id, job_id, ctx):
        return None

    monkeypatch.setattr(screening_reassign, "suggestion_context", no_context)
    monkeypatch.setattr(screening_reassign, "skip_missing_reason", no_reason)
    with pytest.raises(HTTPException) as err:
        await screening_form.assert_skip_allowed(
            None,
            answers=[ScreeningAnswerItem(question_id="q1", skipped=True)],
            previous=None,
            candidate_id=1,
            job_id=2,
            user=_user(),
        )
    assert err.value.status_code == 422
    assert err.value.detail["code"] == "SCREENING_FORM_INVALID"
    assert "Pomiń brakujące" in err.value.detail["message"]


@pytest.mark.parametrize("reason", ["reassign", "earlier_screening", "employed"])
async def test_save_accepts_skips_with_a_reason(monkeypatch, reason: str) -> None:
    from app.services import screening_reassign

    async def context(db, *, candidate_id, job_id, user):
        return None

    async def with_reason(db, *, candidate_id, job_id, ctx):
        return reason

    monkeypatch.setattr(screening_reassign, "suggestion_context", context)
    monkeypatch.setattr(screening_reassign, "skip_missing_reason", with_reason)
    await screening_form.assert_skip_allowed(
        None,
        answers=[ScreeningAnswerItem(question_id="q1", skipped=True)],
        previous=None,
        candidate_id=1,
        job_id=2,
        user=_user(),
    )


async def test_earlier_skip_is_not_checked_again(monkeypatch) -> None:
    from app.services import screening_reassign

    async def boom(*_args, **_kwargs):
        raise AssertionError("powód pominięcia nie powinien być liczony")

    monkeypatch.setattr(screening_reassign, "suggestion_context", boom)
    monkeypatch.setattr(screening_reassign, "skip_missing_reason", boom)
    await screening_form.assert_skip_allowed(
        None,
        answers=[ScreeningAnswerItem(question_id="q1", skipped=True)],
        previous={"answers": [_answer("q1", skipped=True)]},
        candidate_id=1,
        job_id=2,
        user=_user(),
    )


# ── Nordea: para zamknięta z kolejki Cpro ────────────────────────────────────


class _CproDb:
    """Nazwa etapu wiersza bramki, potem id najnowszego wiersza pary."""

    def __init__(self, newest_id: int) -> None:
        self.answers = ["NORDEA: Wysłać do Cpro", newest_id]

    async def scalar(self, _stmt):
        return self.answers.pop(0)


async def test_card_standing_in_the_cpro_queue_is_not_accepted_twice(
    monkeypatch,
) -> None:
    row = SimpleNamespace(id=41, stage_def_id=9)

    async def gate_row(db, *, candidate_id, job_id):
        return row, "cv_qc"

    monkeypatch.setattr(move_rules, "gate_stage_row", gate_row)
    # Karta stoi w kolejce (najnowszy wiersz to wiersz Cpro) — „✓ Wrzucone”.
    assert (
        await move_rules.arrives_from_before_client_send(
            _CproDb(newest_id=41), candidate_id=1, job_id=2
        )
        is False
    )
    # Para zamknięta z kolejki (najnowszy wiersz to zamknięcie) wraca do
    # kolejki przez akceptację Delivery Leada, jak każda inna.
    assert (
        await move_rules.arrives_from_before_client_send(
            _CproDb(newest_id=42), candidate_id=1, job_id=2
        )
        is True
    )


# ── /my-next-steps: „czyj przegląd” raz na żądanie ───────────────────────────


class _ReviewOwnerDb:
    def __init__(self, *, dl_active: bool = True, portfolio: tuple[int, ...] = ()):
        self.dl_active = dl_active
        self.portfolio = portfolio
        self.queries = 0

    async def scalar(self, _stmt):
        self.queries += 1
        return self.dl_active

    async def scalars(self, _stmt):
        self.queries += 1
        return SimpleNamespace(all=lambda: list(self.portfolio))


async def test_review_ownership_is_asked_once_per_request() -> None:
    from app.api.pipeline import _viewer_owns_dl_review

    dl = User(id=5, role=UserRole.delivery_lead, is_active=True)
    boards = [SimpleNamespace(client_id=15, delivery_lead_id=9) for _ in range(25)]
    boards += [SimpleNamespace(client_id=16, delivery_lead_id=None) for _ in range(25)]

    db = _ReviewOwnerDb(dl_active=False, portfolio=(15,))
    memo: dict = {}
    owners = [await _viewer_owns_dl_review(db, job, dl, memo=memo) for job in boards]
    # Nieaktywny DL rekrutacji = brak DL-a, decyduje portfel (klient 15).
    assert owners == [True] * 25 + [False] * 25
    # Jedno pytanie o aktywność DL-a 9 i jedno o portfel — nie 50.
    assert db.queries == 2

    # Bez wspólnej pamięci — jak dotąd, zapytanie na tablicę.
    alone = _ReviewOwnerDb(dl_active=False, portfolio=(15,))
    for job in boards[:3]:
        await _viewer_owns_dl_review(alone, job, dl)
    assert alone.queries == 6
