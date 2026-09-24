"""Praktykant — poprawki z audytu 24.09.2026, bez bazy.

- zgoda „dzwonić mimo oferty poniżej minimum” dotyczy MINIMUM z telefonu, więc
  każda inna zmiana stawki profilu ją unieważnia (M20);
- przekazanie rekruterowi tylko po rozmowie zapisanej dziś (M19);
- oddzwonienia „później” i ranking z rana przechodzą przez te same twarde
  warunki co pula (M17).
"""

from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.core.scheduling import business_today
from app.services import trainee_call_list as lists
from app.services import trainee_program
from app.services.candidate_profile_rate import (
    TRAINEE_CALL_RATE_SOURCE,
    write_profile_rate,
)
from app.services.trainee_rules import normalize_rules


def _candidate(**kw):
    base = dict(
        expected_rate_hourly=Decimal("150.00"),
        expected_rate_currency="PLN",
        profile_rate_version=3,
        profile_rate_updated_at=None,
        accepts_below_min_rate=True,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_trainee_source_constant_matches_the_call_note_source():
    assert TRAINEE_CALL_RATE_SOURCE == trainee_program.NOTE_SOURCE


@pytest.mark.parametrize("source", ["manual", "notes_confirmed", "import"])
def test_other_rate_change_clears_below_minimum_consent(source):
    cand = _candidate()
    details = write_profile_rate(cand, Decimal("200"), source=source)
    assert cand.accepts_below_min_rate is None
    assert details["accepts_below_min_rate_cleared"] is True


def test_clearing_the_rate_also_clears_the_consent():
    cand = _candidate()
    write_profile_rate(cand, None, source="manual")
    assert cand.accepts_below_min_rate is None


def test_trainee_call_keeps_the_consent():
    cand = _candidate()
    details = write_profile_rate(cand, Decimal("180"), source=TRAINEE_CALL_RATE_SOURCE)
    assert cand.accepts_below_min_rate is True
    assert "accepts_below_min_rate_cleared" not in details


def test_same_amount_keeps_the_consent():
    cand = _candidate()
    details = write_profile_rate(cand, Decimal("150"), source="manual")
    assert cand.accepts_below_min_rate is True
    assert "accepts_below_min_rate_cleared" not in details


def test_candidate_without_consent_is_untouched():
    cand = _candidate(accepts_below_min_rate=None)
    details = write_profile_rate(cand, Decimal("200"), source="manual")
    assert cand.accepts_below_min_rate is None
    assert "accepts_below_min_rate_cleared" not in details


def _item(**kw):
    base = dict(outcome="call", list_date=business_today())
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.parametrize("outcome", [None, "declined", "wrong", "noanswer", "later"])
def test_handover_refuses_without_a_saved_call(outcome):
    with pytest.raises(HTTPException) as exc:
        trainee_program._ensure_handover_allowed(_item(outcome=outcome))
    assert exc.value.status_code == 409
    assert "rozmowę" in exc.value.detail


def test_handover_refuses_a_call_from_another_day():
    with pytest.raises(HTTPException) as exc:
        trainee_program._ensure_handover_allowed(
            _item(list_date=business_today() - timedelta(days=1))
        )
    assert exc.value.status_code == 409


def test_handover_accepts_todays_call():
    trainee_program._ensure_handover_allowed(_item())


def test_callbacks_and_recheck_share_the_hard_pool_conditions():
    hard = lists._hard_conditions_sql()
    for fragment in (
        "blacklisted",
        "employment_only",
        "FROM contracts ct",
        "candidate_contact_cases",
        "j.status::text = 'published'",
    ):
        assert fragment in hard
    assert hard in lists.callback_sql()
    rules = normalize_rules(None)
    assert hard in lists.pool_sql(rules)
    assert "c.id = ANY(:ids)" in lists.pool_sql(rules, only_ids=True)
    assert "c.id = ANY(:ids)" not in lists.pool_sql(rules)
    # „Nie kontaktować” wyklucza oddzwonienie bez względu na datę.
    assert "do_not_contact" in lists.callback_sql()
