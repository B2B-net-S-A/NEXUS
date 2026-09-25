"""Wymagania przejścia karty na Tablicy (Rekrutacja v5, 24.09.2026).

`GET /api/pipeline/move-requirements` mówi, CO jest potrzebne, żeby osoba
weszła do kolumny docelowej, zanim ktokolwiek kliknie „Przesuń" — i co z tego
już jest. Do 23.09.2026 rekruter dowiadywał się o braku stawki, CV albo
debriefu dopiero z odmowy serwera (422/409) po upuszczeniu karty.

Dwie warstwy:

* ``build_requirements`` — czysta funkcja z faktów pary (bez bazy); tu żyje
  reguła „co jest potrzebne do której kolumny" i testuje się ją bez Postgresa.
* ``load_pair_facts`` — zbiera fakty jednym przejściem po bazie.

Ruch przez kilka kolumn naraz (np. „Nowi" → „QC CV") sumuje wymagania
wszystkich kolumn po drodze — pominięta kolumna nie zwalnia z jej wymagań.
Ruch wstecz i zamknięcie procesu niczego nie wymagają.

Lista jest podpowiedzią dla ekranu, nie bramką: bramki (stawka przy
„Zweryfikowanym", QC CV przed wysłaniem, debrief przed umową, wysyłka przez
Delivery Leada) egzekwuje `POST /api/pipeline/move`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from sqlalchemy import select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.board_stage_badges import (
    BOARD_COLUMN_ORDER,
    board_column_for,
    cpro_enabled_for_client,
    is_cpro_stage,
)

OK = "ok"
MISSING = "missing"
WAITING = "waiting"

COLUMN_LABEL: dict[str, str] = {
    "new": "Nowi",
    "screening": "Screening",
    "verified": "Zweryfikowany",
    "cv_qc": "QC CV",
    "cv_sent": "CV wysłane",
    "client_interview": "Rozmowa u klienta",
    "contract": "Umowa",
    "hired": "Zatrudniony",
    "closed": "Zamknięci",
}
# U Nordei wysłanie CV do klienta TO JEST wysłanie do Cpro (22.09.2026).
CPRO_SENT_LABEL = "Wysłane do Cpro"

QC_OK_STATUSES = frozenset({"passed", "overridden"})


def column_label(column: str, *, nordea: bool = False) -> str:
    if column == "cv_sent" and nordea:
        return CPRO_SENT_LABEL
    return COLUMN_LABEL.get(column, column)


def sheet_filled(payload: object) -> bool:
    """Czy arkusz screeningu ma treść — lustro `_sheet_filled` w `api/pipeline`.

    `ScreeningAnswers` zapisuje domyślnie `{"answers": [], ...}`, więc samo
    `bool(dict)` dałoby fałszywe „wypełniony".
    """

    if not isinstance(payload, dict) or not payload:
        return False
    answers = payload.get("answers")
    if isinstance(answers, (list, dict)):
        return len(answers) > 0
    return any(value not in (None, "", [], {}) for value in payload.values())


@dataclass(frozen=True)
class PairFacts:
    """Wszystko, co trzeba wiedzieć o parze (kandydat, rekrutacja)."""

    from_column: Optional[str]
    # Najnowszy wiersz etapu pary — do niego prowadzą akcje („Otwórz QC").
    stage_id: Optional[int] = None
    screening_done: bool = False
    screening_stage_id: Optional[int] = None
    candidate_rate: bool = False
    availability_known: bool = False
    company_cv: bool = False
    qc_status: str = "unchecked"
    qc_blocking_failed: int = 0
    client_rate: bool = False
    # Użytkownik może wysłać CV do klienta (admin / Delivery Lead).
    is_client_sender: bool = False
    nordea: bool = False
    cpro_stage_def_id: Optional[int] = None
    qc_stage_def_id: Optional[int] = None
    on_cpro_stage: bool = False
    can_send_to_cpro: bool = False
    cpro_sender_name: Optional[str] = None
    client_slot: bool = False
    debrief_missing: bool = False
    debrief_pending: bool = False
    # Rozmowa u klienta, pod którą zapisuje się debrief.
    debrief_event_id: Optional[int] = None
    client_decision: bool = False
    signed: bool = False


@dataclass
class _Item:
    column: str
    key: str
    label: str
    status: str
    blocking: bool
    detail: Optional[str] = None
    action: Optional[dict[str, Any]] = field(default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "detail": self.detail,
            "status": self.status,
            "blocking": self.blocking,
            "action": self.action,
            # Kolumna, której dotyczy wymaganie — ekran grupuje po niej listę
            # przy ruchu przez kilka kolumn.
            "column": self.column,
        }

    @property
    def blocks(self) -> bool:
        return self.blocking and self.status == MISSING


def _action(kind: str, label: str, stage_id: Optional[int]) -> dict[str, Any]:
    return {"kind": kind, "label": label, "stage_id": stage_id}


def _index(column: Optional[str]) -> int:
    """Pozycja kolumny; brak etapu i „Zamknięci" liczą się jak „Nowi" —
    powrót zamkniętej osoby do procesu przechodzi całą drogę od początku."""

    if column in BOARD_COLUMN_ORDER:
        return BOARD_COLUMN_ORDER.index(column)
    return 0


def _items_for_cpro_upload(column: str, f: PairFacts) -> list[_Item]:
    return [
        _Item(
            column,
            "cpro_upload",
            "Wrzucenie do Cpro",
            WAITING,
            False,
            (
                f"wrzuca {f.cpro_sender_name}"
                if f.cpro_sender_name
                else "nikt nie jest ustawiony do wysyłki do Cpro"
            ),
        )
    ]


def _items_for(column: str, f: PairFacts) -> list[_Item]:
    sid = f.stage_id
    if column == "verified":
        return [
            _Item(
                column,
                "screening_sheet",
                "Arkusz screeningu",
                OK if f.screening_done else MISSING,
                True,
                None if f.screening_done else "odpowiedzi jeszcze nie zapisane",
                None
                if f.screening_done
                else _action(
                    "open_screening", "Otwórz screening", f.screening_stage_id or sid
                ),
            ),
            _Item(
                column,
                "candidate_rate",
                "Stawka kandydata",
                OK if f.candidate_rate else MISSING,
                True,
                None if f.candidate_rate else "brak stawki w profilu i w procesie",
                None
                if f.candidate_rate
                else _action("set_candidate_rate", "Wpisz stawkę", sid),
            ),
            _Item(
                column,
                "availability",
                "Dostępność",
                OK if f.availability_known else MISSING,
                False,
                None if f.availability_known else "nie wiemy, od kiedy może zacząć",
            ),
        ]
    if column == "cv_qc":
        return [
            _Item(
                column,
                "company_cv",
                "CV firmowe „Pod rekrutację”",
                OK if f.company_cv else MISSING,
                True,
                None if f.company_cv else "jeszcze nie wygenerowane",
                None
                if f.company_cv
                else _action("generate_cv", "Wygeneruj teraz", sid),
            )
        ]
    if column == "cv_sent":
        qc_ok = f.qc_status in QC_OK_STATUSES
        # Osoba już w kolejce Cpro przeszła QC przy wejściu do niej — serwer
        # przy „✓ Wrzucone" QC nie liczy drugi raz (`_assert_cv_qc_gate`),
        # więc okno nie może go blokować (audyt 25.09.2026).
        if f.nordea and f.on_cpro_stage and not qc_ok:
            return [
                _Item(
                    column,
                    "cv_qc",
                    "QC CV",
                    OK,
                    False,
                    "sprawdzone przy przekazaniu do kolejki Cpro",
                ),
                *_items_for_cpro_upload(column, f),
            ]
        if f.qc_status == "overridden":
            qc_detail: Optional[str] = "przepuszczone mimo QC (z powodem)"
        elif f.qc_status == "failed":
            from app.services.cv_qc import _checks_word

            qc_detail = f"{_checks_word(f.qc_blocking_failed)} do poprawy"
        elif f.qc_status == "unchecked":
            qc_detail = "QC jeszcze nie policzone"
        else:
            qc_detail = None
        items = [
            _Item(
                column,
                "cv_qc",
                "QC CV",
                OK if qc_ok else MISSING,
                True,
                qc_detail,
                None if qc_ok else _action("open_qc", "Otwórz QC CV", sid),
            )
        ]
        if f.nordea:
            items.extend(_items_for_cpro_upload(column, f))
        elif f.is_client_sender:
            items.append(
                _Item(
                    column,
                    "client_rate",
                    "Stawka do klienta",
                    # Brak nie blokuje: okno stawki pyta o nią w samym ruchu
                    # (test na produkcji 24.09.2026 — czerwony krzyżyk przy
                    # „wpiszesz ją przy wysyłce” czytał się jak blokada).
                    OK if f.client_rate else WAITING,
                    False,
                    None if f.client_rate else "wpiszesz ją przy wysyłce",
                    None
                    if f.client_rate
                    else _action("set_client_rate", "Wpisz stawkę do klienta", sid),
                )
            )
        else:
            items.append(
                _Item(
                    column,
                    "client_rate",
                    "Stawka do klienta",
                    WAITING,
                    False,
                    "ustala Delivery Lead przy wysyłce",
                )
            )
        return items
    if column == "client_interview":
        return [
            _Item(
                column,
                "client_slot",
                "Termin od klienta",
                OK if f.client_slot else WAITING,
                False,
                None if f.client_slot else "czekamy na terminy od klienta",
                None
                if f.client_slot
                else _action("request_slots", "Dodaj terminy od klienta", sid),
            )
        ]
    if column == "contract":
        if f.debrief_pending:
            debrief_detail: Optional[str] = "rozmowa u klienta jeszcze się nie odbyła"
        elif f.debrief_missing:
            debrief_detail = "zapisz pytania klienta po rozmowie"
        else:
            debrief_detail = None
        return [
            _Item(
                column,
                "debrief",
                "Debrief po rozmowie u klienta",
                MISSING if f.debrief_missing else OK,
                True,
                debrief_detail,
                {
                    **_action("open_debrief", "Uzupełnij debrief", sid),
                    "event_id": f.debrief_event_id,
                }
                if f.debrief_missing and not f.debrief_pending
                else None,
            ),
            _Item(
                column,
                "client_decision",
                "Decyzja klienta",
                OK if f.client_decision else WAITING,
                False,
                None if f.client_decision else "brak zapisanej decyzji klienta",
            ),
        ]
    if column == "hired":
        return [
            _Item(
                column,
                "signature",
                "Podpis umowy przez obie strony",
                OK if f.signed else WAITING,
                False,
                None if f.signed else "umowa jeszcze niepodpisana",
            )
        ]
    return []


def build_requirements(facts: PairFacts, to_column: str) -> dict[str, Any]:
    """Lista wymagań i główna akcja dla ruchu na ``to_column``."""

    from_column = facts.from_column
    to_label = column_label(to_column, nordea=facts.nordea)
    forward = to_column in BOARD_COLUMN_ORDER and (
        from_column not in BOARD_COLUMN_ORDER or _index(to_column) > _index(from_column)
    )
    result: dict[str, Any] = {
        "from_column": from_column,
        "to_column": to_column,
        "skipped_columns": [],
        "items": [],
        "primary": {"kind": "move", "label": f"Przesuń na „{to_label}”"},
        "owner_note": None,
    }
    if not forward:
        return result

    start, stop = _index(from_column), _index(to_column)
    path = list(BOARD_COLUMN_ORDER[start + 1 : stop + 1])
    result["skipped_columns"] = path[:-1]
    items = [item for column in path for item in _items_for(column, facts)]
    result["items"] = [item.as_dict() for item in items]

    primary: dict[str, Any] = {"kind": "move", "label": f"Przesuń na „{to_label}”"}
    owner_note: Optional[str] = None
    blocking = [item for item in items if item.blocks]

    if to_column == "cv_sent" and facts.nordea:
        if facts.on_cpro_stage:
            # Osoba już czeka w kolejce Cpro — „✓ Wrzucone" to zwykły ruch,
            # ale robi go osoba od Cpro, admin, DL albo HoR.
            if not facts.can_send_to_cpro:
                primary = {"kind": "blocked", "label": "Czeka w kolejce Cpro"}
                owner_note = (
                    f"Do Cpro wrzuca {facts.cpro_sender_name}."
                    if facts.cpro_sender_name
                    else "Nikt nie jest ustawiony do wysyłki do Cpro."
                )
        else:
            primary = {
                "kind": "hand_to_cpro",
                "label": "Przekaż do kolejki Cpro",
                "target_stage_def_id": facts.cpro_stage_def_id,
            }
            owner_note = (
                f"Do Cpro wrzuca {facts.cpro_sender_name} — osoba trafi do kolejki Cpro."
                if facts.cpro_sender_name
                else (
                    "Nikt nie jest ustawiony do wysyłki do Cpro — ustaw osobę "
                    "w kolejce Cpro."
                )
            )
    elif to_column == "cv_sent" and not facts.is_client_sender:
        # Wysyłka do klienta należy do Delivery Leada: rekruter przekazuje
        # osobę do „QC CV" (to jest „Czeka na Twój przegląd" DL). Blokuje więc
        # tylko to, co jest potrzebne do wejścia do „QC CV".
        qc_index = BOARD_COLUMN_ORDER.index("cv_qc")
        blocking = [
            item
            for item in blocking
            if BOARD_COLUMN_ORDER.index(item.column) <= qc_index
        ]
        primary = {
            "kind": "hand_to_dl",
            "label": "Przekaż Delivery Leadowi",
            "target_stage_def_id": (
                None if from_column == "cv_qc" else facts.qc_stage_def_id
            ),
        }
        owner_note = "CV wysyła Delivery Lead — trafi do jego „Czeka na Ciebie”."

    if blocking and primary["kind"] != "blocked":
        primary = {
            "kind": "blocked",
            # Nazwa wymagania bywa własną nazwą („QC CV”), więc bez `.lower()`.
            "label": f"Najpierw uzupełnij: {blocking[0].label}",
        }
    result["primary"] = primary
    result["owner_note"] = owner_note
    return result


# ── Fakty z bazy ─────────────────────────────────────────────────────────────


async def company_cv_refs(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict[str, Any]]:
    """CV firmowe par — hurtem, bez pobierania plików.

    Kolejność źródeł jak w przeglądzie QC: CV firmowe etapu (zatwierdzone
    przed szkicem), gotowe CV z generatora, plik „…B2B…" kandydata (CV
    zrobione poza generatorem). Brak pary w wyniku = brak CV.
    """

    from app.models.candidate_document import CandidateDocument  # noqa: PLC0415
    from app.models.candidate_stage_cv import CandidateStageCV  # noqa: PLC0415
    from app.models.cv_generated_document import CvGeneratedDocument  # noqa: PLC0415
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415

    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    out: dict[tuple[int, int], dict[str, Any]] = {}

    branded = (
        await db.execute(
            select(
                CandidateStage.candidate_id,
                CandidateStage.job_id,
                CandidateStageCV.candidate_stage_id,
                CandidateStageCV.generated_document_id,
                CandidateStageCV.branded_status,
            )
            .join(
                CandidateStage, CandidateStage.id == CandidateStageCV.candidate_stage_id
            )
            .where(
                tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(wanted),
                CandidateStageCV.branded_status.in_(("draft", "finalized")),
                CandidateStageCV.branded_draft_html.is_not(None),
            )
            .order_by(
                (CandidateStageCV.branded_status == "finalized").desc(),
                CandidateStage.moved_at.desc(),
                CandidateStage.id.desc(),
            )
        )
    ).all()
    for cand, job, stage_id, gen_id, status in branded:
        out.setdefault(
            (cand, job),
            {
                "source": f"branded_{status}",
                "stage_id": stage_id,
                "generated_document_id": gen_id,
                "document_id": None,
            },
        )

    missing = [p for p in wanted if p not in out]
    if missing:
        generated = (
            await db.execute(
                select(
                    CvGeneratedDocument.candidate_id,
                    CvGeneratedDocument.job_id,
                    CvGeneratedDocument.id,
                )
                .where(
                    tuple_(
                        CvGeneratedDocument.candidate_id, CvGeneratedDocument.job_id
                    ).in_(missing),
                    CvGeneratedDocument.status == "ready",
                    CvGeneratedDocument.render_payload.is_not(None),
                )
                .order_by(
                    CvGeneratedDocument.created_at.desc(),
                    CvGeneratedDocument.id.desc(),
                )
            )
        ).all()
        for cand, job, doc_id in generated:
            out.setdefault(
                (cand, job),
                {
                    "source": "generated",
                    "stage_id": None,
                    "generated_document_id": doc_id,
                    "document_id": None,
                },
            )

    missing = [p for p in wanted if p not in out]
    if missing:
        candidate_ids = sorted({c for c, _ in missing})
        documents = (
            await db.execute(
                select(CandidateDocument.candidate_id, CandidateDocument.id)
                .where(
                    CandidateDocument.candidate_id.in_(candidate_ids),
                    CandidateDocument.filename.ilike("%b2b%"),
                    CandidateDocument.source_deleted_at.is_(None),
                )
                .order_by(CandidateDocument.id.desc())
            )
        ).all()
        latest: dict[int, int] = {}
        for cand, doc_id in documents:
            latest.setdefault(cand, doc_id)
        for cand, job in missing:
            if cand in latest:
                out[(cand, job)] = {
                    "source": "document",
                    "stage_id": None,
                    "generated_document_id": None,
                    "document_id": latest[cand],
                }
    return out


async def qc_statuses(
    db: AsyncSession, pairs: Iterable[tuple[int, int]]
) -> dict[tuple[int, int], dict]:
    """Wynik QC CV par (`cv_qc.pair_statuses`) — jedno zapytanie hurtowe.

    Import leniwy: moduł QC ciągnie generator CV i parsery dokumentów, a ta
    funkcja jest wołana przy każdym odczycie kolejki i okna ruchu.
    """

    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    from app.services.cv_qc import pair_statuses  # noqa: PLC0415

    return await pair_statuses(db, wanted)


def _enum(value: Any) -> Optional[str]:
    return getattr(value, "value", value)


def stage_def_column(stage_def: Any) -> str:
    """Kolumna Tablicy etapu docelowego — liczona z etapu, nie z wiersza pary
    (etap docelowy bywa z innego szablonu niż bieżący wiersz)."""

    return board_column_for(
        stage_def.name,
        stage_def.legacy_enum_value,
        category=_enum(stage_def.category),
        terminal_type=_enum(stage_def.terminal_type),
    )


async def load_pair_facts(
    db: AsyncSession, *, candidate: Any, job: Any, user: Any
) -> PairFacts:
    """Fakty pary dla ``build_requirements`` — kilka zapytań, bez plików."""

    from sqlalchemy import exists  # noqa: PLC0415

    from app.models.b2b_generated_contract import (  # noqa: PLC0415
        B2BGeneratedContract,
    )
    from app.models.calendar_event import (  # noqa: PLC0415
        CalendarEvent,
        EventStatus,
        EventType,
    )
    from app.models.client_interview_slot_request import (  # noqa: PLC0415
        ClientInterviewSlotRequest,
    )
    from app.models.interview_feedback import (  # noqa: PLC0415
        FeedbackSource,
        InterviewFeedback,
    )
    from app.models.pipeline_template import (  # noqa: PLC0415
        PipelineStageDef,
        PipelineTemplate,
    )
    from app.models.recruitment_pipeline import CandidateStage  # noqa: PLC0415
    from app.services import candidate_claim, cpro_sender  # noqa: PLC0415
    from app.services.board_tasks import classify_template  # noqa: PLC0415
    from app.services.debrief_gate import missing_debrief  # noqa: PLC0415
    from app.services.pipeline_move_rules import CLIENT_SEND_ROLES  # noqa: PLC0415

    pair = (candidate.id, job.id)
    rows = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    CandidateStage.candidate_id == candidate.id,
                    CandidateStage.job_id == job.id,
                )
                .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            )
        )
        .scalars()
        .all()
    )
    latest = rows[0] if rows else None
    from_column = (
        await candidate_claim.stage_column(db, latest) if latest is not None else None
    )
    screening_row = next((r for r in rows if sheet_filled(r.screening_answers)), None)
    candidate_rate = candidate.expected_rate_hourly is not None or any(
        r.expected_rate_value is not None for r in rows
    )
    client_rate = any(r.client_rate_value is not None for r in rows)

    on_cpro_stage = False
    if latest is not None and latest.stage_def_id is not None:
        latest_name = await db.scalar(
            select(PipelineStageDef.name).where(
                PipelineStageDef.id == latest.stage_def_id
            )
        )
        on_cpro_stage = is_cpro_stage(latest_name)

    template_id = job.pipeline_template_id or await db.scalar(
        select(PipelineTemplate.id)
        .where(PipelineTemplate.is_default.is_(True))
        .order_by(PipelineTemplate.id)
        .limit(1)
    )
    stages = None
    if template_id is not None:
        defs = (
            await db.scalars(
                select(PipelineStageDef).where(
                    PipelineStageDef.template_id == template_id
                )
            )
        ).all()
        stages = classify_template(defs)

    nordea = cpro_enabled_for_client(job.client_id)
    sender_name: Optional[str] = None
    can_cpro = False
    if nordea:
        sender = await cpro_sender.effective_sender(db)
        # Bez osoby na firmę kolejka należy do osoby zapasowej rekrutacji —
        # ta sama reguła co bramka ruchu i `board_tasks._sees_cpro`.
        # Martwe konto nie jest osobą zapasową (lustro `board_tasks._LATEST_SQL`).
        active = await cpro_sender.active_user_ids(
            db,
            (
                getattr(job, "cpro_sender_id", None),
                latest.task_assignee_id if latest is not None else None,
            ),
        )
        fallback_ids = tuple(
            uid
            for uid in (
                getattr(job, "cpro_sender_id", None),
                latest.task_assignee_id if latest is not None else None,
            )
            if uid in active
        )
        shown_sender = sender.user_id or next(
            (uid for uid in fallback_ids if uid is not None), None
        )
        if shown_sender is not None:
            sender_name = (await cpro_sender.user_names(db, {shown_sender})).get(
                shown_sender
            )
        can_cpro = await cpro_sender.can_send_to_cpro(
            db, user, fallback_sender_ids=fallback_ids
        )

    cv = (await company_cv_refs(db, [pair])).get(pair)
    qc = (await qc_statuses(db, [pair])).get(pair) or {}
    debrief = await missing_debrief(db, candidate_id=candidate.id, job_id=job.id)

    client_slot = bool(
        await db.scalar(
            select(
                exists().where(
                    ClientInterviewSlotRequest.candidate_id == candidate.id,
                    ClientInterviewSlotRequest.job_id == job.id,
                    ClientInterviewSlotRequest.status == "confirmed",
                )
            )
        )
    ) or bool(
        await db.scalar(
            select(
                exists().where(
                    CalendarEvent.candidate_id == candidate.id,
                    CalendarEvent.job_id == job.id,
                    CalendarEvent.event_type == EventType.client_interview,
                    CalendarEvent.status != EventStatus.cancelled,
                )
            )
        )
    )
    client_decision = bool(
        await db.scalar(
            select(
                exists().where(
                    InterviewFeedback.candidate_id == candidate.id,
                    InterviewFeedback.job_id == job.id,
                    InterviewFeedback.feedback_source == FeedbackSource.client_side,
                    InterviewFeedback.decision.is_not(None),
                )
            )
        )
    )
    signed = bool(
        await db.scalar(
            select(
                exists().where(
                    B2BGeneratedContract.candidate_id == candidate.id,
                    B2BGeneratedContract.job_id == job.id,
                    B2BGeneratedContract.signature_status == "signed_both",
                )
            )
        )
    )

    return PairFacts(
        from_column=from_column,
        stage_id=latest.id if latest is not None else None,
        screening_done=screening_row is not None,
        screening_stage_id=(
            screening_row.id
            if screening_row is not None
            else (latest.id if latest is not None else None)
        ),
        candidate_rate=candidate_rate,
        availability_known=candidate.availability_date is not None,
        company_cv=cv is not None,
        qc_status=qc.get("status") or "unchecked",
        qc_blocking_failed=int(qc.get("blocking_failed") or 0),
        client_rate=client_rate,
        is_client_sender=user.has_any_role(*CLIENT_SEND_ROLES),
        nordea=nordea,
        cpro_stage_def_id=stages.cpro_id if stages is not None else None,
        qc_stage_def_id=stages.qc_id if stages is not None else None,
        on_cpro_stage=on_cpro_stage,
        can_send_to_cpro=can_cpro,
        cpro_sender_name=sender_name,
        client_slot=client_slot,
        debrief_missing=debrief is not None,
        debrief_pending=bool(debrief and debrief.get("interview_pending")),
        debrief_event_id=debrief.get("event_id") if debrief else None,
        client_decision=client_decision,
        signed=signed,
    )


__all__ = [
    "COLUMN_LABEL",
    "PairFacts",
    "build_requirements",
    "column_label",
    "company_cv_refs",
    "load_pair_facts",
    "qc_statuses",
    "sheet_filled",
    "stage_def_column",
]
