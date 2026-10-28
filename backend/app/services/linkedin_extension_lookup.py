"""Co NEXUS wie o osobie z otwartej strony LinkedIna (wtyczka, 28.10.2026).

Panel wtyczki pyta o jedną osobę (``lookup``) albo o stronę wyników
(``batch_lookup``). Rozpoznanie: najpierw link do profilu
(``candidates.linkedin_slug``), potem imię i nazwisko z firmą. Samo imię
i nazwisko bez zgodnej firmy nie wystarcza — wtedy panel pokazuje
„może to ta osoba” zamiast pewnego „jest w NEXUSIE”.

Dopasowanie do rekrutacji jest podpowiedzią: awaria wyszukiwania daje pustą
listę, nie błąd całego panelu.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.recruitment_access import job_read_scope_clause
from app.core.config import settings
from app.core.scheduling import business_today
from app.models.call import Call
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.candidate_consent import CandidateConsent
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.note import Note, NoteType
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User
from app.schemas.linkedin_extension import (
    AmbiguousItem,
    BatchItem,
    BatchPerson,
    CandidateBrief,
    ContactOut,
    ContractorOut,
    JobChangeOut,
    JobMatchOut,
    OffLimitsOut,
    OwnerOut,
    ProcessOut,
    ProfileRead,
    RateOut,
    RodoOut,
)
from app.schemas.pipeline import STAGE_LABELS
from app.services import client_off_limits
from app.services.candidate_rate_from import effective_rate
from app.services.company_names import normalize_company_name
from app.services.note_kinds import CONTACT_ATTEMPT
from app.services.proxycurl.client import normalize_linkedin_url
from app.services.rejection_reason_labels import rejection_reason_label

logger = logging.getLogger(__name__)

#: Ślad notatek kontaktu zapisanych z wtyczki (``Note.source_ref``).
CONTACT_SOURCE_PREFIX = "linkedin_extension:"

CHANNEL_LABELS: dict[str, str] = {
    "inmail": "InMail",
    "invitation": "zaproszenie na LinkedInie",
    "linkedin_message": "wiadomość na LinkedInie",
    "phone": "telefon",
}

_TERMINAL_STAGES = frozenset({PipelineStage.rejected, PipelineStage.withdrawn, PipelineStage.hired})
_MATCH_MIN_SCORE = 50
_MATCH_LIMIT = 3
_CONTACT_LIMIT = 4
_PROCESS_LIMIT = 6
# „Jan Kowalski, PhD”, „Jan Kowalski (he/him)”, „Jan Kowalski 🚀” — dopiski
# po nazwisku nie są nazwiskiem.
_NAME_SUFFIX_RE = re.compile(r"\s*(?:[,|(].*|\s[^\w\s.'-].*)$")


def split_full_name(full_name: str) -> tuple[str, str]:
    cleaned = _NAME_SUFFIX_RE.sub("", (full_name or "").strip()).strip()
    parts = [p for p in cleaned.split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


def profile_link(profile: ProfileRead | BatchPerson) -> Optional[str]:
    """Kanoniczny link ``linkedin.com/in/<slug>`` albo None (Recruiter bez linku)."""
    for raw in (getattr(profile, "public_url", None), getattr(profile, "page_url", None)):
        if raw and "/in/" in raw:
            normalized = normalize_linkedin_url(raw)
            if normalized:
                return normalized
    return None


def _slug(normalized_url: str) -> str:
    return normalized_url.rstrip("/").split("/")[-1].lower()


def _same_company(a: Optional[str], b: Optional[str]) -> bool:
    left, right = normalize_company_name(a or ""), normalize_company_name(b or "")
    if not left or not right:
        return False
    return left == right or left.startswith(right + " ") or right.startswith(left + " ")


def nexus_current_company(candidate: Any) -> Optional[str]:
    companies = client_off_limits.current_companies(candidate)
    return companies[0][0] if companies else None


def _candidate_companies(candidate: Any) -> list[str]:
    out = [c for c, _ in client_off_limits.current_companies(candidate, undated_counts=True)]
    experience = candidate.experience if isinstance(candidate.experience, list) else []
    out.extend(
        e["company"]
        for e in experience[:3]
        if isinstance(e, dict) and isinstance(e.get("company"), str)
    )
    return out


@dataclass
class PersonMatch:
    status: str  # found | not_found | ambiguous
    matched_by: Optional[str]
    candidate: Optional[Candidate]
    ambiguous: list[Candidate]


async def _by_link(db: AsyncSession, links: Iterable[str]) -> dict[str, Candidate]:
    slugs = {_slug(link) for link in links if link}
    if not slugs:
        return {}
    rows = (
        await db.execute(
            select(Candidate)
            .where(Candidate.linkedin_slug.in_(slugs))
            .order_by(Candidate.id.asc())
        )
    ).scalars().all()
    out: dict[str, Candidate] = {}
    for row in rows:
        out.setdefault(row.linkedin_slug, row)
    return out


async def _by_names(
    db: AsyncSession, names: Iterable[tuple[str, str]]
) -> dict[tuple[str, str], list[Candidate]]:
    keys = {(n.lower(), ln.lower()) for n, ln in names if n and ln}
    if not keys:
        return {}
    rows = (
        await db.execute(
            select(Candidate)
            .where(
                or_(
                    *(
                        and_(func.lower(Candidate.name) == n, func.lower(Candidate.lastname) == ln)
                        for n, ln in keys
                    )
                )
            )
            .order_by(Candidate.id.desc())
            .limit(200)
        )
    ).scalars().all()
    out: dict[tuple[str, str], list[Candidate]] = {}
    for row in rows:
        out.setdefault(((row.name or "").lower(), (row.lastname or "").lower()), []).append(row)
    return out


def _resolve(
    link: Optional[str],
    name_key: tuple[str, str],
    company: Optional[str],
    by_link: dict[str, Candidate],
    by_name: dict[tuple[str, str], list[Candidate]],
) -> PersonMatch:
    if link and (hit := by_link.get(_slug(link))) is not None:
        return PersonMatch("found", "linkedin", hit, [])
    same_name = by_name.get((name_key[0].lower(), name_key[1].lower()), [])
    # Osoba z innym linkiem w NEXUSIE to ktoś inny o tym samym nazwisku.
    if link:
        same_name = [c for c in same_name if not c.linkedin_slug]
    if not same_name:
        return PersonMatch("not_found", None, None, [])
    with_company = [
        c for c in same_name if any(_same_company(company, x) for x in _candidate_companies(c))
    ]
    if len(with_company) == 1:
        return PersonMatch("found", "name_company", with_company[0], [])
    return PersonMatch("ambiguous", None, None, (with_company or same_name)[:5])


async def find_person(db: AsyncSession, profile: ProfileRead) -> PersonMatch:
    link = profile_link(profile)
    name_key = split_full_name(profile.full_name)
    by_link = await _by_link(db, [link] if link else [])
    by_name = {} if link and by_link else await _by_names(db, [name_key])
    return _resolve(link, name_key, profile.current_company, by_link, by_name)


def candidate_url(candidate_id: int) -> str:
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/candidates/{candidate_id}"


def _full_name(candidate: Candidate) -> str:
    return " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()


# ── Sekcje panelu ────────────────────────────────────────────────────────────


async def load_processes(
    db: AsyncSession, user: User, candidate_id: int
) -> tuple[list[ProcessOut], list[tuple[int, int]]]:
    rows = (
        await db.execute(
            select(
                CandidateStage.job_id,
                Job.title,
                func.coalesce(Client.display_name, Client.name),
                CandidateStage.stage,
                CandidateStage.moved_at,
                User.name,
                RejectionReason.name,
                Job.is_open,
            )
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(User, User.id == Job.recruiter_id)
            .outerjoin(RejectionReason, RejectionReason.id == CandidateStage.rejection_reason_id)
            .where(
                CandidateStage.candidate_id == candidate_id,
                job_read_scope_clause(user, CandidateStage.job_id),
            )
            .order_by(CandidateStage.moved_at.desc())
            .limit(_PROCESS_LIMIT)
        )
    ).all()
    out: list[ProcessOut] = []
    open_pairs: list[tuple[int, int]] = []
    for job_id, title, client_name, stage, moved_at, recruiter, reason, is_open in rows:
        terminal = stage in _TERMINAL_STAGES
        closed = terminal or not is_open
        close_label = None
        if stage in (PipelineStage.rejected, PipelineStage.withdrawn):
            reason_label = rejection_reason_label(reason)
            close_label = STAGE_LABELS[stage] + (f" · {reason_label}" if reason_label else "")
        elif not is_open and not terminal:
            close_label = "Rekrutacja zamknięta"
        if not closed:
            open_pairs.append((candidate_id, job_id))
        out.append(
            ProcessOut(
                job_id=job_id,
                job_title=title,
                client_name=client_name,
                stage_label=STAGE_LABELS.get(stage, str(stage)),
                recruiter_name=recruiter,
                closed=closed,
                close_label=close_label,
                updated_at=moved_at,
            )
        )
    return out, open_pairs


async def load_contacts(db: AsyncSession, candidate_id: int) -> list[ContactOut]:
    note_rows = (
        await db.execute(
            select(Note.created_at, User.name, Note.note_type, Note.source_ref, Note.content)
            .outerjoin(User, User.id == Note.author_id)
            .where(
                Note.candidate_id == candidate_id,
                or_(
                    Note.kind == CONTACT_ATTEMPT,
                    Note.note_type.in_([NoteType.call, NoteType.email, NoteType.meeting]),
                ),
            )
            .order_by(Note.created_at.desc())
            .limit(_CONTACT_LIMIT)
        )
    ).all()
    call_rows = (
        await db.execute(
            select(func.coalesce(Call.started_at, Call.created_at), User.name, Call.contact_outcome)
            .outerjoin(User, User.id == Call.user_id)
            .where(Call.candidate_id == candidate_id)
            .order_by(func.coalesce(Call.started_at, Call.created_at).desc())
            .limit(_CONTACT_LIMIT)
        )
    ).all()
    items: list[ContactOut] = []
    for at, author, note_type, source_ref, content in note_rows:
        if source_ref and source_ref.startswith(CONTACT_SOURCE_PREFIX):
            label = CHANNEL_LABELS.get(source_ref[len(CONTACT_SOURCE_PREFIX):], "kontakt")
        else:
            label = {
                NoteType.call: "telefon",
                NoteType.email: "e-mail",
                NoteType.meeting: "spotkanie",
            }.get(note_type, "próba kontaktu")
        items.append(
            ContactOut(at=at, user_name=author, channel_label=label, note=_short(content))
        )
    for at, author, outcome in call_rows:
        if at is None:
            continue
        items.append(
            ContactOut(
                at=at,
                user_name=author,
                channel_label="telefon",
                note="nie odebrał" if outcome == "no_answer" else None,
            )
        )
    items.sort(key=lambda c: c.at, reverse=True)
    return items[:_CONTACT_LIMIT]


def _short(text: Optional[str], limit: int = 140) -> Optional[str]:
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


async def load_owner(
    db: AsyncSession, user: User, open_pairs: list[tuple[int, int]], contacts: list[ContactOut]
) -> Optional[OwnerOut]:
    """Kto prowadzi osobę: „Prowadzi” z najnowszego otwartego procesu."""
    if not open_pairs:
        return None
    from app.services.pair_owner import implicit_owner_id, owner_ids

    owners = await owner_ids(db, open_pairs)
    for pair in open_pairs:
        owner_id = owners.get(pair) or await implicit_owner_id(
            db, candidate_id=pair[0], job_id=pair[1]
        )
        if owner_id is None:
            continue
        owner = await db.get(User, owner_id)
        if owner is None:
            continue
        last = next((c.at for c in contacts if c.user_name == owner.name), None)
        return OwnerOut(
            user_id=owner.id,
            name=owner.name,
            is_me=owner.id == user.id,
            last_contact_at=last,
        )
    return None


def rate_out(candidate: Candidate) -> Optional[RateOut]:
    amount, currency = effective_rate(candidate)
    if amount is None:
        return None
    symbol = {"PLN": "zł", "EUR": "€", "USD": "$"}.get((currency or "PLN").upper(), currency or "zł")
    as_of = getattr(candidate, "rate_from_at", None)
    if isinstance(as_of, datetime):
        as_of = as_of.date()
    return RateOut(label=f"{amount:.0f} {symbol}/h", as_of=as_of)


async def rodo_out(db: AsyncSession, candidate_id: int) -> RodoOut:
    given = await db.scalar(
        select(func.max(CandidateConsent.given_at)).where(
            CandidateConsent.candidate_id == candidate_id
        )
    )
    if given is None:
        return RodoOut(status="none", label="brak zgody zapisanej w NEXUSIE")
    return RodoOut(status="valid", label=f"zgoda z {given.strftime('%d.%m.%Y')}")


async def contractor_out(db: AsyncSession, candidate_id: int) -> Optional[ContractorOut]:
    from app.services.employment_marker import load_employment_markers

    markers = await load_employment_markers(db, [candidate_id], today=business_today())
    marker = markers.get(candidate_id)
    if marker is None or not marker.clients:
        return None
    first = marker.clients[0]
    return ContractorOut(
        client_name=first.client_name,
        end_date=first.order_end_date,
        delivery_lead_name=first.delivery_lead_name,
    )


async def off_limits_out(
    db: AsyncSession, profile_company: Optional[str], candidate: Optional[Candidate]
) -> Optional[OffLimitsOut]:
    """Firma ze strony LinkedIna jest świeższa niż nasze dane — ma pierwszeństwo."""
    labels = await client_off_limits.off_limits_labels(db)
    if not labels:
        return None
    person: Any
    if profile_company:
        person = SimpleNamespace(
            id=0, name=None, lastname=None, linkedin_current_company=profile_company, experience=None
        )
    elif candidate is not None:
        person = candidate
    else:
        return None
    hit = client_off_limits.find_hit(person, labels)
    if hit is None:
        return None
    return OffLimitsOut(client_name=hit.client_name, company=hit.company)


def job_change_out(profile: ProfileRead, candidate: Candidate) -> Optional[JobChangeOut]:
    page = (profile.current_company or "").strip()
    if not page:
        return None
    ours = nexus_current_company(candidate)
    if ours and _same_company(page, ours):
        return None
    if not ours and not candidate.linkedin_current_company:
        # Brak naszej wiedzy to nie „zmiana pracy” — „Zaktualizuj” i tak dopisze firmę.
        return JobChangeOut(page_company=page, nexus_company=None)
    return JobChangeOut(page_company=page, nexus_company=ours)


# ── Dopasowanie do otwartych rekrutacji ──────────────────────────────────────


def matching_text(profile: ProfileRead) -> str:
    parts: list[str] = [profile.headline or "", profile.current_title or ""]
    for entry in profile.experience[:6]:
        parts.append(" ".join(p for p in (entry.title, entry.company) if p))
    parts.extend(profile.skills[:40])
    if profile.about:
        parts.append(profile.about[:1500])
    return " ".join(p for p in parts if p and p.strip())[:4000]


def years_from_experience(profile: ProfileRead) -> Optional[int]:
    years = []
    for entry in profile.experience:
        match = re.match(r"(\d{4})", entry.start or "")
        if match:
            years.append(int(match.group(1)))
    if not years:
        return None
    return max(0, business_today().year - min(years))


def _ephemeral_candidate(profile: ProfileRead) -> SimpleNamespace:
    name, lastname = split_full_name(profile.full_name)
    return SimpleNamespace(
        id=0,
        name=name,
        lastname=lastname,
        email=None,
        skills=[{"name": s} for s in profile.skills[:60]],
        verified_tech=[],
        tags=[],
        experience=[],
        location=profile.location,
        availability_date=None,
        availability_status=AvailabilityStatus.unknown,
        expected_rate_hourly=None,
        years_it_experience=years_from_experience(profile),
        competence_category=None,
        ai_summary=profile.headline,
        raw_cv_text=matching_text(profile),
        preferences={},
        status=CandidateStatus.active,
        champion=False,
        avatar_url=None,
    )


async def job_matches(
    db: AsyncSession,
    profile: ProfileRead,
    *,
    exclude_job_ids: Iterable[int] = (),
    only_job_id: Optional[int] = None,
    limit: int = _MATCH_LIMIT,
) -> list[JobMatchOut]:
    text = matching_text(profile)
    if len(text) < 20:
        return []
    try:
        from app.services.embedding_service import search_jobs_semantic
        from app.services.scoring_service import rank_jobs_for_candidate

        hits = await search_jobs_semantic(text, top_k=30, statuses=[JobStatus.published.value])
        similarity = {h["job_id"]: h["score"] for h in hits}
        excluded = set(exclude_job_ids)
        ids = [jid for jid in similarity if jid not in excluded]
        if only_job_id is not None:
            ids = [only_job_id]
            similarity.setdefault(only_job_id, 0.0)
        if not ids:
            return []
        jobs = (
            await db.execute(
                select(Job).where(
                    Job.id.in_(ids), Job.is_open.is_(True), Job.status == JobStatus.published
                )
            )
        ).scalars().all()
        if not jobs:
            return []
        breakdowns = await rank_jobs_for_candidate(
            _ephemeral_candidate(profile), jobs, db, similarity_map=similarity
        )
    except Exception:  # noqa: BLE001 — dopasowanie jest podpowiedzią, nie warunkiem
        logger.warning("linkedin_extension.matching_failed", exc_info=True)
        return []
    by_id = {j.id: j for j in jobs}
    names = await _job_labels(db, list(by_id))
    out: list[JobMatchOut] = []
    for b in sorted(breakdowns, key=lambda b: b.total, reverse=True):
        score = int(round(b.total))
        if only_job_id is None and score < _MATCH_MIN_SCORE:
            continue
        job = by_id.get(b.job_id)
        if job is None:
            continue
        client_name, recruiter_name = names.get(job.id, (None, None))
        out.append(
            JobMatchOut(
                job_id=job.id,
                title=job.title,
                client_name=client_name,
                recruiter_name=recruiter_name,
                score=score,
            )
        )
        if len(out) >= limit:
            break
    return out


async def _job_labels(db: AsyncSession, job_ids: list[int]) -> dict[int, tuple[Optional[str], Optional[str]]]:
    if not job_ids:
        return {}
    rows = (
        await db.execute(
            select(Job.id, func.coalesce(Client.display_name, Client.name), User.name)
            .outerjoin(Client, Client.id == Job.client_id)
            .outerjoin(User, User.id == Job.recruiter_id)
            .where(Job.id.in_(job_ids))
        )
    ).all()
    return {r[0]: (r[1], r[2]) for r in rows}


# ── Całość dla jednej osoby ──────────────────────────────────────────────────


@dataclass
class LookupResult:
    status: str
    matched_by: Optional[str]
    candidate: Optional[CandidateBrief]
    ambiguous: list[AmbiguousItem]
    owner: Optional[OwnerOut]
    processes: list[ProcessOut]
    contacts: list[ContactOut]
    rate: Optional[RateOut]
    rodo: Optional[RodoOut]
    off_limits: Optional[OffLimitsOut]
    contractor: Optional[ContractorOut]
    job_change: Optional[JobChangeOut]
    matches: list[JobMatchOut]

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


async def lookup(db: AsyncSession, user: User, profile: ProfileRead) -> LookupResult:
    match = await find_person(db, profile)
    candidate = match.candidate
    off_limits = await off_limits_out(db, profile.current_company, candidate)
    if candidate is None:
        return LookupResult(
            status=match.status,
            matched_by=None,
            candidate=None,
            ambiguous=[
                AmbiguousItem(
                    id=c.id,
                    name=_full_name(c),
                    company=nexus_current_company(c),
                    url=candidate_url(c.id),
                )
                for c in match.ambiguous
            ],
            owner=None,
            processes=[],
            contacts=[],
            rate=None,
            rodo=None,
            off_limits=off_limits,
            contractor=None,
            job_change=None,
            matches=await job_matches(db, profile),
        )

    processes, open_pairs = await load_processes(db, user, candidate.id)
    contacts = await load_contacts(db, candidate.id)
    created = candidate.created_at
    return LookupResult(
        status="found",
        matched_by=match.matched_by,
        candidate=CandidateBrief(
            id=candidate.id,
            name=_full_name(candidate),
            headline=candidate.linkedin_current_title or profile.headline,
            city=candidate.city,
            url=candidate_url(candidate.id),
            in_nexus_since=created.date() if isinstance(created, datetime) else None,
        ),
        ambiguous=[],
        owner=await load_owner(db, user, open_pairs, contacts),
        processes=processes,
        contacts=contacts,
        rate=rate_out(candidate),
        rodo=await rodo_out(db, candidate.id),
        off_limits=off_limits,
        contractor=await contractor_out(db, candidate.id),
        job_change=job_change_out(profile, candidate),
        matches=await job_matches(
            db, profile, exclude_job_ids=[p.job_id for p in processes]
        ),
    )


# ── Strona wyników ───────────────────────────────────────────────────────────


async def batch_lookup(
    db: AsyncSession, user: User, people: list[BatchPerson]
) -> list[BatchItem]:
    """Statusy osób z widocznej strony wyników. Bez procentu dopasowania:
    z listy jest tylko nagłówek, a liczenie wymagałoby wywołania Voyage na
    każdą osobę (do 50 na kliknięcie) — procent pokazuje profil."""
    links = [profile_link(p) for p in people]
    names = [split_full_name(p.full_name) for p in people]
    by_link = await _by_link(db, [link for link in links if link])
    by_name = await _by_names(db, names)
    matches = [
        _resolve(link, name, p.current_company, by_link, by_name)
        for link, name, p in zip(links, names, people)
    ]
    found_ids = [m.candidate.id for m in matches if m.candidate is not None]

    active: dict[int, tuple[str, Optional[str], Optional[str]]] = {}
    if found_ids:
        rows = (
            await db.execute(
                select(
                    CandidateStage.candidate_id,
                    CandidateStage.stage,
                    func.coalesce(Client.display_name, Client.name),
                    User.name,
                )
                .join(Job, Job.id == CandidateStage.job_id)
                .outerjoin(Client, Client.id == Job.client_id)
                .outerjoin(User, User.id == Job.recruiter_id)
                .where(
                    CandidateStage.candidate_id.in_(found_ids),
                    CandidateStage.stage.notin_(list(_TERMINAL_STAGES)),
                    Job.is_open.is_(True),
                    job_read_scope_clause(user, CandidateStage.job_id),
                )
                .order_by(CandidateStage.moved_at.desc())
            )
        ).all()
        for cid, stage, client_name, recruiter in rows:
            active.setdefault(cid, (STAGE_LABELS.get(stage, str(stage)), client_name, recruiter))

    from app.services.employment_marker import load_employment_markers

    markers = await load_employment_markers(db, found_ids, today=business_today()) if found_ids else {}
    labels = await client_off_limits.off_limits_labels(db)

    items: list[BatchItem] = []
    for index, (person, match) in enumerate(zip(people, matches)):
        cid = match.candidate.id if match.candidate is not None else None
        hit = (
            client_off_limits.find_hit(
                SimpleNamespace(
                    id=0, name=None, lastname=None,
                    linkedin_current_company=person.current_company, experience=None,
                ),
                labels,
            )
            if labels and person.current_company
            else None
        )
        marker = markers.get(cid) if cid else None
        if marker is not None and marker.clients:
            first = marker.clients[0]
            items.append(BatchItem(index=index, status="contractor", candidate_id=cid,
                                   label=f"Nasz kontraktor · {first.client_name or ''}".strip(" ·")))
        elif hit is not None:
            items.append(BatchItem(index=index, status="off_limits", candidate_id=cid,
                                   label=f"Off-limits · {hit.client_name}"))
        elif cid is not None and cid in active:
            stage_label, client_name, recruiter = active[cid]
            label = " · ".join(p for p in (stage_label, client_name, recruiter) if p)
            items.append(BatchItem(index=index, status="in_process", candidate_id=cid, label=label))
        elif cid is not None:
            items.append(BatchItem(index=index, status="in_base", candidate_id=cid, label="W bazie NEXUSA"))
        else:
            items.append(BatchItem(index=index, status="new", candidate_id=None, label=None))

    return items
