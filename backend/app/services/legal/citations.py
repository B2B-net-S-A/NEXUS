"""Cytaty w piśmie: wyciąganie i sprawdzenie z tekstem źródła, bez modelu.

Decyzja Artura 25.11.2026 (pkt 3 planu): każdy cytat sprawdza kod, a cytat bez
pokrycia blokuje zatwierdzenie pisma. Dwa rodzaje odwołań:

* **przepis** — „art. 61 § 1 KC”, „art. 6 ust. 1 lit. b RODO”, „art. 442¹ k.c.”,
  „art. 111–116 Kodeksu cywilnego”. Akt rozpoznaje skrót albo nazwa z
  ``acts.ActSpec.aliases``; odwołanie bez aktu dostaje ``missing`` z powodem
  ``act_unknown`` (nie wiadomo, z czym porównać).
* **postanowienie umowy** — „§ 5 ust. 2 Umowy”, „§ 7 pkt 3 umowy ramowej”. Słowo
  dokumentu po oznaczeniu jest wymagane, żeby nie pomylić „§ 1” przepisu.

Cytat dosłowny („…”) tuż po odwołaniu albo tuż przed nim w nawiasie
(„„…” (art. 61 § 1 KC)”) porównujemy z tekstem jednostki: wielkość liter,
odstępy, rodzaj myślnika i cudzysłowu nie mają znaczenia, „(…)” i „[…]”
oznaczają pominięcie. Statusy: ``ok`` / ``missing`` (źródła nie ma) /
``mismatch`` (źródło jest, cytat się z nim nie zgadza).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from app.services.legal.acts import ACTS
from app.services.legal.parse import (
    KIND_LIT,
    KIND_PAR,
    KIND_PKT,
    KIND_UST,
    display_number,
    make_key,
    make_ref,
)

KIND_LAW = "law"
KIND_CONTRACT = "contract"

PASSAGE_KINDS: tuple[str, ...] = ("law", "contract", "client", "template", "case")
#: Rodzaje fragmentów, w których szukamy „§ 5 Umowy”.
CONTRACT_PASSAGE_KINDS: frozenset[str] = frozenset({"contract", "client", "template"})

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_MISMATCH = "mismatch"


@dataclass(frozen=True)
class SourcePassage:
    """Fragment źródła, z którym porównujemy cytaty.

    ``kind``: ``law`` (przepis z korpusu), ``contract`` (podpisana umowa
    kontraktu), ``client`` (umowa ramowa klienta), ``template`` (wzór),
    ``case`` (orzeczenie, część C). ``ref`` to oznaczenie jednostki
    („art. 61 § 1”, „§ 5 ust. 2”); ``act_key`` — klucz aktu przy ``law``.
    """

    kind: str
    ref: str
    text: str
    url: Optional[str] = None
    label: Optional[str] = None
    act_key: Optional[str] = None


@dataclass(frozen=True)
class Citation:
    kind: str
    raw: str
    start: int
    end: int
    ref: str
    key: str
    act_key: Optional[str] = None
    range_to: Optional[str] = None
    quote: Optional[str] = None
    document: Optional[str] = None


@dataclass(frozen=True)
class CitationCheck:
    citation: Citation
    status: str
    reason: str
    message: str
    passage: Optional[SourcePassage] = None


# ── wyciąganie ──────────────────────────────────────────────────────────────

_SUP = r"(?:[⁰¹²³⁴⁵⁶⁷⁸⁹ᵃ]+|\^[0-9a-z]+|\[[0-9a-z]+\])"
_N = rf"\d+[a-z]{{0,3}}{_SUP}?"
_PART = rf"(?:§\s*{_N}|ust\.\s*{_N}|pkt\s*{_N}|lit\.\s*[a-z]{{1,2}}{_SUP}?)"
_LAW = re.compile(
    rf"\bart\.\s*(?P<art>{_N})(?:\s*[–—-]\s*(?P<to>{_N}))?(?P<rest>(?:\s*{_PART})*)",
    re.IGNORECASE,
)
_CONTRACT = re.compile(
    rf"§\s*(?P<par>{_N})(?P<rest>(?:\s*(?:ust\.\s*{_N}|pkt\s*{_N}|lit\.\s*[a-z]{{1,2}}))*)"
    r"\s+(?P<doc>(?:niniejszej\s+)?(?:umow[ayieę]|aneks[uiem]*|regulamin[uie]*|wzor[ue]|"
    r"zamówieni[ae]|porozumieni[ae]))"
    r"(?P<doc_rest>(?:\s+(?:ramow(?:ej|a)|o\s+współpracy|B2B|o\s+świadczenie\s+usług))?)",
    re.IGNORECASE,
)
_PART_ITEM = re.compile(
    rf"(§|ust\.|pkt|lit\.)\s*({_N}|[a-z]{{1,2}}{_SUP}?)", re.IGNORECASE
)
_PART_KIND = {"§": KIND_PAR, "ust.": KIND_UST, "pkt": KIND_PKT, "lit.": KIND_LIT}

_DIACRITIC = {
    "a": "[aą]",
    "c": "[cć]",
    "e": "[eę]",
    "l": "[lł]",
    "n": "[nń]",
    "o": "[oó]",
    "s": "[sś]",
    "z": "[zźż]",
}
_FOLD = str.maketrans("ąćęłńóśźż", "acelnoszz")


def _alias_pattern(alias: str) -> str:
    out: list[str] = []
    for ch in alias.lower().translate(_FOLD):
        if ch == ".":
            out.append(r"\.?")
        elif ch == " ":
            out.append(r"\s*")
        elif ch in _DIACRITIC:
            out.append(_DIACRITIC[ch])
        else:
            out.append(re.escape(ch))
    return "".join(out)


_ALIASES: list[tuple[str, str]] = sorted(
    ((alias, spec.key) for spec in ACTS for alias in spec.aliases),
    key=lambda item: -len(item[0]),
)
_ACT_RE = re.compile(
    r"\s*(?:"
    + "|".join(f"(?P<a{i}>{_alias_pattern(a)})" for i, (a, _k) in enumerate(_ALIASES))
    + r")(?![\w])",
    re.IGNORECASE,
)

_QUOTE_AFTER = re.compile(
    r"^\s*(?:[,:–—-]|\)|stanowi[ąc]*:?|brzmi:?|w\s+brzmieniu:?|mówi:?|\s)*?\s*"
    r"[„\"“](?P<q>[^”\"“„]{3,3000})[”\"“]"
)
_QUOTE_BEFORE = re.compile(r"[„\"“](?P<q>[^”\"“„]{3,3000})[”\"“]\s*[(\[]\s*$")


def _parts(rest: str) -> list[tuple[str, str]]:
    parts: list[tuple[str, str]] = []
    for label, number in _PART_ITEM.findall(rest or ""):
        parts.append((_PART_KIND[label.lower()], number))
    return parts


def _act_after(text: str, position: int) -> tuple[Optional[str], int]:
    match = _ACT_RE.match(text, position)
    if not match:
        return None, position
    for name, value in match.groupdict().items():
        if value is not None:
            return _ALIASES[int(name[1:])][1], match.end()
    return None, position


def _quote_near(text: str, start: int, end: int) -> Optional[str]:
    after = _QUOTE_AFTER.match(text[end : end + 3100])
    if after:
        return after.group("q").strip()
    before = _QUOTE_BEFORE.search(text[max(0, start - 3100) : start])
    if before:
        return before.group("q").strip()
    return None


def extract(text: str) -> list[Citation]:
    """Odwołania do przepisów i postanowień umowy w kolejności w tekście."""
    if not text:
        return []
    found: list[Citation] = []
    taken: list[tuple[int, int]] = []
    for match in _LAW.finditer(text):
        article = match.group("art")
        parts = _parts(match.group("rest"))
        act_key, end = _act_after(text, match.end())
        found.append(
            Citation(
                kind=KIND_LAW,
                raw=text[match.start() : end].strip(),
                start=match.start(),
                end=end,
                ref=make_ref(article, parts),
                key=make_key(article, parts),
                act_key=act_key,
                range_to=display_number(match.group("to"))
                if match.group("to")
                else None,
                quote=_quote_near(text, match.start(), end),
            )
        )
        taken.append((match.start(), end))
    for match in _CONTRACT.finditer(text):
        if any(s <= match.start() < e for s, e in taken):
            continue
        number = match.group("par")
        parts = _parts(match.group("rest"))
        ref = " ".join(
            [f"§ {display_number(number)}"]
            + [f"{_label(kind)} {display_number(n)}" for kind, n in parts]
        )
        found.append(
            Citation(
                kind=KIND_CONTRACT,
                raw=match.group(0).strip(),
                start=match.start(),
                end=match.end(),
                ref=ref,
                key=contract_key(number, parts),
                document=(match.group("doc") + (match.group("doc_rest") or "")).strip(),
                quote=_quote_near(text, match.start(), match.end()),
            )
        )
    found.sort(key=lambda c: c.start)
    return found


def _label(kind: str) -> str:
    return {KIND_UST: "ust.", KIND_PKT: "pkt", KIND_LIT: "lit.", KIND_PAR: "§"}[kind]


def contract_key(paragraph: str, parts: Sequence[tuple[str, str]] = ()) -> str:
    return "§" + make_key(paragraph, parts)


_REF_ARTICLE = re.compile(
    rf"^\s*art\.\s*(?P<art>{_N})(?P<rest>(?:\s*{_PART})*)\s*$", re.I
)
_REF_PARAGRAPH = re.compile(
    rf"§\s*(?P<par>{_N})(?P<rest>(?:\s*(?:ust\.\s*{_N}|pkt\s*{_N}|lit\.\s*[a-z]{{1,2}}))*)\s*$",
    re.I,
)


def passage_key(passage: SourcePassage) -> Optional[str]:
    """Klucz oznaczenia fragmentu („art. 61 § 1” → ``61 §1``, „§ 5 ust. 2” → ``§5 ust.2``)."""
    if passage.kind == KIND_LAW:
        match = _REF_ARTICLE.match(passage.ref or "")
        if match:
            return make_key(match.group("art"), _parts(match.group("rest")))
        return None
    # Oznaczenie może nieść nazwę dokumentu przed „§” („umowa 12/2025 § 8 ust. 2”).
    match = _REF_PARAGRAPH.search(passage.ref or "")
    if match:
        return contract_key(match.group("par"), _parts(match.group("rest")))
    return None


# ── porównanie cytatu ───────────────────────────────────────────────────────

_ELLIPSIS = re.compile(r"\(\s*(?:…|\.\.\.)\s*\)|\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.")


def normalize_for_quote(text: str) -> str:
    text = (text or "").replace("­", "")
    text = re.sub(r"[–—‑‒−]", "-", text)
    text = re.sub(r"[„”“\"«»]", '"', text)
    text = re.sub(r"[’‘`]", "'", text)
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip().lower()


#: Kawałek cytatu przy „(…)”: co najmniej tyle wyrazów albo znaków. Krótsze
#: („Klient (…) kara umowna (…) przekracza”) pozwalały przeskoczyć „nie”.
PIECE_MIN_WORDS = 3
PIECE_MIN_CHARS = 15


def quote_matches(quote: str, source: str) -> bool:
    """Wszystkie kawałki cytatu (rozdzielone „(…)”) stoją w źródle po kolei,
    w granicach słów; przy pominięciu każdy kawałek ma ``PIECE_MIN_WORDS``
    wyrazów albo ``PIECE_MIN_CHARS`` znaków."""
    haystack = normalize_for_quote(source)
    position = 0
    pieces = [normalize_for_quote(p).strip(" ,.;:") for p in _ELLIPSIS.split(quote)]
    pieces = [p for p in pieces if p]
    if not pieces:
        return False
    if len(pieces) > 1 and any(
        len(p.split()) < PIECE_MIN_WORDS and len(p) < PIECE_MIN_CHARS for p in pieces
    ):
        return False
    for piece in pieces:
        found = re.compile(rf"(?<!\w){re.escape(piece)}(?!\w)").search(
            haystack, position
        )
        if found is None:
            return False
        position = found.end()
    return True


# ── sprawdzenie ─────────────────────────────────────────────────────────────


def _candidates(
    citation: Citation, passages: Sequence[SourcePassage]
) -> list[tuple[str, SourcePassage]]:
    if citation.kind == KIND_LAW:
        pool = [
            p for p in passages if p.kind == KIND_LAW and p.act_key == citation.act_key
        ]
    else:
        kinds = document_kinds(citation.document)
        pool = [p for p in passages if p.kind in kinds]
    out = []
    for passage in pool:
        key = passage_key(passage)
        if key is not None:
            out.append((key, passage))
    return out


#: Słowo dokumentu po „§ 5” → rodzaje fragmentów, które go pokrywają.
#: „umowy ramowej” to umowa klienta, „Umowy” — umowa B2B kontraktu, „wzoru” —
#: wzór; aneks, regulamin, zamówienie i porozumienie bez zawężenia.
DOCUMENT_WORD: dict[str, str] = {
    "contract": "umowy",
    "client": "umowy ramowej",
    "template": "wzoru",
}


def document_kinds(document: Optional[str]) -> frozenset[str]:
    word = (document or "").lower()
    if "ramow" in word:
        return frozenset({"client"})
    if re.search(r"(^|\s)umow", word):
        return frozenset({"contract"})
    if re.search(r"(^|\s)wzor", word):
        return frozenset({"template"})
    return CONTRACT_PASSAGE_KINDS


def _part_marker(token: str) -> Optional[re.Pattern[str]]:
    """Ślad podjednostki w tekście jednostki nadrzędnej („§ 7”, „8.”, „2)”, „b)”)."""
    match = re.match(r"^(§|ust\.|pkt|lit\.)(.+)$", token)
    if not match:
        return None
    label, number = match.group(1), re.escape(display_number(match.group(2)))
    if label == "§":
        return re.compile(rf"§\s*{number}(?![\w¹²³⁴⁵⁶⁷⁸⁹⁰])", re.I)
    if label == "ust.":
        return re.compile(rf"(?:^|[\s(:;])(?:ust\.\s*)?{number}\.(?=\s)", re.I)
    return re.compile(rf"(?:^|[\s(:;])(?:{label[:3]}\.?\s*)?{number}\)", re.I)


def _find(
    key: str, candidates: Sequence[tuple[str, SourcePassage]]
) -> Optional[SourcePassage]:
    """Jednostka o tym kluczu, a gdy jej nie ma — najbliższa nadrzędna, ale tylko
    gdy źródło nie dzieli jej na podjednostki, a w jej tekście stoi ślad każdej
    brakującej podjednostki (art. 111 z § 1–6 nie pokrywa „art. 111 § 7”)."""
    exact = next((p for k, p in candidates if k == key), None)
    if exact is not None:
        return exact
    parents = [(k, p) for k, p in candidates if key.startswith(k + " ")]
    if not parents:
        return None
    parent_key, parent = max(parents, key=lambda kp: len(kp[0]))
    if any(k.startswith(parent_key + " ") for k, _p in candidates):
        return None  # podział jest w źródle, a cytowanej podjednostki w nim nie ma
    for token in key[len(parent_key) :].split():
        marker = _part_marker(token)
        if marker is None or not marker.search(parent.text or ""):
            return None
    return parent


def _check(citation: Citation, passages: Sequence[SourcePassage]) -> CitationCheck:
    if citation.kind == KIND_LAW and citation.act_key is None:
        return CitationCheck(
            citation,
            STATUS_MISSING,
            "act_unknown",
            f"Nie wiadomo, z którego aktu jest {citation.ref} — dopisz akt (np. „KC”).",
        )
    candidates = _candidates(citation, passages)
    passage = _find(citation.key, candidates)
    if passage is None:
        where = (
            "w korpusie przepisów" if citation.kind == KIND_LAW else "w podanej umowie"
        )
        return CitationCheck(
            citation,
            STATUS_MISSING,
            "not_found",
            f"Nie ma {citation.ref} {where}.",
        )
    if citation.range_to:
        article_key = citation.key.split(" ")[0]
        end_key = make_key(citation.range_to)
        if _find(end_key, candidates) is None and end_key != article_key:
            return CitationCheck(
                citation,
                STATUS_MISSING,
                "range_end_missing",
                f"Nie ma art. {citation.range_to} — koniec zakresu {citation.raw}.",
                passage,
            )
    if citation.quote and not quote_matches(citation.quote, passage.text):
        return CitationCheck(
            citation,
            STATUS_MISMATCH,
            "quote_mismatch",
            f"Cytat nie zgadza się z tekstem {passage.ref}"
            + (f" ({passage.label})" if passage.label else "")
            + ".",
            passage,
        )
    return CitationCheck(citation, STATUS_OK, "ok", "Zgadza się ze źródłem.", passage)


def verify(text: str, passages: Sequence[SourcePassage]) -> list[CitationCheck]:
    """Sprawdza każdy cytat z ``text`` z podanymi fragmentami źródeł."""
    return [_check(citation, passages) for citation in extract(text)]


def blocking(checks: Sequence[CitationCheck]) -> bool:
    """Czy wynik blokuje zatwierdzenie pisma (choć jeden cytat bez pokrycia)."""
    return any(check.status != STATUS_OK for check in checks)
