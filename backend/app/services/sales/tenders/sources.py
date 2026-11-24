"""Pobieranie ogłoszeń z otwartych rejestrów: BZP (e-Zamówienia) i TED.

**BZP** (``mo-board/api/v1/notice``) oddaje najwyżej ``PageSize`` pozycji i nie
stronicuje (``PageNumber`` daje wciąż pierwszą stronę), a ``PublicationDateTo``
z godziną nie działa. Dlatego pobieramy kursorem: ``PublicationDateFrom`` =
ostatnia ``publicationDate`` z poprzedniej porcji, duble odsiewa numer BZP.
Wynik jest posortowany rosnąco po dacie publikacji. Mniejsza porcja (100 zamiast
500), bo każda pozycja niesie pełny HTML ogłoszenia (ok. 30 KB).
Makieta z 20.11.2026 liczyła z jednej porcji na dzień i zaniżyła ruch o ok. 20%.

Zmiana ogłoszenia w BZP to osobny typ (``NoticeUpdateNotice``) z własnym numerem
i tym samym ``tenderId``. ``submittingOffersDate`` jest w nim puste, a nowy termin
stoi tylko w HTML („Termin składania ofert Przed zmianą: … Po zmianie: …”, czas
warszawski). Ogłoszenie o zamówieniu podaje w ``submittingOffersDate`` termin
aktualny w chwili pobrania (24.11.2026: 168 z 168 ogłoszeń ze zmianą), więc zmiana
ma znaczenie dopiero po tym, jak ogłoszenie trafiło do bazy.

**TED** (``api.ted.europa.eu/v3/notices/search``): wyszukiwanie eksperckie po
kraju zamawiającego, kodach CPV usług IT i dniu publikacji, strony po 100.

Do rejestrów idą tylko daty i kody CPV; żadnych danych firmy.
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable, Optional, TypeVar
from zoneinfo import ZoneInfo

import httpx

from app.core.scheduling import DEFAULT_TZ, business_date
from app.services.sales.tenders.rules import Notice

logger = logging.getLogger(__name__)

BZP_URL = "https://ezamowienia.gov.pl/mo-board/api/v1/notice"
BZP_NOTICE_PAGE = (
    "https://ezamowienia.gov.pl/mo-client-board/bzp/notice-details/id/{id}"
)
BZP_PAGE_SIZE = 100
BZP_MAX_REQUESTS = 150
BZP_CONTRACT_NOTICE = "ContractNotice"
BZP_CHANGE_NOTICE = "NoticeUpdateNotice"

TED_URL = "https://api.ted.europa.eu/v3/notices/search"
TED_NOTICE_PAGE = "https://ted.europa.eu/pl/notice/-/detail/{number}"
TED_PAGE_SIZE = 100
TED_MAX_PAGES = 20
#: TED dopasowuje kody CPV hierarchicznie (72000000 łapie 72413000).
TED_CPV = ("72000000", "79610000", "79620000")
TED_NOTICE_TYPES = ("cn-standard", "cn-social", "pin-cfc-standard")
TED_FIELDS = (
    "publication-number",
    "procedure-identifier",
    "notice-title",
    "buyer-name",
    "deadline-receipt-tender-date-lot",
    "classification-cpv",
    "publication-date",
    "contract-nature-main-proc",
    "contract-nature",
    "links",
)

TIMEOUT = httpx.Timeout(60.0, connect=15.0)
_ORDER_TYPES = {"Services": "services", "Delivery": "supplies", "Works": "works"}
_FRACTION = re.compile(r"(\.\d{6})\d+")
_TED_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")
#: Tytuł z TED to „Polska – <opis kodu CPV> – <przedmiot>”; zostaje przedmiot.
_TED_TITLE_PREFIX = re.compile(r"^\s*(?:Polska|Poland)\s+[–-]\s+.+?\s+[–-]\s+")
_HTML_HIDDEN = re.compile(r"<(style|script)\b.*?</\1\s*>", re.S | re.I)
_HTML_TAG = re.compile(r"<[^>]+>")
#: Blok zmiany terminu w ogłoszeniu o zmianie (po zdjęciu znaczników):
#: „8.1. Termin składania ofert Przed zmianą: 2026-11-23 19:00 Po zmianie:
#: 2026-11-26 19:00”. „Termin otwarcia ofert”, „Termin związania ofertą” i treść
#: warunków („przed upływem terminu składania ofert”) tego układu nie mają.
_CHANGED_DEADLINE = re.compile(
    # „Przed zmianą” nie przechodzi przez następne „Po zmianie”: puste pole terminu
    # nie może wziąć daty z bloku niżej (np. otwarcia ofert).
    r"Termin składania ofert Przed zmianą:(?:(?!Po zmianie:).){0,120}? Po zmianie: "
    r"(\d{4})-(\d{2})-(\d{2})(?: (\d{1,2}):(\d{2}))?(?!\d)"
)

_Parsed = TypeVar("_Parsed")


class SourceError(RuntimeError):
    """Rejestr nie odpowiedział albo odpowiedział czymś, czego nie rozumiemy."""


@dataclass(frozen=True)
class BzpBatch:
    notices: list[Notice]
    #: Największa ``publicationDate`` z odpowiedzi — kursor następnego biegu.
    cursor: Optional[datetime]
    requests: int


@dataclass(frozen=True)
class BzpChange:
    """Ogłoszenie o zmianie ogłoszenia w BZP, które przesuwa termin składania ofert."""

    #: Numer ogłoszenia o zmianie (własny numer BZP, inny niż ogłoszenia o zamówieniu).
    number: str
    #: ``tenderId`` — ten sam co w ogłoszeniu o zamówieniu (``procedure_id`` wiersza).
    procedure_id: str
    published_at: datetime
    deadline_date: date
    deadline_at: Optional[datetime]
    url: Optional[str]


@dataclass(frozen=True)
class BzpChangeBatch:
    changes: list[BzpChange]
    #: Największa ``publicationDate`` z odpowiedzi — kursor zmian następnego biegu.
    cursor: Optional[datetime]
    requests: int


def parse_instant(value: Any) -> Optional[datetime]:
    """Czas z API (``2026-11-12T11:32:40.9637498Z``) jako świadomy czas UTC."""

    if not isinstance(value, str) or not value.strip():
        return None
    text = _FRACTION.sub(r"\1", value.strip()).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _cpv_code(value: Any) -> Optional[str]:
    match = re.match(r"\s*(\d{8})", str(value or ""))
    return match.group(1) if match else None


def parse_bzp(item: dict[str, Any]) -> Optional[Notice]:
    number = str(item.get("bzpNumber") or "").strip()
    title = " ".join(str(item.get("orderObject") or "").split())
    buyer = " ".join(str(item.get("organizationName") or "").split())
    published = parse_instant(item.get("publicationDate"))
    if not number or not title or not buyer or published is None:
        return None
    nip = re.sub(r"\D", "", str(item.get("organizationNationalId") or ""))
    deadline_at = parse_instant(item.get("submittingOffersDate"))
    code = _cpv_code(item.get("cpvCode"))
    object_id = str(item.get("objectId") or "").strip()
    below_eu = item.get("isTenderAmountBelowEU")
    return Notice(
        source="bzp",
        number=number[:60],
        procedure_id=(str(item.get("tenderId") or "").strip()[:80] or None),
        title=title[:1000],
        buyer_name=buyer[:500],
        published_at=published,
        buyer_nip=nip if len(nip) == 10 else None,
        buyer_city=(str(item.get("organizationCity") or "").strip() or None),
        cpv_codes=(code,) if code else (),
        cpv_label=(str(item.get("cpvCode") or "").strip()[:300] or None),
        order_type=_ORDER_TYPES.get(str(item.get("orderType") or "")),
        url=BZP_NOTICE_PAGE.format(id=object_id) if object_id else None,
        deadline_date=business_date(deadline_at) if deadline_at else None,
        deadline_at=deadline_at,
        below_eu=below_eu if isinstance(below_eu, bool) else None,
    )


def _html_text(body: str) -> str:
    """Tekst ogłoszenia bez znaczników, z pojedynczymi spacjami."""

    text = _HTML_TAG.sub(" ", _HTML_HIDDEN.sub(" ", body))
    return " ".join(html.unescape(text).split())


def changed_deadline(body: Any) -> Optional[tuple[date, Optional[datetime]]]:
    """Nowy termin składania ofert z HTML ogłoszenia o zmianie: dzień w kalendarzu
    firmy i chwila w UTC (``None``, gdy BZP podało sam dzień). Ostatni blok wygrywa."""

    if not isinstance(body, str) or "Po zmianie" not in body:
        return None
    found = None
    for found in _CHANGED_DEADLINE.finditer(_html_text(body)):
        pass
    if found is None:
        return None
    year, month, day, hour, minute = found.groups()
    try:
        if hour is None:
            return date(int(year), int(month), int(day)), None
        local = datetime(
            int(year),
            int(month),
            int(day),
            int(hour),
            int(minute),
            tzinfo=ZoneInfo(DEFAULT_TZ),
        )
    except ValueError:
        return None
    moment = local.astimezone(timezone.utc)
    return business_date(moment), moment


def parse_bzp_change(item: dict[str, Any]) -> Optional[BzpChange]:
    """Ogłoszenie o zmianie z nowym terminem; zmiana bez terminu (inne sekcje,
    ogłoszenie o wyniku albo o wykonaniu umowy) daje ``None``."""

    number = str(item.get("bzpNumber") or "").strip()
    procedure = str(item.get("tenderId") or "").strip()[:80]
    published = parse_instant(item.get("publicationDate"))
    if not number or not procedure or published is None:
        return None
    deadline = changed_deadline(item.get("htmlBody"))
    if deadline is None:
        return None
    object_id = str(item.get("objectId") or "").strip()
    return BzpChange(
        number=number[:60],
        procedure_id=procedure,
        published_at=published,
        deadline_date=deadline[0],
        deadline_at=deadline[1],
        url=BZP_NOTICE_PAGE.format(id=object_id) if object_id else None,
    )


def _cursor_param(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


async def _walk_bzp(
    client: httpx.AsyncClient,
    *,
    notice_type: str,
    since: datetime,
    until: date,
    parse: Callable[[dict[str, Any]], Optional[_Parsed]],
) -> tuple[list[_Parsed], Optional[datetime], int]:
    """Porcje jednego typu ogłoszeń od ``since`` do końca dnia ``until``: pozycje
    po ``parse`` (bez powtórek numeru BZP), największa ``publicationDate``, zapytania."""

    seen: set[str] = set()
    parsed: list[_Parsed] = []
    cursor = since
    newest: Optional[datetime] = None
    requests = 0
    while requests < BZP_MAX_REQUESTS:
        params = {
            "NoticeType": notice_type,
            "PublicationDateFrom": _cursor_param(cursor),
            "PublicationDateTo": until.isoformat(),
            "PageSize": str(BZP_PAGE_SIZE),
        }
        items = await _get_json_list(client, BZP_URL, params)
        requests += 1
        fresh = 0
        last: Optional[datetime] = None
        for item in items:
            published = parse_instant(item.get("publicationDate"))
            if published is not None and (last is None or published > last):
                last = published
            number = str(item.get("bzpNumber") or "").strip()
            if not number or number in seen:
                continue
            seen.add(number)
            fresh += 1
            # Porcja bez pozycji po ``parse`` (np. same zmiany bez terminu) nie kończy
            # przejścia: liczą się nowe numery, nie wynik parsowania.
            result = parse(item)
            if result is not None:
                parsed.append(result)
        if last is not None and (newest is None or last > newest):
            newest = last
        if len(items) < BZP_PAGE_SIZE or not fresh or last is None:
            break
        # Kursor w sekundach: pozycje z tej samej sekundy wracają i odpadają jako duble.
        cursor = last
    else:
        logger.warning(
            "sales_tenders bzp request limit reached type=%s requests=%d",
            notice_type,
            requests,
        )
    return parsed, newest, requests


async def fetch_bzp(
    client: httpx.AsyncClient, *, since: datetime, until: date
) -> BzpBatch:
    """Ogłoszenia o zamówieniu opublikowane od ``since`` do końca dnia ``until``."""

    notices, cursor, requests = await _walk_bzp(
        client,
        notice_type=BZP_CONTRACT_NOTICE,
        since=since,
        until=until,
        parse=parse_bzp,
    )
    return BzpBatch(notices, cursor, requests)


async def fetch_bzp_changes(
    client: httpx.AsyncClient, *, since: datetime, until: date
) -> BzpChangeBatch:
    """Ogłoszenia o zmianie z nowym terminem składania ofert, od ``since`` do końca
    dnia ``until``. Tych bez terminu nie zwraca, ale kursor idzie i za nimi."""

    changes, cursor, requests = await _walk_bzp(
        client,
        notice_type=BZP_CHANGE_NOTICE,
        since=since,
        until=until,
        parse=parse_bzp_change,
    )
    return BzpChangeBatch(changes, cursor, requests)


async def _get_json_list(
    client: httpx.AsyncClient, url: str, params: dict[str, str]
) -> list[dict[str, Any]]:
    try:
        response = await client.get(url, params=params, timeout=TIMEOUT)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise SourceError(f"bzp: {type(exc).__name__}") from exc
    if not isinstance(data, list):
        raise SourceError("bzp: odpowiedź nie jest listą")
    return [item for item in data if isinstance(item, dict)]


def _first_text(value: Any) -> Optional[str]:
    """Tekst z pola TED: najpierw polski, potem angielski, potem pierwszy."""

    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, list):
        for item in value:
            text = _first_text(item)
            if text:
                return text
        return None
    if isinstance(value, dict):
        for key in ("pol", "eng", *value.keys()):
            if key in value:
                text = _first_text(value[key])
                if text:
                    return text
    return None


def _ted_day(value: Any) -> Optional[date]:
    match = _TED_DATE.match(str(value or ""))
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def parse_ted(item: dict[str, Any]) -> Optional[Notice]:
    number = str(item.get("publication-number") or "").strip()
    title = _first_text(item.get("notice-title"))
    buyer = _first_text(item.get("buyer-name"))
    published_on = _ted_day(item.get("publication-date"))
    if not number or not title or not buyer or published_on is None:
        return None
    deadlines = [
        day
        for day in (
            _ted_day(v) for v in _as_list(item.get("deadline-receipt-tender-date-lot"))
        )
        if day is not None
    ]
    # Rodzaj główny postępowania; ``contract-nature`` miesza główny z dodatkowymi
    # (808107-2026: dostawa z usługą dodatkową), więc bierzemy go tylko bez głównego.
    main = _first_text(item.get("contract-nature-main-proc"))
    natures = [str(v) for v in _as_list(item.get("contract-nature"))]
    codes = tuple(
        dict.fromkeys(str(v)[:8] for v in _as_list(item.get("classification-cpv")) if v)
    )
    links = item.get("links") if isinstance(item.get("links"), dict) else {}
    html = links.get("html") if isinstance(links.get("html"), dict) else {}
    published_at = datetime.combine(published_on, time(0, 0), ZoneInfo(DEFAULT_TZ))
    return Notice(
        source="ted",
        number=number[:60],
        # Zmiana postępowania (np. nowy termin) to w TED nowa publikacja z nowym
        # numerem i tym samym identyfikatorem postępowania.
        procedure_id=(_first_text(item.get("procedure-identifier")) or "")[:80] or None,
        title=ted_title(title)[:1000],
        buyer_name=" ".join(buyer.split())[:500],
        published_at=published_at.astimezone(timezone.utc),
        cpv_codes=codes,
        cpv_label=", ".join(codes)[:300] or None,
        order_type=main or (natures[0] if natures else None),
        url=str(html.get("POL") or TED_NOTICE_PAGE.format(number=number)),
        deadline_date=min(deadlines) if deadlines else None,
        below_eu=False,
    )


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def ted_title(title: str) -> str:
    """Przedmiot bez przedrostka kraju i opisu kodu CPV, który TED dokleja."""

    text = " ".join(title.split())
    return _TED_TITLE_PREFIX.sub("", text, count=1) or text


def ted_query(since: date, until: date) -> str:
    return (
        "buyer-country=POL"
        f" AND classification-cpv IN ({' '.join(TED_CPV)})"
        f" AND publication-date>={since:%Y%m%d} AND publication-date<={until:%Y%m%d}"
        f" AND notice-type IN ({' '.join(TED_NOTICE_TYPES)})"
    )


async def fetch_ted(
    client: httpx.AsyncClient, *, since: date, until: date
) -> list[Notice]:
    """Polskie ogłoszenia IT z TED opublikowane od ``since`` do ``until`` włącznie."""

    query = ted_query(since, until)
    notices: dict[str, Notice] = {}
    total: Optional[int] = None
    fetched = 0
    for page in range(1, TED_MAX_PAGES + 1):
        body = {
            "query": query,
            "fields": list(TED_FIELDS),
            "limit": TED_PAGE_SIZE,
            "page": page,
        }
        try:
            response = await client.post(TED_URL, json=body, timeout=TIMEOUT)
            response.raise_for_status()
            data = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise SourceError(f"ted: {type(exc).__name__}") from exc
        items = data.get("notices") if isinstance(data, dict) else None
        if not isinstance(items, list):
            raise SourceError("ted: odpowiedź bez listy ogłoszeń")
        total = (
            data.get("totalNoticeCount")
            if isinstance(data.get("totalNoticeCount"), int)
            else total
        )
        fetched += len(items)
        for item in items:
            notice = parse_ted(item) if isinstance(item, dict) else None
            if notice is not None:
                notices.setdefault(notice.number, notice)
        if len(items) < TED_PAGE_SIZE or (total is not None and fetched >= total):
            break
    return list(notices.values())


def bzp_since(
    cursor: Optional[datetime], *, now: datetime, initial_days: int
) -> datetime:
    """Początek okna BZP: kursor z poprzedniego biegu albo ``initial_days`` wstecz."""

    if cursor is not None:
        return cursor
    return now - timedelta(days=initial_days)


def bzp_changes_since(
    cursor: Optional[datetime],
    *,
    oldest_row: Optional[datetime],
    now: datetime,
    initial_days: int,
) -> datetime:
    """Początek okna zmian BZP: kursor zmian, a bez niego chwila pobrania najstarszego
    ogłoszenia BZP w bazie (najwyżej ``initial_days`` wstecz). Przy pustej bazie od
    teraz: ogłoszenie pobrane w tym biegu ma już termin po wcześniejszych zmianach,
    a tydzień zmian to ok. 20 zbędnych zapytań (BZP blokuje serię zapytań 403)."""

    if cursor is not None:
        return cursor
    if oldest_row is None:
        return now
    return max(oldest_row, now - timedelta(days=initial_days))


def ted_since(last_day: Optional[date], *, today: date, initial_days: int) -> date:
    """TED ma tylko dzień publikacji: od dnia ostatniego udanego biegu (duble odpadną)."""

    if last_day is not None:
        return last_day
    return today - timedelta(days=initial_days)
