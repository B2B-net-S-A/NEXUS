"""Testy fundamentu stawek — ``app.services.contract_rates``.

Powód istnienia tego pliku: ``test_finance_point_in_time.py`` nazywa się
„point in time", ale seeduje kontrakt BEZ harmonogramu stawek (jego własny
komentarz: „monthly_rate_client/monthly_margin are computed properties — seed
the stored fields") i sprawdza wyłącznie, KTÓRE kontrakty wpadają do okresu.
Nigdy — po jakiej stawce. Kontrakt ze stawką zmienną w czasie był więc
wyceniany źle i cały suite przechodził. To jest test na kwotę, nie na zbiór.
"""

from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import date
from decimal import Decimal

from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate
from app.services.contract_rates import (
    RATE_SCHEDULE_LOADS,
    REVENUE_BEARING_STATUSES,
    effective_rate_fields,
)


def _contract_with_client_step() -> Contract:
    """Kontrakt, któremu 1.06 stawka klienta rośnie 150 -> 205 PLN/h."""
    c = Contract()
    c.rate_unit = RateUnit.hourly
    c.billing_hours_per_month = 160
    c.rate_client = 205  # cache: wartość wpisana przy zapisie aneksu
    c.rate_candidate = 100
    c.framework_rate = None
    c.client_rate_schedule = [
        ContractClientRate(rate=150, effective_from=date(2026, 1, 1)),
        ContractClientRate(rate=205, effective_from=date(2026, 6, 1)),
    ]
    c.candidate_rate_schedule = [
        ContractCandidateRate(rate=100, effective_from=date(2026, 1, 1)),
    ]
    c.framework_rate_schedule = []
    return c


# ── Kwota, nie zbiór ─────────────────────────────────────────────────────────


def test_historical_month_is_priced_at_the_historical_rate():
    """Maj musi kosztować 150/h, mimo że kolumna cache trzyma już 205."""
    c = _contract_with_client_step()

    may = effective_rate_fields(c, date(2026, 5, 15))
    assert may["rate_client"] == 150
    assert may["monthly_rate_client"] == Decimal(150 * 160)
    assert may["monthly_margin"] == Decimal((150 - 100) * 160)

    june = effective_rate_fields(c, date(2026, 6, 15))
    assert june["rate_client"] == 205
    assert june["monthly_rate_client"] == Decimal(205 * 160)

    # Dokładnie ta rozbieżność, przez którą powstało znalezisko #23: kolumna
    # cache odpowiada na maj czerwcową kwotą.
    assert c.monthly_rate_client == Decimal(205 * 160)
    assert may["monthly_rate_client"] != c.monthly_rate_client


def test_future_step_does_not_change_todays_rate():
    c = _contract_with_client_step()
    assert effective_rate_fields(c, date(2026, 3, 1))["rate_client"] == 150


def test_framework_rate_never_feeds_the_margin():
    c = _contract_with_client_step()
    c.framework_rate = 999
    fields = effective_rate_fields(c, date(2026, 6, 15))
    assert fields["framework_rate"] == 999
    assert fields["margin"] == Decimal(205 - 100)


def test_missing_rate_yields_none_not_zero():
    """Brak stawki to brak danych, nie zero — zero sumuje się cicho do MRR."""
    c = Contract()
    c.rate_unit = RateUnit.monthly
    c.rate_client = None
    c.rate_candidate = None
    c.client_rate_schedule = []
    c.candidate_rate_schedule = []
    c.framework_rate_schedule = []
    fields = effective_rate_fields(c, date(2026, 6, 1))
    assert fields["monthly_rate_client"] is None
    assert fields["monthly_margin"] is None


# ── Strażnicy, które nie zgniją ──────────────────────────────────────────────


def test_every_contract_status_is_explicitly_classified():
    """Nowa wartość w enumie MUSI wymusić decyzję, czy niesie przychód.

    Warunek pisany jako negacja (``status != draft``) wpuszczał wszystko, co
    dopisano później — dziś ``ready_for_signature`` i ``void`` (znalezisko #28).
    Ten test pada przy dodaniu statusu, dopóki ktoś go świadomie nie przypisze.
    """
    non_revenue = {
        ContractStatus.draft,
        ContractStatus.ready_for_signature,
        ContractStatus.void,
    }
    assert set(REVENUE_BEARING_STATUSES) | non_revenue == set(ContractStatus)
    assert set(REVENUE_BEARING_STATUSES) & non_revenue == set()


def test_ended_stays_revenue_bearing():
    """O przynależności do okresu decydują daty, nie dzisiejszy status.

    Wycięcie ``ended`` skasowałoby z historii każdy zakończony projekt.
    """
    assert ContractStatus.ended in REVENUE_BEARING_STATUSES


def test_eager_loads_cover_every_relation_the_resolver_touches():
    """Lista ``selectinload`` wyprowadzona ze ŹRÓDŁA, nie z pamięci.

    ``effective_*_rate`` sięga po relacje atrybutem; w sesji async brakujący
    eager-load to ``MissingGreenlet``, czyli 500 bez CORS. Ręczna lista
    przechodzi dalej w dniu, w którym resolver zacznie czytać czwartą relację —
    ta czyta je z kodu modelu.
    """
    touched: set[str] = set()
    for name in (
        "effective_candidate_rate",
        "effective_client_rate",
        "effective_framework_rate",
    ):
        src = textwrap.dedent(inspect.getsource(getattr(Contract, name)))
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "self"
                and node.attr.endswith("_schedule")
            ):
                touched.add(node.attr)

    assert touched, "nie wykryto żadnej relacji — zmienił się kształt resolvera"
    # ORM Path to [Mapper(Contract) -> Contract.<relacja> -> Mapper(cel)];
    # nazwa relacji siedzi w środkowym elemencie.
    declared = {
        el.key for load in RATE_SCHEDULE_LOADS for el in load.path if hasattr(el, "key")
    }
    assert touched <= declared, f"brak eager-loadu dla: {sorted(touched - declared)}"
