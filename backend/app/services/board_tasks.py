"""Kolejka „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0348).

Odznaki „DZ ✓" i „Gotowy do Cpro" są etapami szablonu
(`services/board_stage_badges.py`), więc to, co czeka, wylicza się
z NAJNOWSZEGO wiersza każdej pary (kandydat, opublikowana rekrutacja):

* **Czeka na DZ** — osoba stoi na etapie „Zweryfikowany" (kod ``verified``,
  nie etap-odznaka) w rekrutacji, której szablon MA etap DZ. Zatwierdza admin,
  Delivery Lead albo Head of Recruitment (decyzja Artura: „każdy DL i
  Dominik"). Delivery Lead widzi rekrutacje klientów ze swojego portfela i te,
  w których jest DL-em; Head of Recruitment i admin — wszystkie.
* **Do wysłania do Cpro** (tylko Nordea) — osoba stoi na etapie „Wysłać do
  Cpro". Wysyła JEDNA osoba na całą rekrutację (``jobs.cpro_sender_id``,
  decyzja Artura 23.09.2026); typowanie per kandydat z 0348
  (``candidate_stages.task_assignee_id``) jest zapasem, gdy rekrutacja nie ma
  jeszcze osoby. Nieprzypisane widzą osoby z prawem DZ.
* **Wysłane do Cpro** — u Nordei „CV wysłane" TO JEST wysłanie do Cpro
  (decyzja Artura 22.09.2026); lista mówi, od ilu dni czekamy na Nordeę.
* **Czeka na przegląd DL** (pipeline v4, decyzja Artura 23.09.2026) — u
  klientów INNYCH niż Nordea osoba w kolumnie „Zweryfikowany" (etap
  ``verified`` albo etap DZ) czeka, aż Delivery Lead obejrzy stawkę, CV
  i odpowiedzi ze screeningu i wyśle ją do klienta (ruch na „CV wysłane" ze
  stawką do klienta) albo odrzuci. Kolejka DZ zostaje wyłącznie u Nordei
  (DZ → Cpro bez zmian) — u pozostałych klientów przegląd DL ją zastępuje,
  inaczej ta sama osoba czekałaby w dwóch listach na tę samą decyzję.

Okno: ruch z ostatnich ``WINDOW_DAYS`` dni (przegląd DL:
``DL_REVIEW_WINDOW_DAYS`` — zweryfikowany kandydat bez decyzji DL to praca
do zrobienia dłużej niż odznaka). Import z Traffita zostawia na
opublikowanych rekrutacjach setki osób „zweryfikowanych" rok temu — kolejka
z nimi byłaby listą, której nikt nie przeczyta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services.board_stage_badges import (
    DZ_BADGE_ROLES,
    cpro_enabled_for_client,
    foreign_stage_target,
    is_cpro_stage,
    is_dz_stage,
)

WINDOW_DAYS = 14
DL_REVIEW_WINDOW_DAYS = 30

KIND_DZ = "dz"
KIND_CPRO_TO_SEND = "cpro_to_send"
KIND_CPRO_SENT = "cpro_sent"
KIND_DL_REVIEW = "dl_review"

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
    rejected_id: Optional[int] = None


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
    template_id: Optional[int] = None
    # Przegląd DL: kto i kiedy zweryfikował, stawka z wiersza weryfikacji
    # (migawka oczekiwań kandydata), wiersz z zapisanym arkuszem screeningu
    # i etap „Odrzucony" szablonu — panel nie musi zgadywać żadnego z nich.
    rejected_stage_def_id: Optional[int] = None
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    expected_rate_value: Optional[float] = None
    expected_rate_unit: Optional[str] = None
    expected_rate_currency: Optional[str] = None
    screening_stage_id: Optional[int] = None
    # 0353: osoba ustawiona dla CAŁEJ rekrutacji (`jobs.cpro_sender_id`).
    # `assignee_id` = ona albo, gdy jej brak, typowanie per kandydat z 0348.
    job_sender_id: Optional[int] = None
    job_sender_name: Optional[str] = None

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
            "rejected_stage_def_id": self.rejected_stage_def_id,
            "verified_by_id": self.verified_by_id,
            "verified_by_name": self.verified_by_name,
            "verified_at": self.verified_at,
            "expected_rate_value": self.expected_rate_value,
            "expected_rate_unit": self.expected_rate_unit,
            "expected_rate_currency": self.expected_rate_currency,
            "screening_stage_id": self.screening_stage_id,
            "job_sender_id": self.job_sender_id,
            "job_sender_name": self.job_sender_name,
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
    rejected: list[int] = []
    for d in ordered:
        if d.is_terminal:
            if _terminal_type(d) == "rejected":
                rejected.append(d.id)
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
        rejected_id=rejected[0] if rejected else None,
    )


def _terminal_type(d: PipelineStageDef) -> Optional[str]:
    value = getattr(d, "terminal_type", None)
    if value is None:
        return "rejected" if d.legacy_enum_value == "rejected" else None
    return getattr(value, "value", value)


@dataclass(frozen=True)
class _Catalog:
    stages: dict[int, TemplateStages]
    defs_by_template: dict[int, list[PipelineStageDef]]
    defs: dict[int, PipelineStageDef]

    def effective_def_id(self, template_id: int, stage_def_id: int) -> Optional[int]:
        """Etap szablonu rekrutacji, na którym tablica pokazuje ten wiersz.

        Rekrutacje z Traffita zwykle nie mają własnego szablonu (tablica rysuje
        domyślny), a ruchy zapisują etapy szablonu Traffita — ta sama reguła
        co tablica (`foreign_stage_target`), inaczej kolejka nie widziałaby
        nikogo z tych rekrutacji.
        """

        template_defs = self.defs_by_template.get(template_id, [])
        if any(d.id == stage_def_id for d in template_defs):
            return stage_def_id
        foreign = self.defs.get(stage_def_id)
        if foreign is None:
            return None
        target = foreign_stage_target(
            foreign.name, foreign.legacy_enum_value, template_defs
        )
        return target.id if target is not None else None


async def _catalog(db: AsyncSession) -> _Catalog:
    defs = (await db.scalars(select(PipelineStageDef))).all()
    by_template: dict[int, list[PipelineStageDef]] = {}
    for d in defs:
        by_template.setdefault(d.template_id, []).append(d)
    return _Catalog(
        stages={tid: classify_template(items) for tid, items in by_template.items()},
        defs_by_template=by_template,
        defs={d.id: d for d in defs},
    )


_LATEST_SQL = text(
    """
    WITH latest AS (
        SELECT DISTINCT ON (cs.candidate_id, cs.job_id)
               cs.id, cs.candidate_id, cs.job_id, cs.stage_def_id,
               cs.moved_at, cs.moved_by, cs.task_assignee_id
          FROM candidate_stages cs
          JOIN jobs j ON j.id = cs.job_id
         WHERE j.status = 'published'
           -- Równoważne filtrowi po wyborze najnowszego wiersza: para z ruchem
           -- w oknie ma w oknie także swój NAJNOWSZY wiersz. Bez tego zapytanie
           -- sortowało całą historię etapów przy każdym odczycie pulpitu.
           AND cs.moved_at >= :since
         ORDER BY cs.candidate_id, cs.job_id, cs.moved_at DESC, cs.id DESC
    )
    SELECT l.id, l.candidate_id, l.job_id, l.stage_def_id, l.moved_at,
           l.moved_by, l.task_assignee_id, j.cpro_sender_id,
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
    catalog = await _catalog(db)
    templates = catalog.stages
    targets: set[int] = set()
    for stages in templates.values():
        targets |= stages.verified_ids | stages.cpro_ids | stages.cv_sent_ids
        if stages.dz_id is not None:
            targets.add(stages.dz_id)
    if not targets:
        return BoardTaskSnapshot()
    # Wiersze, które w KTÓRYMKOLWIEK szablonie trafiają na etap kolejki
    # (także przez regułę etapów z innego szablonu).
    relevant = {
        d.id
        for d in catalog.defs.values()
        if any(
            catalog.effective_def_id(tid, d.id) in targets
            for tid in catalog.defs_by_template
        )
    }
    default_template_id = await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    rows = (
        await db.execute(
            _LATEST_SQL,
            {
                "default_template_id": default_template_id,
                "since": now - timedelta(days=max(WINDOW_DAYS, DL_REVIEW_WINDOW_DAYS)),
                "stage_def_ids": sorted(relevant),
            },
        )
    ).all()

    badge_since = now - timedelta(days=WINDOW_DAYS)
    tasks: list[BoardTask] = []
    for r in rows:
        stages = templates.get(r.template_id)
        if stages is None:
            continue
        effective = catalog.effective_def_id(r.template_id, r.stage_def_id)
        if effective is None:
            # Etap bez odpowiednika w szablonie rekrutacji — kubełek „poza
            # szablonem" na tablicy, nie zadanie.
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
            template_id=r.template_id,
        )
        nordea = cpro_enabled_for_client(r.client_id)
        if not nordea:
            in_verified_column = effective in stages.verified_ids or (
                stages.dz_id is not None and effective == stages.dz_id
            )
            if in_verified_column:
                tasks.append(
                    BoardTask(
                        kind=KIND_DL_REVIEW,
                        target_stage_def_id=stages.cv_sent_id,
                        rejected_stage_def_id=stages.rejected_id,
                        **base,
                    )
                )
            continue
        if r.moved_at < badge_since:
            continue
        if effective in stages.verified_ids and stages.dz_id is not None:
            tasks.append(
                BoardTask(kind=KIND_DZ, target_stage_def_id=stages.dz_id, **base)
            )
        elif effective in stages.cpro_ids and nordea:
            tasks.append(
                BoardTask(
                    kind=KIND_CPRO_TO_SEND,
                    target_stage_def_id=stages.cv_sent_id,
                    assignee_id=r.cpro_sender_id or r.task_assignee_id,
                    job_sender_id=r.cpro_sender_id,
                    **base,
                )
            )
        elif effective in stages.cv_sent_ids and nordea:
            tasks.append(
                BoardTask(kind=KIND_CPRO_SENT, target_stage_def_id=None, **base)
            )

    await _attach_dl_review_details(db, catalog, tasks)
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
    user_ids = {t.assignee_id for t in tasks if t.assignee_id is not None} | {
        t.verified_by_id for t in tasks if t.verified_by_id is not None
    }
    user_ids |= {t.job_sender_id for t in tasks if t.job_sender_id is not None}
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
        if t.job_sender_id is not None:
            t.job_sender_name = names.get(t.job_sender_id)
        if t.verified_by_id is not None:
            t.verified_by_name = names.get(t.verified_by_id)


async def _attach_dl_review_details(
    db: AsyncSession, catalog: _Catalog, tasks: list[BoardTask]
) -> None:
    """Dla przeglądu DL: wiersz weryfikacji (kto, kiedy, stawka) i screening.

    Najnowszy wiersz pary bywa etapem DZ (odznaka w kolumnie „Zweryfikowany"),
    więc weryfikację szukamy wstecz w historii pary — ostatni wiersz, który na
    tablicy tej rekrutacji stoi na etapie ``verified``. Arkusz screeningu leży
    na wierszu, na którym go wypełniono (zwykle „Screening").
    """

    review = [t for t in tasks if t.kind == KIND_DL_REVIEW]
    if not review:
        return
    pairs = sorted({(t.candidate_id, t.job_id) for t in review})
    rows = (
        await db.execute(
            select(
                CandidateStage.id,
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStage.stage_def_id,
                CandidateStage.moved_at,
                CandidateStage.moved_by,
                CandidateStage.expected_rate_value,
                CandidateStage.expected_rate_unit,
                CandidateStage.expected_rate_currency,
                CandidateStage.screening_answers.is_not(None).label("has_screening"),
            )
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(pairs)
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        )
    ).all()
    history: dict[tuple[int, int], list] = {}
    for row in rows:
        history.setdefault((row.candidate_id, row.job_id), []).append(row)
    for t in review:
        stages = catalog.stages.get(t.template_id) if t.template_id else None
        for row in history.get((t.candidate_id, t.job_id), []):
            if (
                t.verified_at is None
                and stages is not None
                and row.stage_def_id is not None
                and catalog.effective_def_id(t.template_id, row.stage_def_id)
                in stages.verified_ids
            ):
                t.verified_by_id = row.moved_by
                t.verified_at = row.moved_at
                t.expected_rate_value = (
                    float(row.expected_rate_value)
                    if row.expected_rate_value is not None
                    else None
                )
                t.expected_rate_unit = row.expected_rate_unit
                t.expected_rate_currency = row.expected_rate_currency
            if t.screening_stage_id is None and row.has_screening:
                t.screening_stage_id = row.id
            if t.verified_at is not None and t.screening_stage_id is not None:
                break


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

    * DZ i przegląd DL: role z prawem DZ; Delivery Lead tylko w swoim
      portfelu.
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
        KIND_DL_REVIEW: [],
    }
    for t in snapshot.tasks:
        scoped = sees_all or _in_portfolio(t, user, portfolio)
        if t.kind in (KIND_DZ, KIND_DL_REVIEW):
            if can_dz and scoped:
                out[t.kind].append(t)
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
    dl_review: int = 0

    @property
    def total(self) -> int:
        return self.dz + self.cpro_mine + self.cpro_unassigned + self.dl_review


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
        counts.setdefault(
            uid, {"dz": 0, "cpro_mine": 0, "cpro_unassigned": 0, "dl_review": 0}
        )[key] += 1

    for t in snapshot.tasks:
        if t.kind == KIND_CPRO_TO_SEND and t.assignee_id is not None:
            bump(t.assignee_id, "cpro_mine")
            continue
        if t.kind not in (KIND_DZ, KIND_CPRO_TO_SEND, KIND_DL_REVIEW):
            continue
        key = {
            KIND_DZ: "dz",
            KIND_CPRO_TO_SEND: "cpro_unassigned",
            KIND_DL_REVIEW: "dl_review",
        }[t.kind]
        for u in users:
            if _sees_all(u) or _in_portfolio(t, u, portfolios.get(u.id, frozenset())):
                bump(u.id, key)
    return {uid: DigestLine(**c) for uid, c in counts.items()}


def digest_message(line: DigestLine) -> str:
    parts: list[str] = []
    if line.dl_review:
        parts.append(
            f"{_people(line.dl_review)} {_waits(line.dl_review)} na Twój przegląd"
        )
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
    "DL_REVIEW_WINDOW_DAYS",
    "KIND_CPRO_SENT",
    "KIND_CPRO_TO_SEND",
    "KIND_DL_REVIEW",
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
    db: AsyncSession, *, job_id: int, assignee: User, actor: User
) -> bool:
    """Wytypowana osoba musi móc przesunąć kartę na „Wysłane do Cpro".

    Rekrutacje z Traffita zwykle nie mają w NEXUSIE rekrutera ani zespołu,
    więc rekruter spoza zespołu dostałby 403 przy własnym zadaniu. Dopisać go
    do zespołu może jednak tylko ktoś, kto i tak zmienia zespoły (admin,
    Delivery Lead, Head of Recruitment — role DZ); zwykły członek zespołu nie
    może tą drogą wprowadzać do rekrutacji innych osób (lustro bramki
    `POST /api/jobs/{id}/collaborators`). Zwraca, czy dopisano.
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
    if not actor.has_any_role(*DZ_BADGE_ROLES):
        raise HTTPException(
            status_code=422,
            detail=(
                "Ta osoba nie jest w zespole rekrutacji. Wybierz kogoś z zespołu "
                "albo poproś Delivery Leada o dodanie jej do rekrutacji."
            ),
        )
    stmt = pg_insert(JobCollaborator).values(
        job_id=job_id, user_id=assignee.id, added_by=actor.id
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_job_collaborators_job_user",
            set_={"removed_from_auto_cc": False, "removed_at": None},
        )
    )
    return True


async def notify_cpro_sender(
    db: AsyncSession,
    *,
    job_id: int,
    job_title: str,
    waiting: int,
    sender_id: int,
    actor: User,
) -> None:
    """Dzwonek dla osoby, która od teraz wysyła do Cpro kandydatów rekrutacji.

    Nie dla siebie samego. Dedup dobowy `ix_notif_dedup_daily` jest po
    (osoba, typ, rekrutacja): ponowne ustawienie tej samej osoby tego samego
    dnia nie daje drugiego dzwonka — zmianę widać w historii rekrutacji.
    """

    if sender_id == actor.id:
        return
    from app.models.notification import NotificationType  # noqa: PLC0415
    from app.services.notification_triggers import emit  # noqa: PLC0415

    waits = f" Teraz czeka: {waiting}." if waiting else ""
    await emit(
        db,
        user_id=sender_id,
        title=f"Wysyłasz do Cpro: {job_title}",
        message=(
            f"{actor.name or 'Ktoś z zespołu'} ustawił(a) Cię jako osobę, która "
            f"wysyła do Cpro kandydatów tej rekrutacji.{waits}"
        ),
        ntype=NotificationType.cpro_send_assigned,
        related_entity_type="job",
        related_entity_id=job_id,
        link=f"/jobs/{job_id}",
    )
