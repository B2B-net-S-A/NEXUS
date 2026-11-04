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
* Kopia (szkic CV etapu, szkic edytora generatora) jest sprawdzana po WŁASNYM
  obrazie (``branded_consent_content``) — to z niego renderuje się DOCX. Wymóg
  zgody jest zamrożony w metadanych kopii (``consent_required``), więc
  usunięcie wygenerowanego CV (FK ``SET NULL``) nie zdejmuje blokady (runda 7,
  R7-X4-1 i R7-X4-4).
* Druk / PDF nigdy nie niesie obrazu zgody, więc przy wymogu zgody jest
  zablokowany zawsze — tym samym kodem 409 i tym samym wyłącznikiem (decyzja
  właściciela 26.09.2026, R7-X4-3).
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


PRINT_BLOCKED_MESSAGE = (
    "Ten klient wymaga zrzutu zgody kandydata na przetwarzanie danych pod treścią "
    "CV, a wydruk go nie zawiera. Pobierz DOCX — ma zgodę pod treścią."
)
# Klucz w metadanych kopii CV (etap, wersja) — wymóg zgody zamrożony przy
# podpięciu wygenerowanego CV; przeżywa usunięcie wiersza generatora.
FROZEN_REQUIREMENT_KEY = "consent_required"


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


def _refuse(message: str = CONSENT_REQUIRED_MESSAGE) -> None:
    raise HTTPException(
        status_code=409,
        detail={"code": CONSENT_REQUIRED_CODE, "message": message},
    )


def with_frozen_requirement(metadata, generated) -> dict:
    """Metadane kopii z zamrożonym wymogiem zgody wiersza ``generated``.

    Zawsze nowy słownik (kolumna JSON nie śledzi zmian w miejscu). Wymóg raz
    zamrożony nie jest zdejmowany: kopia opisuje zasady, pod którymi powstał
    dokument źródłowy.
    """
    frozen = dict(metadata or {})
    if consent_required(generated):
        frozen[FROZEN_REQUIREMENT_KEY] = True
    return frozen


def copy_consent_required(generated, copy) -> bool:
    """Wymóg zgody kopii: z wiersza generatora, a bez niego — zamrożony."""
    if generated is not None and consent_required(generated):
        return True
    metadata = getattr(copy, "branded_render_metadata", None)
    return bool(isinstance(metadata, dict) and metadata.get(FROZEN_REQUIREMENT_KEY))


def ensure_copy_downloadable(generated, copy, version=None) -> None:
    """409 ``consent_required`` dla pliku renderowanego z KOPII CV.

    ``copy`` = ``CandidateStageCV`` albo ``CvGeneratedDraft``; DOCX szkicu
    powstaje z ``copy.branded_consent_content``, więc to ten obraz musi być
    (wiersz generatora bywa już ze zgodą, a kopia — ze starszej wersji bez
    niej). ``version`` = zatwierdzona wersja: jej własny obraz.
    """
    if not gate_enabled() or not copy_consent_required(generated, copy):
        return
    if version is not None:
        if not getattr(version, "consent_content", None):
            _refuse()
        return
    if not getattr(copy, "branded_consent_content", None):
        _refuse()


def ensure_printable(generated, copy=None) -> None:
    """Druk / PDF przy wymogu zgody jest zablokowany zawsze (R7-X4-3).

    Wydruk składa się z HTML edytora i nie niesie obrazu zgody. Bez zgody —
    ten sam komunikat co przy pobraniu; ze zgodą — prośba o DOCX.
    """
    if not gate_enabled():
        return
    required = (
        copy_consent_required(generated, copy)
        if copy is not None
        else generated is not None and consent_required(generated)
    )
    if not required:
        return
    has_image = (
        bool(getattr(copy, "branded_consent_content", None))
        if copy is not None
        else consent_attached(generated)
    )
    _refuse(PRINT_BLOCKED_MESSAGE if has_image else CONSENT_REQUIRED_MESSAGE)


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
    "copy_consent_required",
    "ensure_copy_downloadable",
    "ensure_downloadable",
    "ensure_printable",
    "with_frozen_requirement",
    "gate_enabled",
]
