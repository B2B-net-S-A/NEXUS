"""Wnioski o dopłatę za technologię premium (F3, 15.11.2026).

Ścieżka (decyzje Artura z 15.11.2026: NEXUS proponuje, klient potwierdza,
prowadzi tylko DL, walka przy każdej prolongacji):

1. NEXUS proponuje „zna / korzysta” (``premium_skill_evidence``);
2. DL zatwierdza (``approved``) albo odrzuca (``dropped`` z powodem);
3. DL wysyła prośbę z uzasadnieniem do klienta (``sent``);
4. klient przyznaje (``granted``, potwierdzenie: kto, kiedy, dowód) — kontrakt
   dostaje dopłatę i krok limitu przez ``framework_category.set_by_delivery_lead``;
   albo odmawia (``refused``, powód i data kolejnej próby).

Zamknięte wnioski zostają: przy następnej prolongacji DL widzi powód odmowy.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.contract_premium_skill import ContractPremiumSkillClaim
from app.services.framework_category import (
    ClientTerms,
    FrameworkCategoryError,
    set_by_delivery_lead,
)
from app.services.framework_limits import addon_choices, percent_text
from app.services.premium_skill_evidence import (
    PersonSkills,
    TechEvidence,
    UsageRow,
    evidence,
    skill_names,
)
from app.services.premium_skill_schema import OPEN_STATUSES


async def person_skills(db: AsyncSession, contract: Contract) -> PersonSkills:
    from app.models.candidate_skill_usage import CandidateSkillUsage
    from app.models.contract_care import TechCard, TechCardSkill
    from app.models.skill import Skill

    candidate = (
        await db.get(Candidate, contract.candidate_id)
        if contract.candidate_id
        else None
    )
    usage = []
    if candidate is not None:
        usage = (
            await db.execute(
                select(
                    CandidateSkillUsage.skill_canonical,
                    CandidateSkillUsage.months,
                    CandidateSkillUsage.is_current,
                ).where(CandidateSkillUsage.candidate_id == candidate.id)
            )
        ).all()
    card_skills = (
        await db.execute(
            select(Skill.canonical_name)
            .join(TechCardSkill, TechCardSkill.skill_id == Skill.id)
            .join(TechCard, TechCard.id == TechCardSkill.card_id)
            .where(TechCard.contract_id == contract.id)
        )
    ).scalars()
    return PersonSkills(
        cv_skills=skill_names(candidate.skills) if candidate else (),
        verified=skill_names(candidate.verified_tech) if candidate else (),
        usage=tuple(UsageRow(s, m, bool(c)) for s, m, c in usage),
        tech_card=tuple(card_skills),
    )


def contract_technologies(
    terms: ClientTerms, contract: Contract, on: date
) -> list[tuple[str, str]]:
    """Technologie z umowy dla kategorii kontraktu; bez kategorii — wszystkie z umowy."""
    card = terms.card(contract.client_rate_card_id)
    adders = addon_choices(terms.adders, card, on=on) if card else list(terms.adders)
    seen: dict[str, str] = {}
    for adder in adders:
        seen.setdefault(adder.technology, percent_text(adder.percent))
    return list(seen.items())


async def contract_evidence(
    db: AsyncSession, contract: Contract, terms: ClientTerms, on: date
) -> list[TechEvidence]:
    return evidence(
        contract_technologies(terms, contract, on), await person_skills(db, contract)
    )


async def claims_for(
    db: AsyncSession, contract_id: int
) -> list[ContractPremiumSkillClaim]:
    return list(
        (
            await db.execute(
                select(ContractPremiumSkillClaim)
                .where(ContractPremiumSkillClaim.contract_id == contract_id)
                .order_by(
                    ContractPremiumSkillClaim.created_at.desc(),
                    ContractPremiumSkillClaim.id.desc(),
                )
            )
        ).scalars()
    )


def _open_claim(
    claims: list[ContractPremiumSkillClaim], technology: str
) -> Optional[ContractPremiumSkillClaim]:
    wanted = technology.strip().casefold()
    return next(
        (
            c
            for c in claims
            if c.status in OPEN_STATUSES and c.technology.casefold() == wanted
        ),
        None,
    )


async def create_claim(
    db: AsyncSession,
    contract: Contract,
    terms: ClientTerms,
    *,
    technology: str,
    knows: bool,
    uses: bool,
    note: Optional[str],
    actor_id: int,
    on: date,
) -> ContractPremiumSkillClaim:
    """Decyzja DL na propozycji NEXUSA. Bez „zna i korzysta” wniosek od razu jest odrzucony."""
    techs = dict(contract_technologies(terms, contract, on))
    match = next(
        (t for t in techs if t.casefold() == technology.strip().casefold()), None
    )
    if match is None:
        raise FrameworkCategoryError(
            f"Umowa ramowa nie przewiduje dopłaty za „{technology}” w kategorii tego kontraktu."
        )
    claims = await claims_for(db, contract.id)
    if _open_claim(claims, match):
        raise FrameworkCategoryError(f"Wniosek o dopłatę za {match} jest już otwarty.")
    proposal = next(
        (
            e
            for e in await contract_evidence(db, contract, terms, on)
            if e.technology == match
        ),
        None,
    )
    approved = knows and uses
    claim = ContractPremiumSkillClaim(
        contract_id=contract.id,
        technology=match,
        status="approved" if approved else "dropped",
        knows=knows,
        uses=uses,
        evidence=[asdict(proposal)] if proposal else [],
        dl_user_id=actor_id,
        dl_note=(note or "").strip() or None,
        outcome_reason=None
        if approved
        else "Delivery Lead: konsultant nie zna albo nie korzysta na projekcie",
    )
    db.add(claim)
    return claim


def advance_claim(
    db: AsyncSession,
    contract: Contract,
    terms: ClientTerms,
    claim: ContractPremiumSkillClaim,
    *,
    action: str,
    actor_id: int,
    confirmed_by: Optional[str] = None,
    confirmed_on: Optional[date] = None,
    client_evidence: Optional[str] = None,
    reason: Optional[str] = None,
    next_try_on: Optional[date] = None,
    effective_from: Optional[date] = None,
) -> None:
    """``send`` | ``grant`` | ``refuse`` | ``drop`` na otwartym wniosku."""
    if claim.status not in OPEN_STATUSES:
        raise FrameworkCategoryError("Ten wniosek jest już zamknięty.")
    if action == "send":
        claim.status = "sent"
    elif action == "grant":
        if contract.client_rate_card_id is None:
            raise FrameworkCategoryError(
                "Najpierw ustal kategorię kontraktu z umowy ramowej."
            )
        set_by_delivery_lead(
            db,
            contract,
            terms,
            rate_card_id=contract.client_rate_card_id,
            addon_technology=claim.technology,
            confirmed_by=confirmed_by,
            confirmed_on=confirmed_on,
            evidence=client_evidence,
            effective_from=effective_from or confirmed_on or business_today(),
            actor_id=actor_id,
        )
        claim.status = "granted"
        claim.client_confirmed_by = (confirmed_by or "").strip() or None
        claim.client_confirmed_on = confirmed_on
        claim.client_evidence = (client_evidence or "").strip() or None
    elif action == "refuse":
        if not (reason or "").strip():
            raise FrameworkCategoryError(
                "Wpisz powód odmowy klienta — przyda się przy następnej prolongacji."
            )
        claim.status = "refused"
        claim.outcome_reason = reason.strip()
        claim.next_try_on = next_try_on
    elif action == "drop":
        claim.status = "dropped"
        claim.outcome_reason = (reason or "").strip() or "Wycofany przez Delivery Leada"
    else:
        raise FrameworkCategoryError("Nieznana akcja wniosku.")
