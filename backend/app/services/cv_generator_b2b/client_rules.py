"""Stosowanie reguł CV klienta: nazwa pliku, wymuszony język, opis polityki.

Wejście to zatwierdzony wiersz ``client_cv_rules``. Reguła niezatwierdzona
(``confirmed_at IS NULL``) jest **niewidoczna dla runtime'u** — zasiane
propozycje czekają na człowieka, więc błędne dopasowanie szablonu do klienta
nie może wejść w życie po cichu.

Cztery tokeny i jedna flaga pokrywają wszystkie 14 wzorów nazw wyciągniętych
z szablonów Championa:

    {STANOWISKO}      nazwa roli — z ``Job.title`` (tryb "new") albo z pola
                      formularza (tryb "upload", gdzie joba nie ma)
    {IMIE_NAZWISKO}   kandydat
    {PROJEKT}         numer/nazwa projektu — TYLKO tryb "new"
    {DATA}            data generacji (YYYY-MM-DD), wymaga jej Credit Agricole

Flaga ``spaces_to_underscores`` decyduje, czy spacje wewnątrz PODSTAWIONEJ
wartości zamieniają się na ``_``. Dzięki niej „Jan Kowalski" → „Jan_Kowalski"
daje ``Imię_Nazwisko`` bez osobnych tokenów na imię i nazwisko.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.client_cv_rule import ClientCvRule

# Tokeny rozpoznawane we wzorze nazwy pliku. Nieznany token zostaje w nazwie
# dosłownie — lepiej, żeby rekruter zobaczył „{FOO}" w pliku i poprawił wzór,
# niż żeby literówka cicho zniknęła razem z fragmentem nazwy.
TOKEN_POSITION = "{STANOWISKO}"
TOKEN_FULL_NAME = "{IMIE_NAZWISKO}"
TOKEN_PROJECT = "{PROJEKT}"
TOKEN_DATE = "{DATA}"

KNOWN_TOKENS: tuple[str, ...] = (
    TOKEN_POSITION,
    TOKEN_FULL_NAME,
    TOKEN_PROJECT,
    TOKEN_DATE,
)

# Etykiety PL do komunikatów o brakujących wartościach.
_TOKEN_LABELS: dict[str, str] = {
    TOKEN_POSITION: "stanowisko",
    TOKEN_FULL_NAME: "imię i nazwisko",
    TOKEN_PROJECT: "numer projektu",
    TOKEN_DATE: "data",
}

# Separatory, które wolno zwinąć po wypadnięciu pustego tokenu. Kropka NIE jest
# separatorem — „B2B.NET" to część nazwy firmy w wzorze Credit Agricole.
_SEPARATORS = "_-"


@dataclass(frozen=True)
class CvRuleSnapshot:
    """Niezmienna kopia reguły, bezpieczna poza sesją bazy.

    Pipeline generacji jest synchroniczny i leci w ``run_in_threadpool``.
    Wiersz ORM przekazany tam potrafi przy dostępie do atrybutu spróbować
    doczytać coś z bazy — w async SQLAlchemy kończy się to ``MissingGreenlet``,
    czyli 500 bez CORS-a, widocznym w UI jako „Network Error". Snapshot nie ma
    jak tego zrobić.
    """

    filename_pattern: str | None
    spaces_to_underscores: bool
    cv_language: str | None
    requires_en_copy: bool
    requires_rodo_consent_block: bool


def snapshot_rule(rule: Optional[ClientCvRule]) -> Optional[CvRuleSnapshot]:
    """Zamroź wiersz reguły do postaci przenoszalnej między wątkami."""
    if rule is None:
        return None
    return CvRuleSnapshot(
        filename_pattern=rule.filename_pattern,
        spaces_to_underscores=bool(rule.spaces_to_underscores),
        cv_language=rule.cv_language,
        requires_en_copy=bool(rule.requires_en_copy),
        requires_rodo_consent_block=bool(rule.requires_rodo_consent_block),
    )


@dataclass(frozen=True)
class FilenameResult:
    """Nazwa pliku plus ostrzeżenia o tokenach, których nie dało się wypełnić."""

    filename: str
    warnings: tuple[str, ...]


def _apply_word_separator(value: str, spaces_to_underscores: bool) -> str:
    collapsed = re.sub(r"\s+", " ", value).strip()
    if spaces_to_underscores:
        return collapsed.replace(" ", "_")
    return collapsed


def _collapse_separators(stem: str) -> str:
    """Zwiń ślady po pustych tokenach: „B2B__Jan" → „B2B_Jan", „ZOB-_X" → „ZOB_X"."""
    collapsed = re.sub(rf"[{_SEPARATORS}]{{2,}}", "_", stem)
    return collapsed.strip(_SEPARATORS + " ")


def build_filename(
    rule: Optional[CvRuleSnapshot],
    *,
    position: str | None,
    candidate_name: str,
    project: str | None = None,
    today: date | None = None,
) -> Optional[FilenameResult]:
    """Złóż nazwę pliku wg wzoru klienta.

    Zwraca ``None``, gdy reguły nie ma albo nie ma ona wzoru — wtedy woła się
    dotychczasowy, globalny ``_build_download_filename`` i **nic się nie zmienia**.

    Brakująca wartość tokenu nie przerywa generacji: token znika razem
    z osieroconym separatorem, a rekruter dostaje ostrzeżenie, żeby uzupełnić
    nazwę ręcznie. Zablokowanie generacji z powodu nieuzupełnionego numeru
    projektu byłoby gorsze niż plik do przemianowania.
    """
    if rule is None or not (rule.filename_pattern or "").strip():
        return None

    pattern = rule.filename_pattern.strip()
    sep = bool(rule.spaces_to_underscores)

    values: dict[str, str] = {
        TOKEN_POSITION: _apply_word_separator(position or "", sep),
        TOKEN_FULL_NAME: _apply_word_separator(candidate_name or "", sep),
        TOKEN_PROJECT: _apply_word_separator(project or "", sep),
        TOKEN_DATE: (today or date.today()).isoformat(),
    }

    warnings: list[str] = []
    stem = pattern
    for token in KNOWN_TOKENS:
        if token not in pattern:
            continue
        value = values[token]
        if not value:
            warnings.append(
                f"WERYFIKUJ: wzór nazwy pliku tego klienta wymaga pola "
                f"„{_TOKEN_LABELS[token]}”, którego nie udało się ustalić — "
                f"uzupełnij nazwę pliku ręcznie po pobraniu."
            )
        stem = stem.replace(token, value)

    stem = _collapse_separators(stem)

    # Ostatnia linia obrony: nazwa musi nieść tożsamość kandydata. Wzór złożony
    # z samych nierozwiązanych tokenów dałby plik „B2B.docx" dla każdego —
    # nie do odróżnienia w folderze „Pobrane" i nie do wysłania klientowi.
    if not stem or values[TOKEN_FULL_NAME] not in stem:
        return None

    # Znaki zarezerwowane przez systemy plików; polskie znaki i spacje zostają
    # (nagłówek HTTP ma osobną, ASCII-ową ścieżkę przez ``filename*``).
    stem = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", stem).strip(" .")
    if not stem:
        return None

    return FilenameResult(filename=f"{stem}.docx", warnings=tuple(warnings))


async def resolve_client_rule(
    db: AsyncSession, client_id: int | None
) -> Optional[ClientCvRule]:
    """Zwróć **zatwierdzoną** regułę klienta albo ``None``.

    Propozycje z seeda (``confirmed_at IS NULL``) są tu celowo niewidoczne.
    """
    if not client_id:
        return None
    stmt = select(ClientCvRule).where(
        ClientCvRule.client_id == client_id,
        ClientCvRule.confirmed_at.is_not(None),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve_client_name(db: AsyncSession, client_id: int | None) -> Optional[str]:
    """Nazwa klienta do UI — ``display_name`` ma pierwszeństwo przed ``name``,
    bo to ta druga jest nadpisywana przez sync Traffita."""
    if not client_id:
        return None
    stmt = select(Client.display_name, Client.name).where(Client.id == client_id)
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    display_name, name = row
    return (display_name or "").strip() or name


def rule_reminders(rule: Optional[CvRuleSnapshot]) -> tuple[str, ...]:
    """Wymogi klienta, których generator NIE MOŻE spełnić za rekrutera.

    Świadomie nie modyfikujemy dokumentu:

    * PKO BP wymaga wklejenia na dole CV **zrzutu ekranu** maila ze zgodą
      kandydata. Generator nie ma tego obrazu, a wstawienie pustej ramki
      „Zgoda kandydata" wysłałoby do banku dokument wyglądający na
      niedokończony — gorzej niż brak ramki.
    * Czterej klienci wymagają CV w OBU językach. Druga generacja to drugie,
      najdroższe wywołanie modelu w produkcie, więc uruchamia ją człowiek.

    Oba wracają kanałem ostrzeżeń, który rekruter już zna.
    """
    if rule is None:
        return ()
    out: list[str] = []
    if rule.requires_rodo_consent_block:
        out.append(
            "WERYFIKUJ: ten klient wymaga wklejenia na dole CV zrzutu ekranu "
            "maila ze zgodą kandydata na przetwarzanie danych — uzupełnij "
            "dokument przed wysyłką."
        )
    if rule.requires_en_copy:
        out.append(
            "WERYFIKUJ: ten klient oczekuje CV po polsku ORAZ po angielsku — "
            "pamiętaj o wygenerowaniu drugiej wersji językowej."
        )
    return tuple(out)


def describe_rule(rule: Optional[CvRuleSnapshot]) -> str:
    """Opis zastosowanej polityki do UI — odpowiednik ``client_policy``
    z odczytu PDF zamówień.

    Pusty string znaczy „klienta wybrano, ale nie ma dla niego zatwierdzonych
    reguł". Ta różnica musi być widoczna: niewłączona reguła jest inaczej
    NIEWIDOCZNA — generacja »działa«, a jedynym objawem jest plik nazwany
    wzorem, którego klient nie akceptuje.
    """
    if rule is None:
        return ""
    parts: list[str] = []
    if (rule.filename_pattern or "").strip():
        parts.append("nazwa pliku")
    if rule.cv_language:
        parts.append(f"język {rule.cv_language.upper()}")
    if rule.requires_rodo_consent_block:
        parts.append("blok zgody RODO")
    return ", ".join(parts)
