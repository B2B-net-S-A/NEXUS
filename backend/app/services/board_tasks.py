"""Kolejka „Czeka na Ciebie" — praca na Tablicach, której nikt nie widzi (0348).

Kolumny Tablicy wynikają z etapów szablonu (`services/board_stage_badges.py`),
więc to, co czeka, wylicza się z NAJNOWSZEGO wiersza każdej pary (kandydat,
opublikowana rekrutacja). Od 24.09.2026 (Rekrutacja v5) kolejki DZ nie ma —
przed wysłaniem CV liczy się QC CV (`services/cv_qc.py`), a nie zatwierdzenie
Delivery Leada:

* **Do wysłania do Cpro** (tylko Nordea) — osoba stoi na etapie „Wysłać do
  Cpro" (kolumna QC CV, znacznik „w kolejce Cpro"). Wysyła JEDNA osoba na
  całą firmę (`services/cpro_sender.py`, decyzja Artura 23.09.2026). Osoba
  per rekrutacja (``jobs.cpro_sender_id``, 0353) i per kandydat
  (``candidate_stages.task_assignee_id``, 0348) są zapasem wyłącznie wtedy,
  gdy nikt nie jest ustawiony na firmę.
* **Wysłane do Cpro** — u Nordei „CV wysłane" TO JEST wysłanie do Cpro
  (decyzja Artura 22.09.2026); lista mówi, od ilu dni czekamy na Nordeę.
* **Czeka na przegląd DL** — u klientów INNYCH niż Nordea osoba w kolumnie
  „QC CV" (etap QC, nie etap Cpro) czeka, aż Delivery Lead obejrzy stawkę,
  CV i wynik QC i wyśle ją do klienta (ruch na „CV wysłane" ze stawką do
  klienta) albo odrzuci. Osoby w „Zweryfikowanym" nie są już w przeglądzie —
  ich CV nie przeszło jeszcze przez QC, więc DL nie ma czego oglądać.

Okno: ruch z ostatnich ``WINDOW_DAYS`` dni (wysłane do Cpro), a praca do
zrobienia (przegląd DL, do wysłania do Cpro) — ``DL_REVIEW_WINDOW_DAYS``.
Import z Traffita zostawia na opublikowanych rekrutacjach setki osób sprzed
roku — kolejka z nimi byłaby listą, której nikt nie przeczyta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Iterable, Optional

from sqlalchemy import or_, select, text, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.pipeline_template import PipelineStageDef, PipelineTemplate
from app.models.recruitment_pipeline import CandidateStage
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services import cpro_sender
from app.services.board_stage_badges import (
    cpro_enabled_for_client,
    foreign_stage_target,
    is_cpro_stage,
    is_qc_stage,
)


if TYPE_CHECKING:
    from app.services.candidate_followups import DigestCounts

WINDOW_DAYS = 14
DL_REVIEW_WINDOW_DAYS = 30

KIND_CPRO_TO_SEND = "cpro_to_send"
KIND_CPRO_SENT = "cpro_sent"
KIND_DL_REVIEW = "dl_review"

# Kto widzi przegląd DL: wyłącznie Delivery Lead rekrutacji — admin i Head of
# Recruitment nie (rekrutacja bez DL-a dostaje głównego DL-a klienta,
# `job_delivery_lead_fill`). Kolejkę Cpro widzi tylko osoba od Cpro; admin
# i HoR — tylko wtedy, gdy nikt nie jest ustawiony (decyzja Artura
# 24.09.2026). Wysyłkę do klienta i tak rozstrzyga serwer przy ruchu.
REVIEW_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)

# Role, które dostają przegląd DL w porannym skrócie. Admin przegląda, ale
# skrót dostaje tylko wtedy, gdy ma też jedną z tych ról — konto
# administracyjne nie jest osobą, która przegląda kandydatów.
_REVIEW_DIGEST_ROLES: tuple[UserRole, ...] = (
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


@dataclass(frozen=True)
class TemplateStages:
    """Etapy szablonu, między którymi chodzi kolejka."""

    verified_ids: frozenset[int]
    qc_ids: frozenset[int]
    qc_id: Optional[int]
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
    # 0353: osoba ustawiona dla CAŁEJ rekrutacji (`jobs.cpro_sender_id`) —
    # od 24.09.2026 tylko zapas, gdy nikt nie wysyła do Cpro na firmę.
    job_sender_id: Optional[int] = None
    job_sender_name: Optional[str] = None
    # Etap QC CV szablonu rekrutacji — „Zwróć do rekrutera" z kolejki Cpro.
    return_stage_def_id: Optional[int] = None
    # Wynik QC CV pary (`cv_qc.pair_statuses`): passed|failed|overridden|unchecked.
    qc_status: Optional[str] = None
    qc_blocking_failed: int = 0
    # 0379: ``job_title`` = nazwa od klienta (tekst kopiowany do Cpro);
    # ekrany wewnętrzne pokazują tytuł dla rekrutera, gdy jest.
    job_working_title: Optional[str] = None
    client_reference: Optional[str] = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "stage_id": self.stage_id,
            "candidate_id": self.candidate_id,
            "candidate_name": self.candidate_name,
            "job_id": self.job_id,
            "job_title": self.job_title,
            "job_working_title": self.job_working_title,
            "client_reference": self.client_reference,
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
            "return_stage_def_id": self.return_stage_def_id,
            "qc_status": self.qc_status,
            "qc_blocking_failed": self.qc_blocking_failed,
        }


@dataclass
class BoardTaskSnapshot:
    """Wszystkie otwarte zadania kolejki — liczone raz, filtrowane per osoba."""

    tasks: list[BoardTask] = field(default_factory=list)
    # Osoba od Cpro na firmę obowiązująca w chwili odczytu (po zastępstwie).
    firm_sender_id: Optional[int] = None


def classify_template(defs: Iterable[PipelineStageDef]) -> TemplateStages:
    """Rozpoznaje etapy kolejki po nazwie (QC, Cpro) i kodzie (reszta).

    Etap rozpoznawany po nazwie nigdy nie jest mylony z kodem: „QC CV"
    (dawniej „Przepuszczony przez DZ") ma w szablonie domyślnym kod
    ``interview``, a „NORDEA: Wysłać do Cpro" w szablonie z Traffita kod
    ``screening``.
    """

    ordered = sorted(defs, key=lambda d: (d.order, d.id))
    verified: list[int] = []
    qc: list[int] = []
    cpro: list[int] = []
    cv_sent: list[int] = []
    rejected: list[int] = []
    for d in ordered:
        if d.is_terminal:
            if _terminal_type(d) == "rejected":
                rejected.append(d.id)
            continue
        if is_qc_stage(d.name):
            qc.append(d.id)
        elif is_cpro_stage(d.name):
            cpro.append(d.id)
        elif d.legacy_enum_value == "verified":
            verified.append(d.id)
        elif d.legacy_enum_value == "cv_sent":
            cv_sent.append(d.id)
    return TemplateStages(
        verified_ids=frozenset(verified),
        qc_ids=frozenset(qc),
        qc_id=qc[0] if qc else None,
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
           j.title, j.working_title, j.client_reference, j.client_id,
           -- Nieaktywny DL rekrutacji = jak brak DL-a: przegląd idzie do
           -- portfela klienta, zamiast do konta, którego nikt nie czyta.
           CASE WHEN dl.is_active THEN j.delivery_lead_id END AS delivery_lead_id,
           cl.name AS client_name,
           c.name AS cname, c.lastname AS clastname
      FROM latest l
      JOIN jobs j ON j.id = l.job_id
      JOIN candidates c ON c.id = l.candidate_id
      LEFT JOIN clients cl ON cl.id = j.client_id
      LEFT JOIN users dl ON dl.id = j.delivery_lead_id
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
        targets |= stages.qc_ids | stages.cpro_ids | stages.cv_sent_ids
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

    sent_since = now - timedelta(days=WINDOW_DAYS)
    # Jedna osoba na firmę; stare typowania są zapasem, gdy nikogo nie ma.
    firm_sender_id = (await cpro_sender.effective_sender(db, now)).user_id
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
            job_working_title=r.working_title,
            client_reference=r.client_reference,
            client_id=r.client_id,
            client_name=r.client_name,
            since=r.moved_at,
            process_state_version=0,
            moved_by=r.moved_by,
            delivery_lead_id=r.delivery_lead_id,
            template_id=r.template_id,
        )
        nordea = cpro_enabled_for_client(r.client_id)
        in_qc = effective in stages.qc_ids
        if not nordea:
            if in_qc:
                tasks.append(
                    BoardTask(
                        kind=KIND_DL_REVIEW,
                        target_stage_def_id=stages.cv_sent_id,
                        rejected_stage_def_id=stages.rejected_id,
                        **base,
                    )
                )
            continue
        if effective in stages.cpro_ids:
            tasks.append(
                BoardTask(
                    kind=KIND_CPRO_TO_SEND,
                    target_stage_def_id=stages.cv_sent_id,
                    return_stage_def_id=stages.qc_id,
                    assignee_id=(
                        firm_sender_id or r.cpro_sender_id or r.task_assignee_id
                    ),
                    job_sender_id=r.cpro_sender_id,
                    **base,
                )
            )
        elif effective in stages.cv_sent_ids and r.moved_at >= sent_since:
            tasks.append(
                BoardTask(
                    kind=KIND_CPRO_SENT,
                    target_stage_def_id=None,
                    assignee_id=firm_sender_id or r.cpro_sender_id,
                    **base,
                )
            )

    await _attach_dl_review_details(db, catalog, tasks)
    await _attach_qc_statuses(db, tasks)
    await _attach_versions_and_names(db, tasks)
    tasks.sort(key=lambda t: t.since)
    return BoardTaskSnapshot(tasks=tasks, firm_sender_id=firm_sender_id)


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


async def _attach_qc_statuses(db: AsyncSession, tasks: list[BoardTask]) -> None:
    wanted = [t for t in tasks if t.kind in (KIND_DL_REVIEW, KIND_CPRO_TO_SEND)]
    if not wanted:
        return
    from app.services.move_requirements import qc_statuses  # noqa: PLC0415

    statuses = await qc_statuses(db, ((t.candidate_id, t.job_id) for t in wanted))
    for t in wanted:
        status = statuses.get((t.candidate_id, t.job_id)) or {}
        t.qc_status = status.get("status") or "unchecked"
        t.qc_blocking_failed = int(status.get("blocking_failed") or 0)


async def _attach_dl_review_details(
    db: AsyncSession, catalog: _Catalog, tasks: list[BoardTask]
) -> None:
    """Dla przeglądu DL: wiersz weryfikacji (kto, kiedy, stawka) i screening.

    Najnowszy wiersz pary to etap QC CV, więc weryfikację szukamy wstecz
    w historii pary — ostatni wiersz, który na
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


def _sees_dl_review(task: BoardTask, user: User, portfolio: frozenset[int]) -> bool:
    """Przegląd DL należy wyłącznie do Delivery Leada rekrutacji.

    Delivery Lead wpisany w rekrutacji (``jobs.delivery_lead_id``) wygrywa;
    bez niego (zanim `job_delivery_lead_fill` uzupełni pole) — Delivery Lead
    z portfelem klienta. Admin i Head of Recruitment go nie widzą (decyzja
    Artura 24.09.2026), chyba że sami mają rolę Delivery Leada.
    """

    if not user.has_role(UserRole.delivery_lead):
        return False
    if task.delivery_lead_id is not None:
        return task.delivery_lead_id == user.id
    return task.client_id is not None and task.client_id in portfolio


def _sees_cpro(task: BoardTask, user: User) -> bool:
    """Kolejka Cpro jest wyłącznie osoby od Cpro.

    Gdy nikt nie jest ustawiony, zadania do wrzucenia widzi admin i Head of
    Recruitment — żeby ktoś mógł ustawić osobę (jedyne miejsce to ten panel).
    """

    if task.assignee_id is not None:
        return task.assignee_id == user.id
    return task.kind == KIND_CPRO_TO_SEND and _sees_all(user)


def tasks_for_user(
    snapshot: BoardTaskSnapshot, user: User, *, portfolio: frozenset[int]
) -> dict[str, list[BoardTask]]:
    """Co z migawki należy do tej osoby (decyzja Artura 24.09.2026).

    * Przegląd DL: wyłącznie Delivery Lead — rekrutacje przypięte do niego
      (w rekrutacji albo przez portfel klienta).
    * Do wrzucenia i wysłane do Cpro: tylko osoba od Cpro; do wrzucenia —
      także admin i HoR, gdy nikt nie jest ustawiony.
    """

    out: dict[str, list[BoardTask]] = {
        KIND_CPRO_TO_SEND: [],
        KIND_CPRO_SENT: [],
        KIND_DL_REVIEW: [],
    }
    for t in snapshot.tasks:
        if t.kind == KIND_DL_REVIEW:
            if _sees_dl_review(t, user, portfolio):
                out[t.kind].append(t)
        elif t.kind in (KIND_CPRO_TO_SEND, KIND_CPRO_SENT):
            if _sees_cpro(t, user):
                out[t.kind].append(t)
    # Moje zadania Cpro na górze, potem nieprzypisane.
    out[KIND_CPRO_TO_SEND].sort(
        key=lambda t: (0 if t.assignee_id == user.id else 1, t.since)
    )
    return out


@dataclass(frozen=True)
class DigestLine:
    cpro_mine: int = 0
    cpro_unassigned: int = 0
    dl_review: int = 0
    # 0372: follow-upy z kandydatami na dziś (w tym zaległe).
    followups: int = 0
    followups_overdue: int = 0

    @property
    def total(self) -> int:
        return self.cpro_mine + self.cpro_unassigned + self.dl_review + self.followups


async def digest_counts(
    db: AsyncSession,
    snapshot: BoardTaskSnapshot,
    *,
    followups: Optional[dict[int, "DigestCounts"]] = None,
) -> dict[int, DigestLine]:
    """Poranny skrót: kto ma co do zrobienia (tylko to, co wymaga ruchu).

    Wysłane do Cpro nie są zadaniem — czekamy na Nordeę — więc skrót ich nie
    liczy. Osoba od Cpro dostaje liczbę osób w kolejce; kolejka bez nikogo
    ustawionego trafia do Head of Recruitment. Przegląd DL — ta sama reguła co
    panel (`_sees_dl_review`). Follow-upy (``followups`` — liczby telefonów
    per dzwoniący z ``candidate_followups.digest_counts``) dostaje każda rola,
    nie tylko DL i HoR.
    """

    followups = followups or {}
    if not snapshot.tasks:
        return {
            uid: DigestLine(followups=c.due, followups_overdue=c.overdue)
            for uid, c in followups.items()
            if c.due
        }
    users = (
        await db.scalars(
            select(User).where(
                User.is_active.is_(True),
                or_(
                    User.role.in_(_REVIEW_DIGEST_ROLES),
                    *(User.roles.contains([r.value]) for r in _REVIEW_DIGEST_ROLES),
                ),
            )
        )
    ).all()
    portfolios: dict[int, frozenset[int]] = {}
    for u in users:
        if u.has_role(UserRole.delivery_lead):
            portfolios[u.id] = await dl_portfolio_client_ids(db, u.id)

    counts: dict[int, dict[str, int]] = {}

    def bump(uid: int, key: str) -> None:
        counts.setdefault(uid, {"cpro_mine": 0, "cpro_unassigned": 0, "dl_review": 0})[
            key
        ] += 1

    for t in snapshot.tasks:
        if t.kind == KIND_CPRO_TO_SEND:
            if t.assignee_id is not None:
                bump(t.assignee_id, "cpro_mine")
                continue
            for u in users:
                if u.has_role(UserRole.head_of_recruitment):
                    bump(u.id, "cpro_unassigned")
        elif t.kind == KIND_DL_REVIEW:
            for u in users:
                if _sees_dl_review(t, u, portfolios.get(u.id, frozenset())):
                    bump(u.id, "dl_review")
    for uid, c in followups.items():
        if c.due:
            line = counts.setdefault(
                uid, {"cpro_mine": 0, "cpro_unassigned": 0, "dl_review": 0}
            )
            line["followups"] = c.due
            line["followups_overdue"] = c.overdue
    return {uid: DigestLine(**c) for uid, c in counts.items()}


def digest_message(line: DigestLine) -> str:
    parts: list[str] = []
    if line.dl_review:
        parts.append(
            f"{_people(line.dl_review)} {_waits(line.dl_review)} na Twój przegląd"
        )
    if line.cpro_mine:
        parts.append(
            f"{_people(line.cpro_mine)} w kolejce Cpro do wysłania przez Ciebie"
        )
    if line.followups:
        phrase = f"{_followups(line.followups)} z kandydatami do zrobienia"
        if line.followups_overdue:
            phrase += f" ({line.followups_overdue} zaległ{'y' if line.followups_overdue == 1 else ('e' if _few(line.followups_overdue) else 'ych')})"
        parts.append(phrase)
    if line.cpro_unassigned:
        parts.append(
            f"{_people(line.cpro_unassigned)} w kolejce Cpro — "
            "nikt nie jest ustawiony do wysyłki"
        )
    return " · ".join(parts)


def _few(n: int) -> bool:
    return 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14


def _waits(n: int) -> str:
    return "czekają" if _few(n) else "czeka"


def _followups(n: int) -> str:
    if n == 1:
        return "1 follow-up"
    if _few(n):
        return f"{n} follow-upy"
    return f"{n} follow-upów"


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
    "REVIEW_ROLES",
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

    Od 23.09.2026 bramka zespołu przepuszcza każdą rolę operacyjną, więc
    zwykle nie ma czego dopisywać. Gdy jednak trzeba, dopisać osobę do zespołu
    może tylko admin, Delivery Lead, Head of Recruitment albo osoba od Cpro
    (`cpro_sender.can_send_to_cpro`); zwykły członek zespołu nie może tą drogą
    wprowadzać do rekrutacji innych osób (lustro bramki
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
    if not await cpro_sender.can_send_to_cpro(db, actor):
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
