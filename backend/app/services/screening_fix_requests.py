"""Prośba Delivery Leada o poprawki (D6, 08.10.2026).

„Wróć do poprawy” w przeglądzie DL cofało kartę z „QC CV” na „Zweryfikowany”
z jednym zdaniem uwagi — rekruter musiał zgadywać, które pole poprawić,
a DL po powrocie karty nie widział, co się zmieniło. Teraz ruch niesie listę
pól (``StageMove.fix_fields``):

* ``question:<id>`` — odpowiedź na pytanie z Profilu Championa (z zapisaną
  treścią pytania — pytania bywają potem edytowane),
* ``field:<pole karty>`` — pole karty rekomendacji z formularza screeningu,
* ``field:overall_fit`` — ocena rekrutera,
* ``candidate_rate`` — stawka kandydata,
* ``cv`` — CV firmowe.

Prośba to wiersz ``screening_form_versions`` z ``action="fix_requested"``
(migracja 0424, bez osobnej kolumny na etapie): migawka formularza w chwili
prośby, ``meta.stage_id`` = wiersz etapu „Zweryfikowany” powstały z tego ruchu
i ``meta.fields`` = lista pól z etykietami. Prośba jest OTWARTA, dopóki
najnowszy wiersz etapu pary to ``meta.stage_id`` — ruch rekrutera z powrotem
na „QC CV” (albo jakikolwiek inny) ją zamyka. Pole jest „poprawione”, gdy
bieżąca migawka różni się od migawki prośby w tym polu (CV — gdy CV firmowe
zmienił po prośbie człowiek; szkic podpięty przez automat auto-CV po ruchu na
„Zweryfikowany” się nie liczy).

Wyłącznie poza Nordeą (tam nie ma przeglądu DL) i wyłącznie przy ruchu
z „QC CV” na „Zweryfikowany”.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.models.screening_form_version import ScreeningFormVersion
from app.models.user import User
from app.services import screening_form_rules as rules
from app.services import screening_sheets
from app.services.board_stage_badges import cpro_enabled_for_client
from app.services.recommendation_card_rules import DISPLAY_LABELS

ACTION = "fix_requested"
FIX_FIELDS_MAX = 30
QUESTION_PREFIX = "question:"
FIELD_PREFIX = "field:"
KEY_OVERALL_FIT = "field:overall_fit"
KEY_CANDIDATE_RATE = "candidate_rate"
KEY_CV = "cv"
FROM_COLUMN = "cv_qc"
TARGET_COLUMN = "verified"
QUESTION_LABEL_CHARS = 120

INVALID_CODE = "FIX_FIELDS_INVALID"
NOT_ALLOWED_CODE = "FIX_FIELDS_NOT_ALLOWED"


@dataclass(frozen=True)
class FixOption:
    key: str
    label: str
    group: str  # answers | terms | assessment | rate | cv

    def as_dict(self) -> dict[str, str]:
        return {"key": self.key, "label": self.label, "group": self.group}


def _short(text: str, limit: int = QUESTION_LABEL_CHARS) -> str:
    line = " ".join(text.split())
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def fix_options(job: Any) -> list[FixOption]:
    """Co Delivery Lead może wskazać do poprawy — w kolejności formularza."""
    out: list[FixOption] = []
    questions = screening_sheets.question_texts(getattr(job, "champion_profile", None))
    for number, (question_id, text) in enumerate(questions.items(), start=1):
        out.append(
            FixOption(
                f"{QUESTION_PREFIX}{question_id}",
                f"Pytanie {number}: {_short(text)}",
                "answers",
            )
        )
    for key in rules.TERMS_CARD_FIELDS:
        out.append(
            FixOption(f"{FIELD_PREFIX}{key}", DISPLAY_LABELS.get(key, key), "terms")
        )
    out.append(FixOption(KEY_OVERALL_FIT, "Ocena rekrutera", "assessment"))
    for key in rules.ASSESSMENT_CARD_FIELDS:
        out.append(
            FixOption(
                f"{FIELD_PREFIX}{key}", DISPLAY_LABELS.get(key, key), "assessment"
            )
        )
    out.append(FixOption(KEY_CANDIDATE_RATE, "Stawka kandydata", "rate"))
    out.append(FixOption(KEY_CV, "CV firmowe", "cv"))
    return out


def _invalid(message: str, code: str = INVALID_CODE) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": code, "message": message})


def validate(keys: Optional[Sequence[str]], options: Sequence[FixOption]) -> list[str]:
    """Klucze bez powtórzeń, w kolejności formularza; nieznany klucz = 422."""
    if not keys:
        return []
    wanted: list[str] = []
    for raw in keys:
        key = str(raw or "").strip()
        if key and key not in wanted:
            wanted.append(key)
    if len(wanted) > FIX_FIELDS_MAX:
        raise _invalid(f"Wskaż najwyżej {FIX_FIELDS_MAX} pól do poprawy.")
    known = {o.key for o in options}
    unknown = [key for key in wanted if key not in known]
    if unknown:
        raise _invalid(
            "Nie ma takiego pola do poprawy w tej rekrutacji: " + ", ".join(unknown)
        )
    order = {o.key: i for i, o in enumerate(options)}
    return sorted(wanted, key=lambda key: order[key])


def assert_allowed(
    *,
    from_column: Optional[str],
    target_column: Optional[str],
    client_id: Optional[int],
) -> None:
    """Lista poprawek tylko przy „Wróć do poprawy” z „QC CV”, poza Nordeą."""
    if cpro_enabled_for_client(client_id):
        raise _invalid(
            "U tego klienta nie ma przeglądu Delivery Leada — CV idzie do Cpro.",
            NOT_ALLOWED_CODE,
        )
    if from_column != FROM_COLUMN or target_column != TARGET_COLUMN:
        raise _invalid(
            "Listę poprawek wysyła się tylko przy cofnięciu z „QC CV” na "
            "„Zweryfikowany”.",
            NOT_ALLOWED_CODE,
        )


async def record(
    db: AsyncSession,
    *,
    job: Job,
    stage: CandidateStage,
    user: User,
    keys: Sequence[str],
) -> Optional[ScreeningFormVersion]:
    """Wersja ``fix_requested`` formularza pary — w transakcji ruchu.

    Wołać po ``transition_process`` (``stage`` = nowy wiersz „Zweryfikowany”).
    Kandydat jest już zablokowany przez ruch (ta sama blokada co zapis
    formularza), więc numer wersji się nie zderzy.
    """
    if not keys:
        return None
    from app.services import screening_form  # noqa: PLC0415 — cykl serwisów

    labels = {o.key: o.label for o in fix_options(job)}
    await db.flush()
    state = await screening_form.pair_edit_state(
        db, job=job, candidate_id=stage.candidate_id
    )
    current = await screening_form._load_current(  # noqa: SLF001
        db,
        candidate_id=stage.candidate_id,
        job_id=job.id,
        newest=state.newest,
        process=state.process,
        for_write=False,
    )
    head = await screening_form._head(  # noqa: SLF001
        db, candidate_id=stage.candidate_id, job_id=job.id
    )
    row = screening_form._version_row(  # noqa: SLF001
        candidate_id=stage.candidate_id,
        job_id=job.id,
        state=state,
        number=head.version + 1,
        action=ACTION,
        snapshot=current.snapshot(),
        changes=[],
        created_by=user.id,
    )
    row.stage_id = stage.id
    row.meta = {
        "stage_id": stage.id,
        "fields": [{"key": key, "label": labels.get(key, key)} for key in keys],
    }
    db.add(row)
    return row


def _change_keys(changes: Sequence[rules.VersionChange]) -> set[str]:
    out: set[str] = set()
    for change in changes:
        if change.section == "answers":
            out.add(f"{QUESTION_PREFIX}{change.key}")
        elif change.key == "overall_fit":
            out.add(KEY_OVERALL_FIT)
        elif change.key == "rate":
            out.add(KEY_CANDIDATE_RATE)
        else:
            out.add(f"{FIELD_PREFIX}{change.key}")
    return out


def describe(
    row: ScreeningFormVersion,
    *,
    current_snapshot: Mapping[str, Any],
    questions: Sequence[str],
    cv_changed: bool,
    requested_by_name: Optional[str],
    remark: Optional[str],
) -> dict[str, Any]:
    """Kształt ``fix_request`` w odpowiedzi formularza (czysta funkcja)."""
    changed = _change_keys(
        rules.diff_snapshots(row.snapshot, current_snapshot, questions=questions)
    )
    fields = []
    for item in (row.meta or {}).get("fields") or []:
        key = str(item.get("key") or "")
        if not key:
            continue
        done = cv_changed if key == KEY_CV else key in changed
        fields.append(
            {"key": key, "label": str(item.get("label") or key), "changed": done}
        )
    return {
        "version_no": row.version_no,
        "stage_id": (row.meta or {}).get("stage_id"),
        "requested_at": row.created_at.isoformat() if row.created_at else None,
        "requested_by_name": requested_by_name,
        "remark": remark,
        "fields": fields,
        "count": len(fields),
        "changed_count": sum(1 for f in fields if f["changed"]),
    }


async def latest_request(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[ScreeningFormVersion]:
    return await db.scalar(
        select(ScreeningFormVersion)
        .where(
            ScreeningFormVersion.candidate_id == candidate_id,
            ScreeningFormVersion.job_id == job_id,
            ScreeningFormVersion.action == ACTION,
        )
        .order_by(ScreeningFormVersion.version_no.desc())
        .limit(1)
    )


AUTOMATION_ATTACH_ACTION = "branded_cv_attached_by_automation"
# Podpięcie szkicu przez automat stempluje ``branded_updated_at`` w tej samej
# transakcji co wpis w historii (``created_at`` = początek transakcji), więc
# oba czasy dzieli najwyżej czas tej transakcji.
_AUTOMATION_SLACK_SECONDS = 60


def cv_changed_by_person(
    updates: Sequence[tuple[int, datetime]],
    automation: Sequence[tuple[int, datetime]],
    *,
    requested_at: datetime,
) -> bool:
    """Czy CV firmowe pary zmienił po prośbie człowiek (czysta funkcja).

    ``updates`` — (id kopii CV, ``branded_updated_at``), ``automation`` —
    (id kopii CV, czas wpisu „podpięte przez automat”). Zmiana po prośbie, którą
    tłumaczy podpięcie przez automat tej samej kopii, nie jest poprawką.
    """
    for csv_id, updated_at in updates:
        if updated_at is None or updated_at <= requested_at:
            continue
        explained = any(
            auto_id == csv_id
            and auto_at >= requested_at
            and 0 <= (updated_at - auto_at).total_seconds() <= _AUTOMATION_SLACK_SECONDS
            for auto_id, auto_at in automation
        )
        if not explained:
            return True
    return False


async def _cv_changed_since(
    db: AsyncSession, *, candidate_id: int, job_id: int, requested_at: datetime
) -> bool:
    updates = [
        (csv_id, at)
        for csv_id, at in (
            await db.execute(
                select(CandidateStageCV.id, CandidateStageCV.branded_updated_at).where(
                    CandidateStageCV.candidate_id == candidate_id,
                    CandidateStageCV.job_id == job_id,
                    CandidateStageCV.branded_updated_at > requested_at,
                )
            )
        ).all()
    ]
    if not updates:
        return False
    automation = [
        (entity_id, at)
        for entity_id, at in (
            await db.execute(
                select(Activity.entity_id, Activity.created_at).where(
                    Activity.entity_type == "candidate_stage_cv",
                    Activity.entity_id.in_([csv_id for csv_id, _ in updates]),
                    Activity.action == AUTOMATION_ATTACH_ACTION,
                    Activity.created_at >= requested_at,
                )
            )
        ).all()
    ]
    return cv_changed_by_person(updates, automation, requested_at=requested_at)


async def open_for_pair(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    newest_stage_id: Optional[int],
    current_snapshot: Mapping[str, Any],
    questions: Sequence[str],
) -> Optional[dict[str, Any]]:
    """Otwarta prośba pary albo ``None`` (najnowszy wiersz ≠ ``meta.stage_id``)."""
    from app.services import stage_remarks  # noqa: PLC0415

    if newest_stage_id is None:
        return None
    row = await latest_request(db, candidate_id=candidate_id, job_id=job_id)
    if row is None or (row.meta or {}).get("stage_id") != newest_stage_id:
        return None
    requested_at = row.created_at or datetime.now(timezone.utc)
    author = await db.get(User, row.created_by) if row.created_by else None
    return describe(
        row,
        current_snapshot=current_snapshot,
        questions=questions,
        cv_changed=await _cv_changed_since(
            db, candidate_id=candidate_id, job_id=job_id, requested_at=requested_at
        ),
        requested_by_name=author.name if author is not None else None,
        remark=await stage_remarks.for_stage(db, newest_stage_id),
    )


async def labels_for_stages(
    db: AsyncSession,
    stage_ids: Sequence[int],
    *,
    candidate_ids: Optional[Sequence[int]] = None,
) -> dict[int, list[str]]:
    """``{wiersz etapu: [etykiety pól]}`` — dzwonek i lista „CV w drodze”.

    ``candidate_ids`` zawęża odczyt do par tych osób (indeks unikalny
    ``(candidate_id, job_id, version_no)``) — tabela nie ma indeksu po etapie.
    """
    wanted = sorted({int(s) for s in stage_ids if s is not None})
    if not wanted:
        return {}
    query = select(ScreeningFormVersion).where(
        ScreeningFormVersion.action == ACTION,
        ScreeningFormVersion.stage_id.in_(wanted),
    )
    if candidate_ids is not None:
        query = query.where(
            ScreeningFormVersion.candidate_id.in_(sorted(set(candidate_ids)))
        )
    rows = (await db.scalars(query)).all()
    out: dict[int, list[str]] = {}
    for row in rows:
        stage_id = (row.meta or {}).get("stage_id")
        if stage_id not in wanted:
            continue
        out[int(stage_id)] = [
            str(item.get("label") or item.get("key"))
            for item in (row.meta or {}).get("fields") or []
            if item.get("key")
        ]
    return out


async def rounds_for_pairs(
    db: AsyncSession, pairs: Sequence[tuple[int, int]]
) -> dict[tuple[int, int], int]:
    """Ile razy DL odsyłał parę do poprawy (kolejka porównawcza)."""
    wanted = sorted(set(pairs))
    if not wanted:
        return {}
    rows = await db.execute(
        select(
            ScreeningFormVersion.candidate_id,
            ScreeningFormVersion.job_id,
            func.count(),
        )
        .where(
            ScreeningFormVersion.action == ACTION,
            tuple_(ScreeningFormVersion.candidate_id, ScreeningFormVersion.job_id).in_(
                wanted
            ),
        )
        .group_by(ScreeningFormVersion.candidate_id, ScreeningFormVersion.job_id)
    )
    return {(c, j): int(n) for c, j, n in rows.all()}


async def handback_stage_def_id(db: AsyncSession, job: Job) -> Optional[int]:
    """Etap „QC CV” szablonu rekrutacji — „Zapisz i oddaj do przeglądu DL”."""
    from app.models.pipeline_template import (  # noqa: PLC0415
        PipelineStageDef,
        PipelineTemplate,
    )
    from app.services.board_tasks import classify_template  # noqa: PLC0415

    template_id = job.pipeline_template_id or await db.scalar(
        select(PipelineTemplate.id).where(PipelineTemplate.is_default.is_(True))
    )
    if template_id is None:
        return None
    defs = (
        await db.scalars(
            select(PipelineStageDef).where(PipelineStageDef.template_id == template_id)
        )
    ).all()
    return classify_template(defs).qc_id


def bell_suffix(labels: Sequence[str]) -> Optional[str]:
    """„Do poprawy (N): a, b, c.” — dzwonek mówi rekruterowi, co poprawić."""
    if not labels:
        return None
    shown = list(labels[:4])
    rest = len(labels) - len(shown)
    text = ", ".join(shown) + (f" i {rest} więcej" if rest > 0 else "")
    return f"Do poprawy ({len(labels)}): {text}."


__all__ = [
    "ACTION",
    "FIX_FIELDS_MAX",
    "FixOption",
    "KEY_CANDIDATE_RATE",
    "KEY_CV",
    "KEY_OVERALL_FIT",
    "assert_allowed",
    "bell_suffix",
    "describe",
    "fix_options",
    "handback_stage_def_id",
    "labels_for_stages",
    "latest_request",
    "open_for_pair",
    "record",
    "rounds_for_pairs",
    "validate",
]
