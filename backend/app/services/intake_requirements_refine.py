"""Porządki wierszy wymagań po odczycie maila (07.11.2026).

Decyzja Artura „rób wszystko” do makiet M1, M2, M4 i M5
(https://claude.ai/artifact/U5xPzXiKJXixweYv5M8v7n). Pomiar na pięciu
prawdziwych requestach: Delivery Lead po odczycie rozdzielał wyliczanki
złączone przez „lub”, usuwał cechy wpisane jako „musi mieć”, dopisywał
technologie, które stały w mailu, i od zera wybierał krytyczne.

Bez modelu: słownik w pamięci (`skill_normalize`, `keyword_suggest`) i tekst
maila. Każda zmiana zostawia uwagę albo propozycję do kliknięcia; krytyczne
dalej zatwierdza człowiek.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Optional

# M4: znaczniki zamiennika między dwiema technologiami w mailu.
_ALTERNATIVE = re.compile(r"\b(?:lub|albo|bądź|badz|or|either)\b|/|\|")
# Najdalej tyle znaków między dwiema technologiami, żeby czytać je razem.
_PAIR_WINDOW = 60

# M5: cechy osoby, nie umiejętności z CV. Tylko całe słowa albo frazy —
# „Google Drive” i „structured data” zostają w wyszukiwaniu.
TRAIT_PHRASES = frozenset(
    {
        "drive",
        "resilient",
        "resilience",
        "structured",
        "flexible",
        "flexibility",
        "decision making",
        "decision-making",
        "conflict resolution",
        "problem solving",
        "problem-solving",
        "proactive",
        "proactivity",
        "growth mindset",
        "open-minded",
        "self-motivated",
        "detail-oriented",
        "attention to detail",
        "communication",
        "communication skills",
        "teamwork",
        "team player",
        "ownership",
        "adaptability",
        "komunikatywność",
        "samodzielność",
        "proaktywność",
        "odpowiedzialność",
        "zaangażowanie",
        "kreatywność",
        "elastyczność",
        "dokładność",
        "sumienność",
        "odporność na stres",
    }
)

# M2: najwięcej technologii z maila do kliknięcia.
MAIL_TECHNOLOGIES_MAX = 12
_SKIP_CATEGORIES = ("role_",)

# M1: lata przy technologii w jednym zdaniu maila.
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:lat|lata|rok|roku|years?|yrs)\b", re.IGNORECASE
)
CRITICAL_PROPOSAL_MAX = 3
CRITICAL_MIN_YEARS = 3
TITLE_PROPOSAL_MAX = 2
_REASON_MAX = 160


@dataclass(frozen=True)
class Refined:
    rows: list[dict[str, Any]]
    talk: list[dict[str, Any]]
    notes: list[str]


def _fold(text: str) -> str:
    from app.services.keyword_suggest import fold

    return fold(text)


@lru_cache(maxsize=8192)
def _pattern(needle: str) -> re.Pattern[str]:
    return re.compile(r"(?<![0-9a-z])" + re.escape(needle) + r"(?![0-9a-z])")


@lru_cache(maxsize=64)
def _common_word_re(word: str) -> re.Pattern[str]:
    """Słowo w oryginalnym tekście, z grupą jak we wzorcu słownika."""
    return re.compile(
        r"(?<![A-Za-z0-9_])(" + re.escape(word) + r")(?![A-Za-z0-9_])", re.IGNORECASE
    )


def _positions(word: str, folded: str) -> list[int]:
    needle = _fold(word.rstrip("*"))
    if len(needle) < 2:
        return []
    return [m.start() for m in _pattern(needle).finditer(folded)]


def _entry_forms(entry: Any) -> list[str]:
    from app.services.scoring_service import POLISH_WORD_ALIASES

    return [entry.label] + [
        alias
        for alias in entry.aliases
        if len(_fold(alias)) > 2 and _fold(alias) not in POLISH_WORD_ALIASES
    ]


def _entries_in(word: str) -> list[Any]:
    """Hasła słownika stojące w słowie wiersza: „Microsoft Dynamics 365 CE/CRM”
    niesie „Microsoft Dynamics 365”, „C#/.NET” — C# i .NET."""
    from app.services.keyword_suggest import catalog

    folded = _fold(word.rstrip("*"))
    return [
        entry
        for entry in catalog()
        if not (entry.category or "").startswith(_SKIP_CATEGORIES)
        and any(_positions(form, folded) for form in _entry_forms(entry))
    ]


def _canonical(word: str) -> Optional[str]:
    from app.services.skill_normalize import CANONICAL_CATEGORY, canonical_of

    if word.endswith("*"):
        return None
    canon = canonical_of(word)
    category = CANONICAL_CATEGORY.get(canon)
    if category is None or category.startswith("role_"):
        return None
    return canon


def _related(a: str, b: str) -> bool:
    """Ta sama rodzina: wspólne pierwsze słowo („.NET” i „.NET Core”) albo
    jedna wynika z drugiej (powiązania słownika)."""
    from app.services.skill_normalize import implied_forms

    if a.split()[0] == b.split()[0]:
        return True
    return b in implied_forms(a) or a in implied_forms(b)


def _listed_as_alternatives(a: str, b: str, folded: str) -> bool:
    for i in _positions(a, folded):
        for j in _positions(b, folded):
            lo, hi = sorted((i, j))
            if hi - lo > _PAIR_WINDOW:
                continue
            between = folded[lo:hi]
            if _ALTERNATIVE.search(between[len(_fold(a if i < j else b)) :]):
                return True
    return False


def split_listed_alternatives(
    rows: list[dict[str, Any]], folded: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """M4: wiersz z kilkoma różnymi technologiami rozpada się na wiersze,
    chyba że mail podaje je jako zamienniki („Kafka lub RabbitMQ”, „A/B”).

    789180: model złączył „MongoDB | CosmosDB | Elasticsearch” (8 262 osoby,
    sam CosmosDB 167), a w mailu stały po przecinku — DL rozdzielił ręcznie."""
    out: list[dict[str, Any]] = []
    notes: list[str] = []
    for row in rows:
        words = list(row["words"])
        keep: list[str] = []
        kept_techs: list[tuple[str, str]] = []
        apart: list[str] = []
        for word in words:
            canon = _canonical(word)
            if canon is None or not kept_techs:
                keep.append(word)
                if canon:
                    kept_techs.append((word, canon))
                continue
            together = any(
                canon == other
                or _related(canon, other)
                or _listed_as_alternatives(word, kept_word, folded)
                for kept_word, other in kept_techs
            )
            if together:
                keep.append(word)
                kept_techs.append((word, canon))
            else:
                apart.append(word)
        out.append({**row, "words": keep})
        for word in apart:
            out.append({**row, "words": [word]})
        if apart:
            notes.append(
                f"Rozdzielone na osobne wymagania: {', '.join([keep[0], *apart])} — "
                "w mailu nie stoją jako zamienniki („lub”), więc klient chce każdej."
            )
    return out, notes


def _is_trait(word: str) -> bool:
    from app.services.requirement_phrase import read_phrase

    text = " ".join(word.rstrip("*").split()).casefold()
    return text in TRAIT_PHRASES or read_phrase(word).kind == "soft"


def traits_to_talk(rows: list[dict[str, Any]]) -> Refined:
    """M5: wiersz złożony z samych cech („drive”, „resilient”) idzie do
    „Rekruter sprawdza w rozmowie”. 789170: 6 z 8 wierszy „musi mieć” to
    cechy — w CV stoją przypadkiem i obniżają ocenę dobrym kandydatom."""
    kept: list[dict[str, Any]] = []
    talk: list[dict[str, Any]] = []
    for row in rows:
        words = [w for w in row["words"] if w]
        if words and all(_is_trait(w) for w in words):
            level = "nice" if row.get("level") == "nice" else "must"
            talk.append({"name": words[0], "level": level})
        else:
            kept.append(row)
    notes = (
        [
            "Do rozmowy, nie do szukania: "
            + ", ".join(item["name"] for item in talk)
            + " — to cechy osoby; CV ich nie potwierdzi, sprawdzi je rekruter."
        ]
        if talk
        else []
    )
    return Refined(rows=kept, talk=talk, notes=notes)


def _row_covers(rows: list[dict[str, Any]]) -> set[str]:
    from app.services.keyword_suggest import entry_for, fold

    keys: set[str] = set()
    for row in rows:
        for word in row["words"]:
            entry = entry_for(word.rstrip("*"))
            keys.add(entry.key if entry else fold(word.rstrip("*")))
            keys.update(found.key for found in _entries_in(word))
    return keys


def mail_technologies(request_text: str, rows: list[dict[str, Any]]) -> list[str]:
    """M2: hasła słownika, które stoją w mailu, a nie ma ich w żadnym wierszu.
    Propozycja do kliknięcia, nic nie dopisuje się samo. 789198: model wziął
    10 wierszy, a DL dopisał ręcznie m.in. Dataverse, Jenkins, Terraform i OAuth."""
    from app.services.keyword_suggest import catalog
    from app.services.scoring_service import (
        COMMON_WORD_ALIASES,
        POLISH_WORD_ALIASES,
        is_request_mention,
    )
    from app.services.skill_normalize import (
        GATE_TECH_CATEGORIES,
        TECH_CATEGORIES,
        alias_counts_in_text,
    )

    folded = _fold(request_text)
    covered = _row_covers(rows)
    # Zwykłe słowo („access”, „less”, „solid”) liczy się tylko, gdy mail pisze
    # je gdzieś jak nazwę (MS Access, LeSS, SOLID). Tekst po `fold` nie ma
    # wielkich liter, więc sprawdzamy oryginał (09.11.2026).
    plain = {
        word
        for word in COMMON_WORD_ALIASES
        if not any(
            is_request_mention(request_text, m)
            for m in _common_word_re(word).finditer(request_text)
        )
    }
    spans: list[tuple[int, int, int, str]] = []
    for entry in catalog():
        category = entry.category or ""
        if not category or category.startswith(_SKIP_CATEGORIES):
            continue
        # „Jest” i „Go” to też polskie słowa — w mailu po polsku stoją zawsze.
        if entry.key in POLISH_WORD_ALIASES:
            continue
        forms = [entry.label] + [
            alias
            for alias in entry.aliases
            if len(_fold(alias)) > 2
            and _fold(alias) not in POLISH_WORD_ALIASES
            and alias_counts_in_text(alias, entry.label, category, None)
        ]
        forms = [form for form in forms if _fold(form) not in plain]
        # CV-owe technologie najpierw, potem narzędzia i standardy, na końcu praktyki.
        rank = (
            0
            if category in TECH_CATEGORIES
            else 1
            if category in GATE_TECH_CATEGORIES
            else 2
        )
        for form in forms:
            length = len(_fold(form.rstrip("*")))
            for pos in _positions(form, folded):
                spans.append((pos, pos + length, rank, entry.label))
    # Nazwa w środku dłuższej nazwy nie jest osobną wzmianką: „Apache”
    # (Apache HTTPD) w „Apache Kafka”, „SQL” w „Microsoft SQL Server”.
    inside = {
        (start, end, label)
        for start, end, _rank, label in spans
        for o_start, o_end, _o_rank, other in spans
        if other != label
        and o_start <= start
        and end <= o_end
        and (o_end - o_start) > (end - start)
    }
    first: dict[str, tuple[int, int]] = {}
    for start, end, rank, label in spans:
        if (start, end, label) in inside:
            continue
        if label not in first or start < first[label][1]:
            first[label] = (rank, start)
    keys_by_label = {e.label: e for e in catalog()}
    found = sorted(
        (rank, start, label)
        for label, (rank, start) in first.items()
        if keys_by_label[label].key not in covered
        and not any(k in covered for k in keys_by_label[label].alias_keys)
    )
    return [label for _rank, _pos, label in found[:MAIL_TECHNOLOGIES_MAX]]


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"[\n.;•]+(?=\s|$)|\n", text) if s.strip()]


def _row_forms(words: list[str]) -> list[str]:
    from app.services.skill_normalize import text_alias_forms

    forms: list[str] = []
    for word in words:
        if word.endswith("*"):
            continue
        forms.append(word)
        forms.extend(text_alias_forms(word))
        for entry in _entries_in(word):
            forms.extend(_entry_forms(entry))
    return forms


def _years_for(forms: list[str], sentence: str) -> Optional[int]:
    """Lata stojące najbliżej nazwy technologii w zdaniu (najpierw przed nią)."""
    folded = _fold(sentence)
    years = [(m.start(), int(m.group(1))) for m in _YEARS.finditer(folded)]
    if not years:
        return None
    best: Optional[tuple[int, int]] = None
    for form in forms:
        for pos in _positions(form, folded):
            for ypos, value in years:
                distance = pos - ypos if ypos <= pos else (ypos - pos) * 3
                if best is None or distance < best[0]:
                    best = (distance, value)
    return best[1] if best else None


def _quote(sentence: str) -> str:
    text = " ".join(sentence.split())
    return text if len(text) <= _REASON_MAX else text[: _REASON_MAX - 1].rstrip() + "…"


def critical_proposal(
    rows: list[dict[str, Any]], request_text: str, titles: list[str]
) -> list[dict[str, str]]:
    """M1: propozycja krytycznych do zatwierdzenia przez DL.

    Najpierw wiersze „musi mieć”, przy których klient podaje co najmniej
    ``CRITICAL_MIN_YEARS`` lat („minimum 5 lat z D365”), od największej
    liczby lat. Bez takich zdań — technologie z tytułu, najwyżej
    ``TITLE_PROPOSAL_MAX``. Tylko pozycje, które bramka umie sprawdzić
    (`is_gate_technology` albo `critical_eligible`). W 789180 i 789198 DL wybrał dokładnie takie."""
    from app.services.must_gate_terms import critical_eligible
    from app.services.skill_normalize import is_gate_technology

    def eligible(word: str) -> bool:
        # „Dynamics 365”: bramka czyta „365” jako wersję i `critical_eligible`
        # odpada, a hasło słownika jest technologią — bramka DL-a szuka i tak
        # słów wiersza. Fraza z maila („Microsoft Dynamics 365 CE/CRM”) liczy
        # się przez hasło, które w niej stoi.
        return (
            is_gate_technology(word)
            or critical_eligible(word)
            or any(is_gate_technology(entry.label) for entry in _entries_in(word))
        )

    must_rows = [r for r in rows if r.get("level") != "nice" and r["words"]]
    sentences = _sentences(request_text)
    by_years: list[tuple[int, int, dict[str, str]]] = []
    for index, row in enumerate(must_rows):
        head = row["words"][0]
        if not any(eligible(word) for word in row["words"] if not word.endswith("*")):
            continue
        forms = _row_forms(row["words"])
        best: Optional[tuple[int, str]] = None
        for sentence in sentences:
            value = _years_for(forms, sentence)
            if value is not None and (best is None or value > best[0]):
                best = (value, sentence)
        if best and best[0] >= CRITICAL_MIN_YEARS:
            by_years.append(
                (-best[0], index, {"label": head, "reason": _quote(best[1])})
            )
    if by_years:
        by_years.sort(key=lambda item: (item[0], item[1]))
        return [item[2] for item in by_years[:CRITICAL_PROPOSAL_MAX]]
    title_text = _fold(" ".join(t for t in titles if t))
    out: list[dict[str, str]] = []
    for row in must_rows:
        head = row["words"][0]
        if any(eligible(w) for w in row["words"] if not w.endswith("*")) and any(
            _positions(form, title_text) for form in _row_forms(row["words"])
        ):
            out.append({"label": head, "reason": "technologia z nazwy stanowiska"})
        if len(out) >= TITLE_PROPOSAL_MAX:
            break
    return out
