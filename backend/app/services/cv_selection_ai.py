"""AI na zaznaczonym fragmencie CV — Edytor CV 2, PR 3 (decyzja Artura 12.10.2026).

Rekruter zaznacza fragment CV dla klienta i wybiera: skróć, rozwiń z oryginału,
przeredaguj, popraw język albo przetłumacz na angielski. Model proponuje, KOD
sprawdza, a rekruter przyjmuje — nic nie trafia do CV samo:

* skrócenie, redakcja, korekta i tłumaczenie nie mogą dodać faktu (liczby,
  daty, nazwy, technologii) spoza zaznaczonego tekstu,
* rozwinięcie wolno oprzeć tylko na zdaniu z oryginalnego CV albo z notatek
  rekrutera — te same reguły cytatu co poprawki QC (`cv_qc.parse_fixes`) —
  a tekst propozycji musi wynikać z fragmentu i cytatu. Bez drugiego warunku
  model mógłby zacytować cztery słowa i dopisać cokolwiek.

Propozycja, która nie przeszła kontroli, nie wraca do edytora: wraca powód
i zapis, o który poszło. Trasa niczego nie zapisuje w szkicu CV; przyjętą
propozycję nakłada edytor jedną cofalną zmianą i utrwala autozapis.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage
from app.services import cv_qc
from app.services import dz_review as dz
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import (
    _MONEY,
    _RATE_WORD,
    SOURCE_QUOTE_MAX,
    SOURCE_QUOTE_MIN_WORDS,
    _json_object,
    _norm,
    _quote_from_other_role,
    is_tech_list,
)
from app.services.cv_rodo_clause import is_rodo_text
from app.services.dz_review import Requirement
from app.services.llm_prompts import CV_SELECTION_EDIT
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence, json_for_prompt
from app.services.recommendation_card_parser import CV_HIDDEN_FIELDS
from app.services.recommendation_card_assist import _fold, unsupported_facts

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.cv_selection_edit
ACTIVITY_ACTION = "cv_selection_ai"

ACTIONS = ("shorten", "expand", "rephrase", "proofread", "translate")

# Granice wejścia (schemat trasy trzyma te same liczby).
FRAGMENT_MAX = 1200
BLOCK_MAX = 2000
INSTRUCTION_MAX = 300
PREVIOUS_MAX = 3
PROPOSED_MAX = 1600
MAX_QUOTES = 6
MAX_SOURCES = 3
MAX_CAUTIONS = 5

# Ile wolno urosnąć tekstowi, który nie miał dostać nowej treści:
# (mnożnik długości fragmentu, stały zapas znaków).
_GROWTH = {"rephrase": (1.5, 40), "proofread": (1.3, 20), "translate": (2.0, 80)}

# Miesiąc: rdzenie, po których poznajemy go w ŹRÓDLE (łagodnie, po złożeniu
# znaków), dokładne formy, po których poznajemy go w PROPOZYCJI, i nazwa
# angielska. Tłumaczenie „stycznia 2020” na „January 2020” nie jest nowym
# faktem; „March” bez marca w źródle — jest. Same rdzenie łapały w propozycji
# „mają”, „czerwone” i „major” (przegląd 13.10.2026), stąd dokładne formy.
_MONTHS: tuple[tuple[tuple[str, ...], re.Pattern[str], str], ...] = tuple(
    (
        stems,
        re.compile(rf"\b(?:(?i:{polish})|{english})\b"),
        english,
    )
    for stems, polish, english in (
        (("stycz",), r"stycze[nń]|styczni(?:a|u|em)", "January"),
        (("lut",), r"lut(?:y|ego|ym|emu)", "February"),
        (("marz", "marc"), r"marzec|marc(?:a|u|em)", "March"),
        (("kwie",), r"kwiecie[nń]|kwietni(?:a|u|em)", "April"),
        (("maj",), r"maj(?:a|u|em)?", "May"),
        (("czerw",), r"czerw(?:iec|ca|cu|cem)", "June"),
        (("lip",), r"lip(?:iec|ca|cu|cem)", "July"),
        (("sierp",), r"sierpie[nń]|sierpni(?:a|u|em)", "August"),
        (("wrze",), r"wrzesie[nń]|wrze[sś]ni(?:a|u|em)", "September"),
        (("pazdz",), r"pa[zź]dziernik(?:a|u|iem)?", "October"),
        (("listop",), r"listopad(?:a|em|zie)?", "November"),
        (("grud",), r"grudzie[nń]|grudni(?:a|u|em)", "December"),
    )
)

# „500 000”, „500,000”, „500.000” — ta sama liczba w trzech zapisach.
_THOUSANDS = re.compile(r"(?<!\d)\d{1,3}(?:[ .,]\d{3})+(?!\d)")
_YEAR = re.compile(r"(?<!\d)(?:19|20)\d{2}(?!\d)")
# Zdanie o pieniądzach kandydata także bez słowa „stawka” („150 netto na B2B”).
_PAY_WORD = re.compile(r"\b(?:netto|brutto)\b", re.IGNORECASE)

# Odnośnik, adres e-mail albo domena. Pisane małą literą przechodzą kontrolę
# nazw własnych, a to typowa treść wstrzyknięta w tekst CV kandydata.
_ADDRESS = re.compile(
    r"(?:https?://|www\.)[^\s<>()]+|[\w.+-]+@[\w-]+(?:\.[\w-]+)+"
    r"|\b[\w-]+\.(?:pl|com|io|net|org|eu|dev|example)\b",
    re.IGNORECASE,
)

_MESSAGES = {
    "empty": "AI nie zwróciło propozycji. Spróbuj jeszcze raz.",
    "unchanged": "AI nie zmieniło tekstu — nie ma tu nic do poprawienia.",
    "not_shorter": "Propozycja nie była krótsza od zaznaczonego tekstu. Spróbuj jeszcze raz.",
    "too_long": "Propozycja była za długa jak na tę poprawkę. Spróbuj jeszcze raz.",
    "no_quote": (
        "AI nie wskazało zdania z oryginalnego CV ani z notatek, na którym można "
        "oprzeć rozwinięcie. Jeśli kandydat to robił, zapytaj go i zapisz w notatce."
    ),
    "quote_other_role": (
        "Zdanie, na które powołało się AI, dotyczy innego stanowiska w oryginalnym CV."
    ),
}
MSG_ROLE_UNKNOWN = (
    "Nie udało się ustalić, którego stanowiska w oryginalnym CV dotyczy ten "
    "fragment — sprawdź, czy cytat jest z tej samej roli."
)


@dataclass(frozen=True)
class Grounds:
    """Na czym wolno oprzeć propozycję i czego pilnować."""

    # Wymagania rekrutacji (must i nice) — termin z tej listy to fakt także
    # wtedy, gdy model zapisze go małą literą.
    requirements: tuple[Requirement, ...] = ()
    # Źródła rozwinięcia: tekst oryginalnego CV i notatki czytelne dla AI.
    original: str = ""
    notes: str = ""
    # Rola oryginału, w której leży fragment (kształt jak pozycja materiału
    # `cv_qc.fixes_material`); ``None`` = nie ustalono, bez kontroli „inna rola”.
    role: Optional[dict] = None
    # Fragment stoi w stanowisku CV. Gdy roli oryginału nie ustalono, cytat
    # z oryginalnego CV może pochodzić z innej roli — propozycja wraca bez
    # plakietki „Zgodne ze źródłem”.
    role_bound: bool = False


def plain(text: str) -> str:
    return (text or "").replace("**", "")


def clean_markup(text: Any) -> str:
    """Tekst modelu w zapisie edytora: bez punktora, z domkniętym ``**``.

    Znaki sterujące, niewidoczne (zero-width, miękki łącznik) i połówki par
    zastępczych wypadają: ukrywały wymaganie przed kontrolą (znak zerowej szerokości w środku słowa),
    NUL odrzucał autozapis szkicu, a samotna połówka pary kończyła odpowiedź
    błędem 500.
    """
    body = unicodedata.normalize("NFC", str(text or ""))
    body = "".join(
        ch for ch in body if ch.isspace() or unicodedata.category(ch)[0] != "C"
    )
    body = " ".join(body.split())
    body = re.sub(r"^[-•*]\s+", "", body)[:PROPOSED_MAX]
    if body.count("**") % 2:
        # Niedomknięte pogrubienie: zdejmij ostatni znacznik zamiast pogrubiać resztę.
        at = body.rfind("**")
        body = body[:at] + body[at + 2 :]
    body = body.replace("****", "")
    return body.strip()


def _for_check(text: str) -> str:
    """Tekst do kontroli: bez ``**`` i ze znakami zgodności w zwykłej postaci."""
    return unicodedata.normalize("NFKC", plain(text))


def _rejected(
    reason: str, problem: Optional[str] = None, *, expand: bool = False
) -> dict:
    if reason == "new_fact":
        where = (
            "w zaznaczonym tekście ani w cytowanym źródle"
            if expand
            else "w zaznaczonym tekście"
        )
        message = f"Propozycja dodawała „{problem}”, czego nie ma {where}. Spróbuj jeszcze raz."
    elif reason == "amount":
        message = (
            f"Propozycja dodawała kwotę „{problem}”. Kwot AI nie dopisuje do CV — "
            "jeśli ma w nim być, wpisz ją ręcznie."
        )
    else:
        message = _MESSAGES[reason]
    return {
        "status": "rejected",
        "proposed_text": None,
        "verified": False,
        "sources": [],
        "cautions": [],
        "reason": reason,
        "problem": problem,
        "message": message,
    }


def _new_address(text: str, *sources: str) -> Optional[str]:
    """Odnośnik albo adres obecny w propozycji, a nieobecny w źródłach."""
    known = " ".join(sources).casefold()
    for match in _ADDRESS.finditer(text):
        address = match.group(0).rstrip(".,;:")
        if address and address.casefold() not in known:
            return address
    return None


def _new_requirements(
    text: str, grounds: Grounds, *sources: str
) -> Iterator[Requirement]:
    """Wymagania rekrutacji obecne w propozycji, a nieobecne w źródłach."""
    known = " ".join(sources)
    for requirement in grounds.requirements:
        if dz._found(text, requirement) and not dz._found(known, requirement):
            yield requirement


def _odd_character(text: str, *sources: str) -> Optional[str]:
    """Słowo propozycji ze znakiem spoza źródeł, który nie jest zwykłym pismem.

    Litera innego alfabetu wygląda jak łacińska („kubеrnetes” z cyrylicą),
    a znak łączący bywa niewidoczny — jedno i drugie chowa słowo przed kontrolą.
    """
    known = set("".join(sources))
    for word in text.split():
        for ch in word:
            if ch < "\u0250" or ch in known:
                continue
            kind = unicodedata.category(ch)[0]
            if kind == "M" or (
                kind == "L" and not unicodedata.name(ch, "").startswith("LATIN")
            ):
                return word.strip(".,;:")
    return None


def _without(text: str, words: list[str]) -> str:
    """Tekst bez podanych słów (całych)."""
    for word in words:
        text = re.sub(rf"(?<!\w){re.escape(word)}(?!\w)", " ", text)
    return text


def _join_thousands(text: str) -> str:
    return _THOUSANDS.sub(lambda m: re.sub(r"\D", "", m.group(0)), text)


def _facts(text: str, *sources: str) -> Iterator[tuple[str, str]]:
    """Fakty propozycji spoza źródeł (bez miesięcy — te liczy `_new_month`)."""
    joined = [_join_thousands(source) for source in sources]
    for kind, fact in unsupported_facts(_join_thousands(text), *sources, *joined):
        if kind != "month":
            yield kind, fact


def _new_month(text: str, *sources: str) -> Optional[str]:
    """Miesiąc nazwany w propozycji, którego nie ma w źródłach."""
    folded = _fold(" ".join(sources))
    for stems, pattern, english in _MONTHS:
        match = pattern.search(text)
        if match and not any(
            re.search(rf"\b{stem}", folded) for stem in (*stems, english.lower())
        ):
            return match.group(0)
    return None


def _new_amount(text: str, fragment: str) -> Optional[str]:
    """Kwota w propozycji, której nie było w zaznaczonym tekście."""
    known = _norm(fragment)
    for match in _MONEY.finditer(text):
        amount = match.group(0).strip(" .,")
        if _norm(amount) not in known:
            return amount
    return None


def _about_pay(sentence: str) -> bool:
    return bool(
        (_RATE_WORD.search(sentence) and _MONEY.search(sentence))
        or (_PAY_WORD.search(sentence) and re.search(r"\d", sentence))
    )


# Jak daleko od cytatu szukamy granicy zdania. Bez granicy plik bez kropek był
# jednym „zdaniem”, a wzorzec kwoty cofał się po nim kwadratowo.
_SENTENCE_REACH = 300


def _sentence_around(haystack: str, at: int, length: int) -> str:
    """Zdanie źródła, z którego wycięto cytat stojący na pozycji ``at``."""
    low = max(0, at - _SENTENCE_REACH)
    high = min(len(haystack), at + length + _SENTENCE_REACH)
    dot = haystack.rfind(". ", low, at)
    # Od ostatniego znaku cytatu: jego własna kropka kończy zdanie.
    end = haystack.find(". ", at + length - 1, high)
    return haystack[dot + 1 if dot >= 0 else low : end if end >= 0 else high]


def _names_other_company(quote: str, role: dict) -> bool:
    """Cytat sięga w nagłówek innego pracodawcy — zaczyna się w tej roli, kończy w cudzej."""
    names = (_norm(company) for company in role.get("other_companies") or [])
    return any(len(name) >= 3 and name in quote for name in names)


def verify_quotes(quotes: Any, grounds: Grounds) -> tuple[list[dict], bool]:
    """Cytaty, na których wolno oprzeć rozwinięcie, i czy któryś był z innej roli.

    Reguły jak w `cv_qc.parse_fixes`: zdanie (co najmniej
    ``SOURCE_QUOTE_MIN_WORDS`` słów, nie lista technologii), dosłownie
    w oryginale albo w notatkach, nie z innego stanowiska i bez stawki.
    Ostrzej niż QC w dwóch miejscach: cytat z kwotą nie jest źródłem wcale,
    a o tym, czy zdanie mówi o pieniądzach, decyduje całe zdanie źródła, nie
    wycięty z niego kawałek („200 zł/h netto” ze zdania „Stawka 200 zł/h netto”).
    """
    original = _norm(grounds.original)
    notes = _norm(grounds.notes)
    verified: list[dict] = []
    other_role = False
    seen: set[str] = set()
    for raw in (quotes if isinstance(quotes, list) else [])[:MAX_QUOTES]:
        quote = " ".join(str(raw or "").split())
        key = _norm(quote)
        if not key or key in seen or len(quote) > 2 * SOURCE_QUOTE_MAX:
            continue
        seen.add(key)
        if len(quote.split()) < SOURCE_QUOTE_MIN_WORDS or is_tech_list(quote):
            continue
        if _MONEY.search(quote):
            continue
        at = original.find(key)
        if at >= 0:
            kind, where = "original", original
        else:
            at = notes.find(key)
            if at < 0:
                continue
            kind, where = "notes", notes
        if _about_pay(_sentence_around(where, at, len(key))):
            continue
        if (
            kind == "original"
            and grounds.role is not None
            and (
                _quote_from_other_role(key, grounds.role, original)
                or _names_other_company(key, grounds.role)
            )
        ):
            other_role = True
            continue
        verified.append({"kind": kind, "quote": quote[:SOURCE_QUOTE_MAX]})
        if len(verified) >= MAX_SOURCES:
            break
    return verified, other_role


def _translation_source(fragment: str) -> str:
    """Fragment z angielskimi nazwami miesięcy, które w nim występują."""
    folded = _fold(fragment)
    months = [
        english
        for stems, _pattern, english in _MONTHS
        if any(re.search(rf"\b{stem}", folded) for stem in stems)
    ]
    return " ".join([fragment, *months])


def check(action: str, fragment: str, raw: str, grounds: Grounds) -> dict:
    """Odpowiedź modelu → propozycja albo odmowa z powodem.

    ``raw`` to JSON ``{"text": str, "quotes": [str]}``. ``ValueError`` znaczy
    „model nie odpowiedział w umówionym kształcie” — wołający zgłasza to jako
    chwilową niedostępność, nie jako odmowę.
    """
    if action not in ACTIONS:
        raise ValueError(f"unknown action: {action}")
    data = _json_object(raw)
    answer = data.get("text")
    if answer is not None and not isinstance(answer, str):
        # Lista albo obiekt zamiast tekstu wróciłyby do CV jako zapis Pythona.
        raise ValueError("model text is not a string")
    proposed = clean_markup(answer)
    text = _for_check(proposed)
    source = _for_check(fragment)
    if not text.strip():
        return _rejected("empty")
    # Dokładnie, nie przez `_norm`: sama zmiana wielkości liter („github” →
    # „GitHub”) to poprawka, o którą proszono.
    if " ".join(proposed.split()) == " ".join((fragment or "").split()):
        # Rozwinięcie bez zmian = źródła nie mówią nic więcej o tym fragmencie.
        return _rejected("no_quote" if action == "expand" else "unchanged")
    if action == "shorten" and len(text) >= len(source):
        return _rejected("not_shorter")
    if action in _GROWTH:
        factor, slack = _GROWTH[action]
        if len(text) > factor * len(source) + slack:
            return _rejected("too_long")

    sources: list[dict] = []
    cautions: list[str] = []
    known = [source]
    if action == "expand":
        sources, other_role = verify_quotes(data.get("quotes"), grounds)
        if not sources:
            return _rejected("quote_other_role" if other_role else "no_quote")
        amount = _new_amount(text, source)
        if amount:
            return _rejected("amount", amount)
        known += [_for_check(item["quote"]) for item in sources]
    elif action == "translate":
        known = [_translation_source(source)]

    def caution(name: str) -> None:
        seen = {item.casefold() for item in cautions}
        if name.casefold() not in seen and len(cautions) < MAX_CAUTIONS:
            cautions.append(name)

    expand = action == "expand"
    problem = (
        _odd_character(text, *known)
        or _new_address(text, *known)
        or _new_month(text, *known)
    )
    if problem:
        return _rejected("new_fact", problem, expand=expand)
    names: list[str] = []
    for kind, fact in _facts(text, *known):
        if action == "translate" and kind == "capital":
            # Angielski pisze wielką literą więcej niż polski („Project Manager”)
            # — to uwaga dla rekrutera, nie dowód nowego faktu.
            names.append(fact)
            continue
        return _rejected("new_fact", fact, expand=expand)
    for requirement in _new_requirements(text, grounds, *known):
        # W tłumaczeniu wymaganie zapisane zwykłym słowem („mikroserwisów” →
        # „microservices”) to przekład, nie nowy fakt. Zapisane jak nazwa,
        # której nie było („…and Kafka”), jest dopisaną technologią.
        if action != "translate" or not dz._found(_without(text, names), requirement):
            return _rejected("new_fact", requirement.label, expand=expand)
        caution(requirement.label)
    for name in names:
        caution(name)
    # Fragment stoi w stanowisku, którego nie umiemy wskazać w oryginale: cytat
    # z oryginalnego CV może być z innej roli, więc nie dostaje plakietki.
    unattributed = (
        grounds.role_bound
        and grounds.role is None
        and any(item["kind"] == "original" for item in sources)
    )
    return {
        "status": "ok",
        "proposed_text": proposed,
        "verified": bool(sources) and not unattributed,
        "sources": sources,
        "cautions": cautions,
        "reason": None,
        "problem": None,
        "message": MSG_ROLE_UNKNOWN if unattributed else None,
    }


# ── Wywołanie modelu ─────────────────────────────────────────────────────────

MSG_UNAVAILABLE = "Podpowiedź AI jest chwilowo niedostępna. Popraw fragment ręcznie albo spróbuj za chwilę."
MSG_NO_SOURCE = (
    "Nie ma oryginalnego CV ani notatek, z których można rozwinąć ten fragment."
)
MSG_CLAUSE = "Klauzula zgody jest stała — nie tłumaczymy jej ani nie zmieniamy."

_TASKS = {
    "shorten": "Skróć fragment, zachowując sens i najważniejsze fakty. Wynik musi być krótszy.",
    "rephrase": "Przeredaguj fragment: ten sam sens i te same fakty, lepszy styl CV.",
    "proofread": (
        "Popraw wyłącznie język: literówki, interpunkcję, odmianę i pisownię nazw "
        "technologii. Nie zmieniaj treści ani stylu."
    ),
    "translate": (
        "Przetłumacz fragment na angielski (styl CV, bez pierwszej osoby). Nazwy "
        "własne i technologie zostaw bez zmian."
    ),
    "expand": (
        "Rozwiń fragment o konkret, który stoi w oryginalnym CV albo w notatkach "
        "rekrutera i dotyczy TEGO stanowiska. Każdy dodany fakt musi pochodzić ze "
        "zdania, które zacytujesz. Jeśli źródła nie mówią nic więcej o tym "
        "fragmencie, zwróć fragment bez zmian i pustą listę cytatów."
    ),
}
_QUOTES_EXPAND = (
    "dosłowne zdania (co najmniej 4 słowa, nie lista technologii) z <original_cv> "
    "albo <candidate_notes>, z których pochodzą dodane fakty"
)
_QUOTES_NONE = "pusta lista"


def _unavailable(
    action: str, message: str = MSG_UNAVAILABLE, status: str = "unavailable"
) -> dict:
    return {
        "status": status,
        "action": action,
        "proposed_text": None,
        "verified": False,
        "sources": [],
        "cautions": [],
        "reason": None,
        "problem": None,
        "message": message,
    }


def _entry_years(entry: dict) -> set[str]:
    """Lata początku i końca roli z odczytu CV (klucze jak `cv_qc.experience_years`)."""
    keys = ("start", "start_date", "from", "end", "end_date", "to")
    return set(_YEAR.findall(" ".join(str(entry.get(key) or "") for key in keys)))


def resolve_role(candidate: Any, original: str, role: Optional[dict]) -> Optional[dict]:
    """Rola oryginału, do której należy zaznaczony fragment — po firmie albo stanowisku.

    Zwraca pozycję w kształcie `cv_qc.fixes_material` (do odrzucenia cytatu
    z innej roli) albo ``None``, gdy roli nie da się wskazać JEDNOZNACZNIE:
    dwa stanowiska u jednego pracodawcy rozróżnia nazwa, a dwa o tej samej
    nazwie (CV „blind” bez nazw firm) — lata z nagłówka. Pierwsza pasująca
    z listy bywała cudzą rolą: jej cytaty dostawały plakietkę, a własne
    odpadały jako „inne stanowisko”. Nazwy przychodzą od klienta, więc służą
    wyłącznie do WYBORU roli z odczytu oryginału.
    """
    if not role:
        return None
    employer = str(role.get("employer") or "").split(" · ")[0].strip()
    title = str(role.get("title") or "").strip()
    entries = dz.role_entries(candidate, original)
    roles = dz.original_roles(entries)
    found = [r for r in roles if dz._same_company(r.company, employer)]
    titled = [r for r in found or roles if dz._same_title(r.title, title)]
    if titled or not found:
        found = titled
    if len(found) > 1:
        years = set(_YEAR.findall(title))
        dated = [
            r
            for r, entry in zip(roles, entries)
            if any(r is f for f in found)
            and (own_years := _entry_years(entry))
            and own_years <= years
        ]
        found = dated
    if len(found) != 1:
        return None
    own = found[0]
    return {
        "original_role": own.text[: cv_qc.PROMPT_ROLE_MAX],
        "company": own.company,
        "other_roles": [r.text[: cv_qc.PROMPT_ROLE_MAX] for r in roles if r is not own],
        "other_companies": sorted(
            {r.company for r in roles if r.company and r.company != own.company}
        ),
    }


def build_prompt(payload: dict, grounds: Grounds) -> str:
    """Prompt z danymi w znacznikach, których nie da się zamknąć od środka."""
    action = payload["action"]
    context: list[str] = []
    role = payload.get("role") or {}
    if role.get("title") or role.get("employer"):
        described = {
            "stanowisko": str(role.get("title") or "")[:200],
            "firma": str(role.get("employer") or "")[:200],
            "pozostale_punkty": [str(p)[:400] for p in (role.get("points") or [])[:12]],
        }
        context.append(
            "Stanowisko w CV, którego dotyczy fragment:\n"
            + fence("cv_role", json_for_prompt(described))
        )
    if action == "expand":
        if grounds.role and grounds.role.get("original_role"):
            context.append(
                "To stanowisko w oryginalnym CV:\n"
                + fence("original_role", grounds.role["original_role"])
            )
        context.append(
            "Oryginalne CV kandydata:\n"
            + fence(
                "original_cv", grounds.original[: cv_qc.PROMPT_ORIGINAL_MAX] or "(brak)"
            )
        )
        context.append(
            "Notatki rekruterów:\n"
            + fence(
                "candidate_notes", grounds.notes[: cv_qc.NOTES_TEXT_MAX] or "(brak)"
            )
        )
    instruction = str(payload.get("instruction") or "").strip()[:INSTRUCTION_MAX]
    if instruction:
        context.append(
            "Wskazówka rekrutera do stylu (nie jest źródłem faktów):\n"
            + fence("recruiter_hint", instruction)
        )
    previous = [
        str(p)[:PROPOSED_MAX] for p in (payload.get("previous") or [])[:PREVIOUS_MAX]
    ]
    if previous:
        context.append(
            "Wcześniejsze propozycje — daj INNĄ wersję:\n"
            + fence("previous_proposals", json_for_prompt(previous))
        )
    return CV_SELECTION_EDIT.render(
        task=_TASKS[action],
        fragment=fence("cv_fragment", str(payload["fragment"])[:FRAGMENT_MAX]),
        paragraph=fence(
            "cv_paragraph", str(payload.get("block_text") or "")[:BLOCK_MAX]
        ),
        context="".join(part + "\n\n" for part in context),
        quotes_rule=_QUOTES_EXPAND if action == "expand" else _QUOTES_NONE,
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja — testy ją podmieniają."""
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=chain[0],
        fallback_models=chain[1:] or None,
        # Propozycja do 1600 znaków + trzy cytaty po 300: 700 tokenów ucinało JSON.
        max_tokens=1500,
        thinking={"type": "disabled"},
        # Krócej niż domyślne 90 s × 3: rekruter czeka z otwartą kartą.
        timeout=20,
        max_retries=1,
        total_timeout=30,
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


async def _log(
    db: AsyncSession, stage: CandidateStage, user_id: int, payload: dict, result: dict
) -> None:
    """Ślad użycia (bez treści CV). Błąd zapisu nie może zabrać propozycji."""
    try:
        async with db.begin_nested():
            csv_id = await db.scalar(
                select(CandidateStageCV.id).where(
                    CandidateStageCV.candidate_stage_id == stage.id
                )
            )
            if csv_id is None:
                return
            previous = payload.get("previous") or []
            db.add(
                Activity(
                    entity_type="candidate_stage_cv",
                    entity_id=csv_id,
                    action=ACTIVITY_ACTION,
                    user_id=user_id,
                    details={
                        "action": payload.get("action"),
                        "status": result["status"],
                        "reason": result.get("reason"),
                        "refined": bool(str(payload.get("instruction") or "").strip()),
                        "attempt": len(previous) + 1,
                    },
                )
            )
    except Exception:  # noqa: BLE001 — pomiar, nie warunek działania
        logger.warning(
            "[cv_selection_ai] nie zapisano wpisu użycia stage=%s",
            stage.id,
            exc_info=True,
        )


async def propose(
    db: AsyncSession, stage: CandidateStage, *, user_id: int, payload: dict
) -> dict:
    """Propozycja dla zaznaczonego fragmentu. Wołający sprawdził dostęp i schemat.

    Nigdy nie rzuca: brak klucza, błąd modelu, zła odpowiedź albo awaria
    odczytu źródeł to ``status: "unavailable"`` — edytor działa dalej bez AI.
    """
    action = str(payload.get("action") or "")
    fragment = str(payload.get("fragment") or "")
    block_text = str(payload.get("block_text") or "")
    if not settings.CV_SELECTION_AI_ENABLED:
        return _unavailable(action)
    if is_rodo_text(block_text) or is_rodo_text(fragment):
        return _unavailable(action, MSG_CLAUSE, "not_supported")
    chain = tuple(model_chain_for(FEATURE))
    if not api_key_configured(chain[0]):
        return _unavailable(action)
    try:
        job = await db.get(Job, stage.job_id)
        must, nice = dz.job_requirements(job) if job is not None else ([], [])
        role_bound = payload.get("section") == "experience" or bool(payload.get("role"))
        grounds = Grounds(requirements=(*must, *nice), role_bound=role_bound)
        if action == "expand":
            src = await cv_qc._load_sources(db, stage)
            original = src.original.get("text") or ""
            # Jak generator CV: stawka, red flags i motywacja z karty rekomendacji
            # to ustalenia handlowe — nie idą do modelu i nie mogą być cytatem,
            # na którym oprze się treść CV dla klienta.
            notes = await cv_qc._notes_text(db, src.candidate.id, CV_HIDDEN_FIELDS)
            if not original.strip() and not notes.strip():
                result = _unavailable(action, MSG_NO_SOURCE, "no_source")
                await _log(db, stage, user_id, payload, result)
                return result
            grounds = Grounds(
                requirements=grounds.requirements,
                original=original,
                notes=notes,
                role=resolve_role(src.candidate, original, payload.get("role")),
                role_bound=role_bound,
            )
        prompt = build_prompt(payload, grounds)
        system = CV_SELECTION_EDIT.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem,
            # żeby żądanie nie trzymało połączenia i blokady przez cały round-trip.
            await db.commit()
            raw = await run_in_threadpool(_call_model, system, prompt, chain)
        checked = await run_in_threadpool(check, action, fragment, raw, grounds)
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning(
            "[cv_selection_ai] stage=%s failed (%s)", stage.id, type(exc).__name__
        )
        try:
            await db.rollback()
        except Exception:  # noqa: BLE001
            logger.warning("[cv_selection_ai] rollback failed")
        return _unavailable(action)
    result = {"action": action, **checked}
    await _log(db, stage, user_id, payload, result)
    return result
