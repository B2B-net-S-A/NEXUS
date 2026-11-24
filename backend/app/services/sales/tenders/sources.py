"""Pobieranie ogłoszeń z otwartych rejestrów: BZP (e-Zamówienia) i TED.

**BZP** (``mo-board/api/v1/notice``) oddaje najwyżej ``PageSize`` pozycji i nie
stronicuje (``PageNumber`` daje wciąż pierwszą stronę), a ``PublicationDateTo``
z godziną nie działa. Dlatego pobieramy kursorem: ``PublicationDateFrom`` =
ostatnia ``publicationDate`` z poprzedniej porcji, duble odsiewa numer BZP.
Wynik jest posortowany rosnąco po dacie publikacji. Mniejsza porcja (100 zamiast
500), bo każda pozycja niesie pełny HTML ogłoszenia (ok. 30 KB).
Makieta z 20.11.2026 liczyła z jednej porcji na dzień i zaniżyła ruch o ok. 20%.

**TED** (``api.ted.europa.eu/v3/notices/search``): wyszukiwanie eksperckie po
kraju zamawiającego, kodach CPV usług IT i dniu publikacji, strony po 100.

Do rejestrów idą tylko daty i kody CPV; żadnych danych firmy.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Optional
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


class SourceError(RuntimeError):
    """Rejestr nie odpowiedział albo odpowiedział czymś, czego nie rozumiemy."""


@dataclass(frozen=True)
class BzpBatch:
    notices: list[Notice]
    #: Największa ``publicationDate`` z odpowiedzi — kursor następnego biegu.
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


def _cursor_param(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


async def fetch_bzp(
    client: httpx.AsyncClient, *, since: datetime, until: date
) -> BzpBatch:
    """Ogłoszenia o zamówieniu opublikowane od ``since`` do końca dnia ``until``."""

    seen: dict[str, Notice] = {}
    cursor = since
    newest: Optional[datetime] = None
    requests = 0
    while requests < BZP_MAX_REQUESTS:
        params = {
            "NoticeType": "ContractNotice",
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
            notice = parse_bzp(item)
            if notice is None or notice.number in seen:
                continue
            seen[notice.number] = notice
            fresh += 1
        if last is not None and (newest is None or last > newest):
            newest = last
        if len(items) < BZP_PAGE_SIZE or not fresh or last is None:
            break
        # Kursor w sekundach: pozycje z tej samej sekundy wracają i odpadają jako duble.
        cursor = last
    else:
        logger.warning("sales_tenders bzp request limit reached requests=%d", requests)
    return BzpBatch(list(seen.values()), newest, requests)


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


def ted_since(last_day: Optional[date], *, today: date, initial_days: int) -> date:
    """TED ma tylko dzień publikacji: od dnia ostatniego udanego biegu (duble odpadną)."""

    if last_day is not None:
        return last_day
    return today - timedelta(days=initial_days)
