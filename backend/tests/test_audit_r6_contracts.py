"""Runda 6 audytu (26.09.2026) — rdzeń kontraktów.

K1  aneks stawki z datą wcześniejszą niż start umowy działa od startu
    (krok bazowy od startu wygrywał z aneksem),
K2  przedłużenie zakończonej umowy do daty, która już minęła = 422 / pominięcie
    (cron kończył ją drugi raz, z drugim offboardingiem),
K3  „fee” historii requestu = marża MIESIĘCZNA z harmonogramu, bez umów
    anulowanych (była kolumna cache + etykieta „/h”),
K5  promocja na „Zakończony” ma savepoint per kontrakt (jeden zły wiersz
    wycofywał wszystkie promocje i alerty co noc),
K6  alert wygaśnięcia liczy się z pasma progu, nie z jednodniowego okna,
K7  generator B2B przestawia istniejący szkic na zł/h z przeliczeniem kwot
    (ryczałt 20 160 zł/mc stawał się 20 160 zł/h).
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.api.contracts import _amendment_baseline_from, _extension_end_date_passed
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.contract_client_rate import ContractClientRate

TODAY = date(2026, 9, 26)


def _memory_contract(**overrides) -> Contract:
    contract = Contract(
        id=1,
        client_id=10,
        candidate_id=5,
        contract_type=ContractType.uop,
        status=ContractStatus.active,
        start_date=date(2026, 1, 1),
        rate_candidate=Decimal("150"),
        rate_client=Decimal("200"),
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        currency="PLN",
    )
    contract.candidate_rate_schedule = overrides.pop("candidate_rate_schedule", [])
    contract.client_rate_schedule = overrides.pop("client_rate_schedule", [])
    contract.framework_rate_schedule = overrides.pop("framework_rate_schedule", [])
    for key, value in overrides.items():
        setattr(contract, key, value)
    return contract


# ── K1: krok bazowy aneksu stawki ────────────────────────────────────────────


def test_no_baseline_step_when_the_contract_starts_after_the_amendment():
    assert _amendment_baseline_from(date(2026, 10, 1), date(2026, 9, 1), TODAY) is None


def test_baseline_step_from_start_when_the_amendment_is_later():
    assert _amendment_baseline_from(date(2026, 1, 1), date(2026, 9, 1), TODAY) == date(
        2026, 1, 1
    )


def test_baseline_step_without_start_date_is_the_earliest_known_day():
    assert _amendment_baseline_from(None, date(2026, 9, 1), TODAY) == date(2026, 9, 1)
    assert _amendment_baseline_from(None, date(2026, 12, 1), TODAY) == TODAY


def test_amendment_effective_before_start_wins_from_the_start():
    """Umowa od 01.10, aneks od 01.09: od startu obowiązuje nowa stawka."""
    contract = _memory_contract(start_date=date(2026, 10, 1))
    baseline = _amendment_baseline_from(contract.start_date, date(2026, 9, 1), TODAY)
    if baseline is not None:
        contract.candidate_rate_schedule.append(
            ContractCandidateRate(rate=Decimal("150"), effective_from=baseline)
        )
    contract.candidate_rate_schedule.append(
        ContractCandidateRate(rate=Decimal("165"), effective_from=date(2026, 9, 1))
    )
    assert contract.effective_candidate_rate(date(2026, 10, 15)) == Decimal("165")


async def _seed(
    *,
    status: ContractStatus = ContractStatus.active,
    start_date: date | None = date(2025, 1, 1),
    end_date: date | None = None,
    rate_unit: RateUnit = RateUnit.hourly,
    rate_candidate: Decimal = Decimal("150"),
    rate_client: Decimal = Decimal("200"),
    contract_type: ContractType = ContractType.uop,
    job_id: int | None = None,
    client_id: int | None = None,
) -> dict[str, int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        if client_id is None:
            client = Client(name=f"Audit R6 {unique}")
            db.add(client)
            await db.flush()
            client_id = client.id
        candidate = Candidate(name="Audit", lastname=f"R6-{unique}")
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client_id,
            job_id=job_id,
            status=status,
            contract_type=contract_type,
            start_date=start_date,
            end_date=end_date,
            rate_unit=rate_unit,
            billing_hours_per_month=168,
            rate_candidate=rate_candidate,
            rate_client=rate_client,
            currency="PLN",
        )
        db.add(contract)
        await db.commit()
        return {
            "contract_id": contract.id,
            "client_id": client_id,
            "candidate_id": candidate.id,
        }


async def _contract_with_schedules(contract_id: int) -> Contract:
    from sqlalchemy import select

    from app.services.contract_rates import RATE_SCHEDULE_LOADS

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract)
            .where(Contract.id == contract_id)
            .options(*RATE_SCHEDULE_LOADS)
        )


async def test_rate_amendment_dated_before_start_applies_from_the_start(
    app_client: AsyncClient, app_auth_headers: dict
):
    start = business_today() + timedelta(days=20)
    ids = await _seed(status=ContractStatus.draft, start_date=start)
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "rate_change",
            "effective_date": (start - timedelta(days=10)).isoformat(),
            "new_rate_candidate": 165,
            "new_rate_client": 230,
            "reason": "aneks przed startem",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    contract = await _contract_with_schedules(ids["contract_id"])
    on = start + timedelta(days=5)
    assert Decimal(contract.effective_candidate_rate(on)) == Decimal("165")
    assert Decimal(contract.effective_client_rate(on)) == Decimal("230")


# ── K2: przedłużenie do minionej daty ────────────────────────────────────────


def test_extension_of_an_ended_contract_to_a_past_day_is_detected():
    today = business_today()
    ended = SimpleNamespace(status=ContractStatus.ended)
    assert _extension_end_date_passed(ended, today - timedelta(days=1)) is True
    assert _extension_end_date_passed(ended, today) is False
    active = SimpleNamespace(status=ContractStatus.active)
    assert _extension_end_date_passed(active, today - timedelta(days=1)) is False


async def test_extension_amendment_to_a_past_day_on_ended_contract_is_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    ended_on = business_today() - timedelta(days=60)
    ids = await _seed(status=ContractStatus.ended, end_date=ended_on)
    resp = await app_client.post(
        f"/api/contracts/{ids['contract_id']}/amendments",
        json={
            "amendment_type": "extension",
            "effective_date": business_today().isoformat(),
            "new_end_date": (business_today() - timedelta(days=5)).isoformat(),
            "reason": "za krótko",
        },
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["reason"] == "extension_end_date_passed"
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["contract_id"])
        assert contract.status == ContractStatus.ended
        assert contract.end_date == ended_on


async def test_bulk_extend_skips_ended_contract_still_in_the_past(
    app_client: AsyncClient, app_auth_headers: dict
):
    ended_on = business_today() - timedelta(days=200)
    ids = await _seed(status=ContractStatus.ended, end_date=ended_on)
    resp = await app_client.post(
        "/api/contracts/bulk-extend",
        params=[("ids", ids["contract_id"]), ("months", 1)],
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["extended"] == 0
    assert body["skipped_end_date_passed"] == [ids["contract_id"]]
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["contract_id"])
        assert contract.status == ContractStatus.ended
        assert contract.end_date == ended_on


# ── K3: fee historii requestu ────────────────────────────────────────────────


def test_request_history_fee_is_monthly_margin_from_the_schedule():
    from app.services.request_history import _contract_fee

    # Kolumny cache stoją na 150/200 zł/h, ale od 01.09 obowiązuje aneks
    # 150/230 — marża/mc = (230 − 150) × 168 = 13 440.
    contract = _memory_contract(
        client_rate_schedule=[
            ContractClientRate(rate=Decimal("200"), effective_from=date(2026, 1, 1)),
            ContractClientRate(rate=Decimal("230"), effective_from=date(2026, 9, 1)),
        ]
    )
    fee, currency, unit = _contract_fee(contract, TODAY)
    assert Decimal(fee) == Decimal("13440")
    assert currency == "PLN"
    assert unit == "monthly"


def test_request_history_fee_of_an_ended_contract_uses_its_end_day():
    from app.services.request_history import _contract_fee

    contract = _memory_contract(
        status=ContractStatus.ended,
        end_date=date(2026, 8, 31),
        client_rate_schedule=[
            ContractClientRate(rate=Decimal("200"), effective_from=date(2026, 1, 1)),
            ContractClientRate(rate=Decimal("230"), effective_from=date(2026, 9, 1)),
        ],
    )
    fee, _currency, _unit = _contract_fee(contract, TODAY)
    assert Decimal(fee) == Decimal("8400")  # (200 − 150) × 168


async def test_request_history_fee_skips_void_contract():
    from app.models.job import Job, JobStatus
    from app.services.request_history import _aggregate_request_metadata

    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Audit R6 fee {unique}")
        db.add(client)
        await db.flush()
        job = Job(title="R6 fee", status=JobStatus.closed, client_id=client.id)
        db.add(job)
        await db.commit()
        job_id, client_id = job.id, client.id
    await _seed(status=ContractStatus.void, job_id=job_id, client_id=client_id)
    async with AsyncSessionLocal() as db:
        meta = await _aggregate_request_metadata(db, [job_id])
    assert meta[job_id].fee_rate is None
    assert meta[job_id].rate_unit is None


# ── K5: savepoint per kontrakt przy promocji na „Zakończony” ────────────────


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Result:
    rowcount = 0

    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _Scalars(self._rows)


class _PromotionDb:
    """Sesja-atrapa: pierwsze `execute` to UPDATE → ending, drugie to SELECT."""

    def __init__(self, contracts):
        self._contracts = contracts
        self._calls = 0
        self.added = []
        self.rolled_back = 0

    async def execute(self, statement, *args, **kwargs):
        self._calls += 1
        return _Result([] if self._calls == 1 else self._contracts)

    def add(self, obj):
        self.added.append(obj)

    @asynccontextmanager
    async def _nested(self):
        try:
            yield
        except Exception:
            self.rolled_back += 1
            raise

    def begin_nested(self):
        return self._nested()


async def test_one_broken_contract_does_not_stop_the_other_promotions(monkeypatch):
    from app.tasks import contract_alerts

    broken = SimpleNamespace(
        id=101, status=ContractStatus.active, end_date=date(2026, 9, 1)
    )
    fine = SimpleNamespace(
        id=102, status=ContractStatus.active, end_date=date(2026, 9, 1)
    )
    offboarded: list[int] = []

    async def _offboarding(db, *, contract_id, **kwargs):
        if contract_id == broken.id:
            raise RuntimeError("zepsuty wiersz")
        offboarded.append(contract_id)

    async def _generator(db, contract, **kwargs):
        return None

    monkeypatch.setattr(
        contract_alerts, "apply_contract_order_offboarding", _offboarding
    )
    monkeypatch.setattr(
        contract_alerts, "sync_generator_after_contract_ended", _generator
    )
    monkeypatch.setattr(
        contract_alerts.ContractStateBefore, "of", staticmethod(lambda c: None)
    )
    db = _PromotionDb([broken, fine])

    _ending, ended = await contract_alerts._promote_statuses(db)

    assert offboarded == [fine.id]
    assert ended == 1
    assert db.rolled_back == 1
    assert fine.status == ContractStatus.ended


# ── K6: pasmo progu alertu wygaśnięcia ───────────────────────────────────────


class _CapturingDb:
    def __init__(self):
        self.statements = []

    async def execute(self, statement, *args, **kwargs):
        self.statements.append(statement)
        return _Result([])


def _sql(statement) -> str:
    return str(statement.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.parametrize(
    ("threshold", "floor"),
    [
        (90, "end_date > '2026-11-25'"),  # za progiem 60
        (30, "end_date > '2026-10-10'"),  # za progiem 14
        (7, "end_date >= '2026-09-26'"),  # najmniejszy próg: od dziś
    ],
)
async def test_threshold_band_reaches_the_next_smaller_threshold(
    monkeypatch, threshold, floor
):
    """Jednodniowe okno gubiło alert po dniu bez biegu pętli."""
    from app.tasks import contract_alerts

    monkeypatch.setattr(contract_alerts, "business_today", lambda: TODAY)
    db = _CapturingDb()
    await contract_alerts._contracts_at_threshold(db, threshold)
    sql = _sql(db.statements[0])
    assert floor in sql
    target = (TODAY + timedelta(days=threshold)).isoformat()
    assert f"end_date <= '{target}'" in sql


# ── K7: generator B2B nie przestawia samej etykiety jednostki ────────────────


async def test_switch_to_hourly_converts_the_monthly_amounts():
    from app.services.contract_order_sync import switch_loaded_contract_to_hourly

    contract = _memory_contract(
        rate_unit=RateUnit.monthly,
        rate_candidate=Decimal("16800"),
        rate_client=Decimal("20160"),
    )

    class _Db:
        async def refresh(self, obj, attrs):
            return None

    assert await switch_loaded_contract_to_hourly(_Db(), contract) is True
    assert contract.rate_unit == RateUnit.hourly
    assert Decimal(contract.rate_client) == Decimal("120")  # 20 160 / 168
    assert Decimal(contract.rate_candidate) == Decimal("100")


async def test_switch_to_hourly_is_a_noop_for_hourly_contracts():
    from app.services.contract_order_sync import switch_loaded_contract_to_hourly

    contract = _memory_contract()

    class _Db:
        async def refresh(self, obj, attrs):  # pragma: no cover - nie wołane
            raise AssertionError("kontrakt godzinowy nie potrzebuje odświeżenia")

    assert await switch_loaded_contract_to_hourly(_Db(), contract) is False
    assert Decimal(contract.rate_client) == Decimal("200")


async def test_generate_on_a_monthly_draft_converts_the_client_rate(
    app_client: AsyncClient,
):
    from sqlalchemy import select

    from app.models.b2b_contract_role import B2BContractRole
    from app.models.contract_template import ContractTemplate
    from tests.test_b2b_generator_rate_visibility import _seed_user

    admin_h, _admin_id = await _seed_user(app_client, "admin")
    ids = await _seed(
        status=ContractStatus.draft,
        start_date=date(2026, 10, 1),
        rate_unit=RateUnit.monthly,
        rate_candidate=Decimal("16800"),
        rate_client=Decimal("20160"),
        contract_type=ContractType.b2b,
    )
    async with AsyncSessionLocal() as db:
        has_template = await db.scalar(
            select(ContractTemplate.id).where(
                ContractTemplate.contract_type == "b2b",
                ContractTemplate.language == "pl",
            )
        )
        if has_template is None:
            db.add(
                ContractTemplate(
                    name="B2B PL (test)",
                    contract_type="b2b",
                    language="pl",
                    content_jinja="<p>{{ b2b.contract_number }}</p>",
                )
            )
        role_id = await db.scalar(select(B2BContractRole.id).limit(1))
        if role_id is None:
            role = B2BContractRole(
                category_key="dev",
                category_label_pl="Dev",
                category_label_en="Dev",
                slug=f"rola-{uuid.uuid4().hex[:6]}",
                name_pl="Rola",
                name_en="Role",
                area_label_pl="Obszar",
                area_label_en="Area",
                scope_pl=["Zakres"],
                scope_en=["Scope"],
            )
            db.add(role)
            await db.flush()
            role_id = role.id
        await db.commit()

    resp = await app_client.post(
        "/api/b2b-generator/generate",
        headers=admin_h,
        json={
            "role_id": role_id,
            "contract_id": ids["contract_id"],
            "rate_candidate": 100,
            "start_date": "2026-10-01",
        },
    )
    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, ids["contract_id"])
        assert contract.rate_unit == RateUnit.hourly
        # 20 160 zł/mc ÷ 168 h — nie „20 160 zł/h”.
        assert Decimal(contract.rate_client) == Decimal("120")
