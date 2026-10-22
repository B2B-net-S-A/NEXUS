"""Off-limits: z firm, w których mamy aktywne zamówienie, nie wyciągamy ludzi.

Decyzja Artura 21.10.2026. Umowa z klientem zabrania aktywnego podbierania
jego ludzi, a „klient” znaczy tu firmę z co najmniej jednym AKTYWNYM
zamówieniem — nikt nie prowadzi listy ręcznie, firma wypada sama, gdy kończy
się jej ostatnie zamówienie. Osoba, która SAMA się do nas zgłosiła, jest w
porządku (także przez LinkedIn); zakazane jest tylko to, że my odzywamy się
pierwsi.

Dlatego dodanie przez człowieka do rekrutacji osoby, która dziś pracuje
w takiej firmie, wymaga potwierdzenia „sama się zgłosiła” (jak: LinkedIn,
ogłoszenie, telefon/mail, wcześniej przysłane CV, polecenie) albo „już tam
nie pracuje”. Bez potwierdzenia trasa odpowiada 409
``off_limits_confirmation_required``; front pyta i ponawia to samo żądanie
z nagłówkiem ``X-Off-Limits-Confirmation`` (``{"<id kandydata>": "<jak>"}``),
więc bramka obejmuje każdą drogę dodania bez zmiany schematów tras.
Potwierdzenie zostaje przy procesie (``entry_meta["off_limits"]``) z autorem
i datą — panel osoby i karta Tablicy je pokazują.

Bez pytania: zgłoszenie do tej rekrutacji formularzem (dowód z
``integration_intake``), przepięcie z innej naszej rekrutacji, automaty
i integracje (``source_authority``/``entry_source`` spoza człowieka).

„Pracuje teraz” = firma z LinkedIna, a gdy jej brak — wpis CV bez daty końca,
który to MÓWI (data startu albo „obecnie”; sam brak dat to artefakt importu,
reguła ``company_names.entry_says_current``).
"""

from __future__ import annotations

import json
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Optional, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_directory import ClientAlias
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.services.company_names import entry_says_current, normalize_company_name
from app.services.experience_end import is_current_end

CONFIRMATION_REQUIRED_CODE = "off_limits_confirmation_required"
CONFIRMATION_HEADER = "X-Off-Limits-Confirmation"
OFF_LIMITS_META_KEY = "off_limits"
# Odpowiedź „Nie, to my się odezwaliśmy” przy dodaniu kilku osób naraz:
# ta osoba wypada z partii (``skipped``), reszta się dodaje.
SKIP = "skip"

HOW_LABELS: dict[str, str] = {
    "linkedin_inbound": "Napisał(a) do nas na LinkedInie",
    "job_ad": "Zaaplikował(a) na ogłoszenie",
    "phone_or_email": "Zadzwonił(a) albo napisał(a) maila",
    "sent_cv_before": "Wcześniej sam(a) przysłał(a) CV",
    "referral": "Polecenie innej osoby",
    "left_company": "Już tam nie pracuje",
}

# Etykieta krótsza niż dwa znaki dopasowałaby pół bazy.
_MIN_LABEL_LEN = 2
# Nagłówek to mapa z okna potwierdzenia — partia „Dodaj do rekrutacji” ma
# górny limit 500 osób (``proposals_bulk``).
_MAX_CONFIRMATIONS = 500
_LABELS_CACHE_KEY = "client_off_limits_labels"

_confirmations: ContextVar[dict[int, str] | None] = ContextVar(
    "off_limits_confirmations", default=None
)


class PersonLike(Protocol):
    """Encja ``Candidate`` albo wiersz z tymi kolumnami."""

    id: int
    name: Optional[str]
    lastname: Optional[str]
    linkedin_current_company: Optional[str]
    experience: Any


@dataclass(frozen=True)
class OffLimitsHit:
    client_id: int
    client_name: str
    company: str
    source: str  # "linkedin" | "cv"


@dataclass(frozen=True)
class OffLimitsPerson:
    candidate_id: int
    name: str
    hit: OffLimitsHit

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "name": self.name,
            "company": self.hit.company,
            "client_name": self.hit.client_name,
            "source": self.hit.source,
        }


class OffLimitsConfirmationRequired(Exception):
    """Człowiek dodaje osobę z firmy off-limits bez potwierdzenia.

    Wyjątek (nie ``HTTPException``), żeby sesja żądania zrobiła rollback
    i żeby serwisy nie zależały od warstwy HTTP; 409 oddaje handler
    zarejestrowany w ``main.py``.
    """

    def __init__(self, people: list[OffLimitsPerson]):
        super().__init__(CONFIRMATION_REQUIRED_CODE)
        self.people = people

    def detail(self) -> dict[str, Any]:
        if len(self.people) == 1:
            person = self.people[0]
            message = (
                f"{person.name} pracuje w firmie {person.hit.client_name} — "
                "stamtąd nie wyciągamy ludzi. Potwierdź, że ta osoba sama "
                "się do nas zgłosiła."
            )
        else:
            message = (
                f"{len(self.people)} osoby pracują w firmach, z których nie "
                "wyciągamy ludzi. Potwierdź, które same się do nas zgłosiły."
            )
        return {
            "code": CONFIRMATION_REQUIRED_CODE,
            "message": message,
            "candidates": [p.as_dict() for p in self.people],
        }


def extension_skip_reason(exc: OffLimitsConfirmationRequired) -> str:
    """Powód dla wtyczki LinkedIn, która nie ma okna potwierdzenia.

    Wtyczka pokazuje go przy zapisanej osobie zamiast przypisania — 409
    wywróciłby cały zapis, a ona nie ma jak go ponowić z nagłówkiem."""
    client = exc.people[0].hit.client_name if exc.people else "klienta"
    return (
        f"Pracuje w firmie {client} — stamtąd nie wyciągamy ludzi. Osoba jest "
        "zapisana w bazie; dodaj ją do rekrutacji w NEXUSIE i potwierdź, że "
        "sam(a) się do nas zgłosił(a)."
    )


# --- potwierdzenia z nagłówka żądania ---------------------------------------


def parse_confirmation_header(raw: Optional[str]) -> dict[int, str]:
    """``{"123": "linkedin_inbound"}`` → ``{123: "linkedin_inbound"}``.

    Nieznany sposób, zły klucz albo zepsuty JSON = brak potwierdzenia dla
    tej osoby (bramka zapyta znowu), nigdy błąd żądania.
    """
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except (ValueError, TypeError, RecursionError):
        # RecursionError: JSON zagnieżdżony na ~10 tys. poziomów (audyt
        # 22.10, F111) — middleware stoi poza siatką błędów, więc to byłby
        # 500 na każdej trasie, także bez logowania.
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[int, str] = {}
    for key, value in list(data.items())[:_MAX_CONFIRMATIONS]:
        try:
            candidate_id = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, str) and (value in HOW_LABELS or value == SKIP):
            out[candidate_id] = value
    return out


def current_confirmations() -> dict[int, str]:
    return _confirmations.get() or {}


class OffLimitsConfirmationMiddleware:
    """Czyta ``X-Off-Limits-Confirmation`` do zmiennej kontekstu żądania."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        raw = None
        header = CONFIRMATION_HEADER.lower().encode("ascii")
        for name, value in scope.get("headers", []):
            if name == header:
                raw = value.decode("latin-1")
                break
        token = _confirmations.set(parse_confirmation_header(raw))
        try:
            await self.app(scope, receive, send)
        finally:
            _confirmations.reset(token)


# --- które firmy są off-limits i kto w nich pracuje -------------------------


async def off_limits_labels(db: AsyncSession) -> list[tuple[str, int, str]]:
    """``(znormalizowana nazwa, id klienta, nazwa do pokazania)`` firm
    z aktywnym zamówieniem — nazwa, nazwa wyświetlana, prawna i aliasy.

    Liczone raz na sesję żądania (partia 500 osób = jedno zapytanie).
    """
    cached = db.info.get(_LABELS_CACHE_KEY)
    if cached is not None:
        return cached
    standalone = select(ClientOrder.client_id).where(
        ClientOrder.status == ClientOrderStatus.active
    )
    grouped = select(ClientOrderGroup.client_id).where(
        ClientOrderGroup.status == "active"
    )
    clients = (
        await db.execute(
            select(
                Client.id, Client.name, Client.display_name, Client.legal_name
            ).where(
                Client.deleted_at.is_(None),
                or_(Client.id.in_(standalone), Client.id.in_(grouped)),
            )
        )
    ).all()
    shown = {row.id: (row.display_name or row.name) for row in clients}
    names: list[tuple[int, Optional[str]]] = []
    for row in clients:
        names.extend(
            [(row.id, row.name), (row.id, row.display_name), (row.id, row.legal_name)]
        )
    if shown:
        aliases = await db.execute(
            select(ClientAlias.client_id, ClientAlias.alias).where(
                ClientAlias.client_id.in_(list(shown)),
                ClientAlias.archived_at.is_(None),
            )
        )
        names.extend((int(r.client_id), r.alias) for r in aliases.all())
    labels: dict[str, tuple[int, str]] = {}
    for client_id, name in names:
        label = normalize_company_name(name or "")
        if len(label) >= _MIN_LABEL_LEN and label not in labels:
            labels[label] = (client_id, shown[client_id])
    result = [(label, cid, shown_name) for label, (cid, shown_name) in labels.items()]
    # Najdłuższa nazwa wygrywa: „bnp paribas cardif” przed „bnp paribas”.
    result.sort(key=lambda item: len(item[0]), reverse=True)
    db.info[_LABELS_CACHE_KEY] = result
    return result


def _match_label(
    company: str, labels: list[tuple[str, int, str]]
) -> Optional[tuple[int, str]]:
    """Firma z CV pasuje do klienta, gdy zaczyna się jego nazwą jako całymi
    słowami: „Nordea Bank Abp” → „nordea”, ale „Nordeax” i „Bank Nordea” nie."""
    normalized = normalize_company_name(company)
    if not normalized:
        return None
    for label, client_id, shown in labels:
        if normalized == label or normalized.startswith(label + " "):
            return client_id, shown
    return None


def current_companies(candidate: PersonLike) -> list[tuple[str, str]]:
    """``(firma, źródło)`` — gdzie osoba pracuje teraz według naszych danych."""
    out: list[tuple[str, str]] = []
    linkedin = (candidate.linkedin_current_company or "").strip()
    if linkedin:
        out.append((linkedin, "linkedin"))
    experience = candidate.experience
    if isinstance(experience, list):
        for entry in experience:
            if not isinstance(entry, dict):
                continue
            company = entry.get("company")
            if (
                isinstance(company, str)
                and company.strip()
                and is_current_end(entry.get("end"))
                and entry_says_current(entry)
            ):
                out.append((company.strip(), "cv"))
    return out


def find_hit(
    candidate: PersonLike, labels: list[tuple[str, int, str]]
) -> Optional[OffLimitsHit]:
    if not labels:
        return None
    for company, source in current_companies(candidate):
        matched = _match_label(company, labels)
        if matched is not None:
            return OffLimitsHit(
                client_id=matched[0],
                client_name=matched[1],
                company=company[:200],
                source=source,
            )
    return None


def _person_name(candidate: PersonLike) -> str:
    return " ".join(p for p in (candidate.name, candidate.lastname) if p).strip()


async def people_needing_confirmation(
    db: AsyncSession, *, job_id: int, candidates: Iterable[PersonLike]
) -> list[OffLimitsPerson]:
    """Osoby z firm off-limits bez dowodu zgłoszenia do TEJ rekrutacji."""
    labels = await off_limits_labels(db)
    if not labels:
        return []
    hits = [
        OffLimitsPerson(candidate_id=c.id, name=_person_name(c), hit=hit)
        for c in candidates
        if (hit := find_hit(c, labels)) is not None
    ]
    if not hits:
        return []
    from app.services.integration_intake import (  # noqa: PLC0415
        candidates_with_application_evidence,
    )

    applied = await candidates_with_application_evidence(
        db, job_id=job_id, candidate_ids=[p.candidate_id for p in hits]
    )
    return [p for p in hits if p.candidate_id not in applied]


def confirmation_meta(
    person: OffLimitsPerson, *, how: str, actor_user_id: Optional[int]
) -> dict[str, Any]:
    """Ślad przy procesie: kto, kiedy i jak potwierdził."""
    return {
        "client_id": person.hit.client_id,
        "client_name": person.hit.client_name,
        "company": person.hit.company,
        "source": person.hit.source,
        "how": how,
        "confirmed_by": actor_user_id,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
    }


async def confirm_or_raise(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    actor_user_id: Optional[int],
) -> Optional[dict[str, Any]]:
    """Bramka jednej pary przy NOWYM procesie dodanym przez człowieka.

    ``None`` = osoba nie jest z firmy off-limits (albo zgłosiła się do tej
    rekrutacji). Inaczej meta potwierdzenia z nagłówka albo wyjątek → 409.
    """
    # Jawne kolumny zamiast ``db.get``: osoba bywa już w sesji wczytana
    # z ``load_only`` i dociąganie ``experience`` w async kończy się błędem.
    candidate = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Candidate.linkedin_current_company,
                Candidate.experience,
            ).where(Candidate.id == candidate_id)
        )
    ).first()
    if candidate is None:
        return None
    people = await people_needing_confirmation(
        db, job_id=job_id, candidates=[candidate]
    )
    if not people:
        return None
    how = current_confirmations().get(candidate_id)
    if how is None or how == SKIP:
        raise OffLimitsConfirmationRequired(people)
    return confirmation_meta(people[0], how=how, actor_user_id=actor_user_id)


def off_limits_badge(
    meta: Any, user_names: Optional[dict[int, str]] = None
) -> Optional[dict[str, Any]]:
    """Plakietka dla frontu z ``entry_meta`` — tylko znane pola."""
    if not isinstance(meta, dict):
        return None
    data = meta.get(OFF_LIMITS_META_KEY)
    if not isinstance(data, dict) or data.get("how") not in HOW_LABELS:
        return None
    confirmed_by = data.get("confirmed_by")
    confirmed_by = confirmed_by if isinstance(confirmed_by, int) else None
    return {
        "client_name": str(data.get("client_name") or ""),
        "company": str(data.get("company") or ""),
        "how": data["how"],
        "how_label": HOW_LABELS[data["how"]],
        "confirmed_by_id": confirmed_by,
        "confirmed_by_name": (
            (user_names or {}).get(confirmed_by) if confirmed_by else None
        ),
        "confirmed_at": (
            data.get("confirmed_at")
            if isinstance(data.get("confirmed_at"), str)
            else None
        ),
    }
