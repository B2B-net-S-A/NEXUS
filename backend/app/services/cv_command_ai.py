"""Polecenie własnymi słowami dla całego CV — Edytor CV 2, PR 4 (decyzja Artura 12.10.2026).

Rekruter pisze polecenie („skróć do dwóch stron, zostaw wszystko o Kafce”)
albo wybiera gotowe. Model zwraca PLAN: listę operacji na wierszach CV. KOD
sprawdza każdą operację osobno i wypuszcza tylko te, które da się bezpiecznie
zastosować:

* usuwać, łączyć, przestawiać i przeredagować wolno zwykłą treść (punkty
  i akapity); tytuł, nagłówki, stanowisko, firma, etykieta obowiązków i lista
  technologii mają zapis, z którego serwer składa Word — znikają tylko razem
  z całą rolą albo sekcją,
* nowy tekst (przeredagowanie, połączenie) przechodzi tę samą kontrolę „bez
  nowych faktów” co AI na zaznaczeniu (`cv_selection_ai.check`),
* jeden wiersz należy do jednej operacji, więc rekruter może odznaczyć
  dowolną z nich bez psucia pozostałych.

Trasa niczego nie zapisuje: plan nakłada edytor jedną cofalną zmianą, po tym
jak rekruter wybierze operacje, a utrwala go zwykły autozapis.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_selection_ai
from app.services import dz_review as dz
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import _json_object
from app.services.dz_review import Requirement
from app.services.llm_prompts import CV_EDITOR_COMMAND
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.cv_editor_command
ACTIVITY_ACTION = "cv_command_ai"

# Rodzaje wierszy, które przysyła edytor. Klauzuli zgody edytor nie wysyła wcale.
LINE_KINDS = (
    "title",
    "heading",
    "role",
    "employer",
    "label",
    "technologies",
    "bullet",
    "text",
)
# Zwykła treść — jedyne wiersze, które operacja może ruszyć pojedynczo.
EDITABLE = frozenset({"bullet", "text"})
OPERATION_TYPES = (
    "remove",
    "replace",
    "merge",
    "reorder",
    "remove_role",
    "remove_section",
)

# Granice wejścia (schemat trasy trzyma te same liczby).
LINES_MAX = 400
LINE_TEXT_MAX = 1200
COMMAND_MAX = 300
OPERATIONS_MAX = 40
WHY_MAX = 200

PRESETS = {
    "shorten": (
        "Skróć CV do około dwóch stron: usuń ogólniki i powtórzenia, połącz punkty "
        "o tym samym, zostaw to, co odpowiada wymaganiom klienta."
    ),
    "drop_old_roles": (
        "Usuń najstarsze stanowiska, które nie mają związku z wymaganiami klienta "
        "(zwykle starsze niż 10 lat). Nie ruszaj pozostałych."
    ),
    "order_by_requirements": (
        "W każdym stanowisku ułóż punkty tak, żeby najpierw stały te, które "
        "odpowiadają wymaganiom klienta. Nie zmieniaj treści punktów."
    ),
    "unify_sentences": (
        "Ujednolić formę punktów w całym CV (ta sama forma gramatyczna, bez "
        "pierwszej osoby). Nie zmieniaj faktów."
    ),
}

MSG_UNAVAILABLE = (
    "Asystent jest chwilowo niedostępny. Popraw CV ręcznie albo spróbuj za chwilę."
)
MSG_EMPTY = "Asystent nie znalazł zmian, które odpowiadają temu poleceniu."
MSG_ALL_DROPPED = (
    "Asystent zaproponował zmiany, ale żadna nie przeszła kontroli (dopisywały "
    "fakty albo ruszały układ szablonu). Spróbuj opisać polecenie inaczej."
)


@dataclass(frozen=True)
class Line:
    """Wiersz CV tak, jak widzi go rekruter: blok dokumentu albo punkt listy."""

    id: int
    kind: str
    text: str
    # Sekcja (klucz szablonu) i numer stanowiska w CV — albo ``None``.
    section: Optional[str] = None
    role: Optional[int] = None


class _Dropped(Exception):
    """Operacja nie przeszła kontroli (powód i ewentualny zapis, o który poszło)."""

    def __init__(self, reason: str, problem: Optional[str] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.problem = problem


def _ids(value: Any, known: dict[int, Line]) -> list[int]:
    """Lista różnych, znanych numerów wierszy — albo odmowa."""
    if not isinstance(value, list) or not value:
        raise _Dropped("bad_lines")
    out: list[int] = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, int) or item not in known:
            raise _Dropped("bad_lines")
        if item in out:
            raise _Dropped("bad_lines")
        out.append(item)
    return out


class _Plan:
    """Kontrola planu na jednym zrzucie wierszy CV."""

    def __init__(self, lines: list[Line], requirements: tuple[Requirement, ...]):
        self.lines = {item.id: item for item in lines}
        self.requirements = requirements
        self.grounds = cv_selection_ai.Grounds(requirements=requirements)
        # Miejsce zwykłej treści: stanowisko albo sekcja (nagłówek, pod którym stoi).
        self.place: dict[int, tuple[str, int]] = {}
        self.members: dict[tuple[str, int], list[int]] = {}
        self.role_lines: dict[int, list[int]] = {}
        self.section_lines: dict[int, list[int]] = {}
        heading: Optional[int] = None
        for item in lines:
            if item.kind in ("title", "heading"):
                heading = item.id if item.kind == "heading" else None
            if heading is not None:
                self.section_lines.setdefault(heading, []).append(item.id)
            if item.role is not None:
                self.role_lines.setdefault(item.role, []).append(item.id)
            if item.kind in EDITABLE:
                place = (
                    ("role", item.role)
                    if item.role is not None
                    else ("section", heading if heading is not None else -1)
                )
                self.place[item.id] = place
                self.members.setdefault(place, []).append(item.id)
        # Gdzie stoi każde wymaganie — raz, zamiast szukać przy każdej operacji.
        self.found: list[tuple[str, frozenset[int]]] = []
        for requirement in requirements:
            where = frozenset(
                item.id for item in lines if dz._found(item.text, requirement)
            )
            if where:
                self.found.append((requirement.label, where))
        self.by_label = {r.label: r for r in requirements}
        self.used: set[int] = set()
        self.removed: set[int] = set()
        self.removed_roles: set[int] = set()

    # ── pojedyncze operacje ──

    def _editable(self, ids: list[int]) -> None:
        if any(self.lines[i].kind not in EDITABLE for i in ids):
            raise _Dropped("not_editable")

    def _new_text(self, source: str, text: Any) -> str:
        if text is not None and not isinstance(text, str):
            raise _Dropped("empty")
        raw = json.dumps({"text": text or ""}, ensure_ascii=False)
        checked = cv_selection_ai.check("rephrase", source, raw, self.grounds)
        if checked["status"] != "ok":
            raise _Dropped(checked["reason"] or "new_fact", checked.get("problem"))
        return checked["proposed_text"]

    def remove(self, op: dict) -> tuple[list[int], Optional[str]]:
        ids = _ids(op.get("lines"), self.lines)
        self._editable(ids)
        gone = self.removed | set(ids)
        for place in {self.place[i] for i in ids}:
            if all(member in gone for member in self.members[place]):
                kind = "role" if place[0] == "role" else "section"
                raise _Dropped(f"would_empty_{kind}")
        return ids, None

    def replace(self, op: dict) -> tuple[list[int], Optional[str]]:
        ids = _ids([op.get("line")], self.lines)
        self._editable(ids)
        return ids, self._new_text(self.lines[ids[0]].text, op.get("text"))

    def merge(self, op: dict) -> tuple[list[int], Optional[str]]:
        ids = _ids(op.get("lines"), self.lines)
        if len(ids) < 2:
            raise _Dropped("bad_lines")
        self._editable(ids)
        first = self.lines[ids[0]]
        if any(
            self.place[i] != self.place[first.id] or self.lines[i].kind != first.kind
            for i in ids
        ):
            raise _Dropped("mixed_places")
        source = " ".join(self.lines[i].text for i in ids)
        return ids, self._new_text(source, op.get("text"))

    def reorder(self, op: dict) -> tuple[list[int], Optional[str]]:
        ids = _ids(op.get("lines"), self.lines)
        if any(self.lines[i].kind != "bullet" for i in ids):
            raise _Dropped("bad_order")
        current = [
            i
            for i in self.members[self.place[ids[0]]]
            if self.lines[i].kind == "bullet"
        ]
        if sorted(ids) != sorted(current):
            raise _Dropped("bad_order")
        if ids == current:
            raise _Dropped("unchanged")
        return ids, None

    def remove_role(self, op: dict) -> tuple[list[int], Optional[str]]:
        role = op.get("role")
        if isinstance(role, bool) or not isinstance(role, int):
            raise _Dropped("unknown_role")
        if role not in self.role_lines:
            raise _Dropped("unknown_role")
        if len(self.removed_roles | {role}) >= len(self.role_lines):
            raise _Dropped("last_role")
        return list(self.role_lines[role]), None

    def remove_section(self, op: dict) -> tuple[list[int], Optional[str]]:
        target = op.get("line")
        line = self.lines.get(target) if isinstance(target, int) else None
        if line is None or line.kind != "heading":
            raise _Dropped("not_a_section")
        if line.section == "experience" or any(
            self.lines[i].role is not None for i in self.section_lines[line.id]
        ):
            raise _Dropped("protected_section")
        return list(self.section_lines[line.id]), None

    # ── plan ──

    def _loses(self, kind: str, ids: list[int], text: Optional[str]) -> list[str]:
        """Wymagania rekrutacji, które po tej jednej operacji znikają z CV."""
        if kind == "reorder":
            return []
        touched = set(ids)
        return [
            label
            for label, where in self.found
            if where <= touched and not (text and dz._found(text, self.by_label[label]))
        ]

    def accept(self, raw: Any) -> dict:
        if not isinstance(raw, dict) or raw.get("type") not in OPERATION_TYPES:
            raise _Dropped("unknown_type")
        kind = raw["type"]
        ids, text = getattr(self, kind)(raw)
        if self.used.intersection(ids):
            raise _Dropped("overlap")
        self.used.update(ids)
        if kind in ("remove", "remove_section"):
            self.removed.update(ids)
        elif kind == "merge":
            self.removed.update(ids[1:])
        elif kind == "remove_role":
            self.removed.update(ids)
            self.removed_roles.add(raw["role"])
        why = cv_selection_ai.plain(cv_selection_ai.clean_markup(raw.get("why")))
        return {
            "type": kind,
            "lines": ids,
            "text": text,
            "why": " ".join(why.split())[:WHY_MAX],
            "loses": self._loses(kind, ids, text),
        }


def verify_plan(
    raw: str, lines: list[Line], requirements: tuple[Requirement, ...]
) -> dict:
    """Odpowiedź modelu → operacje, które przeszły kontrolę, i odrzucone z powodem.

    ``raw`` to JSON ``{"operations": [...]}``. ``ValueError`` znaczy „model nie
    odpowiedział w umówionym kształcie” — wołający zgłasza to jako chwilową
    niedostępność. Pusta albo zła lista operacji to pusty plan.
    """
    data = _json_object(raw)
    proposed = data.get("operations")
    plan = _Plan(lines, tuple(requirements))
    operations: list[dict] = []
    dropped: list[dict] = []
    for item in (proposed if isinstance(proposed, list) else [])[:OPERATIONS_MAX]:
        try:
            accepted = plan.accept(item)
        except _Dropped as refusal:
            kind = item.get("type") if isinstance(item, dict) else None
            dropped.append(
                {
                    "type": kind if kind in OPERATION_TYPES else None,
                    "reason": refusal.reason,
                    "problem": refusal.problem,
                }
            )
            continue
        operations.append({"id": len(operations), **accepted})
    return {"operations": operations, "dropped": dropped}


# ── Wywołanie modelu ─────────────────────────────────────────────────────────


def _unavailable(message: str = MSG_UNAVAILABLE, status: str = "unavailable") -> dict:
    return {"status": status, "operations": [], "dropped": [], "message": message}


def command_text(payload: dict) -> str:
    """Treść polecenia: gotowe (z kodu) albo własne słowa rekrutera."""
    preset = payload.get("preset")
    if preset in PRESETS:
        return PRESETS[preset]
    return str(payload.get("command") or "").strip()[:COMMAND_MAX]


def build_prompt(payload: dict, lines: list[Line], requirements: tuple) -> str:
    """Prompt z danymi w znacznikach, których nie da się zamknąć od środka."""
    rows = [
        {
            "id": item.id,
            "rodzaj": item.kind,
            **({"stanowisko": item.role} if item.role is not None else {}),
            "tekst": item.text[:LINE_TEXT_MAX],
        }
        for item in lines
    ]
    own = payload.get("preset") not in PRESETS
    command = command_text(payload)
    return CV_EDITOR_COMMAND.render(
        # Gotowe polecenie pochodzi z kodu; własne słowa rekrutera to dane.
        command=fence("recruiter_command", command) if own else command,
        requirements=fence(
            "cv_requirements",
            json_for_prompt([r.label for r in requirements][:60]),
        ),
        lines=fence("cv_lines", json_for_prompt(rows)),
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=chain[0],
        fallback_models=chain[1:] or None,
        # Do 40 operacji z nowym tekstem i powodem.
        max_tokens=6000,
        thinking={"type": "disabled"},
        # Rekruter czeka z otwartym edytorem; plan dla całego CV trwa dłużej
        # niż propozycja dla jednego zdania.
        timeout=45,
        max_retries=1,
        total_timeout=60,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


async def _log(
    db: AsyncSession, stage: CandidateStage, user_id: int, payload: dict, result: dict
) -> None:
    """Ślad użycia (bez treści CV i bez polecenia). Błąd zapisu nie zabiera planu."""
    try:
        async with db.begin_nested():
            csv_id = await db.scalar(
                select(CandidateStageCV.id).where(
                    CandidateStageCV.candidate_stage_id == stage.id
                )
            )
            if csv_id is None:
                return
            preset = payload.get("preset")
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv_id,
                    action=ACTIVITY_ACTION,
                    user_id=user_id,
                    details={
                        "preset": preset if preset in PRESETS else None,
                        "status": result["status"],
                        "operations": len(result["operations"]),
                        "dropped": len(result["dropped"]),
                    },
                )
            )
    except Exception:  # noqa: BLE001 — pomiar, nie warunek działania
        logger.warning(
            "[cv_command_ai] nie zapisano wpisu użycia stage=%s",
            stage.id,
            exc_info=True,
        )


async def propose_plan(
    db: AsyncSession, stage: CandidateStage, *, user_id: int, payload: dict
) -> dict:
    """Plan zmian dla całego CV. Wołający sprawdził dostęp i schemat.

    Nigdy nie rzuca: brak klucza, błąd modelu albo zła odpowiedź to
    ``status: "unavailable"`` — edytor działa dalej bez asystenta.
    """
    if not settings.CV_EDITOR_COMMAND_ENABLED:
        return _unavailable()
    lines = [
        Line(
            id=int(item["id"]),
            kind=str(item["kind"]),
            text=str(item.get("text") or ""),
            section=item.get("section"),
            role=item.get("role"),
        )
        for item in payload.get("lines") or []
    ]
    if not command_text(payload) or not lines:
        return _unavailable(MSG_EMPTY, "empty")
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return _unavailable()
    try:
        job = await db.get(Job, stage.job_id)
        must, nice = dz.job_requirements(job) if job is not None else ([], [])
        requirements = (*must, *nice)
        prompt = build_prompt(payload, lines, requirements)
        system = CV_EDITOR_COMMAND.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem,
            # żeby żądanie nie trzymało połączenia przez cały round-trip.
            await db.commit()
            raw = await run_in_threadpool(_call_model, system, prompt, chain)
        checked = await run_in_threadpool(verify_plan, raw, lines, requirements)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "[cv_command_ai] stage=%s failed (%s)", stage.id, type(exc).__name__
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[cv_command_ai] rollback failed")
        return _unavailable()
    if checked["operations"]:
        result = {"status": "ok", "message": None, **checked}
    else:
        message = MSG_ALL_DROPPED if checked["dropped"] else MSG_EMPTY
        result = {"status": "empty", "message": message, **checked}
    await _log(db, stage, user_id, payload, result)
    return result
