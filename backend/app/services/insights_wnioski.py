"""Zakładka „Wnioski” w Insights: co się powtarza w danych i decyzja, co z tym zrobić.

Decyzje Artura 04.11.2026 (reguła: ``docs/claude/finanse-insights/zakladka-wnioski.md``).

Stały zestaw reguł w kodzie, bez modelu AI i bez pętli w tle: sprawy liczą się przy
odczycie, a trasa trzyma je 5 minut. Decyzja zapisuje ślad i termin oceny, działania
systemu nie zmienia. Odczyt opisów „Inne” to słowa kluczowe, liczone przy odczycie
i niezapisywane: ręczne sprawdzenie 90 wpisów dało ok. 90% trafności, więc ekran pisze
„Szacunek”.

Granice, które łatwo zgubić:

* Żadnych miar per osoba z zespołu (decyzja o PIP). Tylko klienci, rekrutacje i typy
  sygnałów. Osoby z liczby wychodzą wyłącznie przez ``compute_reason_people``.
* Opis z cechą chronioną nie staje się powodem, cytatem ani przykładem
  (``PROTECTED_RE``). Liczy się jako nieodczytany.
* Wniosek nie sugeruje wstrzymania CV: po takich odmowach ludzie idą dalej.
* Reguły ocenia się na 100 dodanych osób i na kartach w tym samym wieku. Sam udział
  w odrzuceniach myli, bo zmienia się też to, jak często ludzie odrzucają.
"""

from __future__ import annotations

import asyncio
import difflib
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Iterable, Iterator, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import DEFAULT_TZ
from app.models.insight_decision import InsightDecision
from app.models.user import User, UserRole
from app.services.competition_history import cutover_utc

VIEWER_ROLES = (UserRole.admin, UserRole.head_of_recruitment)

STATE_APPROVED = "approved"
STATE_LATER = "later"
STATE_REJECTED = "rejected"

MAX_OPEN_CASES = 5
LATER_DAYS = 30
REVIEW_DAYS = 30
# Okno odczytu: powody odrzuceń są w NEXUSIE od 12.10.2026 (`cutover_utc`), a po 90 dniach
# okno zaczyna się przesuwać, żeby obraz mówił o bieżącej pracy.
WINDOW_DAYS = 90
# „Nie” porównuje liczbę z ostatnich 30 dni. Liczba od początku rośnie sama, więc przy stałym
# tempie sprawa wracałaby po kilku tygodniach, wcześniej niż po „Nie teraz”.
RECENT_DAYS = 30

_TZ = ZoneInfo(DEFAULT_TZ)


# Cechy chronione: narodowość, wiek, zdrowie, ciąża, wyznanie, płeć. Jedno źródło dla odczytu
# opisów i cytatów. Fałszywe trafienie tylko chowa przykład, więc lista jest szeroka.
PROTECTED_RE = (
    r"\m(narodowo|obywatel|pochodzeni|cudzoziem|obcokraj|ukrai|rosj|rosyj|russia|ruski|białoru|bialoru"
    r"|belarus|hindus|indyj|indii|indian|polak|polk[aię]\M|akcent|nationalit|citizen|foreigner"
    r"|afryk|turek|turc|tureck|arab|szachid|szahid|ciapat|kultur|irland|francj|francuz|niemiec|niemc"
    r"|imigran|emigran|spoza polski|skąd on|skad on|skąd jest|skad jest"
    r"|kraj\w* (obję|obje|konflikt)|obję\w* konflikt|obje\w* konflikt|konflikt\w* zbrojn"
    r"|wiek|ma \d\d lat|\d\d[- ]?lat(ek|ka|ni)|starsz\w* (pan|osob|kandydat)|za star|za młod|za mlod"
    r"|emeryt|too old|too young"
    r"|zdrow|chor[aoyuąęe]|schorz|niepełnospr|niepelnospr|health|disabil|sick|illness|l4\M"
    r"|zwolnieni[eau] lekarsk"
    r"|ciąż|ciaz|ciężarn|ciezarn|pregnan|macierzy|maternity|rodzicielsk|parental"
    r"|wyznani|relig|\mpłe[cć]|kobiet|mężczyzn|mezczyzn|gender)"
)

# Ten sam wzorzec w Pythonie (``\m``/``\M`` Postgresa to granice słowa) — dla opisów,
# które czyta kod, zanim trafią do modelu (``autofill_quality.model_lines``, 12.11.2026).
PROTECTED_PY = re.compile(
    PROTECTED_RE.replace(r"\m", r"\b").replace(r"\M", r"\b"), re.IGNORECASE
)


def is_protected(text: str) -> bool:
    """Czy opis mówi o cesze chronionej (narodowość, pochodzenie, wiek, zdrowie…)."""
    return bool(PROTECTED_PY.search(text or ""))


# Lustro zapytań z testu danych 04.11.2026. Kolejność WHEN ma znaczenie: pierwsze
# trafienie wygrywa, a cecha chroniona stoi przed każdym powodem.
_READ_CASE = rf"""
    CASE
        WHEN powod IN ('Brak doświadczenia', 'Nie spełnia wymagań technicznych') THEN 'Umiejetnosci'
        WHEN powod IN ('Za wysokie oczekiwania finansowe', 'salary_mismatch') THEN 'Stawka'
        WHEN powod IN ('Zatrudniony gdzie indziej', 'accepted_other_offer') THEN 'Zatrudniony'
        WHEN powod = 'work_mode_mismatch' THEN 'Tryb'
        WHEN powod IN ('lost_interest', 'Kandydat się wycofał', 'process_too_long',
                       'counter_offer', 'personal_reasons') THEN 'Rezygnacja'
        WHEN powod IN ('Kandydat nieosiągalny', 'Brak odpowiedzi') THEN 'BrakKontaktu'
        WHEN powod = 'not_looking_for_work' THEN 'Rezygnacja'
        WHEN powod = 'client_conflict' THEN 'KonfliktKlient'
        WHEN powod = 'contract_form' THEN 'FormaUmowy'
        WHEN powod = 'no_contact' THEN 'BrakKontaktu'
        WHEN powod = 'client_no_reason' THEN 'KlientBezKonkretu'
        WHEN powod = 'client_chose_other' THEN 'KlientWybral'
        WHEN powod IN ('request_closed', 'client_no_response') THEN 'KlientBezKonkretu'
        WHEN powod NOT ILIKE 'Inne%' THEN 'Reszta'
        WHEN t = '' THEN 'BezOpisu'
        WHEN t ~ '{PROTECTED_RE}' THEN 'Nieodczytane'
        WHEN t ~ 'nie odbiera|brak kontaktu|brak odpowiedzi|nie odpowiada|no answer|nie oddzwania|nie odpisuje|nr nie|nie ma takiego n|numer|zły nr|zly nr|brak nr|poczta głos' THEN 'BrakKontaktu'
        WHEN t ~ 'pracuje (w|u) |pracuje dla|zatrudnion[ya] u nas|pracuje u nas|nie chce (do|w) (nordei|nordea|pko|bnp|orlen)|nie chce nordei|innego (vendora|dostawcy)|other vendor|przez aztec|employed by|już jest w|był na interview od' THEN 'KonfliktKlient'
        WHEN t ~ 'other candidate|another candidate|inny kandydat|innego kandydata|wybra[łl] (innego|kogoś)|went with|selected for|position (is )?closed|position has been|został wybrany|zdecydowal się pokryć|zdecydował się pokryć|pokryć' THEN 'KlientWybral'
        WHEN t ~ 'thank you for|bez podania|not matching|not a match|do not match|not a fit|nie ten profil|profile|nie pasuje|not shortlisted|interview result|klient odrzuci' THEN 'KlientBezKonkretu'
        WHEN t ~ 'stawk|\mzł( |$|[.,])|\mpln\M|budżet|budzet|\mrate\M|expensive|finans|za drog|oczekiwania|\mcen[aey]\M' THEN 'Stawka'
        WHEN t ~ '\muop\M|umow[aęy] o prac|b2b|na etat|pełen etat|fulltime|full time|full-time|\metat' THEN 'FormaUmowy'
        WHEN t ~ 'lokaliz|hybryd|zdaln|remote|\mbiur|dojazd|miast|przeprowad|relok|wrocław|krak|poznań|łódź|lublin|katowic|gdańsk|gdynia|warszaw' THEN 'Tryb'
        WHEN t ~ 'overqual|za wysoki poziom|przekwal|za senior|za doświadcz|too senior' THEN 'ZaWysokiPoziom'
        WHEN t ~ 'nie szuka|niezainteres|nie jest zaintereso|nie zaintereso|not interested|zmiana pracy|rezygn|wycofa|nie chce|od nowego roku|kontrofert|zostaje|znalazł|znalazl|nowa praca|przyją[łl]|przyjal' THEN 'Rezygnacja'
        WHEN t ~ 'not sufficient|not enough|not enought|experience|doświadcz|doswiadcz|kompeten|knowledge|wiedz|umiejętn|umiejetn|skill|\mbrak\M|junior|seniorit|poziom|za słab|technicz|język|jezyk|angielsk|english|limited|\mpm\M' THEN 'Umiejetnosci'
        WHEN t ~ 'duplik|duplicate|omyłk|omylk|pomyłk|pomylk|test' THEN 'Porzadki'
        ELSE 'Nieodczytane'
    END
"""

# Liczba i lista osób biorą bucket z tego samego CTE. `translate` przed `lower`, bo produkcja
# ma ctype C i `lower` nie zna polskich wielkich liter (`keyword_terms.py`).
_CLASSIFIED = f"""
    WITH source AS (
        SELECT cs.id AS stage_id, cs.candidate_id, cs.job_id, cs.moved_at, cs.ended_by,
               j.title AS job_title, j.client_id, COALESCE(cl.name, 'Bez klienta') AS client,
               r.name AS powod,
               lower(translate(regexp_replace(COALESCE(cs.notes, ''), '\\s+', ' ', 'g'),
                               'ĄĆĘŁŃÓŚŹŻ', 'ąćęłńóśźż')) AS t
        FROM candidate_stages cs
        JOIN rejection_reasons r ON r.id = cs.rejection_reason_id
        JOIN jobs j ON j.id = cs.job_id
        LEFT JOIN clients cl ON cl.id = j.client_id
        WHERE cs.moved_at >= :since AND r.name <> 'legacy_unknown'
    ),
    classified AS (
        SELECT source.*, powod ILIKE 'Inne%' AS is_other, {_READ_CASE} AS k FROM source
    )
"""


@dataclass(frozen=True)
class ReasonBucket:
    key: str
    label: str
    kinds: tuple[str, ...]


_UNREAD = ("Nieodczytane", "BezOpisu")
_UNAVAILABLE = ("Zatrudniony", "Rezygnacja", "BrakKontaktu")
_MODE = ("Tryb", "FormaUmowy")

WHY_OUT_BUCKETS = (
    ReasonBucket("skills", "Umiejętności lub doświadczenie", ("Umiejetnosci",)),
    ReasonBucket("unavailable", "Osoba niedostępna", _UNAVAILABLE),
    ReasonBucket("rate", "Stawka", ("Stawka",)),
    ReasonBucket("mode", "Tryb pracy, miasto, umowa", _MODE),
    ReasonBucket(
        "client_silent",
        "Klient bez powodu lub wybrał innego",
        ("KlientBezKonkretu", "KlientWybral"),
    ),
    ReasonBucket(
        "client_conflict", "Pracuje u klienta, nie chce do klienta", ("KonfliktKlient",)
    ),
    ReasonBucket("rest", "Pozostałe", ("Reszta", "Porzadki", "ZaWysokiPoziom")),
    ReasonBucket("unread", "„Inne” albo nieodczytane", _UNREAD),
)
HEATMAP_BUCKETS = (
    ReasonBucket("skills", "Umiejętności", ("Umiejetnosci",)),
    ReasonBucket("unavailable", "Niedostępni", _UNAVAILABLE),
    ReasonBucket("rate", "Stawka", ("Stawka",)),
    ReasonBucket("mode", "Tryb i umowa", _MODE),
    ReasonBucket("unread", "Nieodczytane", _UNREAD),
)
_BUCKET_BY_KEY = {bucket.key: bucket for bucket in WHY_OUT_BUCKETS}
BUCKET_PATTERN = "^(" + "|".join(_BUCKET_BY_KEY) + ")$"
_HEATMAP_MIN_REJECTIONS = 40

MIN_REFUSALS = 30
MIN_CV_POINTS = 100
MIN_JUSTIFICATIONS = 100
# Wiersz „Powtarza się” z etapu 2: od tylu odmów i takiego udziału tego samego tekstu.
REPEAT_MIN_REFUSALS = 5
REPEAT_MIN_SHARE = 0.6
_QUOTE_LENGTH = 44


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def _of(part: int, whole: int) -> str:
    """„8 z 10”, „60 ze 180”: „ze” przed setką, jak w mowie."""
    return f"{_fmt(part)} {'ze' if 100 <= whole < 200 else 'z'} {_fmt(whole)}"


def _fmt(value: int) -> str:
    return f"{value:,}".replace(",", " ") if value >= 10000 else str(value)


def _pct(part: int, whole: int) -> int:
    return round(100 * part / whole) if whole else 0


def _per_100(part: int, whole: int) -> Optional[float]:
    return round(100 * part / whole, 1) if whole else None


def _midnight_utc(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=_TZ).astimezone(timezone.utc)


def counted_from(today: date) -> datetime:
    return max(cutover_utc(), _midnight_utc(today - timedelta(days=WINDOW_DAYS)))


def _recent_start() -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=RECENT_DAYS)


def counted_from_label(since: datetime) -> str:
    return since.astimezone(_TZ).strftime("%d.%m")


@dataclass(frozen=True)
class CaseCopy:
    """Tekst sprawy, który zostaje w historii także wtedy, gdy reguła już nic nie liczy."""

    title: str
    measure: str
    owner: str
    owner_role: str
    yes_label: str


CASE_COPY = {
    "konkret": CaseCopy(
        title="Klient często odmawia bez konkretu, a zespół nie widzi wzorca",
        measure="odmowy klienta bez powodu",
        owner="Head of Recruitment",
        owner_role=UserRole.head_of_recruitment.value,
        yes_label="Tak, zleć zmianę",
    ),
    "cv": CaseCopy(
        title="Rekruterzy najczęściej przepisują „Dlaczego nasz kandydat”",
        measure="punkty przepisane w tej sekcji",
        owner="Head of Recruitment",
        owner_role=UserRole.head_of_recruitment.value,
        yes_label="Tak, zleć przykłady",
    ),
    "kciuki": CaseCopy(
        title="Kciuków przy dopasowaniu nikt nie używa",
        measure="nie dotyczy",
        owner="Administrator",
        owner_role=UserRole.admin.value,
        yes_label="Tak, zleć zmianę",
    ),
}
CASE_KEYS = tuple(CASE_COPY)

# Zatwierdzone przez Artura 04.11.2026 razem z makietą, budowane w osobnych PR-ach.
# Liczby to stan z tamtego dnia: nowy odczyt nie może ich przepisać.
APPROVED_AT_LAUNCH = (
    {
        "key": "zatrudnieni",
        "title": "System dalej podsuwa ludzi, którzy pracują już gdzie indziej",
        "number": "61",
        "number_note": "kart bez efektu",
        "measure": "karty od systemu dla takich osób",
        "change": "#3034",
        "decided_on": date(2026, 11, 4),
        "review_on": date(2026, 12, 4),
    },
    {
        "key": "inne",
        "title": "W oknie odrzucenia brakuje powodów, które zespół wpisuje ręcznie",
        "number": "38%",
        "number_note": "odrzuceń to „Inne”",
        "measure": "udział „Inne” w odrzuceniach",
        "change": "#3040",
        "decided_on": date(2026, 11, 4),
        "review_on": date(2026, 12, 4),
    },
)
_APPROVED_BY_LABEL = "Artur"


@dataclass(frozen=True)
class Rule:
    """Reguła z października z nagłówka ``services/new_column_autofill.py``."""

    label: str
    reason: str
    reason_label: str
    since: date


CHECKED_RULES = (
    Rule(
        "Stawka do 15% ponad budżet: za resztą",
        "too_expensive",
        "„Za drogo”",
        date(2026, 10, 27),
    ),
    Rule(
        "Mniej dni w biurze, niż chce klient: za resztą",
        "location_mode",
        "„Tryb pracy”",
        date(2026, 10, 27),
    ),
    Rule(
        "„Nie szuka pracy”: system nie dodaje",
        "not_looking",
        "„Nie szuka”",
        date(2026, 10, 28),
    ),
)
# Od tego dnia system sam dodaje ludzi na Tablicę.
SYSTEM_CARDS_START = date(2026, 10, 23)
_CARD_AGE_DAYS = 3
_VERDICT_MIN_ADDED = 200
_VERDICT_MIN_DROP = 0.25


def _quote(raw: str) -> str:
    quote = raw[:1].upper() + raw[1:]
    return (
        quote if len(quote) <= _QUOTE_LENGTH else quote[:_QUOTE_LENGTH].rstrip() + "…"
    )


_JOB_NUMBER = re.compile(r"\((\d{4,6})\)\s*$")


def _job_label(job_id: int, title: Optional[str]) -> str:
    """Numer zlecenia z tytułu, bo tak zespół mówi o rekrutacji; bez niego id."""
    found = _JOB_NUMBER.search(title or "")
    return found.group(1) if found else str(job_id)


_REFUSALS_SQL = f"""
    {_CLASSIFIED},
    refusals AS (
        SELECT * FROM classified WHERE ended_by = 'client'
    ),
    texts AS (
        SELECT job_id, candidate_id, moved_at,
               trim(regexp_replace(regexp_replace(t, '^z cpro:\\s*', ''), '[[:punct:]]', '', 'g')) AS n
        FROM refusals
        WHERE t <> '' AND t !~ '{PROTECTED_RE}'
    ),
    numbered AS (
        SELECT job_id, moved_at, n,
               row_number() OVER (PARTITION BY job_id ORDER BY moved_at) AS total_so_far,
               row_number() OVER (PARTITION BY job_id, n ORDER BY moved_at) AS same_so_far,
               count(*) OVER (PARTITION BY job_id) AS total,
               count(*) OVER (PARTITION BY job_id, n) AS same
        FROM texts
        WHERE n <> ''
    ),
    tops AS (
        SELECT DISTINCT ON (job_id) job_id, n, total, same
        FROM numbered
        WHERE total >= :repeat_min
        ORDER BY job_id, same DESC, n
    ),
    crossed AS (
        SELECT DISTINCT ON (job_id) job_id, moved_at AS crossed_at
        FROM numbered
        WHERE total_so_far >= :repeat_min AND same_so_far >= total_so_far * CAST(:repeat_share AS double precision)
        ORDER BY job_id, moved_at
    )
    SELECT tops.job_id, tops.n, tops.total, tops.same, j.title, COALESCE(cl.name, 'Bez klienta') AS client,
           (SELECT count(DISTINCT s.candidate_id) FROM candidate_stages s
            WHERE s.job_id = tops.job_id AND s.moved_at > crossed.crossed_at
              AND s.stage::text IN ('client_interview', 'acceptance', 'hired')) AS went_on
    FROM tops
    JOIN jobs j ON j.id = tops.job_id
    LEFT JOIN clients cl ON cl.id = j.client_id
    LEFT JOIN crossed ON crossed.job_id = tops.job_id
    ORDER BY tops.same::float / tops.total DESC, tops.same DESC, tops.job_id
"""

_REFUSAL_TOTALS_SQL = f"""
    {_CLASSIFIED}
    SELECT client, count(*) AS total,
           count(*) FILTER (WHERE k = ANY(CAST(:silent AS text[]))) AS silent,
           count(*) FILTER (WHERE k = ANY(CAST(:silent AS text[])) AND moved_at >= :recent) AS recent_silent
    FROM classified
    WHERE ended_by = 'client'
    GROUP BY client
    ORDER BY total DESC, client
"""
_SILENT_KINDS = ["KlientBezKonkretu", "BezOpisu", "Nieodczytane"]


async def _case_refusals(db: AsyncSession, since: datetime) -> dict[str, Any]:
    totals = (
        await db.execute(
            text(_REFUSAL_TOTALS_SQL),
            {"since": since, "silent": _SILENT_KINDS, "recent": _recent_start()},
        )
    ).all()
    total = sum(int(row.total) for row in totals)
    silent = sum(int(row.silent) for row in totals)
    jobs = (
        await db.execute(
            text(_REFUSALS_SQL),
            {
                "since": since,
                "repeat_min": REPEAT_MIN_REFUSALS,
                "repeat_share": REPEAT_MIN_SHARE,
            },
        )
    ).all()
    repeating = [job for job in jobs if job.same >= job.total * REPEAT_MIN_SHARE]
    examples = [job for job in jobs if job.same >= 3][:4]
    leader = totals[0] if totals else None
    leader_part = (
        f" {leader.client}: {_of(int(leader.silent), int(leader.total))}."
        if leader is not None and int(leader.total) < total
        else ""
    )
    example = repeating[0] if repeating else None
    example_part = (
        f" Rekrutacja {_job_label(example.job_id, example.title)}: {_of(int(example.same), int(example.total))}"
        f" odmów to „{_quote(example.n)}”."
        if example is not None
        else ""
    )
    moved_on = max(jobs, key=lambda job: job.went_on, default=None)
    if moved_on is not None and moved_on.went_on > 0:
        count = int(moved_on.went_on)
        verb = _plural(count, "osoba poszła", "osoby poszły", "osób poszło")
        risk = (
            "Wiersz tylko informuje i niczego nie blokuje, bo w rekrutacji "
            f"{_job_label(moved_on.job_id, moved_on.title)} po piątej odmowie {count} {verb} dalej."
        )
    else:
        risk = "Wiersz tylko informuje i niczego nie blokuje. Odmowa bez konkretu nie mówi, że następna osoba też odpadnie."
    copy = CASE_COPY["konkret"]
    ratio = round(total / silent) if silent else 0
    return {
        "key": "konkret",
        "number": f"1 na {ratio}" if ratio >= 2 else f"{_pct(silent, total)}%",
        "number_note": "odmowy klienta bez powodu",
        "count": sum(int(row.recent_silent) for row in totals),
        "sample": total,
        "enough": total >= MIN_REFUSALS,
        "title": copy.title,
        "why": f"{_of(silent, total)} odmów nie mówi, czego zabrakło.{leader_part}{example_part}",
        "if_yes": (
            f"Przy {REPEAT_MIN_REFUSALS} odmowach i {round(REPEAT_MIN_SHARE * 100)}% tego samego tekstu "
            "na Tablicy pojawia się wiersz „Powtarza się”, a DL dostaje prośbę o konkret. "
            f"Dziś dotyczy to {len(repeating)} {_plural(len(repeating), 'rekrutacji', 'rekrutacji', 'rekrutacji')}."
        ),
        "risk": risk,
        "certainty": "Szacunek",
        "evidence": [
            {
                "label": f"{job.client}, {_job_label(job.job_id, job.title)}: „{_quote(job.n)}”",
                "value": f"{int(job.same)} z {int(job.total)}",
            }
            for job in examples
        ],
    }


_CV_KEYS = {"why_points": "why", "responsibilities": "duties"}
_CV_MIN_LENGTH = 25
_BLOCK_SPLIT = re.compile(r"</(?:p|li|h\d|td|div)>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"\s+")
_PUNCT = re.compile(r"[^\w ]+")


def _norm(value: str) -> str:
    plain = html.unescape(_TAGS.sub(" ", value))
    return _PUNCT.sub("", _SPACES.sub(" ", plain).strip().lower())


def _walk(node: Any, key: str = "") -> Iterator[tuple[str, str]]:
    if isinstance(node, str):
        yield key, node
    elif isinstance(node, dict):
        for child_key, child in node.items():
            yield from _walk(child, child_key)
    elif isinstance(node, list):
        for child in node:
            yield from _walk(child, key)


def compare_cv_points(payload: Any, final_html: Optional[str]) -> dict[str, list[int]]:
    """Ile punktów wersji AI dotarło do gotowego CV: ``{sekcja: [zniknęło, wszystkie]}``.

    Porównanie tekstów, nie decyzja: poprawka literówki poniżej 80% podobieństwa liczy
    się jako zmiana, stąd „Szacunek” na ekranie.
    """
    blocks = [
        normed
        for normed in (_norm(part) for part in _BLOCK_SPLIT.split(final_html or ""))
        if len(normed) >= _CV_MIN_LENGTH
    ]
    joined = " ".join(blocks)
    counts = {section: [0, 0] for section in _CV_KEYS.values()}
    for key, value in _walk(payload or {}):
        section = _CV_KEYS.get(key)
        if section is None or len(value) < _CV_MIN_LENGTH:
            continue
        counts[section][1] += 1
        normed = _norm(value)
        if normed in joined or difflib.get_close_matches(
            normed, blocks, n=1, cutoff=0.8
        ):
            continue
        counts[section][0] += 1
    return counts


_CV_SQL = """
    SELECT COALESCE(cl.name, 'Bez klienta') AS client, d.render_payload,
           c.branded_draft_html AS final_html, c.branded_finalized_at AS finalized_at
    FROM candidate_stage_cvs c
    JOIN cv_generated_documents d ON d.id = c.generated_document_id
    JOIN jobs j ON j.id = c.job_id
    LEFT JOIN clients cl ON cl.id = j.client_id
    WHERE c.branded_from_generator AND c.branded_finalized_at IS NOT NULL
"""
_CV_CLIENT_MIN_POINTS = 100


def summarize_cv(
    rows: Iterable[tuple[str, Any, Optional[str], datetime]], *, recent: datetime
) -> dict[str, Any]:
    per_client: dict[str, dict[str, list[int]]] = {}
    cvs = 0
    why_recent = 0
    for client, payload, final_html, finalized_at in rows:
        cvs += 1
        counts = compare_cv_points(payload, final_html)
        if finalized_at >= recent:
            why_recent += counts["why"][0]
        bucket = per_client.setdefault(client, {s: [0, 0] for s in _CV_KEYS.values()})
        for section, (gone, all_points) in counts.items():
            bucket[section][0] += gone
            bucket[section][1] += all_points
    why = [
        sum(c["why"][0] for c in per_client.values()),
        sum(c["why"][1] for c in per_client.values()),
    ]
    duties = [
        sum(c["duties"][0] for c in per_client.values()),
        sum(c["duties"][1] for c in per_client.values()),
    ]
    outlier: Optional[tuple[str, int, int]] = None
    for client, counts in per_client.items():
        gone, all_points = counts["duties"]
        if all_points >= _CV_CLIENT_MIN_POINTS and (
            outlier is None or gone / all_points > outlier[1] / outlier[2]
        ):
            outlier = (client, gone, all_points)
    return {
        "cvs": cvs,
        "why": why,
        "why_recent": why_recent,
        "duties": duties,
        "outlier": outlier,
    }


async def _summarize_cv_rows(rows: Any) -> dict[str, Any]:
    # Porównanie tekstów trwa ok. sekundy, a backend ma jeden wątek obsługi żądań.
    return await asyncio.to_thread(
        summarize_cv,
        [
            (row.client, row.render_payload, row.final_html, row.finalized_at)
            for row in rows
        ],
        recent=_recent_start(),
    )


async def _case_cv(db: AsyncSession) -> dict[str, Any]:
    rows = (await db.execute(text(_CV_SQL))).all()
    summary = await _summarize_cv_rows(rows)
    why_gone, why_all = summary["why"]
    duties_gone, duties_all = summary["duties"]
    evidence = [
        {"label": "„Dlaczego nasz kandydat”", "value": _of(why_gone, why_all)},
        {"label": "Obowiązki", "value": _of(duties_gone, duties_all)},
    ]
    if summary["outlier"]:
        client, gone, all_points = summary["outlier"]
        evidence.append(
            {"label": f"{client}, obowiązki", "value": _of(gone, all_points)}
        )
    copy = CASE_COPY["cv"]
    return {
        "key": "cv",
        "number": f"{_pct(why_gone, why_all)}%",
        "number_note": "punktów znika przy edycji",
        "count": summary["why_recent"],
        "sample": why_all,
        "enough": why_all >= MIN_CV_POINTS,
        "title": copy.title,
        "why": (
            f"{_pct(why_gone, why_all)}% punktów tej sekcji nie trafia do gotowego CV, przy obowiązkach to "
            f"{_pct(duties_gone, duties_all)}%. To porównanie tekstów z {summary['cvs']} CV, "
            "więc najpierw warto obejrzeć przykłady."
        ),
        "if_yes": (
            "Dostajesz 20 par „wersja AI i gotowe CV” z propozycją nowej instrukcji sekcji. "
            "Publikujesz ją osobno, po obejrzeniu."
        ),
        "risk": "Żadnej zmiany w generatorze bez Twojej drugiej decyzji.",
        "certainty": "Szacunek",
        "evidence": evidence,
    }


async def _case_thumbs(db: AsyncSession) -> dict[str, Any]:
    row = (
        await db.execute(
            text(
                """
                SELECT (SELECT count(*) FROM candidate_match_justifications) AS justifications,
                       (SELECT count(*) FROM candidate_match_justifications
                        WHERE created_at >= :recent) AS recent_justifications,
                       (SELECT count(rating) FROM candidate_match_justifications) AS rated,
                       (SELECT count(*) FROM interview_question_ratings) AS question_ratings
                """
            ),
            {"recent": _recent_start()},
        )
    ).one()
    justifications, rated = int(row.justifications), int(row.rated)
    copy = CASE_COPY["kciuki"]
    return {
        "key": "kciuki",
        "number": _fmt(rated),
        "number_note": f"ocen na {_fmt(justifications)} uzasadnień",
        "count": int(row.recent_justifications),
        "sample": justifications,
        # Sprawa istnieje, dopóki oceny są marginesem: przy 1% to już sygnał, nie martwy przycisk.
        "enough": justifications >= MIN_JUSTIFICATIONS and rated * 100 < justifications,
        "title": copy.title,
        "why": "Nikt ich nie klika i żaden kod ich nie czyta. Kciuków przy pytaniach na rozmowę też nikt nie użył.",
        "if_yes": "Kciuki znikają z ekranów, a sygnał bierzemy z ruchu karty i powodu odrzucenia.",
        "risk": "Brak. Kolumny w bazie zostają, więc można to cofnąć.",
        "certainty": "Policzone",
        "evidence": [
            {"label": "Oceny przy dopasowaniu", "value": _of(rated, justifications)},
            {
                "label": "Oceny pytań na rozmowę",
                "value": _fmt(int(row.question_ratings)),
            },
        ],
    }


async def _watching(db: AsyncSession) -> list[dict[str, str]]:
    """Za mało danych na decyzję. Bez progów i bez przycisków.

    Wynik liczy się bez przerzuceń (``reassign``): ich wynik to wynik w poprzedniej
    rekrutacji, a nie pomiar dopasowania.
    """
    row = (
        await db.execute(
            text(
                """
                WITH added AS (
                    SELECT p.score, EXISTS (
                        SELECT 1 FROM candidate_stages s
                        WHERE s.job_id = p.job_id AND s.candidate_id = p.candidate_id
                          AND s.stage::text IN ('verified', 'cv_sent', 'interview',
                                                'client_interview', 'acceptance', 'hired')
                    ) AS verified
                    FROM job_proposals p
                    WHERE p.status = 'added' AND p.source <> 'reassign'
                )
                SELECT
                    (SELECT count(*) FROM autofill_feedback WHERE reason = 'missing_skill') AS skill_all,
                    (SELECT count(*) FROM autofill_feedback
                     WHERE reason = 'missing_skill' AND note ~* 'bank') AS skill_bank,
                    (SELECT count(*) FROM added WHERE score >= 80) AS top_all,
                    (SELECT count(*) FROM added WHERE score >= 80 AND verified) AS top_verified,
                    (SELECT count(*) FROM added WHERE score >= 75 AND score < 80) AS near_all,
                    (SELECT count(*) FROM added WHERE score >= 75 AND score < 80 AND verified) AS near_verified,
                    (SELECT count(*) FROM notifications
                     WHERE notification_type::text = 'cv_ready'
                       AND created_at >= now() - INTERVAL '60 days') AS ready_all,
                    (SELECT count(*) FROM notifications
                     WHERE notification_type::text = 'cv_ready' AND is_read
                       AND created_at >= now() - INTERVAL '60 days') AS ready_read
                """
            ),
        )
    ).one()
    return [
        {
            "text": "„Brak bankowości” w opisach odrzuceń",
            "value": _of(int(row.skill_bank), int(row.skill_all)),
        },
        {
            "text": f"Wynik 80+ a zweryfikowani (75–79: {_of(int(row.near_verified), int(row.near_all))})",
            "value": _of(int(row.top_verified), int(row.top_all)),
        },
        {
            "text": "„CV gotowe” przeczytane",
            "value": f"{_pct(int(row.ready_read), int(row.ready_all))}% {'ze' if 100 <= int(row.ready_all) < 200 else 'z'} {_fmt(int(row.ready_all))}",
        },
    ]


async def compute_cases(db: AsyncSession, today: date) -> dict[str, Any]:
    """Wynik reguł bez decyzji. Trasa trzyma go 5 minut, a decyzje czyta na świeżo."""
    since = counted_from(today)
    cases = [
        await _case_refusals(db, since),
        await _case_cv(db),
        await _case_thumbs(db),
    ]
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "counted_from": since.isoformat(),
        "counted_from_label": counted_from_label(since),
        "cases": cases,
        "watching": await _watching(db),
    }


def is_case_open(count: int, latest: Optional[Any], today: date) -> bool:
    """Czy sprawa czeka na decyzję, patrząc na ostatnią decyzję i liczbę dziś.

    „Tak” zamyka sprawę na stałe, „Nie teraz” chowa do ``return_on``, „Nie” do
    dwukrotnego wzrostu liczby z chwili decyzji.
    """
    if latest is None:
        return True
    if latest.state == STATE_APPROVED:
        return False
    if latest.state == STATE_LATER:
        return latest.return_on is None or latest.return_on <= today
    return count >= 2 * max(latest.count_at_decision, 1)


def open_cases(
    cases: list[dict[str, Any]], latest: dict[str, Any], today: date
) -> list[dict[str, Any]]:
    """Najwyżej ``MAX_OPEN_CASES``, od najważniejszej (kolejność reguł w ``compute_cases``)."""
    ready = [
        case
        for case in cases
        if case["enough"]
        and is_case_open(case["count"], latest.get(case["key"]), today)
    ]
    return ready[:MAX_OPEN_CASES]


def with_copy(case: dict[str, Any]) -> dict[str, Any]:
    copy = CASE_COPY[case["key"]]
    return {
        **case,
        "yes_label": copy.yes_label,
        "owner": copy.owner,
        "owner_role": copy.owner_role,
        "measure": copy.measure,
    }


async def latest_decisions(db: AsyncSession) -> dict[str, InsightDecision]:
    rows = (
        await db.execute(
            select(InsightDecision)
            .distinct(InsightDecision.insight_key)
            .order_by(
                InsightDecision.insight_key,
                InsightDecision.decided_at.desc(),
                InsightDecision.id.desc(),
            )
        )
    ).scalars()
    return {row.insight_key: row for row in rows}


async def lock_case(db: AsyncSession, key: str) -> None:
    """Dwie osoby klikają tę samą sprawę: druga ma zobaczyć decyzję pierwszej."""
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock))"),
        {"lock": f"insight_decision:{key}"},
    )


def decision_dates(state: str, today: date) -> tuple[Optional[date], Optional[date]]:
    """``(return_on, review_on)`` nowej decyzji."""
    if state == STATE_LATER:
        return today + timedelta(days=LATER_DAYS), None
    if state == STATE_APPROVED:
        return None, today + timedelta(days=REVIEW_DAYS)
    return None, None


async def _measure_now(
    db: AsyncSession, key: str, since: datetime, cv_cache: dict[str, Any]
) -> Optional[str]:
    """Ta sama miara co przy decyzji, liczona od decyzji. ``None``: bez miary."""
    if key == "konkret":
        row = (
            await db.execute(
                text(_REFUSAL_TOTALS_SQL),
                {"since": since, "silent": _SILENT_KINDS, "recent": since},
            )
        ).all()
        total = sum(int(item.total) for item in row)
        silent = sum(int(item.silent) for item in row)
        return f"{_pct(silent, total)}% ({_of(silent, total)})"
    if key == "cv":
        if "summary" not in cv_cache:
            rows = (
                await db.execute(
                    text(_CV_SQL + " AND c.branded_finalized_at >= :since"),
                    {"since": since},
                )
            ).all()
            cv_cache["summary"] = await _summarize_cv_rows(rows)
        gone, all_points = cv_cache["summary"]["why"]
        return f"{_pct(gone, all_points)}% ({_of(gone, all_points)})"
    if key == "inne":
        row = (
            await db.execute(
                text(
                    f"{_CLASSIFIED} SELECT count(*) AS total, "
                    "count(*) FILTER (WHERE is_other) AS other FROM classified"
                ),
                {"since": since},
            )
        ).one()
        return f"{_pct(int(row.other), int(row.total))}% ({_of(int(row.other), int(row.total))})"
    if key == "zatrudnieni":
        row = (
            await db.execute(
                text(
                    """
                    WITH z AS (
                        SELECT cs.candidate_id, min(cs.moved_at) AS at
                        FROM candidate_stages cs
                        JOIN rejection_reasons r ON r.id = cs.rejection_reason_id
                        WHERE r.name = 'Zatrudniony gdzie indziej'
                        GROUP BY cs.candidate_id
                    )
                    SELECT count(*) AS cards
                    FROM recruitment_processes rp
                    JOIN z ON z.candidate_id = rp.candidate_id
                    WHERE rp.entry_source = 'system' AND rp.opened_at > z.at AND rp.opened_at >= :since
                    """
                ),
                {"since": since},
            )
        ).one()
        return f"{_fmt(int(row.cards))} kart"
    return None


def rule_verdict(before: tuple[int, int], after: tuple[int, int]) -> str:
    """Wynik reguły po terminie oceny, z par (odrzuceni z powodu, dodani)."""
    (before_hits, before_added), (after_hits, after_added) = before, after
    if before_added < _VERDICT_MIN_ADDED or after_added < _VERDICT_MIN_ADDED:
        return "Za mało danych"
    before_rate = before_hits / before_added
    after_rate = after_hits / after_added
    if before_rate > 0 and after_rate <= before_rate * (1 - _VERDICT_MIN_DROP):
        return "Pomogło"
    return "Nie widać poprawy"


_RULE_SQL = """
    WITH cards AS (
        SELECT rp.job_id, rp.candidate_id, rp.opened_at, rp.opened_at < :since AS is_before
        FROM recruitment_processes rp
        WHERE rp.entry_source = 'system' AND rp.opened_at >= :start AND rp.opened_at < :until
    ),
    refused AS (
        SELECT cards.is_before, f.reason
        FROM cards
        JOIN autofill_feedback f ON f.job_id = cards.job_id AND f.candidate_id = cards.candidate_id
        WHERE f.created_at <= cards.opened_at + make_interval(days => :age)
    )
    SELECT
        (SELECT count(*) FROM cards WHERE is_before) AS added_before,
        (SELECT count(*) FROM cards WHERE NOT is_before) AS added_after,
        (SELECT count(*) FROM refused WHERE is_before) AS refused_before,
        (SELECT count(*) FROM refused WHERE NOT is_before) AS refused_after,
        (SELECT count(*) FROM refused WHERE is_before AND reason = :reason) AS hits_before,
        (SELECT count(*) FROM refused WHERE NOT is_before AND reason = :reason) AS hits_after
"""


async def _rule_row(db: AsyncSession, rule: Rule, today: date) -> dict[str, Any]:
    review_on = rule.since + timedelta(days=REVIEW_DAYS)
    now = datetime.now(timezone.utc)
    # Karty młodsze niż 3 dni jeszcze nie miały czasu odpaść.
    until = min(_midnight_utc(review_on), now - timedelta(days=_CARD_AGE_DAYS))
    row = (
        await db.execute(
            text(_RULE_SQL),
            {
                "since": _midnight_utc(rule.since),
                "start": _midnight_utc(SYSTEM_CARDS_START),
                "until": until,
                "age": _CARD_AGE_DAYS,
                "reason": rule.reason,
            },
        )
    ).one()
    before = (int(row.hits_before), int(row.added_before))
    after = (int(row.hits_after), int(row.added_after))
    return {
        "rule": rule.label,
        "since": rule.since.strftime("%d.%m"),
        "metric": rule.reason_label,
        "before": {
            "hits": before[0],
            "added": before[1],
            "refused": int(row.refused_before),
            "per_100": _per_100(*before),
        },
        "after": {
            "hits": after[0],
            "added": after[1],
            "refused": int(row.refused_after),
            "per_100": _per_100(*after),
        },
        "review_on": review_on.isoformat(),
        "verdict": rule_verdict(before, after) if review_on <= today else None,
    }


def rules_takeaway(rows: list[dict[str, Any]]) -> Optional[str]:
    """Czemu sam udział myli, na liczbach pierwszej reguły."""
    if not rows:
        return None
    first = rows[0]
    before, after = first["before"], first["after"]
    if (
        not before["refused"]
        or not after["refused"]
        or before["per_100"] is None
        or after["per_100"] is None
    ):
        return None
    share_before = _pct(before["hits"], before["refused"])
    share_after = _pct(after["hits"], after["refused"])
    per_100 = f"{str(before['per_100']).replace('.', ',')} i {str(after['per_100']).replace('.', ',')}"
    return (
        f"Udział {first['metric']} w odrzuceniach to {share_before}% przed regułą i {share_after}% po niej, "
        f"ale na 100 dodanych osób {per_100}. Sam udział myli, bo zmienia się też to, jak często ludzie "
        "odrzucają, więc werdykt dopiero po 30 dniach."
    )


async def compute_history(db: AsyncSession, today: date) -> dict[str, Any]:
    decisions = (
        await db.execute(
            select(InsightDecision, User.name)
            .outerjoin(User, User.id == InsightDecision.decided_by_id)
            .order_by(InsightDecision.decided_at.desc(), InsightDecision.id.desc())
        )
    ).all()
    cv_cache: dict[str, Any] = {}
    approved: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    for row, decided_by in decisions:
        copy = CASE_COPY.get(row.insight_key)
        title = copy.title if copy else row.insight_key
        base = {
            "key": row.insight_key,
            "title": title,
            "number": row.number_at_decision,
            "decided_at": row.decided_at.isoformat(),
            "decided_by": decided_by,
        }
        if row.state == STATE_APPROVED:
            due = row.review_on is not None and row.review_on <= today
            approved.append(
                {
                    **base,
                    "measure": copy.measure if copy else "",
                    "review_on": row.review_on.isoformat() if row.review_on else None,
                    "measure_now": (
                        await _measure_now(
                            db, row.insight_key, row.decided_at, cv_cache
                        )
                        if due
                        else None
                    ),
                    "change": None,
                }
            )
        else:
            deferred.append(
                {
                    **base,
                    "state": row.state,
                    "return_on": row.return_on.isoformat() if row.return_on else None,
                    "return_count": 2 * max(row.count_at_decision, 1)
                    if row.state == STATE_REJECTED
                    else None,
                }
            )
    for seed in APPROVED_AT_LAUNCH:
        due = seed["review_on"] <= today
        approved.append(
            {
                "key": seed["key"],
                "title": seed["title"],
                "number": seed["number"],
                "number_note": seed["number_note"],
                "decided_at": _midnight_utc(seed["decided_on"]).isoformat(),
                "decided_by": _APPROVED_BY_LABEL,
                "measure": seed["measure"],
                "review_on": seed["review_on"].isoformat(),
                "measure_now": (
                    await _measure_now(
                        db, seed["key"], _midnight_utc(seed["decided_on"]), cv_cache
                    )
                    if due
                    else None
                ),
                "change": seed["change"],
            }
        )
    rules = [await _rule_row(db, rule, today) for rule in CHECKED_RULES]
    return {
        "approved": approved,
        "deferred": deferred,
        "rules": rules,
        "rules_takeaway": rules_takeaway(rules),
    }


_REASONS_SQL = f"""
    {_CLASSIFIED}
    SELECT client_id, client, is_other, k, count(*) AS total
    FROM classified
    GROUP BY client_id, client, is_other, k
"""


def build_reasons(rows: Iterable[Any]) -> dict[str, Any]:
    """Wykres „przed i po odczytaniu” i tabela klient × powód z jednego rozkładu."""
    today_counts: dict[str, int] = {}
    after_counts: dict[str, int] = {}
    total = 0
    clients: dict[tuple[Optional[int], str], dict[str, int]] = {}
    kind_to_bucket = {
        kind: bucket.key for bucket in WHY_OUT_BUCKETS for kind in bucket.kinds
    }
    for row in rows:
        count = int(row.total)
        total += count
        bucket = kind_to_bucket[row.k]
        after_counts[bucket] = after_counts.get(bucket, 0) + count
        today_bucket = "unread" if row.is_other else bucket
        today_counts[today_bucket] = today_counts.get(today_bucket, 0) + count
        per_client = clients.setdefault((row.client_id, row.client), {})
        per_client[bucket] = per_client.get(bucket, 0) + count
    why_out = [
        {
            "key": bucket.key,
            "reason": bucket.label,
            "today": today_counts.get(bucket.key, 0),
            "after": after_counts.get(bucket.key, 0),
        }
        for bucket in WHY_OUT_BUCKETS
    ]
    heatmap = sorted(
        (
            {
                "client_id": client_id,
                "client": client,
                "total": sum(counts.values()),
                "values": [counts.get(bucket.key, 0) for bucket in HEATMAP_BUCKETS],
            }
            for (client_id, client), counts in clients.items()
            if sum(counts.values()) >= _HEATMAP_MIN_REJECTIONS
        ),
        key=lambda item: (-item["total"], item["client"]),
    )
    unread_today = today_counts.get("unread", 0)
    unread_after = after_counts.get("unread", 0)
    unavailable = after_counts.get("unavailable", 0)
    return {
        "total": total,
        "why_out": why_out,
        "why_out_takeaway": (
            f"Odczyt opisów zmniejsza „Inne” z {unread_today} do {unread_after} i pokazuje, że "
            f"{_pct(unavailable, total)}% z {_fmt(total)} odrzuceń to osoby niedostępne."
            if total
            else None
        ),
        "columns": [
            {"key": bucket.key, "label": bucket.label} for bucket in HEATMAP_BUCKETS
        ],
        "heatmap": heatmap,
        "heatmap_takeaway": _heatmap_takeaway(heatmap, after_counts, total),
    }


def _heatmap_takeaway(
    heatmap: list[dict[str, Any]], after_counts: dict[str, int], total: int
) -> Optional[str]:
    """Trzy największe odchylenia od całości, po jednym na klienta. Bez „Nieodczytane”."""
    if not total:
        return None
    gaps = []
    for row in heatmap:
        best = None
        for index, bucket in enumerate(HEATMAP_BUCKETS):
            if bucket.key == "unread":
                continue
            share = 100 * row["values"][index] / row["total"]
            gap = share - 100 * after_counts.get(bucket.key, 0) / total
            if best is None or gap > best[0]:
                best = (gap, bucket.label.lower(), round(share))
        if best is not None and best[0] > 0:
            gaps.append((best[0], row["client"], best[1], best[2]))
    gaps.sort(reverse=True)
    parts = [f"{client}: {label} {share}%" for _, client, label, share in gaps[:3]]
    return f"Najbardziej odstają od całości. {'; '.join(parts)}." if parts else None


async def compute_reasons(db: AsyncSession, today: date) -> dict[str, Any]:
    since = counted_from(today)
    rows = (await db.execute(text(_REASONS_SQL), {"since": since})).all()
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "counted_from": since.isoformat(),
        "counted_from_label": counted_from_label(since),
        **build_reasons(rows),
    }


_PEOPLE_SQL = f"""
    {_CLASSIFIED}
    SELECT c.candidate_id, cand.name AS first_name, cand.lastname AS last_name,
           c.moved_at, c.job_id, c.job_title, c.client,
           count(*) OVER () AS total
    FROM classified c
    JOIN candidates cand ON cand.id = c.candidate_id
    WHERE {{condition}}
    ORDER BY c.moved_at DESC, c.stage_id DESC
    LIMIT :limit OFFSET :offset
"""


async def compute_reason_people(
    db: AsyncSession,
    *,
    today: date,
    bucket: str,
    basis: str,
    client_id: Optional[int],
    limit: int,
    offset: int,
) -> dict[str, Any]:
    """Odrzucenia za liczbą. Bez opisu odrzucenia: lista ma odpowiedzieć „kto”, nie „co”."""
    kinds = list(_BUCKET_BY_KEY[bucket].kinds)
    if basis == "after":
        condition = "k = ANY(CAST(:kinds AS text[]))"
    elif bucket == "unread":
        condition = "is_other"
    else:
        condition = "NOT is_other AND k = ANY(CAST(:kinds AS text[]))"
    params: dict[str, Any] = {
        "since": counted_from(today),
        "limit": limit,
        "offset": offset,
    }
    if ":kinds" in condition:
        params["kinds"] = kinds
    if client_id is not None:
        condition += " AND c.client_id = :client_id"
        params["client_id"] = client_id
    rows = (
        await db.execute(text(_PEOPLE_SQL.format(condition=condition)), params)
    ).all()
    return {
        "total": int(rows[0].total) if rows else 0,
        "rows": [
            {
                "candidate_id": row.candidate_id,
                "name": " ".join(
                    part for part in (row.first_name, row.last_name) if part
                ),
                "rejected_at": row.moved_at.isoformat(),
                "job_id": row.job_id,
                "job_title": row.job_title,
                "client": row.client,
            }
            for row in rows
        ],
    }


_COLLECTED_SQL = """
    SELECT
        (SELECT count(*) FROM cv_finding_dismissals) AS qc_dismissals,
        (SELECT count(*) FROM autofill_feedback) AS system_refusals,
        (SELECT count(*) FROM job_proposals WHERE status = 'expired') AS expired_proposals,
        (SELECT count(*) FROM candidate_stage_cvs c
         JOIN cv_generated_documents d ON d.id = c.generated_document_id
         WHERE c.branded_from_generator AND c.branded_finalized_at IS NOT NULL) AS final_cvs,
        (SELECT count(*) FROM notifications WHERE created_at >= now() - INTERVAL '60 days') AS notifications,
        (SELECT count(*) FROM notifications
         WHERE is_read AND created_at >= now() - INTERVAL '60 days') AS notifications_read,
        (SELECT count(*) FROM order_mail_documents
         WHERE reviewed_at IS NOT NULL AND outcome IN ('applied', 'auto_applied')) AS order_decisions,
        (SELECT count(*) FROM cc_suggestion_overrides) AS category_overrides,
        (SELECT count(*) FROM candidate_match_justifications) AS justifications,
        (SELECT count(rating) FROM candidate_match_justifications) AS justifications_rated,
        (SELECT count(*) FROM interview_question_ratings) AS question_ratings
"""

COLLECT_WORKS = "Działa samo"
COLLECT_REPORT = "Tylko raport"
COLLECT_UNREAD = "Nikt nie czyta"
COLLECT_UNUSED = "Nikt nie używa"
COLLECT_ORDER = (COLLECT_WORKS, COLLECT_REPORT, COLLECT_UNREAD, COLLECT_UNUSED)


async def compute_collected(db: AsyncSession, today: date) -> dict[str, Any]:
    since = counted_from(today)
    row = (await db.execute(text(_COLLECTED_SQL))).one()
    rejections = (
        await db.execute(
            text(
                f"{_CLASSIFIED} SELECT count(*) AS total, "
                "count(*) FILTER (WHERE ended_by = 'client') AS client, "
                "count(*) FILTER (WHERE is_other) AS other FROM classified"
            ),
            {"since": since},
        )
    ).one()
    rows = [
        (
            "Uwagi „to nieprawda” przy kontroli CV",
            _fmt(int(row.qc_dismissals)),
            "Słabe sprawdzenia same się wyciszają",
            COLLECT_WORKS,
            "Zostaje",
        ),
        (
            "Kto doszedł do „Zweryfikowany”",
            "ruchy kart",
            "Ustawia kolejność propozycji",
            COLLECT_WORKS,
            "Zostaje",
        ),
        (
            "Odrzucenia osób od systemu",
            _fmt(int(row.system_refusals)),
            "Raport tygodniowy z propozycjami, bez decyzji",
            COLLECT_REPORT,
            "Propozycje trafiają do Wniosków",
        ),
        (
            "Powody odrzuceń",
            _fmt(int(rejections.total)),
            f"Raport lejka, {_pct(int(rejections.other), int(rejections.total))}% to „Inne”",
            COLLECT_REPORT,
            "Nowe powody w oknie",
        ),
        (
            "Odmowy klienta",
            _fmt(int(rejections.client)),
            "Widać je pojedynczo przy osobie",
            COLLECT_REPORT,
            "„Powtarza się”",
        ),
        (
            "Propozycje wygasłe bez reakcji",
            _fmt(int(row.expired_proposals)),
            "Nic poza statusem",
            COLLECT_UNREAD,
            "Pomiar wag, gdy będzie próba",
        ),
        (
            "Poprawki w gotowych CV",
            f"{_fmt(int(row.final_cvs))} CV",
            "Działają dla jednej osoby",
            COLLECT_UNREAD,
            "Przykłady do oceny",
        ),
        (
            "Powiadomienia przeczytane, 60 dni",
            f"{_pct(int(row.notifications_read), int(row.notifications))}% z {_fmt(int(row.notifications))}",
            "Sterują tylko dzwonkiem",
            COLLECT_UNREAD,
            "Obserwujemy",
        ),
        (
            "Ręczne decyzje przy zamówieniach z PDF",
            _fmt(int(row.order_decisions)),
            "Odczyt nie jest porównywany z decyzją",
            COLLECT_UNREAD,
            "Później",
        ),
        (
            "Zmienione kategorie rekrutacji",
            _fmt(int(row.category_overrides)),
            "Zapisane, bez ekranu",
            COLLECT_UNREAD,
            "Później",
        ),
        (
            "Kciuki przy dopasowaniu",
            _of(int(row.justifications_rated), int(row.justifications)),
            "Nic",
            COLLECT_UNUSED,
            "Usunąć",
        ),
        (
            "Kciuki przy pytaniach na rozmowę",
            _fmt(int(row.question_ratings)),
            "Nic",
            COLLECT_UNUSED,
            "Usunąć",
        ),
    ]
    return {
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "statuses": list(COLLECT_ORDER),
        "rows": [
            {
                "signal": signal,
                "amount": amount,
                "today": note,
                "status": status_,
                "next": next_step,
            }
            for signal, amount, note, status_, next_step in rows
        ],
    }
