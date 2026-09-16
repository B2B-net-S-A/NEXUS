"""Jednorazowy import zamówień MD Centrum e-Zdrowia z manifestu (Faza C, 09.2026).

Ticket „dane startowe": trzy karty zamówień MD (jedna na umowę wykonawczą),
osoby z zakresem podstawowym/opcjonalnym i stawkami PLN/MD, historia miesięczna
ze statusem („Protokół" / „Zaakceptowany"), zastępstwa jako para linii
(poprzednik zakończony z własną historią, następca z własnym budżetem).

Dlaczego import, a nie klikanie: ~70 wpisów miesięcznych, a zakończone linie
osób, które nie mają już kontraktu u klienta, nie dają się założyć z UI
(zapis historyczny wymaga kontraktu ``ended``, którego te osoby nie mają).
Manifest niesie nazwiska i stawki, więc żyje POZA repozytorium — trafia tu
jako ciało żądania admina.

Reguły (każda ma test w ``tests/test_ezdrowie_md_seed.py``):

* osoba: ``contract_id`` (musi być tego klienta) → ``candidate_id`` (kontrakt
  u klienta, a bez niego nowy z ``person.contract``) → nazwisko (DOKŁADNIE
  jedno trafienie wśród kontraktów klienta, potem kandydatów; więcej =
  ``ambiguous`` z listą do wskazania w manifeście; zero + ``create_if_missing``
  = nowy kandydat i kontrakt);
* grupa o numerze już istniejącym u klienta = ``already_exists`` (pomijana
  w całości — import jest idempotentny, nie dokłada drugiej karty);
* linia = ``ClientOrder`` jak w ``_build_line`` (stawki, tryb MD, opcja,
  umowa wykonawcza i część z grupy); ``completed`` wymaga daty końca i NIE
  wznawia kontraktu; zastępstwo = ``predecessor_order_id`` na następcy;
* historia = ``upsert_consumption(source="manual", status)``; pozostałość
  liczy ``recompute_remaining`` (podstawa + opcja − zejścia);
* szkice z ``supersede_order_ids``: tylko ``draft`` tego klienta, bez pliku
  i poza grupą — ANULOWANE (nie kasowane: ``DELETE`` szkicu kasuje plik);
* jakikolwiek bloker przy ``dry_run=False`` = nic nie zapisane (409).

Paragon w ``app_settings`` niesie WYŁĄCZNIE liczniki, ID i daty (log workflowu
``migration-receipts`` jest publiczny).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.app_setting import AppSetting
from app.models.candidate import Candidate
from app.models.client_executive_contract import (
    EXECUTIVE_CONTRACT_STATUS_ACTIVE,
    ClientExecutiveContract,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    ClientOrderGroup,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.md_consumption import CONSUMPTION_SOURCE_MANUAL
from app.schemas.ezdrowie_md_seed import (
    EzdrowieMdSeedManifest,
    EzdrowieMdSeedReport,
    SeedGroup,
    SeedGroupReport,
    SeedLine,
    SeedLineReport,
    SeedPerson,
    SeedPersonReport,
    SeedTotals,
)
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.client_order_lines import (
    consumed_md,
    record_event,
    recompute_remaining,
    split_md_usage,
    upsert_consumption,
)
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.multi_consultant_orders import (
    CONSUMPTION_STATUS_LABELS,
    EVENT_CONSULTANT_ADDED,
    EVENT_CONSULTANT_ENDED,
    EVENT_ORDER_CREATED,
    INPUT_MODE_MD,
    format_md,
    quantize_md,
)
from app.services.order_engagement_separation import absorb_auto_draft_shells
from app.services.polish_ilike import polish_folded_ilike

SEED_LINE_HISTORY_REASON = "seed_history"
"""``payload.reason`` zdarzenia zakończenia linii poprzednika. Świadomie INNY
niż ``removed_from_order`` — tamten daje badge „Usunięty z zamówienia"."""

RECEIPT_KEY_PREFIX = "ezdrowie_md_seed_"
_ZERO = Decimal("0")
_HOURS_PER_MD = Decimal("8")


class EzdrowieMdSeedBlocked(ValueError):
    """Manifest ma blokery — ``dry_run=False`` nie zapisuje niczego."""

    def __init__(self, report: EzdrowieMdSeedReport):
        super().__init__("Import zablokowany")
        self.report = report


def manifest_sha256(manifest: EzdrowieMdSeedManifest) -> str:
    canonical = json.dumps(
        manifest.model_dump(mode="json"), sort_keys=True, ensure_ascii=False
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


# ── Rozpoznanie osoby ────────────────────────────────────────────────────────


def _name_tokens(name: str) -> set[str]:
    return {normalize_person_name_part(part) for part in name.split() if part.strip()}


def _split_name(name: str) -> tuple[str, str]:
    parts = [part for part in name.split() if part.strip()]
    if len(parts) == 1:
        return parts[0], parts[0]
    return " ".join(parts[:-1]), parts[-1]


@dataclass
class _ResolvedPerson:
    candidate: Optional[Candidate] = None
    contract: Optional[Contract] = None
    report: SeedPersonReport = field(
        default_factory=lambda: SeedPersonReport(resolution="missing")
    )

    @property
    def ok(self) -> bool:
        return self.contract is not None


async def _latest_client_contract(
    db: AsyncSession, *, client_id: int, candidate_id: int
) -> Optional[Contract]:
    """Kontrakt osoby u klienta — DOWOLNY status (zakończony też): poprzednik
    zastępstwa ma zwykle kontrakt ``ended`` i właśnie na nim wisi jego linia."""
    return await db.scalar(
        select(Contract)
        .where(Contract.candidate_id == candidate_id, Contract.client_id == client_id)
        .order_by(Contract.start_date.desc().nullslast(), Contract.id.desc())
    )


async def _contracts_by_name(
    db: AsyncSession, *, client_id: int, name: str
) -> list[tuple[Contract, Candidate]]:
    wanted = _name_tokens(name)
    rows = (
        await db.execute(
            select(Contract, Candidate)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.client_id == client_id)
        )
    ).all()
    matches: list[tuple[Contract, Candidate]] = []
    for contract, candidate in rows:
        tokens = _name_tokens(f"{candidate.name or ''} {candidate.lastname or ''}")
        if tokens and tokens == wanted:
            matches.append((contract, candidate))
    return matches


async def _candidates_by_name(db: AsyncSession, name: str) -> list[Candidate]:
    """Kandydaci o tym imieniu i nazwisku — prefiltr w SQL po nazwisku
    (``polish_folded_ilike``), dokładne porównanie zbiorów tokenów w Pythonie.
    Bez prefiltru zapytanie ściągałoby całą bazę kandydatów."""
    _first, last = _split_name(name)
    wanted = _name_tokens(name)
    candidates = (
        await db.execute(
            select(Candidate)
            .where(polish_folded_ilike(Candidate.lastname, last))
            .order_by(Candidate.id.asc())
            .limit(200)
        )
    ).scalars()
    return [
        candidate
        for candidate in candidates
        if _name_tokens(f"{candidate.name or ''} {candidate.lastname or ''}") == wanted
    ]


def _new_contract(
    *, client_id: int, candidate_id: int, person: SeedPerson, line: SeedLine
) -> Contract:
    spec = person.contract
    assert spec is not None
    # Kontrakty CeZ są GODZINOWE (reguła „kontrakty zawsze zł/h", 0309):
    # stawki z linii są za MD, więc MD ÷ 8.
    return Contract(
        candidate_id=candidate_id,
        client_id=client_id,
        status=ContractStatus.ended
        if spec.status == "ended"
        else ContractStatus.active,
        start_date=spec.start_date,
        end_date=spec.end_date,
        rate_unit=RateUnit.hourly,
        rate_candidate=(line.rate_cost / _HOURS_PER_MD),
        rate_client=(line.rate_revenue / _HOURS_PER_MD),
        billing_hours_per_month=176,
    )


async def _resolve_person(
    db: AsyncSession,
    *,
    client_id: int,
    line: SeedLine,
    cache: dict[str, _ResolvedPerson],
) -> _ResolvedPerson:
    """Osoba z linii — kolejność: ``contract_id`` → ``candidate_id`` → nazwisko.

    Wynik jest cache'owany po kluczu osoby, więc dwie linie tej samej osoby
    (druga pozycja, następca po sobie samym) trafiają na TEN SAM kontrakt —
    także wtedy, gdy pierwszy raz go tu założyliśmy.
    """
    person = line.person
    cache_key = (
        f"contract:{person.contract_id}"
        if person.contract_id
        else f"candidate:{person.candidate_id}"
        if person.candidate_id
        else f"name:{' '.join(sorted(_name_tokens(person.name)))}"
    )
    if cache_key in cache:
        return cache[cache_key]

    resolved = _ResolvedPerson()
    if person.contract_id is not None:
        contract = await db.scalar(
            select(Contract).where(
                Contract.id == person.contract_id, Contract.client_id == client_id
            )
        )
        if contract is None:
            resolved.report = SeedPersonReport(
                resolution="missing",
                reason=f"Kontrakt {person.contract_id} nie należy do tego klienta",
            )
        else:
            resolved.contract = contract
            resolved.report = SeedPersonReport(
                resolution="resolved",
                candidate_id=contract.candidate_id,
                contract_id=contract.id,
            )
        cache[cache_key] = resolved
        return resolved

    candidate: Optional[Candidate] = None
    candidate_created = False
    if person.candidate_id is not None:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == person.candidate_id)
        )
        if candidate is None:
            resolved.report = SeedPersonReport(
                resolution="missing",
                reason=f"Kandydat {person.candidate_id} nie istnieje",
            )
            cache[cache_key] = resolved
            return resolved
    else:
        by_contract = await _contracts_by_name(
            db, client_id=client_id, name=person.name
        )
        distinct_candidates = {cand.id: cand for _c, cand in by_contract}
        if len(distinct_candidates) == 1:
            candidate = next(iter(distinct_candidates.values()))
        elif len(distinct_candidates) > 1:
            resolved.report = SeedPersonReport(
                resolution="ambiguous",
                reason="Kilka osób o tym nazwisku ma kontrakt u klienta",
                candidates=[
                    {"id": cand.id, "full_name": f"{cand.name} {cand.lastname}"}
                    for cand in distinct_candidates.values()
                ],
            )
            cache[cache_key] = resolved
            return resolved
        else:
            found = await _candidates_by_name(db, person.name)
            if len(found) == 1:
                candidate = found[0]
            elif len(found) > 1:
                resolved.report = SeedPersonReport(
                    resolution="ambiguous",
                    reason="Kilka rekordów kandydata o tym nazwisku — wskaż candidate_id",
                    candidates=[
                        {"id": cand.id, "full_name": f"{cand.name} {cand.lastname}"}
                        for cand in found[:10]
                    ],
                )
                cache[cache_key] = resolved
                return resolved
            elif person.create_if_missing:
                first, last = _split_name(person.name)
                candidate = Candidate(
                    name=first, lastname=last, source="ezdrowie_md_seed"
                )
                db.add(candidate)
                await db.flush()
                candidate_created = True
            else:
                resolved.report = SeedPersonReport(
                    resolution="missing",
                    reason="Nie znaleziono osoby — wskaż candidate_id albo create_if_missing",
                )
                cache[cache_key] = resolved
                return resolved

    assert candidate is not None
    contract = await _latest_client_contract(
        db, client_id=client_id, candidate_id=candidate.id
    )
    contract_created = False
    if contract is None:
        if person.contract is None:
            resolved.report = SeedPersonReport(
                resolution="missing",
                candidate_id=candidate.id,
                candidate_created=candidate_created,
                reason="Osoba nie ma kontraktu u klienta — podaj person.contract",
            )
            cache[cache_key] = resolved
            return resolved
        contract = _new_contract(
            client_id=client_id, candidate_id=candidate.id, person=person, line=line
        )
        db.add(contract)
        await db.flush()
        contract_created = True
    resolved.candidate = candidate
    resolved.contract = contract
    resolved.report = SeedPersonReport(
        resolution="created" if (candidate_created or contract_created) else "resolved",
        candidate_id=candidate.id,
        contract_id=contract.id,
        contract_created=contract_created,
        candidate_created=candidate_created,
    )
    cache[cache_key] = resolved
    return resolved


# ── Grupa i linie ────────────────────────────────────────────────────────────


async def _executive_contract(
    db: AsyncSession, *, client_id: int, number: str
) -> Optional[ClientExecutiveContract]:
    return await db.scalar(
        select(ClientExecutiveContract)
        .options(selectinload(ClientExecutiveContract.framework_contract))
        .where(
            ClientExecutiveContract.client_id == client_id,
            ClientExecutiveContract.number == number.strip(),
        )
    )


async def _group_exists(db: AsyncSession, *, client_id: int, order_number: str) -> bool:
    existing = await db.scalar(
        select(ClientOrderGroup.id).where(
            ClientOrderGroup.client_id == client_id,
            ClientOrderGroup.order_number == order_number.strip(),
        )
    )
    return existing is not None


def _ordered_lines(group: SeedGroup) -> list[SeedLine]:
    """Poprzednicy przed następcami — następca wskazuje ``predecessor_order_id``."""
    without = [line for line in group.lines if line.replaces_key is None]
    with_pred = [line for line in group.lines if line.replaces_key is not None]
    return without + with_pred


async def _create_line(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    executive: ClientExecutiveContract,
    line: SeedLine,
    person: _ResolvedPerson,
    predecessor: Optional[ClientOrder],
    user_id: int,
) -> ClientOrder:
    contract = person.contract
    assert contract is not None
    who = person.candidate
    display = (
        f"{who.name or ''} {who.lastname or ''}".strip()
        if who is not None
        else line.person.name
    )
    completed = line.line_status == "completed"
    status = ClientOrderStatus.completed if completed else ClientOrderStatus.active
    base = quantize_md(line.base_md)
    optional = quantize_md(line.optional_md) if line.optional_md is not None else None
    order = ClientOrder(
        client_id=group.client_id,
        contract_id=contract.id,
        order_group_id=group.id,
        order_type=group.order_type,
        title=f"Zamówienie {group.order_number} — {display or 'konsultant'}"[:255],
        status=status,
        start_date=line.start_date,
        end_date=line.end_date or group.end_date,
        filled_at=datetime.now(timezone.utc),
        md_rate_cost=line.rate_cost,
        md_rate_revenue=line.rate_revenue,
        rate_candidate=line.rate_cost,
        rate_client=line.rate_revenue,
        rate_unit=RateUnit.daily,
        billing_hours_per_month=160,
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        md_input_mode=INPUT_MODE_MD,
        md_input_value=base,
        md_total=base,
        md_optional_total=optional,
        md_remaining=base + (optional or _ZERO),
        md_manual_adjustment=_ZERO,
        executive_contract_id=executive.id,
        project_part=(
            executive.framework_contract.project_part
            if executive.framework_contract is not None
            else None
        ),
        predecessor_order_id=predecessor.id if predecessor is not None else None,
        created_by_user_id=user_id,
    )
    db.add(order)
    await db.flush()
    for removed_order_id in await absorb_auto_draft_shells(db, contract.id):
        db.add(
            Activity(
                entity_type="client_order",
                entity_id=removed_order_id,
                action="order_deleted",
                user_id=user_id,
                details={
                    "contract_id": contract.id,
                    "client_id": group.client_id,
                    "order_group_id": group.id,
                    "reason": "absorbed_auto_draft_shell",
                },
            )
        )
    predecessor_name = None
    if predecessor is not None:
        predecessor_name = predecessor.title.split(" — ", 1)[-1]
    record_event(
        db,
        group_id=group.id,
        order_id=order.id,
        event_type=EVENT_CONSULTANT_ADDED,
        description=(
            f"{display} — stawka kosztowa {format_md(order.md_rate_cost)} zł/MD, "
            f"przychodowa {format_md(order.md_rate_revenue)} zł/MD, "
            f"budżet {format_md(base)} MD"
            + (f" + opcja {format_md(optional)} MD" if optional is not None else "")
            + " (import startowy z manifestu)"
            + (f"; zastępstwo za {predecessor_name}" if predecessor_name else "")
        ),
        payload={
            "origin": "document",
            "document_name": display,
            "replaces": predecessor_name,
            "replaces_order_id": predecessor.id if predecessor is not None else None,
            "historical": completed,
            "seed": True,
        },
        user_id=user_id,
    )
    if completed:
        record_event(
            db,
            group_id=group.id,
            order_id=order.id,
            event_type=EVENT_CONSULTANT_ENDED,
            description=(
                f"{display} — udział na zamówieniu zakończony "
                f"{line.end_date.isoformat() if line.end_date else ''} "
                "(zapis historyczny z importu startowego)"
            ),
            payload={
                "reason": SEED_LINE_HISTORY_REASON,
                "end_date": line.end_date.isoformat() if line.end_date else None,
            },
            user_id=user_id,
        )
    else:
        await sync_contract_to_live_order(
            db,
            contract,
            order_start=order.start_date,
            order_end=order.end_date,
            actor_id=user_id,
            today=business_today(),
        )
    for row in line.history:
        await upsert_consumption(
            db,
            order=order,
            period_month=row.month,
            md_reported=row.md,
            source=CONSUMPTION_SOURCE_MANUAL,
            user_id=user_id,
            status=row.status,
            note=row.note,
        )
    await recompute_remaining(db, order)
    return order


async def _supersede_drafts(
    db: AsyncSession,
    *,
    client_id: int,
    order_ids: list[int],
    replacement_numbers: list[str],
    user_id: int,
) -> tuple[list[dict], list[str]]:
    superseded: list[dict] = []
    blockers: list[str] = []
    for order_id in order_ids:
        order = await db.scalar(select(ClientOrder).where(ClientOrder.id == order_id))
        if order is None or order.client_id != client_id:
            blockers.append(
                f"Szkic {order_id}: nie istnieje albo należy do innego klienta"
            )
            superseded.append({"order_id": order_id, "status": "blocked"})
            continue
        if order.status != ClientOrderStatus.draft:
            blockers.append(
                f"Szkic {order_id}: status {order.status.value}, można anulować tylko szkic"
            )
            superseded.append({"order_id": order_id, "status": "blocked"})
            continue
        if order.order_group_id is not None or order.file_path is not None:
            blockers.append(f"Szkic {order_id}: jest linią grupy albo ma plik PO")
            superseded.append({"order_id": order_id, "status": "blocked"})
            continue
        order.status = ClientOrderStatus.cancelled
        note = (
            "Zastąpione przez zamówienie MD "
            f"{', '.join(replacement_numbers)} (import startowy)"
        )
        order.notes = f"{order.notes}\n{note}" if order.notes else note
        db.add(
            Activity(
                entity_type="client_order",
                entity_id=order.id,
                action="order_cancelled",
                user_id=user_id,
                details={
                    "reason": "superseded_by_md_seed",
                    "contract_id": order.contract_id,
                    "client_id": client_id,
                },
            )
        )
        superseded.append({"order_id": order_id, "status": "cancelled"})
    return superseded, blockers


# ── Przebieg ─────────────────────────────────────────────────────────────────


async def run_ezdrowie_md_seed(
    db: AsyncSession,
    *,
    manifest: EzdrowieMdSeedManifest,
    user_id: int,
    dry_run: bool,
) -> EzdrowieMdSeedReport:
    """Jedna transakcja; przy ``dry_run`` wołający robi ``rollback()``.

    Zapisy idą do sesji także w dry-runie (kandydat/kontrakt/linie) — tylko tak
    da się policzyć raport dokładnie tą samą ścieżką, którą pójdzie apply.
    Przy blokerach i ``dry_run=False`` rzuca :class:`EzdrowieMdSeedBlocked`;
    wołający ma wtedy zrobić rollback i odpowiedzieć 409.
    """
    client_id = manifest.client_id
    blockers: list[str] = []
    totals = SeedTotals()
    group_reports: list[SeedGroupReport] = []
    person_cache: dict[str, _ResolvedPerson] = {}

    for spec in manifest.groups:
        executive = await _executive_contract(
            db, client_id=client_id, number=spec.executive_contract_number
        )
        report = SeedGroupReport(
            order_number=spec.order_number,
            executive_contract_number=spec.executive_contract_number,
            status="blocked",
        )
        if executive is None or executive.status != EXECUTIVE_CONTRACT_STATUS_ACTIVE:
            blockers.append(
                f"Umowa wykonawcza {spec.executive_contract_number} nie istnieje "
                "u klienta albo jest zakończona"
            )
            group_reports.append(report)
            continue
        if await _group_exists(db, client_id=client_id, order_number=spec.order_number):
            report.status = "already_exists"
            group_reports.append(report)
            continue

        group = ClientOrderGroup(
            client_id=client_id,
            order_number=spec.order_number.strip(),
            start_date=spec.start_date,
            end_date=spec.end_date,
            status=GROUP_STATUS_ACTIVE,
            order_type="md",
            md_budget_mode="per_person",
            md_budget_mode_locked=True,
            is_cost_based=False,
            is_md_budget_based=False,
            executive_contract_id=executive.id,
            created_by_user_id=user_id,
        )
        db.add(group)
        await db.flush()
        record_event(
            db,
            group_id=group.id,
            event_type=EVENT_ORDER_CREATED,
            description=(
                f"Utworzono zamówienie nr {group.order_number} "
                f"({group.start_date.isoformat()} → "
                f"{group.end_date.isoformat() if group.end_date else 'bezterminowo'}) "
                f"— umowa wykonawcza {executive.number}, import startowy"
            ),
            user_id=user_id,
        )
        report.status = "created"
        report.group_id = group.id
        totals.groups_created += 1

        created_by_key: dict[str, ClientOrder] = {}
        successors: set[int] = set()
        for line in _ordered_lines(spec):
            person = await _resolve_person(
                db, client_id=client_id, line=line, cache=person_cache
            )
            if person.report.candidate_created:
                totals.candidates_created += 1
                person.report.candidate_created = False  # liczymy raz
            if person.report.contract_created:
                totals.contracts_created += 1
                person.report.contract_created = False
            line_report = SeedLineReport(
                key=line.key,
                person=person.report,
                status=line.line_status,
                md_total=quantize_md(line.base_md),
                md_optional_total=(
                    quantize_md(line.optional_md)
                    if line.optional_md is not None
                    else None
                ),
                md_used=_ZERO,
                md_base_used=_ZERO,
                md_optional_used=_ZERO,
                consumptions=len(line.history),
                predecessor_key=line.replaces_key,
            )
            if not person.ok:
                blockers.append(
                    f"{spec.order_number} / {line.key}: {person.report.reason}"
                )
                report.lines.append(line_report)
                continue
            predecessor = (
                created_by_key.get(line.replaces_key) if line.replaces_key else None
            )
            if line.replaces_key and predecessor is None:
                blockers.append(
                    f"{spec.order_number} / {line.key}: poprzednik {line.replaces_key} "
                    "nie został utworzony"
                )
                report.lines.append(line_report)
                continue
            order = await _create_line(
                db,
                group=group,
                executive=executive,
                line=line,
                person=person,
                predecessor=predecessor,
                user_id=user_id,
            )
            created_by_key[line.key] = order
            if predecessor is not None:
                successors.add(predecessor.id)
            used = await consumed_md(db, order.id)
            base_used, optional_used = split_md_usage(order, used)
            line_report.order_id = order.id
            line_report.md_used = used
            line_report.md_base_used = base_used
            line_report.md_optional_used = optional_used
            report.lines.append(line_report)
            totals.lines += 1
            totals.consumptions += len(line.history)
            totals.md_used_sum += used

        for line_report in report.lines:
            if line_report.order_id is None:
                continue
            order = created_by_key[line_report.key]
            revenue = Decimal(str(order.md_rate_revenue or 0))
            report.md_used_total += line_report.md_used
            report.used_value_pln += line_report.md_used * revenue
            if order.id not in successors:
                budget = line_report.md_total + (line_report.md_optional_total or _ZERO)
                report.md_positions_total += budget
                report.contract_value_pln += budget * revenue
        group_reports.append(report)

    replacement_numbers = [
        r.order_number for r in group_reports if r.status == "created"
    ]
    superseded, supersede_blockers = await _supersede_drafts(
        db,
        client_id=client_id,
        order_ids=manifest.supersede_order_ids,
        replacement_numbers=replacement_numbers
        or [g.order_number for g in manifest.groups],
        user_id=user_id,
    )
    blockers.extend(supersede_blockers)
    totals.orders_superseded = sum(
        1 for row in superseded if row["status"] == "cancelled"
    )

    report = EzdrowieMdSeedReport(
        dry_run=dry_run,
        applied=False,
        groups=group_reports,
        superseded=superseded,
        totals=totals,
        blockers=blockers,
    )
    if dry_run:
        return report
    if blockers:
        raise EzdrowieMdSeedBlocked(report)

    sha = manifest_sha256(manifest)
    receipt_key = f"{RECEIPT_KEY_PREFIX}{sha[:12]}"
    db.add(
        AppSetting(
            key=receipt_key,
            value={
                "manifest_sha256": sha,
                "client_id": client_id,
                "applied_at": datetime.now(timezone.utc).isoformat(),
                "groups": [
                    {"group_id": g.group_id, "status": g.status, "lines": len(g.lines)}
                    for g in group_reports
                ],
                "line_order_ids": [
                    line.order_id
                    for g in group_reports
                    for line in g.lines
                    if line.order_id is not None
                ],
                "superseded_order_ids": [
                    row["order_id"]
                    for row in superseded
                    if row["status"] == "cancelled"
                ],
                "totals": totals.model_dump(mode="json"),
            },
            updated_by=user_id,
        )
    )
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="ezdrowie_md_orders_imported",
            user_id=user_id,
            external_source="ezdrowie_md_seed",
            details={"receipt_key": receipt_key, **totals.model_dump(mode="json")},
        )
    )
    report.applied = True
    report.receipt_key = receipt_key
    return report


def label_for_status(status: Optional[str]) -> str:
    return CONSUMPTION_STATUS_LABELS.get(status or "", "bez statusu")
