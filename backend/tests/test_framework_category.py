"""Kategoria z umowy ramowej na kontrakcie: z COA i od Delivery Leada (F1).

Bez bazy: kontrakt to obiekt przejściowy ORM, sesja tylko zbiera ``add``.
Wartości fikcyjne.
"""

from datetime import date
from decimal import Decimal

import pytest

from app.models.contract import Contract
from app.services.framework_category import (
    ClientTerms,
    FrameworkCategoryError,
    apply_category,
    set_by_delivery_lead,
)
from app.services.framework_limits import AdderView, CardView

DAY = date(2031, 4, 1)


class FakeDb:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def terms():
    return ClientTerms(
        cards=(
            CardView(1, "IT Developer", "Senior", 100),
            CardView(2, "IT Developer", "Expert", 110),
            CardView(3, "IT Architect", None, 120),
        ),
        adders=(
            AdderView(10, "Kafka", Decimal("20"), ({"role": "IT Developer", "seniority": "Senior"}, {"role": "IT Developer", "seniority": "Expert"})),
            AdderView(11, "PEGA", Decimal("10"), ({"role": "IT Developer", "seniority": "Senior"},)),
        ),
    )


def contract(**kw):
    c = Contract(id=7, client_id=1, framework_rate=None, **kw)
    c.framework_rate_schedule = []
    return c


def test_coa_category_sets_card_and_limit_step_from_order_start():
    db, c = FakeDb(), contract()
    assert apply_category(db, c, terms(), "IT Developer - Senior", effective_from=DAY, actor_id=None) == "updated"
    assert (c.client_rate_card_id, c.rate_card_source, c.rate_card_coa_label) == (1, "coa", "IT Developer - Senior")
    assert c.effective_framework_rate(DAY) == Decimal("100.00")
    assert [s.note for s in c.framework_rate_schedule] == ["Z COA: IT Developer - Senior"]


def test_same_coa_twice_is_unchanged_and_adds_no_step():
    db, c = FakeDb(), contract()
    apply_category(db, c, terms(), "IT Developer - Senior", effective_from=DAY, actor_id=None)
    assert apply_category(db, c, terms(), "IT Developer - Senior", effective_from=DAY, actor_id=None) == "unchanged"
    assert len(c.framework_rate_schedule) == 1


def test_coa_upgrade_keeps_eligible_addon_in_the_limit():
    db, c = FakeDb(), contract(framework_addon_technology="Kafka", framework_addon_percent=Decimal("20"))
    apply_category(db, c, terms(), "IT Developer - Expert", effective_from=DAY, actor_id=None)
    assert c.effective_framework_rate(DAY) == Decimal("132.00")


def test_coa_category_without_addon_rights_drops_addon_from_limit():
    db, c = FakeDb(), contract(framework_addon_technology="PEGA", framework_addon_percent=Decimal("10"))
    apply_category(db, c, terms(), "IT Developer - Expert", effective_from=DAY, actor_id=None)
    assert c.effective_framework_rate(DAY) == Decimal("110.00")


def test_unknown_category_keeps_label_and_leaves_limit_alone():
    db, c = FakeDb(), contract()
    assert apply_category(db, c, terms(), "Business Analyst - Expert", effective_from=DAY, actor_id=None) == "no_card"
    assert c.rate_card_coa_label == "Business Analyst - Expert"
    assert c.client_rate_card_id is None and c.framework_rate_schedule == []
    assert apply_category(db, c, terms(), None, effective_from=DAY, actor_id=None) == "no_label"


def test_delivery_lead_sets_addon_with_client_confirmation():
    db, c = FakeDb(), contract()
    set_by_delivery_lead(
        db, c, terms(), rate_card_id=1, addon_technology="kafka", confirmed_by="LM klienta",
        confirmed_on=DAY, evidence="mail z potwierdzeniem", effective_from=DAY, actor_id=5,
    )
    assert (c.framework_addon_technology, c.framework_addon_percent) == ("Kafka", Decimal("20"))
    assert c.rate_card_source == "dl"
    assert c.effective_framework_rate(DAY) == Decimal("120.00")


def test_addon_outside_contract_is_refused():
    with pytest.raises(FrameworkCategoryError, match="nie przewiduje"):
        set_by_delivery_lead(
            FakeDb(), contract(), terms(), rate_card_id=3, addon_technology="Kafka", confirmed_by="LM",
            confirmed_on=DAY, evidence=None, effective_from=DAY, actor_id=5,
        )


def test_addon_without_confirmation_is_refused():
    with pytest.raises(FrameworkCategoryError, match="potwierdzeniem"):
        set_by_delivery_lead(
            FakeDb(), contract(), terms(), rate_card_id=1, addon_technology="Kafka", confirmed_by=" ",
            confirmed_on=DAY, evidence=None, effective_from=DAY, actor_id=5,
        )


def test_card_of_another_client_is_refused():
    with pytest.raises(FrameworkCategoryError, match="nie należy"):
        set_by_delivery_lead(
            FakeDb(), contract(), terms(), rate_card_id=99, addon_technology=None, confirmed_by=None,
            confirmed_on=None, evidence=None, effective_from=DAY, actor_id=5,
        )


def test_removing_addon_lowers_limit_and_clears_confirmation():
    db, c = FakeDb(), contract()
    set_by_delivery_lead(db, c, terms(), rate_card_id=1, addon_technology="Kafka", confirmed_by="LM",
                         confirmed_on=DAY, evidence=None, effective_from=DAY, actor_id=5)
    later = date(2031, 6, 1)
    set_by_delivery_lead(db, c, terms(), rate_card_id=1, addon_technology=None, confirmed_by=None,
                         confirmed_on=None, evidence=None, effective_from=later, actor_id=5)
    assert c.framework_addon_technology is None and c.framework_addon_confirmed_by is None
    assert c.effective_framework_rate(DAY) == Decimal("120.00")
    assert c.effective_framework_rate(later) == Decimal("100.00")
