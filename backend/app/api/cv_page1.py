"""Strona 1 „Nowego CV” w edytorze: „najmocniejszy wynik” (22.11.2026).

  PATCH  /api/candidates/stages/{stage_id}/cv/page1

Wyróżnik kandydata (25.11.2026): `highlight` = „auto” (praca u klienta
rekrutacji, z dat stanowisk), „custom” (etykieta, znak w wieńcu, zdanie
rekrutera) albo „off”.

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

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import CandidateWriteAccess
from app.api.candidate_stage_cv import _build_branded_response, _load_csv_for_stage
from app.core.database import get_db
from app.models.activity import Activity
from app.schemas.candidate_stage_cv import CVBrandedResponse
from app.services import cv_layout as layout_service
from app.services.cv_new_layout.highlight import LABEL_MAX, TEXT_MAX, TOKEN_MAX

router = APIRouter()

RESULT_TEXT_MAX = 400

MSG_FINALIZED = (
    "CV jest zatwierdzone — zmień najpierw treść w edytorze, żeby powstał nowy szkic."
)
MSG_EMPTY = "Podaj wynik do strony 1."
MSG_BAD_INDEX = "Tego wyniku nie ma na liście sprawdzonych wyników."


MSG_HIGHLIGHT_EMPTY = "Wyróżnik potrzebuje etykiety i zdania."


class HighlightUpdate(BaseModel):
    """Wyróżnik pod nazwiskiem: „auto” = praca u klienta rekrutacji, „custom” = wpis rekrutera."""

    mode: Literal["auto", "custom", "off"]
    label: Optional[str] = Field(default=None, max_length=LABEL_MAX)
    token: Optional[str] = Field(default=None, max_length=TOKEN_MAX)
    text: Optional[str] = Field(default=None, max_length=TEXT_MAX)


class Page1Update(BaseModel):
    """`result_index` wybiera sprawdzony wynik (i czyści wpisane zdanie, gdy
    `result_text: null`); `result_text` = zdanie rekrutera, pusty = brak."""

    result_index: Optional[int] = Field(default=None, ge=0)
    result_text: Optional[str] = Field(default=None, max_length=RESULT_TEXT_MAX * 2)
    highlight: Optional[HighlightUpdate] = None


def _verified_results(extras: dict) -> list:
    results = extras.get("results")
    return results if isinstance(results, list) else []


def _merged(extras: Optional[dict], payload: Page1Update) -> dict:
    """Nowe dodatki strony 1; nieznane pola (np. `why`, `results`) zostają."""
    merged = dict(extras) if isinstance(extras, dict) else {}
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
        else:
            fields = {
                key: " ".join((getattr(choice, key) or "").split())
                for key in ("label", "token", "text")
            }
            if not (fields["label"] and fields["text"]):
                raise HTTPException(422, MSG_HIGHLIGHT_EMPTY)
            merged["highlight"] = {"mode": "custom", **fields}
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
    """Strona 1 „Nowego CV”: najmocniejszy wynik (wpisany albo z listy) i wyróżnik."""
    from app.services.new_cv_company_cv import locked_after_send

    if not layout_service.enabled():
        raise HTTPException(409, layout_service.MSG_DISABLED)
    if not payload.model_fields_set & {
        "result_index",
        "result_text",
        "highlight",
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
    merged = _merged(before, payload)
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
                    "version": csv.branded_version,
                },
            )
        )
        await db.commit()
    return _build_branded_response(csv)
