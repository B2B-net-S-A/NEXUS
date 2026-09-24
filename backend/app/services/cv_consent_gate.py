"""Blokada pobrania CV bez zrzutu zgody RODO (generator v3, 23.09.2026).

Centralna polityka klienta (dziś wyłącznie PKO BP) wymaga, żeby pod treścią
CV był widoczny zrzut maila ze zgodą kandydata. Do 23.09.2026 generacja bez
zrzutu dawała dokument, który dało się pobrać i wysłać — a bank odsyła takie
CV. Od generatora v3 zgodę można dołączyć (i wymienić) PO generacji, więc
generacja przechodzi, a blokada stoi na POBRANIU: DOCX, HTML, zatwierdzone
wersje, podgląd i druk edytora oraz link dla klienta.

Reguły, które łatwo cofnąć „przy okazji":

* Wymóg czytamy z polityki ZAMROŻONEJ na wierszu (``central_policy``), nie
  z bieżącej reguły klienta — dokument opisuje zasady, pod którymi powstał.
  Wiersze bez polityki centralnej (historia, klienci bez wymogu) nie są
  blokowane.
* Zatwierdzona wersja jest blokowana po WŁASNYM ``consent_content`` — wersja
  zatwierdzona przed dołączeniem zgody nie niesie obrazu, więc jej plik jest
  tym samym niekompletnym dokumentem.
* Odmowa to 409 ``{"code": "consent_required", "message": …}``; front
  pokazuje komunikat i przycisk dołączenia zgody.
* Wyłącznik awaryjny: ``CV_CONSENT_DOWNLOAD_GATE_ENABLED=false``.
* Blokada dotyczy POBRANIA, nie ruchu w pipeline ani edycji treści.
"""

from __future__ import annotations

from fastapi import HTTPException

from app.core.config import settings

CONSENT_REQUIRED_CODE = "consent_required"
CONSENT_REQUIRED_MESSAGE = (
    "Ten klient wymaga zrzutu zgody kandydata na przetwarzanie danych pod treścią "
    "CV. Dołącz zgodę do tego CV — do tego czasu nie da się go pobrać ani "
    "udostępnić."
)


def gate_enabled() -> bool:
    return bool(getattr(settings, "CV_CONSENT_DOWNLOAD_GATE_ENABLED", True))


def consent_required(row) -> bool:
    """Czy polityka zamrożona na wierszu wymaga zrzutu zgody RODO."""
    policy = getattr(row, "central_policy", None)
    return bool(isinstance(policy, dict) and policy.get("requires_rodo_consent_block"))


def consent_attached(row) -> bool:
    """Czy wiersz ma dołączony zrzut zgody.

    Czytamy WYŁĄCZNIE ``render_payload``: każdy zapis zgody (generacja,
    dołączenie po generacji) ustawia tam klucz w magazynie, a kolumna bajtów
    bywa odroczona (lista „Moje CV") — dotknięcie jej w sesji async to
    ``MissingGreenlet``.
    """
    payload = getattr(row, "render_payload", None)
    screenshot = (
        payload.get("consent_screenshot") if isinstance(payload, dict) else None
    )
    return bool(
        isinstance(screenshot, dict)
        and str(screenshot.get("storage_key") or "").strip()
    )


def consent_missing(row) -> bool:
    """Wymagana zgoda, a dokument jej nie ma — pobranie będzie zablokowane.

    Liczone przez wyłącznik awaryjny: front chowa „Pobierz” po tej fladze, więc
    bez tego zdjęcie blokady na serwerze nie zmieniłoby niczego w interfejsie.
    """
    return gate_enabled() and consent_required(row) and not consent_attached(row)


def _refuse() -> None:
    raise HTTPException(
        status_code=409,
        detail={"code": CONSENT_REQUIRED_CODE, "message": CONSENT_REQUIRED_MESSAGE},
    )


def ensure_downloadable(row, version=None) -> None:
    """409 ``consent_required``, gdy pliku nie wolno wydać bez zgody.

    ``row`` = wygenerowane CV (``CvGeneratedDocument``) albo ``None`` (CV etapu
    ze starego szablonu — bez polityki centralnej, bez blokady). ``version`` =
    zatwierdzona wersja, której plik ma wyjść: sprawdzamy jej własny obraz.
    """
    if row is None or not gate_enabled() or not consent_required(row):
        return
    if version is not None:
        if not getattr(version, "consent_content", None):
            _refuse()
        return
    if not consent_attached(row):
        _refuse()


__all__ = [
    "CONSENT_REQUIRED_CODE",
    "CONSENT_REQUIRED_MESSAGE",
    "consent_attached",
    "consent_missing",
    "consent_required",
    "ensure_downloadable",
    "gate_enabled",
]
