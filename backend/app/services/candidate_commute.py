"""Karta dojazdu przy odrzuceniu „Lokalizacja lub tryb pracy” (27.11.2026).

Decyzja Artura: wariant D (https://claude.ai/artifact/66p2W5u7cB9oPfC8ZEpoPm).
Okno pyta „Co nie pasuje?”: za daleko do biura (gdzie mieszka, do jakich biur
dojedzie, inne miasto raz w miesiącu, przeprowadzka) albo za dużo dni
w biurze (dni + zgoda na więcej przy wyjątkowym projekcie). Wcześniej okno
pytało tylko o dni z domyślnym 0, więc na kopii produkcji 141 z 224 takich
osób dostało fałszywe „Tylko zdalnie”, a 36 z 53 notatek przy tym powodzie
podawało miasto, które nigdzie nie trafiało.

Tu: reguły „które pole przy czym” (422 przed zapisem), linia opisu do
historii procesu i zapis odpowiedzi o dojeździe w ``preferences``. Miasto
zamieszkania pisze ``residence.record_city_from_rejection``, dni w biurze —
``candidate_notes_facts.set_work_mode_from_rejection``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm.attributes import flag_modified

# Skąd są odpowiedzi o dojeździe na profilu — rekrutacja, data, kto.
COMMUTE_SOURCE_KEY = "commute_source"

_DISTANCE_FIELDS = (
    "residence_city",
    "commute_office_cities",
    "occasional_commute",
    "relocation_willing",
    "relocation_targets",
)


def rejection_fields_error(data: Any, *, work_mode_rejection: bool) -> Optional[str]:
    """Polski komunikat 422, gdy pola karty dojazdu nie pasują do powodu
    albo do odpowiedzi „Co nie pasuje?”; ``None`` = ruch może iść dalej."""
    issue = data.work_mode_issue
    distance_given = any(getattr(data, name) is not None for name in _DISTANCE_FIELDS)
    if not work_mode_rejection:
        if data.work_mode_max_onsite_days is not None:
            return (
                "Liczbę dni w biurze podaje się tylko przy powodzie "
                "„Nie akceptuje trybu pracy”."
            )
        if (
            issue is not None
            or distance_given
            or data.accepts_more_office_days is not None
        ):
            return (
                "Dojazd, przeprowadzkę i zgodę na więcej dni w biurze podaje się "
                "tylko przy powodzie „Lokalizacja lub tryb pracy”."
            )
        return None
    if issue != "distance":
        # Stare wywołania (`None`) i „za dużo dni” — dni są obowiązkowe jak dotąd.
        if data.work_mode_max_onsite_days is None:
            return "Podaj, ile dni w biurze kandydat akceptuje."
        if distance_given:
            return (
                "Miasto, dojazd i przeprowadzkę podaje się tylko przy "
                "„Za daleko do biura”."
            )
    if issue != "office_days" and data.accepts_more_office_days is not None:
        return (
            "Zgodę na więcej dni w biurze podaje się tylko przy "
            "„Chce mniej dni w biurze”."
        )
    if data.relocation_targets is not None and data.relocation_willing is not True:
        return (
            "Miasta przeprowadzki podaje się tylko, gdy kandydat zgadza się "
            "na przeprowadzkę."
        )
    return None


def _days_text(days: int, *, in_office: str) -> str:
    if days == 0:
        return "tylko zdalnie"
    return f"do {days} {'dnia' if days == 1 else 'dni'}{in_office}"


def _yes_no(value: bool) -> str:
    return "tak" if value else "nie"


def rejection_note(data: Any, *, notes: Optional[str]) -> Optional[str]:
    """Odpowiedź z karty jedną linią przed opisem rekrutera (historia procesu).

    Jak „Chce min. 150 zł/h” przy „za drogo”: profil pokazuje odrzucenie jako
    „Powód — opis”, więc odpowiedź stoi tam także przy pustym opisie. Stare
    wywołania (bez „Co nie pasuje?”) zostawiają opis bez zmian.
    """
    issue = data.work_mode_issue
    if issue is None:
        return notes
    days = data.work_mode_max_onsite_days
    if issue == "distance":
        parts = ["Za daleko do biura"]
        if data.residence_city:
            parts.append(f"mieszka: {data.residence_city}")
        if data.commute_office_cities:
            parts.append(f"dojedzie do: {', '.join(data.commute_office_cities)}")
        if days is not None:
            parts.append(_days_text(days, in_office=" w biurze"))
        if data.occasional_commute is not None:
            parts.append(
                "inne miasto: raz w miesiącu"
                if data.occasional_commute
                else "inne miasto: nie"
            )
        if data.relocation_willing is not None:
            targets = data.relocation_targets or []
            reloc = f"przeprowadzka: {_yes_no(data.relocation_willing)}"
            if data.relocation_willing and targets:
                reloc += f" ({', '.join(targets)})"
            parts.append(reloc)
    else:
        parts = ["Chce mniej dni w biurze"]
        if days is not None:
            parts.append(_days_text(days, in_office=""))
        if data.accepts_more_office_days is not None:
            parts.append(
                "więcej przy wyjątkowym projekcie: "
                f"{_yes_no(data.accepts_more_office_days)}"
            )
    line = " · ".join(parts)
    rest = (notes or "").strip()
    return f"{line} — {rest}" if rest else line


def apply_commute_from_rejection(
    candidate: Any,
    *,
    office_cities: Optional[list[str]],
    occasional_commute: Optional[bool],
    relocation_willing: Optional[bool],
    relocation_targets: Optional[list[str]],
    origin: dict,
) -> dict[str, dict]:
    """Odpowiedzi o dojeździe w ``preferences``. Zwraca ``{klucz: {before, after}}``
    tylko dla kluczy, które się zmieniły; przy zmianie dopisuje źródło
    (``commute_source``). Najświeższa odpowiedź z rozmowy nadpisuje profil.
    Bez commitu i bez audytu — to robi wołający."""
    wanted: dict[str, Any] = {}
    if office_cities:
        wanted["office_cities"] = list(office_cities)
    if occasional_commute is not None:
        wanted["occasional_commute"] = bool(occasional_commute)
    if relocation_willing is not None:
        wanted["relocation"] = {
            "willing": bool(relocation_willing),
            "targets": list(relocation_targets or []) if relocation_willing else [],
        }
    current = candidate.preferences
    prefs = dict(current) if isinstance(current, dict) else {}
    changed = {
        key: {"before": prefs.get(key), "after": value}
        for key, value in wanted.items()
        if prefs.get(key) != value
    }
    if not changed:
        return {}
    for key in changed:
        prefs[key] = wanted[key]
    prefs[COMMUTE_SOURCE_KEY] = dict(origin)
    candidate.preferences = prefs
    flag_modified(candidate, "preferences")
    return changed
