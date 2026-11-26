"""Strona 1 „Nowego CV” w edytorze: „najmocniejszy wynik” (22.11.2026).

  PATCH  /api/candidates/stages/{stage_id}/cv/page1

Zdania 1–3 „Dlaczego nasz kandydat” (25.11.2026): `why` = trzy sloty, każdy
to sprawdzone zdanie modelu (`services/cv_page1_why.py`) albo zdanie
poprawione przez rekrutera. W żądaniu `null` w slocie = bez zmiany, pusty
napis = „Przywróć z generatora” (sprawdzone zdanie modelu, a bez niego punkt
generatora — `cv_layout.compose_page1_why`).

Wyróżnik kandydata (25.11.2026): `highlight` = „auto” (praca u klienta
rekrutacji, z dat stanowisk), „custom” (etykieta, znak w wieńcu, zdanie
rekrutera) albo „off”. Od 26.11.2026 także „ai” z `proposal` = numer
sprawdzonej propozycji z `highlight_proposals` (przyjęcie rekrutera: kod
sprawdza jeszcze raz cytat na bieżącym szkicu), a `highlight_reject` = numer
propozycji, którą rekruter odrzuca (znika i nie wraca przy kolejnym biegu).
Bez przyjęcia propozycja nie trafia do CV — render czyta tylko `highlight`.

Trzeci punkt strony 1 to dodatek CV (`candidate_stage_cvs.page1_extras`), nie
treść edytora: zdanie wpisane przez rekrutera (`result_text`) albo wybrany
sprawdzony wynik z listy (`result_index` w `results`). Punkty 1–2 („lata”,
„technologie”) edytor zmienia w samym HTML-u, bo dzielą je z plikiem Word
(`services/cv_layout.compose_page1_why`).

Zasady jak przy przełączniku układu (`PATCH …/cv/layout`): bramka zapisu
w kandydatach + zespół rekrutacji (`_load_csv_for_stage`), po „CV wysłane”
409. Zatwierdzona wersja ma dodatki zamrożone, więc trasa zmienia tylko
szkic — edytor zakłada go wcześniej (`ensureDraft`), tak jak przy każdej
innej poprawce. Wpis w Historii zdarzeń bez treści zdania.
"""

from typing import Annotated, Callable, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.candidate_stage_cv import _branded_response, _load_csv_for_stage
from app.core.database import get_db
from app.models.activity import Activity
from app.schemas.candidate_stage_cv import CVBrandedResponse
from app.services import cv_layout as layout_service
from app.services import cv_page1_highlight_checks as highlight_checks
from app.services.cv_new_content import cv_json_from_editor_html
from app.services.cv_new_layout.highlight import LABEL_MAX, TEXT_MAX, TOKEN_MAX

router = APIRouter()

RESULT_TEXT_MAX = 400
WHY_TEXT_MAX = 400

MSG_FINALIZED = (
    "CV jest zatwierdzone — zmień najpierw treść w edytorze, żeby powstał nowy szkic."
)
MSG_EMPTY = "Podaj wynik do strony 1."
MSG_BAD_INDEX = "Tego wyniku nie ma na liście sprawdzonych wyników."


MSG_HIGHLIGHT_EMPTY = "Wyróżnik potrzebuje etykiety i zdania."
MSG_BAD_PROPOSAL = "Tej propozycji wyróżnika nie ma na liście sprawdzonych propozycji."
MSG_PROPOSAL_STALE = "Tego fragmentu nie ma już w CV — poszukaj propozycji od nowa albo wpisz własny wyróżnik."


class HighlightUpdate(BaseModel):
    """Wyróżnik pod nazwiskiem: „auto” = praca u klienta rekrutacji, „ai” =
    przyjęta propozycja AI (`proposal`), „custom” = wpis rekrutera."""

    mode: Literal["auto", "ai", "custom", "off"]
    label: Optional[str] = Field(default=None, max_length=LABEL_MAX)
    token: Optional[str] = Field(default=None, max_length=TOKEN_MAX)
    text: Optional[str] = Field(default=None, max_length=TEXT_MAX)
    proposal: Optional[int] = Field(default=None, ge=0)


# Długość po złączeniu spacji sprawdza `_why` (422 z polskim zdaniem); tu tylko
# twardy sufit na ciało żądania.
WhySlot = Annotated[str, Field(max_length=WHY_TEXT_MAX * 2)]


class Page1Update(BaseModel):
    """`result_index` wybiera sprawdzony wynik (i czyści wpisane zdanie, gdy
    `result_text: null`); `result_text` = zdanie rekrutera, pusty = brak."""

    result_index: Optional[int] = Field(default=None, ge=0)
    result_text: Optional[str] = Field(default=None, max_length=RESULT_TEXT_MAX * 2)
    highlight: Optional[HighlightUpdate] = None
    # Numer propozycji wyróżnika AI, którą rekruter odrzuca.
    highlight_reject: Optional[int] = Field(default=None, ge=0)
    # Zdania 1–3 strony 1: `null` = slot bez zmiany, "" = z generatora.
    why: Optional[list[Optional[WhySlot]]] = Field(default=None, max_length=3)


def _why(extras: dict, sent: list[Optional[str]]) -> list[str]:
    """Sloty po zmianie rekrutera; pusty slot bierze sprawdzone zdanie modelu."""
    from app.services.cv_page1_why_checks import auto_texts, why_slots

    slots = why_slots(extras)
    auto = auto_texts(extras.get("why_generated"))
    for index, value in enumerate(sent):
        if value is None:
            continue
        text = " ".join(value.split())
        if len(text) > WHY_TEXT_MAX:
            raise HTTPException(
                422,
                f"Zdanie na stronie 1 może mieć najwyżej {WHY_TEXT_MAX} znaków.",
            )
        slots[index] = text or auto[index]
    return slots


def _verified_results(extras: dict) -> list:
    results = extras.get("results")
    return results if isinstance(results, list) else []


def _proposal(extras: dict, index: Optional[int]) -> dict:
    items = highlight_checks.proposals(extras)
    if index is None or index >= len(items) or items[index].get("verified") is not True:
        raise HTTPException(422, MSG_BAD_PROPOSAL)
    return items[index]


def _key(proposal: dict) -> str:
    return proposal.get("key") or highlight_checks.proposal_key(proposal)


def _rejected(merged: dict, key: str) -> dict:
    """Dodatki po odrzuceniu propozycji: znika z listy, jej odcisk idzie na listę
    odrzuconych (nie wraca przy kolejnym biegu); odrzucenie przyjętej wraca do
    automatu."""
    out = dict(merged)
    out["highlight_proposals"] = [
        p for p in highlight_checks.proposals(out) if _key(p) != key
    ]
    out["highlight_rejected"] = [
        *[k for k in highlight_checks.rejected_keys(out) if k != key],
        key,
    ]
    current = out.get("highlight")
    if (
        isinstance(current, dict)
        and current.get("mode") == "ai"
        and current.get("key") == key
    ):
        out.pop("highlight")
    return out


def _merged(
    extras: Optional[dict],
    payload: Page1Update,
    stands_in_cv: Callable[[dict], bool] = lambda highlight: True,
) -> dict:
    """Nowe dodatki strony 1; nieznane pola (np. `why`, `results`) zostają.

    ``stands_in_cv`` sprawdza przyjmowaną propozycję AI na bieżącym szkicu."""
    merged = dict(extras) if isinstance(extras, dict) else {}
    original = dict(merged)
    sent = payload.model_fields_set
    if "result_index" in sent:
        index = payload.result_index
        results = _verified_results(merged)
        if index is None:
            merged.pop("result_index", None)
        elif not (
            index < len(results)
            and isinstance(results[index], dict)
            and results[index].get("verified") is True
        ):
            raise HTTPException(422, MSG_BAD_INDEX)
        else:
            merged["result_index"] = index
    if "result_text" in sent:
        text = " ".join((payload.result_text or "").split())
        if len(text) > RESULT_TEXT_MAX:
            raise HTTPException(
                422, f"Wynik na stronie 1 może mieć najwyżej {RESULT_TEXT_MAX} znaków."
            )
        if text:
            merged["result_text"] = text
        else:
            merged.pop("result_text", None)
    if "highlight" in sent:
        choice = payload.highlight
        if choice is None or choice.mode == "auto":
            merged.pop("highlight", None)
        elif choice.mode == "off":
            merged["highlight"] = {"mode": "off"}
        elif choice.mode == "ai":
            accepted = highlight_checks.accepted_highlight(
                _proposal(original, choice.proposal)
            )
            if not stands_in_cv(accepted):
                raise HTTPException(422, MSG_PROPOSAL_STALE)
            merged["highlight"] = accepted
        else:
            fields = {
                key: " ".join((getattr(choice, key) or "").split())
                for key in ("label", "token", "text")
            }
            if not (fields["label"] and fields["text"]):
                raise HTTPException(422, MSG_HIGHLIGHT_EMPTY)
            merged["highlight"] = {"mode": "custom", **fields}
    if "highlight_reject" in sent and payload.highlight_reject is not None:
        items = highlight_checks.proposals(original)
        if payload.highlight_reject >= len(items):
            raise HTTPException(422, MSG_BAD_PROPOSAL)
        merged = _rejected(merged, _key(items[payload.highlight_reject]))
    if "why" in sent and payload.why is not None:
        merged["why"] = _why(merged, payload.why)
    return merged


@router.patch(
    "/candidates/stages/{stage_id}/cv/page1",
    response_model=CVBrandedResponse,
)
async def update_stage_cv_page1(
    stage_id: int,
    payload: Page1Update,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> CVBrandedResponse:
    """Strona 1 „Nowego CV”: zdania 1–3, najmocniejszy wynik (wpisany albo z listy) i wyróżnik."""
    from app.services.new_cv_company_cv import locked_after_send

    if not layout_service.enabled():
        raise HTTPException(409, layout_service.MSG_DISABLED)
    if not payload.model_fields_set & {
        "result_index",
        "result_text",
        "highlight",
        "highlight_reject",
        "why",
    }:
        raise HTTPException(422, MSG_EMPTY)
    csv = await _load_csv_for_stage(db, stage_id, current_user, lock=True)
    if csv.branded_status == "none":
        raise HTTPException(409, layout_service.MSG_NO_CV)
    if await locked_after_send(db, csv):
        raise HTTPException(409, layout_service.MSG_LOCKED)
    if csv.branded_status != "draft":
        raise HTTPException(409, MSG_FINALIZED)
    before = csv.page1_extras if isinstance(csv.page1_extras, dict) else {}
    blind = csv.branded_template == "blind"

    def stands_in_cv(highlight: dict) -> bool:
        cv_json = cv_json_from_editor_html(
            csv.branded_draft_html or "",
            language="en" if csv.branded_language == "en" else "pl",
            blind=blind,
        ).cv_json
        return highlight_checks.stands_in_cv(highlight, cv_json, blind=blind)

    merged = _merged(before, payload, stands_in_cv)
    if merged != before:
        csv.page1_extras = merged
        db.add(
            Activity(
                entity_type="candidate_stage_cv",
                entity_id=csv.id,
                action="cv_page1_changed",
                user_id=current_user.id,
                details={
                    "candidate_stage_id": csv.candidate_stage_id,
                    "fields": sorted(payload.model_fields_set),
                    "result_index": merged.get("result_index"),
                    "result_text": bool(merged.get("result_text")),
                    "highlight": (merged.get("highlight") or {}).get("mode", "auto"),
                    # Które sloty `why` mają zdanie — bez treści zdań.
                    "why": [bool(t) for t in merged.get("why") or []],
                    "version": csv.branded_version,
                },
            )
        )
        await db.commit()
    return await _branded_response(db, csv)
