"""Przewodniki ekranów Jarvisa (``app/data/screen_guides``).

Treść pomocy bez danych domenowych — czyta ją każda zalogowana osoba, jak
procedury w Pomocy. Przewodnik ekranu, którego ktoś nie ma w menu (brak
sekcji), i kotwice przycisków, których nie widzi, są odfiltrowane.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from app.api.deps import CurrentUser
from app.data.screen_guides import guide_for_user, load_guides
from app.services.section_permissions import ProductSection, section_access_for_user

router = APIRouter()


def _audience(user: Any) -> tuple[set[str], dict[str, int]]:
    try:
        roles = {getattr(r, "value", str(r)) for r in user.get_all_roles()}
    except Exception:  # noqa: BLE001 — rola główna wystarcza jako zapas
        roles = {getattr(user.role, "value", str(user.role))}
    sections = {
        section.value: int(section_access_for_user(user, section))
        for section in ProductSection
    }
    return roles, sections


@router.get("/help/screens")
async def list_screen_guides(current_user: CurrentUser) -> list[dict[str, Any]]:
    roles, sections = _audience(current_user)
    out = []
    for guide in load_guides().values():
        shaped = guide_for_user(guide, roles, sections)
        if shaped is not None:
            out.append(shaped)
    return out


@router.get("/help/screens/{key}")
async def get_screen_guide(key: str, current_user: CurrentUser) -> dict[str, Any]:
    guide = load_guides().get(key)
    if guide is None:
        raise HTTPException(
            status_code=404, detail="Nie ma przewodnika dla tego ekranu."
        )
    roles, sections = _audience(current_user)
    shaped = guide_for_user(guide, roles, sections)
    if shaped is None:
        raise HTTPException(
            status_code=404, detail="Nie ma przewodnika dla tego ekranu."
        )
    return shaped
