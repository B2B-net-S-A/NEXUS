"""Sprawdzenie propozycji wyróżnika strony 1 „Nowego CV” (Artur 26.11.2026).

Model proponuje wyróżnik pod nazwiskiem (`cv_page1_highlight`): nagrodę albo
wyróżnienie z CV (`award`) albo certyfikat z wymagań MUST Profilu Championa
(`certificate`), każdy z dosłownym cytatem. Tu kod decyduje, którą propozycję
rekruter w ogóle zobaczy jako gotową do przyjęcia (`verified`), bez sieci i bazy:

- cytat stoi w całości w jednym wpisie CV — punkcie albo nazwie stanowiska,
  certyfikacie, wierszu wykształcenia (po słowach, jak przy wynikach strony 1);
- nagroda: cytat nazywa nagrodę, wyróżnienie, tytuł albo miejsce w konkursie
  (zwykły obowiązek udający nagrodę odpada);
- certyfikat: cytat to wpis z certyfikatów, a certyfikat jest wymaganiem MUST
  (ta sama reguła co kolejność w Edukacji — `education.must_certificate`);
- każda liczba z etykiety, znaku i zdania stoi w cytacie albo w tym wpisie
  (przy stanowisku: w całej roli);
- etykieta ≤ 60, znak ≤ 8, jedno zdanie ≤ 160 znaków, bez form z rodzajem,
  w Blind CV bez nazw firm.

Bez cytatu nie ma propozycji. Propozycja nigdy nie trafia na stronę 1 sama:
render czyta wyłącznie `page1_extras.highlight`, a tryb „ai” zapisuje dopiero
przyjęcie przez rekrutera (`PATCH …/cv/page1`). Przyjęty wyróżnik render
sprawdza jeszcze raz na bieżącej treści (`rechecked_highlight`).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from app.services.cv_new_layout.education import must_certificate
from app.services.cv_new_layout.highlight import LABEL_MAX, TEXT_MAX, TOKEN_MAX
from app.services.cv_page1_result_checks import (
    _company_core,
    _numbers,
    _phrase,
    _words,
    clean_text,
    is_one_sentence,
    roles_from_cv_json,
    strip_bold,
)

KINDS = ("award", "certificate")
MAX_PROPOSALS = 3
# Ile propozycji modelu w ogóle czytamy — więcej to szum, nie wybór.
MAX_CANDIDATES = 6
# Certyfikat bywa krótki („PMP – PMI”), więc mniej niż przy wynikach strony 1.
QUOTE_MIN_WORDS = 2

ISSUE_KIND = "kind_unknown"
ISSUE_EMPTY = "empty"
ISSUE_LABEL_TOO_LONG = "label_too_long"
ISSUE_TOKEN_TOO_LONG = "token_too_long"
ISSUE_TOO_LONG = "too_long"
ISSUE_NOT_ONE_SENTENCE = "not_one_sentence"
ISSUE_GENDERED = "gendered"
ISSUE_QUOTE_MISSING = "quote_missing"
ISSUE_QUOTE_NOT_IN_CV = "quote_not_in_cv"
ISSUE_NOT_AN_AWARD = "not_an_award"
ISSUE_NOT_A_CERTIFICATE = "not_a_certificate"
ISSUE_NOT_MUST = "not_must"
ISSUE_NUMBER_NOT_IN_CV = "number_not_in_cv"
ISSUE_COMPANY_NAMED = "company_named"

# Słowa nagrody w cytacie. Tylko słowa, które same znaczą nagrodę: „najlepszych”,
# „z tytułu”, „top”, „won” i „wyróżniających się” bywają zwykłym obowiązkiem
# („Won 3 new clients”, „Rozliczenia z tytułu umów”), więc liczą się dopiero
# w nagrodzie („won the first prize”, „tytuł „Pracownik Roku””) — przegląd 26.11.2026.
_AWARD = re.compile(
    r"\b(?:nagrod\w*|nagrodzon\w*|wyróżnieni\w*|wyróżnion\w*|wyroznieni\w*|"
    r"laureat\w*|zwycięzc\w*|zwycięstw\w*|zwyciężył\w*|medal\w*|odznaczen\w*|"
    r"odznaczon\w*|stypendi\w*|finalist\w*|award\w*|winner\w*|prize\w*|"
    r"honou?rs|scholarship\w*|employee of the (?:year|month|quarter))\b|"
    r"\btytuł\w*\s+[„\"“]|"
    r"\b(?:[1-3]|i{1,3})\.?\s*(?:miejsce|miejsca|place)\b|"
    r"\b(?:first|second|third|1st|2nd|3rd) place\b",
    re.IGNORECASE,
)
# Formy z rodzajem — płeć kandydata nie jest znana (jak przy zdaniach 1–3).
_GENDERED = re.compile(
    r"\b(?:nagrodzony|nagrodzona|wyróżniony|wyróżniona|zdobył|zdobyła|"
    r"otrzymał|otrzymała|uzyskał|uzyskała|zwyciężył|zwyciężyła|wygrał|wygrała|"
    r"był|była|pracował|pracowała|he|she|his|her|him)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Entry:
    """Jeden wpis CV, w którym może stać cały cytat."""

    source: str  # "role" | "certification" | "education"
    text: str
    # Tekst, w którym wolno szukać liczb z propozycji (przy roli: cała rola).
    context: str
    company: str = ""


def entries_from_cv_json(cv_json: dict[str, Any]) -> list[Entry]:
    """Wpisy CV z treści edytora (`cv_new_content.cv_json_from_editor_html`)."""
    entries: list[Entry] = []
    for role in roles_from_cv_json(cv_json):
        for unit in role.units:
            entries.append(Entry("role", unit, role.text, role.company))
    for cert in cv_json.get("certifications") or []:
        text = " ".join(str(cert or "").split())
        if text:
            entries.append(Entry("certification", text, text))
    for school in cv_json.get("education") or []:
        if isinstance(school, dict):
            parts = (school.get(k) for k in ("degree", "institution", "dates"))
            text = " ".join(" ".join(str(p or "") for p in parts).split())
        else:
            text = " ".join(str(school or "").split())
        if text:
            entries.append(Entry("education", text, text))
    return entries


def companies_from_cv_json(cv_json: dict[str, Any]) -> list[str]:
    return [r.company for r in roles_from_cv_json(cv_json) if r.company]


def locate(quote: str, entries: Sequence[Entry]) -> Optional[Entry]:
    """Wpis, w którym stoi cały cytat (po słowach)."""
    words = _words(quote)
    if len(words) < QUOTE_MIN_WORDS:
        return None
    needle = f" {' '.join(words)} "
    for entry in entries:
        if needle in f" {_phrase(entry.text)} ":
            return entry
    return None


def _line(value: Any) -> str:
    return " ".join(str(value or "").split())


def find_issue(
    item: dict[str, str],
    entries: Sequence[Entry],
    *,
    must: Optional[Sequence[str]],
    companies: Sequence[str],
    blind: bool,
) -> tuple[Optional[str], Optional[Entry]]:
    """Pierwszy powód, dla którego propozycji nie wolno przyjąć (i wpis z cytatem).

    ``must=None`` pomija warunek MUST — przy ponownym sprawdzeniu przyjętego
    wyróżnika, bo zmiana Profilu Championa nie cofa decyzji rekrutera.
    """
    kind, label, token, text = (item[k] for k in ("kind", "label", "token", "text"))
    if kind not in KINDS:
        return ISSUE_KIND, None
    if not (label and text):
        return ISSUE_EMPTY, None
    if len(label) > LABEL_MAX:
        return ISSUE_LABEL_TOO_LONG, None
    if len(token) > TOKEN_MAX:
        return ISSUE_TOKEN_TOO_LONG, None
    if len(strip_bold(text)) > TEXT_MAX:
        return ISSUE_TOO_LONG, None
    if not is_one_sentence(text):
        return ISSUE_NOT_ONE_SENTENCE, None
    words = " ".join((label, token, strip_bold(text)))
    if _GENDERED.search(words):
        return ISSUE_GENDERED, None
    quote = item["quote"]
    if len(_words(quote)) < QUOTE_MIN_WORDS:
        return ISSUE_QUOTE_MISSING, None
    entry = locate(quote, entries)
    if entry is None:
        return ISSUE_QUOTE_NOT_IN_CV, None
    if kind == "award" and not _AWARD.search(strip_bold(quote)):
        return ISSUE_NOT_AN_AWARD, entry
    if kind == "certificate":
        if entry.source != "certification":
            return ISSUE_NOT_A_CERTIFICATE, entry
        if must is not None and must_certificate(entry.text, must) is None:
            return ISSUE_NOT_MUST, entry
    if not _numbers(words) <= _numbers(quote) | _numbers(entry.context):
        return ISSUE_NUMBER_NOT_IN_CV, entry
    if blind:
        folded = words.casefold()
        for company in companies:
            core = _company_core(company)
            if len(core) >= 3 and core.casefold() in folded:
                return ISSUE_COMPANY_NAMED, entry
    return None, entry


def clean_item(raw: Any) -> Optional[dict[str, str]]:
    """Pola propozycji jako jedna linia każde; nie-słownik = ``None``."""
    if not isinstance(raw, dict):
        return None
    return {
        "kind": _line(raw.get("kind")).casefold(),
        "label": strip_bold(_line(raw.get("label"))),
        "token": strip_bold(_line(raw.get("token"))),
        "text": clean_text(raw.get("text")),
        "quote": _line(raw.get("quote")),
    }


def proposal_key(item: dict[str, Any]) -> str:
    """Odcisk propozycji (rodzaj + cytat po słowach) — do listy odrzuconych."""
    raw = f"{item.get('kind') or ''}|{_phrase(str(item.get('quote') or ''))}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def verify_proposals(
    items: Sequence[Any],
    entries: Sequence[Entry],
    must: Sequence[str],
    *,
    companies: Sequence[str],
    blind: bool,
) -> list[dict[str, Any]]:
    """Propozycje po sprawdzeniu: sprawdzone pierwsze, w kolejności modelu, bez
    powtórek, najwyżej ``MAX_PROPOSALS``. Niesprawdzone zostają z ``issue``
    (edytor ich nie podaje do przyjęcia)."""
    verified: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in list(items)[:MAX_CANDIDATES]:
        item = clean_item(raw)
        if item is None:
            continue
        key = proposal_key(item)
        if key in seen:
            continue
        seen.add(key)
        issue, entry = find_issue(
            item, entries, must=must, companies=companies, blind=blind
        )
        out: dict[str, Any] = {**item, "key": key, "verified": issue is None}
        if entry is not None:
            out["source"] = entry.source
            if entry.company and not blind:
                out["company"] = entry.company
        if issue:
            out["issue"] = issue
            rejected.append(out)
        else:
            verified.append(out)
    return (verified + rejected)[:MAX_PROPOSALS]


def highlight_sha(html: Optional[str], must: Sequence[str], version: int) -> str:
    """Odcisk wejścia propozycji: HTML edytora, MUST i wersja promptu."""
    raw = json.dumps(
        {"html": html or "", "must": list(must), "v": version}, ensure_ascii=False
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def rejected_keys(extras: Optional[dict]) -> list[str]:
    keys = (extras or {}).get("highlight_rejected")
    return [str(k) for k in keys if k] if isinstance(keys, list) else []


def merged_highlight(
    extras: Optional[dict], proposals: list[dict[str, Any]], sha: str
) -> dict[str, Any]:
    """Nowe dodatki z propozycjami; odrzucone wcześniej przez rekrutera nie wracają,
    a wybór rekrutera (`highlight`) i reszta kluczy zostają."""
    out = dict(extras) if isinstance(extras, dict) else {}
    rejected = set(rejected_keys(out))
    out["highlight_proposals"] = [p for p in proposals if p.get("key") not in rejected]
    out["highlight_source_sha"] = sha
    return out


def proposals(extras: Optional[dict]) -> list[dict[str, Any]]:
    items = (extras or {}).get("highlight_proposals")
    return [p for p in items if isinstance(p, dict)] if isinstance(items, list) else []


def accepted_highlight(proposal: dict[str, Any]) -> dict[str, Any]:
    """Wpis `page1_extras.highlight` po przyjęciu propozycji przez rekrutera."""
    return {
        "mode": "ai",
        "kind": proposal.get("kind") or "",
        "label": _line(proposal.get("label"))[:LABEL_MAX],
        "token": _line(proposal.get("token"))[:TOKEN_MAX],
        "text": _line(proposal.get("text"))[:TEXT_MAX],
        "quote": _line(proposal.get("quote")),
        "key": proposal.get("key") or proposal_key(proposal),
    }


def stands_in_cv(
    highlight: dict[str, Any], cv_json: dict[str, Any], *, blind: bool
) -> bool:
    """Przyjęty wyróżnik „ai” na bieżącej treści CV: cytat, liczby, Blind (bez MUST)."""
    item = clean_item(highlight)
    if item is None:
        return False
    issue, _ = find_issue(
        item,
        entries_from_cv_json(cv_json),
        must=None,
        companies=companies_from_cv_json(cv_json),
        blind=blind,
    )
    return issue is None


def rechecked_highlight(
    extras: Optional[dict], cv_json: dict[str, Any], *, blind: bool
) -> Optional[dict]:
    """Dodatki do renderu: wyróżnik „ai”, którego cytatu nie ma już w bieżącej
    treści CV (rekruter usunął nagrodę, zmienił rok, CV jest teraz Blind),
    ustępuje automatowi — bez zapisu i bez sieci."""
    if not isinstance(extras, dict):
        return extras
    highlight = extras.get("highlight")
    if not (isinstance(highlight, dict) and highlight.get("mode") == "ai"):
        return extras
    if stands_in_cv(highlight, cv_json, blind=blind):
        return extras
    return {k: v for k, v in extras.items() if k != "highlight"}


__all__ = [
    "Entry",
    "KINDS",
    "MAX_PROPOSALS",
    "accepted_highlight",
    "companies_from_cv_json",
    "entries_from_cv_json",
    "find_issue",
    "highlight_sha",
    "locate",
    "merged_highlight",
    "proposal_key",
    "proposals",
    "rechecked_highlight",
    "rejected_keys",
    "stands_in_cv",
    "verify_proposals",
]
