"""Kolejka „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0346).

Odznaki „DZ ✓" i „Gotowy do Cpro" są etapami szablonu
(`services/board_stage_badges.py`), więc to, co czeka, wylicza się
z NAJNOWSZEGO wiersza każdej pary (kandydat, opublikowana rekrutacja):

* **Czeka na DZ** — osoba stoi na etapie „Zweryfikowany" (kod ``verified``,
  nie etap-odznaka) w rekrutacji, której szablon MA etap DZ. Zatwierdza admin,
  Delivery Lead albo Head of Recruitment (decyzja Artura: „każdy DL i
  Dominik"). Delivery Lead widzi rekrutacje klientów ze swojego portfela i te,
  w których jest DL-em; Head of Recruitment i admin — wszystkie.
* **Do wysłania do Cpro** (tylko Nordea) — osoba stoi na etapie „Wysłać do
  Cpro". Wysyła osoba wytypowana przy oznaczeniu gotowości
  (``candidate_stages.task_assignee_id``); wiersze z importu Traffita są
  nieprzypisane i widzą je osoby z prawem DZ.
* **Wysłane do Cpro** — u Nordei „CV wysłane" TO JEST wysłanie do Cpro
  (decyzja Artura 22.09.2026); lista mówi, od ilu dni czekamy na Nordeę.

Okno: ruch z ostatnich ``WINDOW_DAYS`` dni. Import z Traffita zostawia na
opublikowanych rekrutacjach setki osób „zweryfikowanych" rok temu — kolejka
z nimi byłaby listą, której nikt nie przeczyta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services.board_stage_badges import (
    DZ_BADGE_ROLES,
    cpro_enabled_for_client,
    is_cpro_stage,
    is_dz_stage,
)

WINDOW_DAYS = 14

KIND_DZ = "dz"
KIND_CPRO_TO_SEND = "cpro_to_send"
KIND_CPRO_SENT = "cpro_sent"

# Role, które dostają kolejkę DZ w porannym skrócie. Admin może zatwierdzać,
# ale skrót dostaje tylko wtedy, gdy ma też jedną z tych ról — konto
# administracyjne nie jest osobą, która przegląda kandydatów.
_DZ_DIGEST_ROLES: tuple[UserRole, ...] = (
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


@dataclass(frozen=True)
class TemplateStages:
    """Etapy szablonu, między którymi chodzi kolejka."""

    verified_ids: frozenset[int]
    dz_id: Optional[int]
    cpro_ids: frozenset[int]
    cpro_id: Optional[int]
    cv_sent_ids: frozenset[int]
    cv_sent_id: Optional[int]


@dataclass
class BoardTask:
    kind: str
    stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: Optional[int]
    client_name: Optional[str]
    since: datetime
    process_state_version: int
    target_stage_def_id: Optional[int]
    assignee_id: Optional[int] = None
    assignee_name: Optional[str] = None
    moved_by: Optional[int] = None
    delivery_lead_id: Optional[int] = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "stage_id": self.stage_id,
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "client_id": self.client_id,
            "client_name": self.client_name,
            "since": self.since,
            "process_state_version": self.process_state_version,
            "target_stage_def_id": self.target_stage_def_id,
            "assignee_id": self.assignee_id,
            "assignee_name": self.assignee_name,
        }


@dataclass
class BoardTaskSnapshot:
    """Wszystkie otwarte zadania kolejki — liczone raz, filtrowane per osoba."""

    tasks: list[BoardTask] = field(default_factory=list)


def classify_template(defs: Iterable[PipelineStageDef]) -> TemplateStages:
    """Rozpoznaje etapy kolejki po nazwie (odznaki) i kodzie (reszta).

    Etap-odznaka nigdy nie jest „gospodarzem": „Przepuszczony przez DZ" ma
    w szablonie domyślnym kod ``interview``, a „NORDEA: Wysłać do Cpro"
    w szablonie z Traffita kod ``screening``.
    """

    ordered = sorted(defs, key=lambda d: (d.order, d.id))
    verified: list[int] = []
    dz: list[int] = []
    cpro: list[int] = []
    cv_sent: list[int] = []
    for d in ordered:
        if d.is_terminal:
            continue
        if is_dz_stage(d.name):
            dz.append(d.id)
        elif is_cpro_stage(d.name):
            cpro.append(d.id)
        elif d.legacy_enum_value == "verified":
            verified.append(d.id)
        elif d.legacy_enum_value == "cv_sent":
            cv_sent.append(d.id)
    return TemplateStages(
        verified_ids=frozenset(verified),
        dz_id=dz[0] if dz else None,
        cpro_ids=frozenset(cpro),
        cpro_id=cpro[0] if cpro else None,
        cv_sent_ids=frozenset(cv_sent),
        cv_sent_id=cv_sent[0] if cv_sent else None,
    )


async def _template_stages(db: AsyncSession) -> dict[int, TemplateStages]:
    defs = (await db.scalars(select(PipelineStageDef))).all()
    by_template: dict[int, list[PipelineStageDef]] = {}
    for d in defs:
        by_template.setdefault(d.template_id, []).append(d)
    return {tid: classify_template(items) for tid, items in by_template.items()}


_LATEST_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.id, cs.candidate_id, cs.job_id, cs.stage_def_id,
               cs.moved_at, cs.moved_by, cs.task_assignee_id
          FROM candidate_stages cs
          JOIN jobs j ON j.id = cs.job_id
         WHERE j.status = 'published'
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT l.id, l.candidate_id, l.job_id, l.stage_def_id, l.moved_at,
           l.moved_by, l.task_assignee_id,
           COALESCE(j.pipeline_template_id, :default_template_id) AS template_id,
           j.title, j.client_id, j.delivery_lead_id, cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname
      FROM latest l
      JOIN jobs j ON j.id = l.job_id
      JOIN candidates c ON c.id = l.candidate_id
      LEFT JOIN clients cl ON cl.id = j.client_id
     WHERE l.moved_at >= :since
       AND l.stage_def_id = ANY(:stage_def_ids)
    """
)


async def load_snapshot(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> BoardTaskSnapshot:
    """Jedno przejście po najnowszych wierszach opublikowanych rekrutacji."""

    now = now or datetime.now(timezone.utc)
    templates = await _template_stages(db)
    relevant: set[int] = set()
    for stages in templates.values():
        relevant |= stages.verified_ids | stages.cpro_ids | stages.cv_sent_ids
    if not relevant:
        return BoardTaskSnapshot()
    default_template_id = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    rows = (
        await db.execute(
            _LATEST_SQL,
            {
                "default_template_id": default_template_id,
                "since": now - timedelta(days=WINDOW_DAYS),
                "stage_def_ids": sorted(relevant),
            },
        )
    ).all()

    tasks: list[BoardTask] = []
    for r in rows:
        stages = templates.get(r.template_id)
        if stages is None:
            # Wiersz z etapem spoza szablonu rekrutacji (stary import) — ruch
            # na etap docelowy i tak by się nie udał.
            continue
        name = " ".join(p for p in (r.cname, r.clastname) if p) or "Kandydat"
        base = dict(
            stage_id=r.id,
            candidate_id=r.candidate_id,
            candidate_name=name,
            job_id=r.job_id,
            job_title=r.title,
            client_id=r.client_id,
            client_name=r.client_name,
            since=r.moved_at,
            process_state_version=0,
            moved_by=r.moved_by,
            delivery_lead_id=r.delivery_lead_id,
        )
        nordea = cpro_enabled_for_client(r.client_id)
        if r.stage_def_id in stages.verified_ids and stages.dz_id is not None:
            tasks.append(
                BoardTask(kind=KIND_DZ, target_stage_def_id=stages.dz_id, **base)
            )
        elif r.stage_def_id in stages.cpro_ids and nordea:
            tasks.append(
                BoardTask(
                    kind=KIND_CPRO_TO_SEND,
                    target_stage_def_id=stages.cv_sent_id,
                    assignee_id=r.task_assignee_id,
                    **base,
                )
            )
        elif r.stage_def_id in stages.cv_sent_ids and nordea:
            tasks.append(
                BoardTask(kind=KIND_CPRO_SENT, target_stage_def_id=None, **base)
            )

    await _attach_versions_and_names(db, tasks)
    tasks.sort(key=lambda t: t.since)
    return BoardTaskSnapshot(tasks=tasks)


async def _attach_versions_and_names(db: AsyncSession, tasks: list[BoardTask]) -> None:
    if not tasks:
        return
    pairs = {(t.candidate_id, t.job_id) for t in tasks}
    job_ids = sorted({j for _, j in pairs})
    cand_ids = sorted({c for c, _ in pairs})
    rows = await db.execute(
        select(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.job_id,
            RecruitmentProcess.state_version,
        )
        .where(
            RecruitmentProcess.job_id.in_(job_ids),
            RecruitmentProcess.candidate_id.in_(cand_ids),
        )
        .order_by(
            RecruitmentProcess.candidate_id,
            RecruitmentProcess.job_id,
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .distinct(RecruitmentProcess.candidate_id, RecruitmentProcess.job_id)
    )
    versions = {(c, j): int(v or 0) for c, j, v in rows.all()}
    user_ids = {t.assignee_id for t in tasks if t.assignee_id is not None}
    names: dict[int, str] = {}
    if user_ids:
        for uid, uname, email in (
            await db.execute(
                select(User.id, User.name, User.email).where(User.id.in_(user_ids))
            )
        ).all():
            names[uid] = uname or email
    for t in tasks:
        t.process_state_version = versions.get((t.candidate_id, t.job_id), 0)
        if t.assignee_id is not None:
            t.assignee_name = names.get(t.assignee_id)


async def dl_portfolio_client_ids(db: AsyncSession, user_id: int) -> frozenset[int]:
    return frozenset(
        (
            await db.scalars(
                select(DeliveryLeadClientAssignment.client_id).where(
                    DeliveryLeadClientAssignment.delivery_lead_user_id == user_id
                )
            )
        ).all()
    )


def _sees_all(user: User) -> bool:
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


def _in_portfolio(task: BoardTask, user: User, portfolio: frozenset[int]) -> bool:
    return task.delivery_lead_id == user.id or (
        task.client_id is not None and task.client_id in portfolio
    )


def tasks_for_user(
    snapshot: BoardTaskSnapshot, user: User, *, portfolio: frozenset[int]
) -> dict[str, list[BoardTask]]:
    """Co z migawki należy do tej osoby.

    * DZ: role z prawem DZ; Delivery Lead tylko w swoim portfelu.
    * Do wysłania do Cpro: wytypowany zawsze; role DZ — także nieprzypisane
      i cudze (ktoś musi je przydzielić albo zastąpić nieobecnego).
    * Wysłane: kto przesunął na „Wysłane do Cpro", albo role DZ.
    """

    can_dz = user.has_any_role(*DZ_BADGE_ROLES)
    sees_all = _sees_all(user)
    out: dict[str, list[BoardTask]] = {
        KIND_DZ: [],
        KIND_CPRO_TO_SEND: [],
        KIND_CPRO_SENT: [],
    }
    for t in snapshot.tasks:
        scoped = sees_all or _in_portfolio(t, user, portfolio)
        if t.kind == KIND_DZ:
            if can_dz and scoped:
                out[KIND_DZ].append(t)
        elif t.kind == KIND_CPRO_TO_SEND:
            if t.assignee_id == user.id or (can_dz and scoped):
                out[KIND_CPRO_TO_SEND].append(t)
        elif t.kind == KIND_CPRO_SENT:
            if t.moved_by == user.id or (can_dz and scoped):
                out[KIND_CPRO_SENT].append(t)
    # Moje zadania Cpro na górze, potem nieprzypisane, potem cudze.
    out[KIND_CPRO_TO_SEND].sort(
        key=lambda t: (
            0 if t.assignee_id == user.id else 1 if t.assignee_id is None else 2,
            t.since,
        )
    )
    return out


@dataclass(frozen=True)
class DigestLine:
    dz: int = 0
    cpro_mine: int = 0
    cpro_unassigned: int = 0

    @property
    def total(self) -> int:
        return self.dz + self.cpro_mine + self.cpro_unassigned


async def digest_counts(
    db: AsyncSession, snapshot: BoardTaskSnapshot
) -> dict[int, DigestLine]:
    """Poranny skrót: kto ma co do zrobienia (tylko to, co wymaga ruchu).

    Wysłane do Cpro nie są zadaniem — czekamy na Nordeę — więc skrót ich nie
    liczy. Nieprzypisane zadania Cpro trafiają do Head of Recruitment i do
    Delivery Leadów, w których portfelu jest klient.
    """

    if not snapshot.tasks:
        return {}
    users = (
        await db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role.in_(_DZ_DIGEST_ROLES),
                    *(User.roles.contains([r.value]) for r in _DZ_DIGEST_ROLES),
                ),
            )
        )
    ).all()
    portfolios: dict[int, frozenset[int]] = {}
    for u in users:
        if u.has_role(UserRole.delivery_lead) and not _sees_all(u):
            portfolios[u.id] = await dl_portfolio_client_ids(db, u.id)

    counts: dict[int, dict[str, int]] = {}

    def bump(uid: int, key: str) -> None:
        counts.setdefault(uid, {"dz": 0, "cpro_mine": 0, "cpro_unassigned": 0})[
            key
        ] += 1

    for t in snapshot.tasks:
        if t.kind == KIND_CPRO_TO_SEND and t.assignee_id is not None:
            bump(t.assignee_id, "cpro_mine")
            continue
        if t.kind not in (KIND_DZ, KIND_CPRO_TO_SEND):
            continue
        key = "dz" if t.kind == KIND_DZ else "cpro_unassigned"
        for u in users:
            if _sees_all(u) or _in_portfolio(t, u, portfolios.get(u.id, frozenset())):
                bump(u.id, key)
    return {uid: DigestLine(**c) for uid, c in counts.items()}


def digest_message(line: DigestLine) -> str:
    parts: list[str] = []
    if line.dz:
        parts.append(f"{_people(line.dz)} {_waits(line.dz)} na DZ")
    if line.cpro_mine:
        parts.append(f"{line.cpro_mine} do wysłania przez Ciebie do Cpro")
    if line.cpro_unassigned:
        parts.append(f"{line.cpro_unassigned} do Cpro bez wytypowanej osoby")
    return " · ".join(parts)


def _few(n: int) -> bool:
    return 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14


def _waits(n: int) -> str:
    return "czekają" if _few(n) else "czeka"


def _people(n: int) -> str:
    if n == 1:
        return "1 osoba"
    if _few(n):
        return f"{n} osoby"
    return f"{n} osób"


__all__ = [
    "KIND_CPRO_SENT",
    "KIND_CPRO_TO_SEND",
    "KIND_DZ",
    "WINDOW_DAYS",
    "BoardTask",
    "BoardTaskSnapshot",
    "DigestLine",
    "classify_template",
    "digest_counts",
    "digest_message",
    "dl_portfolio_client_ids",
    "load_snapshot",
    "tasks_for_user",
]


# ── Wytypowanie osoby, która wysyła do Cpro ───────────────────────────────


_ASSIGNEE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.talent_community_manager,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)


async def load_assignee(db: AsyncSession, assignee_id: int) -> User:
    """Aktywne konto operacyjne z dostępem do kandydatów — inaczej 422."""

    from fastapi import HTTPException  # noqa: PLC0415

    from app.api.candidate_access import (  # noqa: PLC0415
        user_can_access_candidate_domain,
    )

    user = await db.get(User, assignee_id)
    if (
        user is None
        or not user.is_active
        or not user.has_any_role(*_ASSIGNEE_ROLES)
        or not user_can_access_candidate_domain(user)
    ):
        raise HTTPException(
            status_code=422,
            detail="Wybierz aktywną osobę z zespołu rekrutacji, która wyśle kandydata do Cpro.",
        )
    return user


async def ensure_assignee_can_move(
    db: AsyncSession, *, job_id: int, assignee: User, added_by: int
) -> bool:
    """Wytypowana osoba musi móc przesunąć kartę na „Wysłane do Cpro".

    Rekrutacje z Traffita zwykle nie mają w NEXUSIE rekrutera ani zespołu,
    więc rekruter spoza zespołu dostałby 403 przy własnym zadaniu. Typowanie
    dopisuje go do zespołu rekrutacji (jawny ślad: ``added_by``). Zwraca, czy
    dopisano.
    """

    from fastapi import HTTPException  # noqa: PLC0415
    from sqlalchemy.dialects.postgresql import insert as pg_insert  # noqa: PLC0415

    from app.api.recruitment_access import ensure_job_membership  # noqa: PLC0415
    from app.models.job_collaborator import JobCollaborator  # noqa: PLC0415

    try:
        await ensure_job_membership(db, assignee, job_id)
        return False
    except HTTPException:
        pass
    stmt = pg_insert(JobCollaborator).values(
        job_id=job_id, user_id=assignee.id, added_by=added_by
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_job_collaborators_job_user",
            set_={"removed_from_auto_cc": False, "removed_at": None},
        )
    )
    return True


async def notify_cpro_assignment(
    db: AsyncSession,
    *,
    stage_id: int,
    candidate_name: str,
    job_id: int,
    job_title: str,
    candidate_id: int,
    assignee_id: int,
    actor: User,
) -> None:
    """Dzwonek dla wytypowanej osoby (nie dla siebie samego)."""

    if assignee_id == actor.id:
        return
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    await emit(
        db,
        user_id=assignee_id,
        title=f"Wyślij do Cpro: {candidate_name}",
        message=(
            f"{actor.name or 'Ktoś z zespołu'} wytypował(a) Cię do wysłania "
            f"kandydata do Cpro — {job_title}."
        ),
        ntype=NotificationType.cpro_send_assigned,
        related_entity_type="candidate_stage",
        related_entity_id=stage_id,
        link=f"/jobs/{job_id}?candidate={candidate_id}",
    )
