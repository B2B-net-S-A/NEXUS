"""Jeden stan QC pary z serwera (audyt 08.11.2026, QC-11).

Ten sam fakt tłumaczyło sześć miejsc po swojemu: „Przepuszczone mimo QC”,
„QC przepuszczone”, „przepuszczone mimo uwag (z powodem)”. Każda poprawka stanu
szła w sześciu kopiach i kopie się rozjechały. Tu jest słownik: nazwa, liczba,
ton i dymek. Front tylko to renderuje.
"""

from __future__ import annotations

from typing import Optional, Sequence

CHECKED = "checked"
CHECKED_MANUALLY = "checked_manually"
VERIFY_ROLES = "verify_roles"
CANDIDATE_GAP = "candidate_gap"
TO_FIX = "to_fix"
OVERRIDDEN = "overridden"
UNCHECKED = "unchecked"

CONSENT_MANUAL_ITEM = "Zgoda RODO — obejrzyj plik"
# Dłuższa nazwa nie mieści się na chipie karty — wtedy zostaje liczba.
_GAP_NAME_ON_CHIP_MAX = 24


def _state(
    kind: str,
    text: str,
    tone: str,
    *,
    n: int = 0,
    items: Sequence[str] = (),
    who: Optional[str] = None,
    hint: Optional[str] = None,
) -> dict:
    return {
        "kind": kind,
        "n": n,
        "items": list(items),
        "text": text,
        "tone": tone,
        "who": who,
        "hint": hint,
    }


def _with_who(text: str, who: Optional[str]) -> str:
    return f"{text} · {who}" if who else text


def _rzeczy(n: int) -> str:
    if n == 1:
        return "1 rzecz zatrzymuje"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} rzeczy zatrzymują"
    return f"{n} rzeczy zatrzymuje"


def _verify_roles(items: Sequence[str], unverified: Sequence[str]) -> dict:
    n = len(items)
    listed = ", ".join(items)
    if unverified:
        text, hint = (
            f"QC: wskaż stanowisko · {n}",
            f"Nikt nie sprawdził opisu w rolach: {listed}.",
        )
    elif list(items) == [CONSENT_MANUAL_ITEM]:
        text, hint = (
            "QC: obejrzyj zgodę RODO",
            "Zgoda RODO jest w pliku kandydata — obejrzyj ją przed wysłaniem.",
        )
    else:
        text, hint = (
            f"QC: sprawdź ręcznie · {n}",
            f"QC tego nie umiało sprawdzić: {listed}.",
        )
    return _state(VERIFY_ROLES, text, "wait", n=n, items=items, hint=hint)


def _candidate_gap(gaps: Sequence[str]) -> dict:
    n = len(gaps)
    text = (
        f"QC: kandydat nie ma: {gaps[0]}"
        if n == 1 and len(gaps[0]) <= _GAP_NAME_ON_CHIP_MAX
        else f"QC: kandydat nie ma · {n}"
    )
    return _state(
        CANDIDATE_GAP,
        text,
        "wait",
        n=n,
        items=gaps,
        hint=(
            f"Kandydat nie ma: {', '.join(gaps)}. W CV nie ma czego poprawić — "
            "o wysyłce decyduje Delivery Lead."
        ),
    )


def describe(
    *,
    status: str,
    blocking_failed: int = 0,
    manual_items: Sequence[str] = (),
    unverified: Sequence[str] = (),
    candidate_gaps: Sequence[str] = (),
    manual_requirements: Sequence[str] = (),
    manual_by: Optional[str] = None,
    override_by: Optional[str] = None,
    to_fix_items: Sequence[str] = (),
) -> dict:
    """``qc_state`` pary: {kind, n, items, text, tone, who, hint}.

    „Wskaż stanowisko” wygrywa z luką kandydata: najpierw ruch rekrutera, a o
    luce decyduje Delivery Lead, kiedy para już do niego trafi.
    """

    if status == "unchecked":
        return _state(
            UNCHECKED,
            "QC: jeszcze nie sprawdzone",
            "neutral",
            hint="Nikt jeszcze nie uruchomił kontroli CV — kliknij, żeby sprawdzić.",
        )
    if status == "failed":
        n = max(1, int(blocking_failed or 0))
        named = "; ".join(to_fix_items)
        return _state(
            TO_FIX,
            f"QC: {n} do poprawy",
            "urgent",
            n=n,
            items=to_fix_items,
            hint=f"{_rzeczy(n)} wysyłkę{f': {named}' if named else ''}.",
        )
    if status == "overridden":
        return _state(
            OVERRIDDEN,
            _with_who("QC: przepuszczone", override_by),
            "wait",
            who=override_by,
            hint="Przepuszczone mimo uwag QC. Uwagi nadal widać w oknie QC.",
        )
    if manual_items:
        return _verify_roles(manual_items, unverified)
    if candidate_gaps:
        return _candidate_gap(candidate_gaps)
    if manual_by:
        return _state(
            CHECKED_MANUALLY,
            _with_who("QC: sprawdzone ręcznie", manual_by),
            "info",
            n=len(manual_requirements),
            items=manual_requirements,
            who=manual_by,
            hint=(
                f"Stanowiska wskazano ręcznie: {', '.join(manual_requirements)}."
                if manual_requirements
                else "Stanowiska wskazano ręcznie."
            ),
        )
    return _state(
        CHECKED, "QC: sprawdzone", "ok", hint="CV przeszło kontrolę przed wysłaniem."
    )
