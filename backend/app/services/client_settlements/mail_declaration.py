"""Deklaracja konsultanta w treści maila jako raport za miesiąc. Bez bazy.

Reguła klienta ``report.consultant_declaration`` (decyzja Artura z 23.11.2026,
„Deklaracja wystarcza”): u klienta bez pliku godzin raportem jest zdanie
konsultanta w mailu z fakturą, np. „We wrześniu nie miałam dni wolnych”.

* „nie miałam/miałem (żadnych) dni wolnych”, „bez dni wolnych”, „pełny miesiąc”
  → MD = dni robocze miesiąca (kalendarz firmy, jak reszta modułu);
* „miałam 2 dni wolnego”, „miałem 3 dni urlopu” → dni robocze minus ta liczba.
* „w dniach 3.06 i 08.06 byłam niedostępna”, „w dniach 17-21 oraz 31 byłam
  niedostępna” (mLeasing, VI–VIII 2026) → dni robocze minus dni robocze z listy;
  zapowiedź „w dniach 27-31 będę niedostępna” liczy się tak samo, ale z uwagą
  (decyzja Artura z 25.11.2026: MD wpisane, przyjęcie po spojrzeniu Finansów).

Zdanie (albo jego część między przecinkami) musi nazywać miesiąc pełną nazwą
i poza deklaracją nie mieć nic znaczącego (biała lista ``_FILLER``). Bez nazwy
miesiąca, za inny miesiąc, bez liczby („miałam dni wolne”), z ułamkiem dnia,
w innym czasie („będę miała”), z przeczeniem („nie przepracowałam pełnego
miesiąca”), z chorobą albo nieobecnością, z dwiema różnymi deklaracjami — MD
nie wpisujemy, przypadek idzie do Finansów. Czytamy tylko własną część
maila: cytowany wątek pod „Od:”/„From:” i linie z „>” pomijamy.

Że nadawca jest konsultantem z kontraktu, sprawdza wywołujący (``service``),
bo potrzebuje bazy; zdanie od koordynatora o kimś innym nie jest deklaracją.
"""

from __future__ import annotations

import calendar
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Mapping, Optional

from app.services.client_settlements import mail_text
from app.services.client_settlements.declared import month_mismatch, short_lines
from app.services.client_settlements.rcp_checks import ProofResult, _fmt, _Group
from app.services.client_settlements.timesheet_pko import month_limit
from app.services.person_workdays import business_days

SOURCE = "Deklaracja konsultanta"
RULE = "report.consultant_declaration"

_WORDS = {"jeden": 1, "jedna": 1, "dwa": 2, "dwie": 2, "trzy": 3, "cztery": 4}
#: Liczba całkowita; ułamek („0,5 dnia”) nie pasuje i idzie do człowieka.
_COUNT_WORD = r"(\d{1,2}(?![.,]\d)|" + "|".join(_WORDS) + r")"
_DAY = r"(?:dni|dzien|dnia)"
#: Tekst po ``_fold``: małe litery bez ogonków („miałam” → „mialam”). Tylko czas
#: przeszły w pierwszej osobie: „będę miała”, „miała” (o kimś) nie pasują.
#: „dni wolnych od pracy” znaczy to samo co „dni wolnych” (mLeasing, IX 2026).
_FROM_WORK = r"(?:\s+od\s+pracy)?"
_FULL = re.compile(
    r"\bnie\s+mial(?:am|em)\s+(?:zadnych\s+)?(?:dni\s+wolnych|wolnego)"
    + _FROM_WORK
    + r"\b|\bbez\s+(?:zadnych\s+)?dni\s+wolnych"
    + _FROM_WORK
    + r"\b|\bpe(?:lny|len)\s+miesiac\b"
)
_COUNT = re.compile(
    r"\b(nie\s+)?mial(?:am|em)\s+"
    + _COUNT_WORD
    + r"\s+"
    + _DAY
    + r"\s+(?:wolnego|wolnych|wolny|urlopu)"
    + _FROM_WORK
    + r"\b"
)
#: Pełne formy nazw miesięcy (po ``_fold``). Same rdzenie łapały imiona:
#: „Marta”, „Marek”, „Lipski”.
_MONTH_FORMS = {
    form: index + 1
    for index, forms in enumerate(
        (
            ("styczen", "stycznia", "styczniu"),
            ("luty", "lutego", "lutym"),
            ("marzec", "marca", "marcu"),
            ("kwiecien", "kwietnia", "kwietniu"),
            ("maj", "maja", "maju"),
            ("czerwiec", "czerwca", "czerwcu"),
            ("lipiec", "lipca", "lipcu"),
            ("sierpien", "sierpnia", "sierpniu"),
            ("wrzesien", "wrzesnia", "wrzesniu"),
            ("pazdziernik", "pazdziernika", "pazdzierniku"),
            ("listopad", "listopada", "listopadzie"),
            ("grudzien", "grudnia", "grudniu"),
        )
    )
    for form in forms
}
#: Nazwa miesiąca bez jednej litery („wrzeniu”, mLeasing IX 2026), tylko dla form
#: od 7 liter: krótsze („maja”, „luty”) bez litery dają inne słowa.
_MONTH_NAMES = {
    **{
        form[:i] + form[i + 1 :]: month
        for form, month in _MONTH_FORMS.items()
        if len(form) >= 7
        for i in range(len(form))
    },
    **_MONTH_FORMS,
}
_MONTH = re.compile(
    r"\b("
    + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True))
    + r")\b(?:\s+(20\d{2})\b(?:\s+r\b)?)?"
)
#: Słowa, które mogą stać obok deklaracji. Każde inne („nie przepracowałam”,
#: „byłam chora”, „pracowałam 15 dni”, „będę”, „czy”) = człowiek: przy kwotach
#: lepiej przepuścić deklarację do Finansów niż wpisać złe MD.
_FILLER = frozenset(
    {
        "w",
        "we",
        "za",
        "i",
        "a",
        "oraz",
        "tez",
        "rowniez",
        "takze",
        "miesiacu",
        "miesiac",
        "rok",
        "roku",
        "przepracowalam",
        "przepracowalem",
        "caly",
        "calym",
    }
)
#: Wzmianka o nieobecności albo dniach pracy w zdaniu bez deklaracji = człowiek.
_ABSENCE = re.compile(
    r"\b" + _DAY + r"\s+woln|\bwolne\b|\bwolnego\b|\burlop|\bl4\b|\bchor"
    r"|\bzwolnien|\bnieobecn|\bdni\b|\bpracowal|\bprzepracowal"
)
#: Lista dni: „3.06 i 08.06”, „17-21 oraz 31”, „27–31”.
_DAY_ITEM = r"\d{1,2}(?:\.\d{1,2}(?:\.\d{4})?)?"
_DAY_SPAN = _DAY_ITEM + r"(?:\s*[-–]\s*" + _DAY_ITEM + r")?"
_DAY_LIST = _DAY_SPAN + r"(?:\s*(?:\bi\b|\boraz\b)\s*" + _DAY_SPAN + r")*"
_UNAVAILABLE = r"(?:(bylam|bylem)|(bede))\s+niedostepn[ay]\b"
_LISTED = (
    re.compile(r"\bw\s+dni(?:ach|u)\s+(" + _DAY_LIST + r")\s+" + _UNAVAILABLE),
    re.compile(_UNAVAILABLE + r"\s+w\s+dni(?:ach|u)\s+(" + _DAY_LIST + r")(?!\S)"),
)
_DAY_PART = re.compile(r"(\d{1,2})(?:\.(\d{1,2})(?:\.(\d{4}))?)?")
_QUOTED_HEADER = re.compile(r"^(?:od|from|wys[lł]ano|sent)\s*:", re.IGNORECASE)
#: Zdania i zdania składowe; kropka i przecinek w liczbie („0,5”) nie dzielą.
_SENTENCE = re.compile(r"[!?;\n]+|[.,](?!\d)")
_TOKEN = re.compile(r"\w+")


@dataclass(frozen=True)
class Declaration:
    #: Dni wolne z deklaracji; 0 = pełny miesiąc. ``None`` = nie da się policzyć.
    #: Przy liście dni (``days``) to liczba dni z listy; dni robocze z niej
    #: liczy ``evaluate`` z kalendarza firmy.
    days_off: Optional[int]
    #: ``RRRR-MM`` ze zdania; nazwa bez roku bierze rok rozliczanego miesiąca.
    month: Optional[str]
    #: Dlaczego MD nie wpisujemy (tytuł kontroli), gdy ``days_off is None``.
    problem: Optional[str] = None
    #: Dni miesiąca z listy „w dniach … byłam niedostępna”.
    days: tuple[int, ...] = ()
    #: Zapowiedź („będę niedostępna”), nie stan po fakcie.
    planned: bool = False


def _fold(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _own_part(text: str) -> str:
    """Treść nadawcy bez cytowanego wątku."""

    lines: list[str] = []
    for line in short_lines(text).splitlines():
        stripped = line.strip()
        if _QUOTED_HEADER.match(stripped) or stripped.startswith("-----"):
            break
        if not stripped.startswith(">"):
            lines.append(stripped)
    return "\n".join(lines)


def _months(sentence: str, year: str) -> set[str]:
    return {
        f"{match.group(2) or year}-{_MONTH_NAMES[match.group(1)]:02d}"
        for match in _MONTH.finditer(sentence)
    }


def _sentence_days(sentence: str) -> Optional[tuple[Optional[int], Optional[str]]]:
    """(dni wolne, problem) dla zdania z deklaracją; ``None`` = zdanie bez niej."""

    full = list(_FULL.finditer(sentence))
    counts = list(_COUNT.finditer(sentence))
    if not full and not counts:
        if _ABSENCE.search(sentence):
            return None, "Deklaracja bez liczby dni wolnych"
        return None
    rest = _MONTH.sub(" ", _COUNT.sub(" ", _FULL.sub(" ", sentence)))
    if (
        any(token not in _FILLER for token in _TOKEN.findall(rest))
        or len(full) + len(counts) > 1
    ):
        return None, "Deklaracja niejednoznaczna"
    if full:
        return 0, None
    found = counts[0]
    if found.group(1):
        return None, "Deklaracja niejednoznaczna"
    raw = found.group(2)
    return (int(raw) if raw.isdigit() else _WORDS[raw]), None


def _list_days(raw: str, month: int) -> Optional[tuple[int, ...]]:
    """„17-21 oraz 31” → (17, 18, 19, 20, 21, 31); dzień z innego miesiąca = ``None``."""

    days: set[int] = set()
    for span in re.split(r"\s*(?:\bi\b|\boraz\b)\s*", raw.strip()):
        ends = []
        for part in re.split(r"\s*[-–]\s*", span):
            found = _DAY_PART.fullmatch(part)
            if found is None or (found.group(2) and int(found.group(2)) != month):
                return None
            ends.append(int(found.group(1)))
        first, last = ends[0], ends[-1]
        if not 1 <= first <= last <= 31 or len(ends) > 2:
            return None
        days.update(range(first, last + 1))
    return tuple(sorted(days))


def _listed(sentence: str, year: str) -> Optional[Declaration]:
    """Zdanie „w <miesiącu> w dniach <lista> byłam/będę niedostępna”; ``None`` = inne."""

    hits = [m for pattern in _LISTED for m in pattern.finditer(sentence)]
    if not hits:
        return None
    months = _months(sentence, year)
    rest = sentence
    for pattern in _LISTED:
        rest = pattern.sub(" ", rest)
    rest = _MONTH.sub(" ", rest)
    if (
        len(hits) > 1
        or len(months) != 1
        or any(token not in _FILLER for token in _TOKEN.findall(rest))
    ):
        return Declaration(None, None, "Deklaracja niejednoznaczna")
    hit = hits[0]
    groups = hit.groups()
    raw = next(g for g in groups if g and g[0].isdigit())
    planned = "bede" in groups
    month = next(iter(months))
    days = _list_days(raw, int(month[5:]))
    if days is None:
        return Declaration(None, month, "Deklaracja niejednoznaczna")
    return Declaration(len(days), month, None, days=days, planned=planned)


def parse_text(text: str, month: str) -> Optional[Declaration]:
    """Deklaracja z treści maila; ``None`` = mail bez zdania o dniach pracy."""

    year = month.split("-")[0]
    found: list[Declaration] = []
    for sentence in _SENTENCE.split(_fold(_own_part(text))):
        listed = _listed(sentence, year)
        if listed is not None:
            found.append(listed)
            continue
        days = _sentence_days(sentence)
        if days is None:
            continue
        days_off, problem = days
        months = _months(sentence, year)
        if problem is None and not months:
            problem = "Deklaracja bez nazwy miesiąca"
        if problem is None and len(months) > 1:
            problem = "Deklaracja niejednoznaczna"
        found.append(
            Declaration(
                days_off=None if problem else days_off,
                month=next(iter(months)) if len(months) == 1 else None,
                problem=problem,
            )
        )
    if not found:
        return None
    if len(set(found)) > 1:
        return Declaration(None, None, "Deklaracja niejednoznaczna")
    return found[0]


def parse(content: bytes, mime: str, month: str) -> Optional[Declaration]:
    mail = mail_text.read(content, mime)
    return parse_text(mail.body, month) if mail is not None else None


def evaluate(
    parsed: Declaration,
    *,
    month: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
) -> ProofResult:
    result = ProofResult(md_regular=None, md_extra=None)
    group = _Group(result, rules, SOURCE)
    if parsed.problem is not None or parsed.days_off is None:
        group.warn(
            parsed.problem or "Deklaracja bez liczby dni",
            "MD wpisują Finanse; mail zostaje w NEXUS-ie.",
        )
        group.close()
        return result
    if parsed.month != month:
        month_mismatch(
            group,
            f"{SOURCE} za inny miesiąc",
            f"W mailu: {mail_text.month_label(parsed.month or month)}.",
        )
        group.close()
        return result
    if parsed.days:
        return _evaluate_listed(
            parsed, month=month, rules=rules, other_md=other_md, group=group
        )
    if parsed.days_off > working_days:
        group.warn(
            f"{parsed.days_off} dni wolnych przy {working_days} dniach roboczych",
            "MD wpisują Finanse; mail zostaje w NEXUS-ie.",
        )
        group.close()
        return result
    md = Decimal(working_days - parsed.days_off)
    label = mail_text.month_label(month)
    if parsed.days_off:
        group.ok(
            f"Deklaracja w treści maila: {parsed.days_off} dni wolnych ({label})",
            f"{working_days} dni roboczych − {parsed.days_off} = {_fmt(md)} MD.",
        )
    else:
        group.ok(
            f"Deklaracja w treści maila: bez dni wolnych ({label})",
            f"{working_days} dni roboczych = {_fmt(md)} MD.",
        )
    result.md_regular = md
    result.md_extra = Decimal("0")
    group.close()

    sums = _Group(result, rules, "Pola i sumy")
    month_limit(sums, md, working_days, other_md)
    sums.close()
    return result


def _evaluate_listed(
    parsed: Declaration,
    *,
    month: str,
    rules: Mapping[str, Mapping[str, Any]],
    other_md: Decimal,
    group: _Group,
) -> ProofResult:
    """MD = dni robocze miesiąca bez dni roboczych z listy „w dniach …”."""

    result = group.result
    year, number = int(month[:4]), int(month[5:])
    last = calendar.monthrange(year, number)[1]
    workdays = business_days(date(year, number, 1), date(year, number, last))
    if parsed.days[-1] > last:
        group.warn(
            "Deklaracja z dniem spoza miesiąca",
            "MD wpisują Finanse; mail zostaje w NEXUS-ie.",
        )
        group.close()
        return result
    off = sum(1 for d in workdays if d.day in parsed.days)
    md = Decimal(len(workdays) - off)
    label = mail_text.month_label(month)
    listed = ", ".join(str(d) for d in parsed.days)
    title = (
        f"Zapowiedź w treści maila: {off} dni roboczych niedostępności ({label})"
        if parsed.planned
        else f"Deklaracja w treści maila: {off} dni roboczych niedostępności ({label})"
    )
    detail = (
        f"Dni z maila: {listed}. {len(workdays)} dni roboczych − {off} = {_fmt(md)} MD."
    )
    if parsed.planned:
        group.warn(
            title,
            detail
            + " To zapowiedź przed końcem miesiąca: sprawdź, czy się sprawdziła.",
        )
    else:
        group.ok(title, detail)
    result.md_regular = md
    result.md_extra = Decimal("0")
    group.close()

    sums = _Group(result, rules, "Pola i sumy")
    month_limit(sums, md, len(workdays), other_md)
    sums.close()
    return result
