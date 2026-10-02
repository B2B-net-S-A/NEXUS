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


def clean_rows(value: Any) -> list[dict[str, Any]]:
    """Wiersze w kształcie zapisu: słowa jak w wyszukiwarce, poziom ze słownika.

    Dwa wiersze o tym samym pierwszym słowie to to samo wymaganie — zostaje
    pierwszy. Limity jak w edytorze: 10 wierszy obowiązkowych, 20 mile
    widzianych, najwyżej 2 krytyczne (kolejne schodzą do „musi mieć”).
    """
    if not isinstance(value, list):
        return []
    rows: list[dict[str, Any]] = []
    heads: set[str] = set()
    required = nice = critical = 0
    for raw in value:
        data = raw.model_dump() if hasattr(raw, "model_dump") else raw
        if not isinstance(data, Mapping):
            continue
        words = _search_words(data.get("words"))
        head = _head(words).casefold()
        if not head or head in heads:
            continue
        level = data.get("level")
        if level not in REQUIREMENT_ROW_LEVELS:
            level = "must"
        if level == "critical" and critical >= CRITICAL_MAX:
            level = "must"
        if level == "nice":
            if nice >= REQUIREMENT_NICE_MAX_ROWS:
                continue
            nice += 1
        else:
            if required >= SEARCH_REQUIREMENT_MAX_ROWS:
                continue
            required += 1
            critical += level == "critical"
        heads.add(head)
        rows.append({"words": words, "level": level})
    return rows


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


def expand_patch(patch: Any) -> Any:
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
    rows = clean_rows(stack["rows"])
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
    return {
        **patch,
        "stack": {
            **stack,
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
) -> dict[str, Any]:
    """Stare pola → wiersze (przycisk „Uprość do słów kluczowych”, kopia
    rekrutacji z szablonu).

    Wiersze wyszukiwania zostają, jakie były. Must będące technologią dochodzi
    jako wiersz (bez wersji — tę niesie zdanie opisowe), krótka pozycja bez
    technologii zostaje słowem kluczowym, a zdanie klienta wraca jako
    `descriptive` — nie filtruje kandydatów. `no_critical` mówi, że DL wybrał
    wcześniej „Brak krytycznych”.
    """
    from app.services.must_gate_terms import gate_requirement
    from app.services.skill_normalize import canonical_of, strip_version

    rows: list[dict[str, Any]] = [
        {"words": list(row), "level": "must"} for row in requirements if row
    ]
    descriptive: list[str] = []

    def keys(words: list[str]) -> set[str]:
        # „Java 17+” w starym wierszu wyszukiwania to ta sama technologia.
        return {canonical_of(strip_version(_plain(word))[0]) for word in words}

    def find(words: list[str]) -> Optional[dict[str, Any]]:
        wanted = keys(words)
        return next((row for row in rows if keys(row["words"]) & wanted), None)

    def add(label: str, level: str) -> None:
        text = " ".join(str(label or "").split())
        if not text:
            return
        requirement = gate_requirement(text)
        if requirement is not None:
            words = list(requirement.options)
            if ALTERNATIVE_JOINER.join(words).casefold() != text.casefold():
                descriptive.append(text)
        elif _is_keyword(text):
            words = [text]
        else:
            descriptive.append(text)
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
        "rows": clean_rows(rows),
        "descriptive": descriptive,
        "no_critical": critical == [],
    }
