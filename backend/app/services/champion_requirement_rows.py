"""Wiersze wymagań rekrutacji — jedna lista słów kluczowych (02.10.2026).

Do 02.10 Delivery Lead wpisywał to samo trzy razy: must-have (zdania klienta),
umiejętności krytyczne (wybór z must) i „wymagania do wyszukiwania w bazie”
(słowa kluczowe). Pomiar na 20 rekrutacjach: 53 ze 185 must to zdania, 59% słów
z wymagań wyszukiwania powtarzało must, krytycznych nie wybrał nikt.

Teraz źródłem jest `stack.rows`: wiersz = wymaganie, słowa = warianty
(wystarczy jedno), poziom = krytyczne / musi mieć / mile widziane. Z wierszy
serwer WYPROWADZA pola, które czyta reszta systemu — nic poza zapisem się nie
zmienia:

* `stack.must` / `stack.nice` — etykieta wiersza (`row_label`),
* `stack.critical` — etykiety wierszy krytycznych (w zapisanych wierszach
  poziom to już tylko must / nice — krytyczne ma jedno źródło),
* `search.requirements` — wiersze krytyczne i „musi mieć” ze wszystkimi słowami.

Profil, w którym te pola przestały odpowiadać wierszom (import dokumentu,
szkic AI, zapis starym edytorem), wraca do starych pól: `ChampionProfile`
kasuje `stack.rows` przy walidacji (`rows_consistent`), zamiast pokazywać
listę, która nie jest już prawdą.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Optional

from app.schemas.champion import (
    CRITICAL_MAX,
    REQUIREMENT_NICE_MAX_ROWS,
    REQUIREMENT_ROW_LEVELS,
    SEARCH_REQUIREMENT_MAX_ROWS,
    _search_words,
)

# Krótka pozycja bez technologii („bankowość”, „KYC/AML”) zostaje słowem
# kluczowym; dłuższa to zdanie klienta i idzie do opisu.
KEYWORD_MAX_WORDS = 3
KEYWORD_MAX_CHARS = 40
ALTERNATIVE_JOINER = " lub "


def _plain(word: str) -> str:
    return word.rstrip("*").strip()


def _head(words: list[str]) -> str:
    """Słowo, po którym wiersz jest rozpoznawany: pierwsze bez gwiazdki,
    a gdy są same rdzenie — pierwszy rdzeń bez gwiazdki."""
    for word in words:
        if not word.endswith("*"):
            return word
    return _plain(words[0]) if words else ""


_ALTERNATIVE_SPLIT = re.compile(r"\s+(?:lub|or)\s+", re.IGNORECASE)


def _row_words(value: Any) -> list[str]:
    """Słowa wiersza po rozbiciu „A lub B” na warianty (P3) i bez gwiazdki
    przy technologii ze słownika (P5) — przed regułami ``_search_words``.

    Słowo „Kafka lub RabbitMQ” w jednym polu kasowało ``stack.rows`` przy
    walidacji (etykieta przestawała pasować do słów), a „Java*” łapało
    JavaScript.
    """
    from app.services.skill_normalize import is_gate_technology

    raw_words = [value] if isinstance(value, str) else value
    if not isinstance(raw_words, list):
        return []
    out: list[str] = []
    for raw in raw_words:
        if not isinstance(raw, str):
            continue
        for part in _ALTERNATIVE_SPLIT.split(raw):
            word = part.strip()
            if word.endswith("*") and is_gate_technology(_plain(word)):
                word = _plain(word)
            out.append(word)
    return _search_words(out)


def split_rows(value: Any) -> tuple[list[dict[str, Any]], list[str]]:
    """Wiersze w kształcie zapisu + etykiety wierszy, które się nie zmieściły.

    Dwa wiersze o tym samym pierwszym słowie to to samo wymaganie — zostaje
    pierwszy. Limity jak w edytorze: 10 wierszy obowiązkowych, 20 mile
    widzianych, najwyżej 3 krytyczne (kolejne schodzą do „musi mieć”).

    Nadmiar wierszy obowiązkowych schodzi do „mile widziane”, dopóki jest
    tam miejsce; dopiero reszta wraca jako lista etykiet (audyt 06.10.2026,
    N3 — 11. i dalszy wiersz „musi mieć” znikał po cichu, a 662 z 1 208
    profili ma ponad 10 pozycji must).
    """
    if not isinstance(value, list):
        return [], []
    parsed: list[dict[str, Any]] = []
    heads: set[str] = set()
    for raw in value:
        data = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(data, Mapping):
            continue
        words = _row_words(data.get("words"))
        head = _head(words).casefold()
        if not head or head in heads:
            continue
        level = data.get("level")
        if level not in REQUIREMENT_ROW_LEVELS:
            level = "must"
        heads.add(head)
        parsed.append({"words": words, "level": level})

    rows: list[dict[str, Any]] = []
    overflow: list[dict[str, Any]] = []
    required = nice = critical = 0
    for row in parsed:
        level = row["level"]
        if level == "critical" and critical >= CRITICAL_MAX:
            level = "must"
        if level == "nice":
            if nice >= REQUIREMENT_NICE_MAX_ROWS:
                overflow.append(row)
                continue
            nice += 1
        else:
            if required >= SEARCH_REQUIREMENT_MAX_ROWS:
                overflow.append(row)
                continue
            required += 1
            critical += level == "critical"
        rows.append({"words": row["words"], "level": level})
    dropped: list[str] = []
    for row in overflow:
        if row["level"] != "nice" and nice < REQUIREMENT_NICE_MAX_ROWS:
            nice += 1
            rows.append({"words": row["words"], "level": "nice"})
        else:
            dropped.append(row_label(row["words"]))
    return rows, dropped


def clean_rows(value: Any) -> list[dict[str, Any]]:
    """Wiersze w kształcie zapisu (``split_rows`` bez listy nadmiaru)."""
    return split_rows(value)[0]


def overflow_note(dropped: list[str]) -> str:
    """Zdanie do opisu wymagań o wierszach, które nie zmieściły się w limitach."""
    return "Nie zmieściło się w wymaganiach: " + ", ".join(dropped) + "."


def row_label(words: list[str]) -> str:
    """Etykieta wiersza w `stack.must` / `stack.nice`.

    Pierwsze słowo bez gwiazdki. Zamienniki dopisujemy przez „lub” tylko wtedy,
    gdy są RÓŻNYMI technologiami ze słownika („Kafka lub RabbitMQ”) — tak czyta
    je bramka krytycznych (`must_gate_terms.gate_requirement`). Inna pisownia
    tej samej technologii, rdzeń z gwiazdką i angielski odpowiednik zostają
    wyłącznie w wierszu wyszukiwania.
    """
    from app.services.skill_normalize import canonical_of, is_gate_technology

    head = _head(words)
    if not head or not is_gate_technology(head):
        return head
    names = [head]
    seen = {canonical_of(head)}
    for word in words:
        if word.endswith("*") or not is_gate_technology(word):
            continue
        canonical = canonical_of(word)
        if canonical not in seen:
            seen.add(canonical)
            names.append(word)
    return ALTERNATIVE_JOINER.join(names)


def _full_label(label: str, words: list[str]) -> str:
    """Etykieta do czytania: wszystkie zamienniki wiersza, także spoza słownika.

    Bez innej pisowni tej samej nazwy i bez rdzenia, który jest początkiem
    pokazanego już słowa („bankow*” przy „bankowości”).
    """
    from app.services.skill_normalize import canonical_of

    names = label.split(ALTERNATIVE_JOINER)
    seen = {canonical_of(name) for name in names}
    for word in words:
        canonical = canonical_of(word)
        if not word.endswith("*") and canonical not in seen:
            seen.add(canonical)
            names.append(word)
    for word in words:
        stem = canonical_of(_plain(word))
        if word.endswith("*") and not any(name.startswith(stem) for name in seen):
            seen.add(stem)
            names.append(word)
    return ALTERNATIVE_JOINER.join(names)


def label_row_words(stack: Any) -> dict[str, list[str]]:
    """Etykieta z `stack.must` / `stack.nice` → słowa jej wiersza (po `_head`)."""
    if not isinstance(stack, Mapping):
        return {}
    rows = stack.get("rows")
    by_head = {
        _head(row["words"]).casefold(): row["words"]
        for row in (rows if isinstance(rows, list) else ())
        if isinstance(row, Mapping)
        and isinstance(row.get("words"), list)
        and row["words"]
    }
    out: dict[str, list[str]] = {}
    for key in ("must", "nice"):
        items = stack.get(key)
        for item in items if isinstance(items, list) else ():
            name = item.get("name") if isinstance(item, Mapping) else None
            if not isinstance(name, str):
                continue
            words = by_head.get(name.split(ALTERNATIVE_JOINER)[0].strip().casefold())
            if words:
                out[name] = words
    return out


def full_labels(stack: Any) -> dict[str, str]:
    """Etykieta → pełne brzmienie na ekranach do czytania (zgłoszenie 30.10.2026).

    Tylko wiersze, w których pełne brzmienie jest dłuższe. Sama etykieta zostaje
    bez zmian: czytają ją bramka krytycznych i kontrakt wymagań (`row_label`).
    """
    out: dict[str, str] = {}
    for label, words in label_row_words(stack).items():
        full = _full_label(label, words)
        if full != label:
            out[label] = full
    return out


def derive(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Pola profilu wyprowadzone z wierszy (wiersze już po `clean_rows`)."""
    must: list[dict[str, str]] = []
    nice: list[dict[str, str]] = []
    critical: list[str] = []
    requirements: list[list[str]] = []
    for row in rows:
        label = row_label(row["words"])
        if row["level"] == "nice":
            nice.append({"name": label})
            continue
        must.append({"name": label})
        requirements.append(list(row["words"]))
        if row["level"] == "critical":
            critical.append(label)
    return {
        "must": must,
        "nice": nice,
        "critical": critical,
        "requirements": requirements,
    }


def _kept_critical(given: Any, rows: list[dict[str, Any]]) -> Optional[list[str]]:
    """Krytyczne podane etykietami, gdy żaden wiersz nie niesie poziomu."""
    if not isinstance(given, list):
        return None
    if not given:
        return []
    required = [row for row in rows if row["level"] != "nice"]
    kept: list[str] = []
    for name in given:
        if not isinstance(name, str):
            continue
        head = name.split(ALTERNATIVE_JOINER)[0].strip().casefold()
        row = next((r for r in required if _head(r["words"]).casefold() == head), None)
        label = row_label(row["words"]) if row is not None else None
        if label and label not in kept:
            kept.append(label)
    return kept[:CRITICAL_MAX] or None


def expand_patch(patch: Any, *, previous_notes: Optional[str] = None) -> Any:
    """Ładunek zapisu profilu z `stack.rows` → te same wiersze plus pola z nich
    wyprowadzone. Ładunek bez `stack.rows` wraca nietknięty.

    Krytyczne: wiersze z poziomem „krytyczne” wygrywają. Bez nich liczy się
    lista `critical` z ładunku: `[]` to świadome „Brak krytycznych”, etykiety
    zostają te, które nadal mają swój wiersz (tak wygląda zapisany profil
    odesłany bez zmian — w zapisie poziom wiersza to już tylko must / nice),
    a `None` albo brak klucza znaczy „DL nie zdecydował”.
    """
    if not isinstance(patch, Mapping):
        return patch
    stack = patch.get("stack")
    if not isinstance(stack, Mapping) or not isinstance(stack.get("rows"), list):
        return patch
    rows, dropped = split_rows(stack["rows"])
    derived = derive(rows)
    critical: Optional[list[str]] = derived["critical"] or _kept_critical(
        stack.get("critical"), rows
    )
    search = patch.get("search")
    # W zapisie wiersz jest „musi mieć” albo „mile widziane”; które są
    # krytyczne, mówi wyłącznie `stack.critical` — jedno źródło dla bramki,
    # kopii rekrutacji (gubi krytyczne) i edytora.
    stored = [
        {**row, "level": "nice" if row["level"] == "nice" else "must"} for row in rows
    ]
    extra: dict[str, Any] = {}
    if dropped:
        # Wiersz, który nie zmieścił się nawet w „mile widziane”, zostaje
        # zdaniem w opisie wymagań — czyta go rekruter i generator CV.
        notes = stack.get("notes") if "notes" in stack else previous_notes
        base = str(notes or "").strip()
        extra["notes"] = "\n".join(
            part for part in (base, overflow_note(dropped)) if part
        )
    return {
        **patch,
        "stack": {
            **stack,
            **extra,
            "rows": stored,
            "must": derived["must"],
            "nice": derived["nice"],
            "critical": critical,
        },
        "search": {
            **(search if isinstance(search, Mapping) else {}),
            "requirements": derived["requirements"],
        },
    }


# Wierszy czytanych przy zapisie: 10 obowiązkowych + 20 mile widzianych
# z zapasem; dalsze `split_rows` i tak odkłada do opisu.
_TALK_ROWS_MAX = 60


def _row_key(words: Any) -> frozenset[str]:
    return frozenset(
        w.strip().casefold() for w in words or () if isinstance(w, str) and w.strip()
    )


def _merge_talk(items: list[dict], name: str, level: str) -> bool:
    """Dopisuje pozycję do listy sekcji 4 (bez powtórek, w limicie)."""
    from app.schemas.champion import EXPERIENCE_ITEMS_MAX

    key = name.casefold()
    if any(str(i.get("name", "")).casefold() == key for i in items):
        return True
    if len(items) >= EXPERIENCE_ITEMS_MAX:
        return False
    items.append({"name": name, "level": level, "min_years": None, "note": ""})
    return True


def separate_talk_items(
    patch: Any,
    *,
    previous_rows: Any = None,
    previous_experience: Any = None,
    previous_language: Optional[str] = None,
    keep_required: bool = False,
) -> tuple[Any, list[str]]:
    """Zdanie nie zostaje słowem do szukania (wariant A, 13.10.2026).

    Słowa NOWYCH albo ZMIENIONYCH wierszy (względem ``previous_rows``) czyta
    ``requirement_phrase.read_phrase``:

    * zdanie, umiejętność miękka, branża opisana zdaniem → „Rekruter sprawdza
      w rozmowie” (``experience.skills`` / ``experience.domains``),
    * język z poziomem → pole „Język” (``basics.language`` — jedno źródło),
    * technologia z komentarzem („SQL (bardzo dobra znajomość)”) → słowo
      „SQL”, a poziom do rozmowy.

    Wiersz bez słów znika; jego krytyczne idzie za wierszem albo znika.
    ``keep_required`` (rekrutacja już przekazana): gdy przeniesienie zostawiłoby
    zero wierszy obowiązkowych, wiersze zostają — inaczej zapis kończyłby się
    422 ``handoff_regression``; odpowiedź mówi to uwagą. Zwraca (ładunek,
    uwagi po polsku). Ładunek bez ``stack.rows`` wraca nietknięty.
    """
    from app.services.requirement_phrase import read_phrase

    if not isinstance(patch, Mapping):
        return patch, []
    stack = patch.get("stack")
    if not isinstance(stack, Mapping) or not isinstance(stack.get("rows"), list):
        return patch, []
    known = {
        _row_key(r.get("words"))
        for r in (previous_rows if isinstance(previous_rows, list) else [])
        if isinstance(r, Mapping)
    }
    patch_exp = patch.get("experience")
    base_exp = patch_exp if isinstance(patch_exp, Mapping) else previous_experience
    experience = {
        key: [dict(i) for i in value if isinstance(i, Mapping)]
        if isinstance(value, list)
        else value
        for key, value in (base_exp.items() if isinstance(base_exp, Mapping) else ())
    }
    basics = patch.get("basics")
    language = (
        basics.get("language")
        if isinstance(basics, Mapping) and "language" in basics
        else previous_language
    )
    languages: list[str] = []
    notices: list[str] = []
    renamed: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    for index, raw in enumerate(stack["rows"]):
        data = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(data, Mapping):
            continue
        level = data.get("level")
        if index >= _TALK_ROWS_MAX:
            # Ponad limit zapisu i tak trafia do opisu (`split_rows`) — bez
            # czytania, żeby długie ciało żądania nie zamroziło API.
            rows.append(dict(data))
            continue
        # Słowa po sicie wiersza (≤ 20 po ≤ 100 znaków) — przegląd
        # bezpieczeństwa 13.10.2026: surowy tekst do 30 MB szedł do odczytu
        # przed limitami schematu.
        words = _row_words(data.get("words"))
        if _row_key(words) in known:
            rows.append({**data, "words": words})
            continue
        kept: list[str] = []
        for word in words:
            reading = read_phrase(word)
            talk_level = "nice" if level == "nice" else "must"
            if reading.needs_decision and reading.talk == "language":
                languages.append(reading.text)
                notices.append(f"„{reading.text}” przeniesione do pola „Język”.")
                continue
            if reading.needs_decision and reading.talk in ("skills", "domains"):
                items = experience.setdefault(reading.talk, [])
                if _merge_talk(items, reading.talk_text or reading.text, talk_level):
                    notices.append(
                        f"„{reading.text}” przeniesione do „Rekruter sprawdza "
                        "w rozmowie” — wyszukiwanie go nie czyta."
                    )
                    continue
            if reading.keyword and reading.comment and reading.keyword != word:
                kept.append(reading.keyword)
                if reading.talk_text:
                    _merge_talk(
                        experience.setdefault("skills", []),
                        reading.talk_text,
                        talk_level,
                    )
                    notices.append(
                        f"„{word}”: szukamy „{reading.keyword}”, poziom przeszedł "
                        "do „Rekruter sprawdza w rozmowie”."
                    )
                else:
                    notices.append(
                        f"„{word}”: szukamy „{reading.keyword}”, komentarz "
                        f"„{reading.comment}” pominięty."
                    )
                continue
            kept.append(word)
        if words and kept != words:
            renamed[_head(words).casefold()] = _head(kept) if kept else ""
        if kept:
            rows.append({**data, "words": kept})
    required_before = [r for r in stack["rows"] if _level_of(r) != "nice"]
    required_after = [r for r in rows if _level_of(r) != "nice"]
    if keep_required and required_before and not required_after:
        return patch, [
            "Wymagania zostały bez zmian: rekrutacja w searchu musi mieć co "
            "najmniej jedno słowo do szukania. Dodaj słowo, a zdania przenieś "
            "do „Rekruter sprawdza w rozmowie”."
        ]
    if not renamed and not languages:
        return patch, []
    out_stack: dict[str, Any] = {**stack, "rows": rows}
    critical = stack.get("critical")
    if isinstance(critical, list):
        out_stack["critical"] = [
            renamed.get(name.split(ALTERNATIVE_JOINER)[0].strip().casefold(), name)
            for name in critical
            if isinstance(name, str)
            and renamed.get(name.split(ALTERNATIVE_JOINER)[0].strip().casefold(), name)
        ]
    elif any(_level_of(r) == "critical" for r in stack["rows"]) and not any(
        _level_of(r) == "critical" for r in rows
    ):
        # Edytor niesie krytyczne poziomem wiersza i `critical: null`. Gdy
        # ostatnia krytyczna poszła do rozmowy, decyzja DL zostaje „Brak
        # krytycznych” (`[]`) jak w „Wymaganiach do poprawy” — `None` dokładał
        # blokadę `critical` i kończył zapis 422 `handoff_regression` (audyt
        # 13.10.2026).
        out_stack["critical"] = []
    out: dict[str, Any] = {**patch, "stack": out_stack, "experience": experience}
    if languages:
        parts = [p for p in [str(language or "").strip()] if p]
        for text in languages:
            if text.casefold() not in " ".join(parts).casefold():
                parts.append(text)
        out["basics"] = {
            **(basics if isinstance(basics, Mapping) else {}),
            "language": ", ".join(parts),
        }
    return out, notices


def _level_of(row: Any) -> Optional[str]:
    data = row.model_dump() if hasattr(row, "model_dump") else row
    return data.get("level") if isinstance(data, Mapping) else None


ROWS_OWN_COLUMNS_DETAIL = (
    "Wymagania tej rekrutacji są prowadzone wierszami w Profilu Championa — "
    "edytuj je tam (zakładka „Profil Championa”), a kolumny must/nice "
    "zaktualizują się same."
)


def profile_has_rows(profile: Any) -> bool:
    """Czy profil prowadzi wymagania wierszami (``stack.rows``)."""
    stack = profile.get("stack") if isinstance(profile, Mapping) else None
    return isinstance(stack, Mapping) and isinstance(stack.get("rows"), list)


def skill_column_names(value: Any) -> list[str]:
    """Nazwy z kolumny ``must_skills``/``nice_skills`` (napisy albo słowniki)."""
    return [name.strip().casefold() for name in _names(value) if name.strip()]


def _names(items: Any) -> list[str]:
    out: list[str] = []
    for item in items or []:
        name = item.get("name") if isinstance(item, Mapping) else item
        if isinstance(name, str):
            out.append(name)
    return out


def _label_fits(label: str, words: list[str]) -> bool:
    """Etykieta należy do wiersza: zaczyna się jego pierwszym słowem, a każdy
    zamiennik po „lub” jest słowem wiersza. Niezależne od stanu słownika —
    technologia dopisana do słownika po zapisie nie unieważnia wierszy."""
    parts = [part.strip().casefold() for part in label.split(ALTERNATIVE_JOINER)]
    known = {_plain(word).casefold() for word in words}
    return bool(parts) and parts[0] == _head(words).casefold() and set(parts) <= known


def rows_consistent(stack: Any, search: Any) -> bool:
    """Czy `must`, `nice` i `search.requirements` nadal odpowiadają wierszom."""
    if not isinstance(stack, Mapping) or not isinstance(stack.get("rows"), list):
        return True
    rows = clean_rows(stack["rows"])
    required = [row for row in rows if row["level"] != "nice"]
    optional = [row for row in rows if row["level"] == "nice"]
    must = _names(stack.get("must"))
    nice = _names(stack.get("nice"))
    stored = [
        [word.casefold() for word in row]
        for row in (search.get("requirements") if isinstance(search, Mapping) else None)
        or []
    ]
    if len(must) != len(required) or len(nice) != len(optional):
        return False
    if stored != [[word.casefold() for word in row["words"]] for row in required]:
        return False
    return all(
        _label_fits(label, row["words"])
        for label, row in (*zip(must, required), *zip(nice, optional))
    )


def _is_keyword(label: str) -> bool:
    return len(label) <= KEYWORD_MAX_CHARS and len(label.split()) <= KEYWORD_MAX_WORDS


def rows_from_legacy(
    *,
    must: list[str],
    nice: list[str],
    requirements: list[list[str]],
    critical: Optional[list[str]] = None,
    clip: bool = True,
) -> dict[str, Any]:
    """Stare pola → wiersze (przycisk „Uprość do słów kluczowych”, kopia
    rekrutacji z szablonu).

    ``clip=False`` oddaje wiersze bez limitów zapisu — „Wymagania do poprawy”
    najpierw przenoszą zdania do rozmowy, a dopiero potem liczą nadmiar.

    Wiersze wyszukiwania zostają, jakie były. Must będące technologią dochodzi
    jako wiersz (bez wersji — tę niesie zdanie opisowe), krótka pozycja bez
    technologii zostaje słowem kluczowym, a zdanie klienta wraca jako
    `descriptive` — nie filtruje kandydatów. `descriptive_nice` to te z nich,
    które przyszły z „mile widziane” (14.10.2026: „Zatwierdź” i „Uprość”
    robiły z nich „musi” w rozmowie). `no_critical` mówi, że DL wybrał
    wcześniej „Brak krytycznych”.
    """
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of, strip_version

    rows: list[dict[str, Any]] = [
        {"words": list(row), "level": "must"} for row in requirements if row
    ]
    descriptive: list[str] = []
    descriptive_nice: list[str] = []

    def keys(words: list[str]) -> set[str]:
        # „Java 17+” w starym wierszu wyszukiwania to ta sama technologia.
        return {canonical_of(strip_version(_plain(word))[0]) for word in words}

    def find(words: list[str]) -> Optional[dict[str, Any]]:
        wanted = keys(words)
        return next((row for row in rows if keys(row["words"]) & wanted), None)

    def describe(text: str, level: str) -> None:
        descriptive.append(text)
        if level == "nice":
            descriptive_nice.append(text)

    def add(label: str, level: str) -> None:
        text = " ".join(str(label or "").split())
        if not text:
            return
        requirement = gate_requirement(text)
        if requirement is not None:
            words = list(requirement.options)
            if ALTERNATIVE_JOINER.join(words).casefold() != text.casefold():
                describe(text, level)
        elif _is_keyword(text):
            words = [text]
        else:
            describe(text, level)
            return
        if find(words) is None:
            rows.append({"words": words, "level": level})

    for label in must:
        add(label, "must")
    for label in nice:
        add(label, "nice")
    for name in critical or []:
        requirement = gate_requirement(name)
        row = find(list(requirement.options) if requirement else [name])
        if row is not None and row["level"] != "nice":
            row["level"] = "critical"
    return {
        "rows": clean_rows(rows) if clip else rows,
        "descriptive": descriptive,
        "descriptive_nice": descriptive_nice,
        "no_critical": critical == [],
    }
