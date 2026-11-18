"""Co się zmieniło w Profilu Championa — różnica po ludzku dla rekrutera.

Pomysł rekruterki 17.11.2026, makiety runda 2 (karta w Briefie + zakładka
„Zmiany” + zdanie Delivery Leada). Zapis profilu rekrutacji w pracy zostawia
wersję (``champion_profile_revisions``) z listą pozycji liczoną tutaj.

Porównujemy ZNORMALIZOWANE profile (``ChampionProfile.model_dump``), a wiersze
wymagań po etykietach, nie po indeksach: usunięcie jednego wiersza przesuwa
indeksy wszystkich kolejnych, więc surowa różnica JSON-a dla rekrutacji 789123
(jedno usunięcie w „Musi mieć” i jedno w „Mile widziane”) miała 70 linii.

Pozycja to ``{"kind", "text", "detail"}``:
``added`` / ``removed`` / ``moved`` (zmiana poziomu) / ``set`` (pole albo opis).
Pusta lista = zapis bez zmiany, którą warto pokazać rekruterowi (np. sama
kolejność wierszy albo wymagania do wyszukiwania w bazie) — wtedy wersji nie ma.
"""

from __future__ import annotations

from typing import Any, Iterable

LEVEL_LABELS: dict[str, str] = {
    "critical": "Krytyczne",
    "must": "Musi mieć",
    "nice": "Mile widziane",
}

_EXPERIENCE_GROUPS: tuple[tuple[str, str], ...] = (
    ("domains", "Dziedzina"),
    ("certifications", "Certyfikat"),
    ("regulations", "Regulacja"),
    ("skills", "Umiejętność"),
)

# Pola „Warunków”, które rekruter mówi kandydatowi albo sprawdza w rozmowie.
_BASICS_FIELDS: tuple[tuple[str, str], ...] = (
    ("role_name", "Rola"),
    ("seniority_min_years", "Doświadczenie (lata)"),
    ("rate_value", "Budżet (PLN/h)"),
    ("work_mode", "Tryb pracy"),
    ("onsite_days_per_week", "Dni w biurze w tygodniu"),
    ("onsite_days_per_month", "Dni w biurze w miesiącu"),
    ("candidate_location_pref", "Lokalizacja biura"),
    ("language", "Język pracy"),
    ("start_date", "Start"),
    ("contract_length", "Długość współpracy"),
)

_WORK_MODES = {"remote": "zdalnie", "hybrid": "hybrydowo", "onsite": "stacjonarnie"}
_TEXT_LIMIT = 140


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split())


def _short(value: Any) -> str:
    text = _clean(value)
    return text if len(text) <= _TEXT_LIMIT else text[: _TEXT_LIMIT - 1].rstrip() + "…"


def _item(kind: str, text: str, detail: str = "") -> dict[str, str]:
    return {"kind": kind, "text": _short(text), "detail": _short(detail)}


def _row_words(row: Any) -> list[str]:
    if not isinstance(row, dict):
        return []
    return [_clean(w) for w in row.get("words") or [] if _clean(w)]


def _head(label: str) -> str:
    """Pierwsza nazwa etykiety wiersza („Kafka lub RabbitMQ” → „Kafka”).

    `stack.critical` i stare listy `must`/`nice` trzymają etykietę z
    zamiennikami (`champion_requirement_rows.row_label`), a wiersz — słowa.
    Kluczem jest głowa, jak w `_kept_critical`.
    """
    return _clean(label).split(" lub ")[0].strip()


def _requirement_rows(stack: dict) -> dict[str, tuple[str, str, tuple[str, ...]]]:
    """Wiersz → (etykieta, poziom, warianty) z kluczem po pierwszej nazwie.

    Profil sprzed wierszy (02.10.2026) ma tylko listy ``must``/``nice``
    i ``critical`` — czytamy je w tym samym kształcie, żeby porównanie
    starego profilu z nowym nie raportowało „wszystko usunięte, wszystko dodane”.
    """
    out: dict[str, tuple[str, str, tuple[str, ...]]] = {}
    # Zapis trzyma wybór krytycznych w `stack.critical` (etykiety wierszy),
    # a wiersz może zostać na poziomie „musi mieć”.
    critical = {_head(name).casefold() for name in stack.get("critical") or []}
    rows = stack.get("rows")
    if isinstance(rows, list) and rows:
        for row in rows:
            words = _row_words(row)
            if not words:
                continue
            key = _head(words[0]).casefold()
            level = row.get("level") if row.get("level") in LEVEL_LABELS else "must"
            if level == "must" and key in critical:
                level = "critical"
            out.setdefault(key, (words[0], level, tuple(w.casefold() for w in words)))
        return out
    for level in ("must", "nice"):
        for entry in stack.get(level) or []:
            name = _clean(entry.get("name") if isinstance(entry, dict) else entry)
            if not name:
                continue
            head = _head(name)
            key = head.casefold()
            variants = tuple(
                v.strip().casefold() for v in name.split(" lub ") if v.strip()
            )
            effective = "critical" if level == "must" and key in critical else level
            out.setdefault(key, (head, effective, variants))
    return out


def _stack_changes(old: dict, new: dict) -> list[dict[str, str]]:
    before = _requirement_rows(old or {})
    after = _requirement_rows(new or {})
    changes: list[dict[str, str]] = []
    for key, (label, level, words) in after.items():
        if key not in before:
            changes.append(_item("added", label, f"nowe w „{LEVEL_LABELS[level]}”"))
            continue
        _, old_level, old_words = before[key]
        if old_level != level:
            changes.append(
                _item(
                    "moved",
                    label,
                    f"„{LEVEL_LABELS[old_level]}” → „{LEVEL_LABELS[level]}”",
                )
            )
        elif set(old_words) != set(words):
            variants = " lub ".join(dict.fromkeys(w for w in words))
            changes.append(_item("set", label, f"teraz: {variants}"))
    for key, (label, level, _words) in before.items():
        if key not in after:
            changes.append(
                _item("removed", label, f"usunięte z „{LEVEL_LABELS[level]}”")
            )
    return changes


def _experience_changes(old: dict, new: dict) -> list[dict[str, str]]:
    changes: list[dict[str, str]] = []
    for key, label in _EXPERIENCE_GROUPS:
        before = {
            _clean(i.get("name")).casefold(): _clean(i.get("name"))
            for i in (old or {}).get(key) or []
            if isinstance(i, dict) and _clean(i.get("name"))
        }
        after = {
            _clean(i.get("name")).casefold(): _clean(i.get("name"))
            for i in (new or {}).get(key) or []
            if isinstance(i, dict) and _clean(i.get("name"))
        }
        for k, name in after.items():
            if k not in before:
                changes.append(
                    _item(
                        "added",
                        f"{label}: {name}",
                        "nowe w „Rekruter sprawdza w rozmowie”",
                    )
                )
        for k, name in before.items():
            if k not in after:
                changes.append(
                    _item(
                        "removed",
                        f"{label}: {name}",
                        "usunięte z „Rekruter sprawdza w rozmowie”",
                    )
                )
    return changes


def _format_basic(key: str, value: Any) -> str:
    if value is None or _clean(value) == "":
        return ""
    if key == "work_mode":
        return _WORK_MODES.get(str(value), _clean(value))
    if key == "rate_value":
        number = float(value)
        return (
            f"{number:.0f}"
            if number.is_integer()
            else f"{number:.2f}".replace(".", ",")
        )
    return _clean(value)


def _set_detail(old: str, new: str) -> str:
    if old and new:
        return f"{old} → {new}"
    if new:
        return f"{new} (wcześniej brak)"
    return f"usunięte (było: {old})"


def _deadline(basics: dict) -> str:
    raw = _clean(basics.get("deadline"))
    if not raw:
        return ""
    parts = raw.split("-")
    shown = f"{parts[2]}.{parts[1]}" if len(parts) == 3 and len(parts[0]) == 4 else raw
    time = _clean(basics.get("deadline_time"))
    return f"{shown}, {time}" if time else shown


def _basics_changes(old: dict, new: dict) -> list[dict[str, str]]:
    old = old or {}
    new = new or {}
    changes: list[dict[str, str]] = []
    for key, label in _BASICS_FIELDS:
        before = _format_basic(key, old.get(key))
        after = _format_basic(key, new.get(key))
        if before != after:
            changes.append(_item("set", label, _set_detail(before, after)))
    before_deadline, after_deadline = _deadline(old), _deadline(new)
    if before_deadline != after_deadline:
        changes.append(
            _item(
                "set",
                "Deadline na kandydatów",
                _set_detail(before_deadline, after_deadline),
            )
        )
    return changes


def _question_changes(old: Iterable[Any], new: Iterable[Any]) -> list[dict[str, str]]:
    def texts(items: Iterable[Any]) -> dict[str, str]:
        out: dict[str, str] = {}
        for q in items or []:
            if isinstance(q, dict) and _clean(q.get("question")):
                out.setdefault(_clean(q["question"]).casefold(), _clean(q["question"]))
        return out

    before, after = texts(old), texts(new)
    changes = [
        _item("added", "Pytanie na rozmowę", q)
        for k, q in after.items()
        if k not in before
    ]
    changes += [
        _item("removed", "Pytanie na rozmowę", q)
        for k, q in before.items()
        if k not in after
    ]
    return changes


def _plural(n: int, one: str, few: str, many: str) -> str:
    if n == 1:
        return one
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return few
    return many


def _open_client_questions(insights: Iterable[Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for note in insights or []:
        if (
            isinstance(note, dict)
            and note.get("topic") == "ask_client"
            and not note.get("done")
            and _clean(note.get("text"))
        ):
            out[_clean(note.get("id")) or _clean(note["text"])] = _clean(note["text"])
    return out


def _client_question_changes(
    old: Iterable[Any], new: Iterable[Any]
) -> list[dict[str, str]]:
    before, after = _open_client_questions(old), _open_client_questions(new)
    closed = [text for key, text in before.items() if key not in after]
    opened = [text for key, text in after.items() if key not in before]
    changes: list[dict[str, str]] = []
    if closed:
        noun = _plural(
            len(closed), "pytanie zamknięte", "pytania zamknięte", "pytań zamkniętych"
        )
        changes.append(
            _item(
                "set",
                "Do dopytania u klienta",
                f"{len(closed)} {noun}: {'; '.join(closed)}",
            )
        )
    for text in opened:
        changes.append(_item("added", "Do dopytania u klienta", text))
    return changes


def describe_changes(old: dict | None, new: dict | None) -> list[dict[str, str]]:
    """Pozycje zmian między dwoma ZNORMALIZOWANYMI profilami, w kolejności Briefu."""
    old = old or {}
    new = new or {}
    changes: list[dict[str, str]] = []
    changes += _stack_changes(old.get("stack") or {}, new.get("stack") or {})
    changes += _experience_changes(
        old.get("experience") or {}, new.get("experience") or {}
    )
    changes += _basics_changes(old.get("basics") or {}, new.get("basics") or {})
    changes += _question_changes(
        old.get("screening_questions") or [], new.get("screening_questions") or []
    )
    old_project, new_project = old.get("project") or {}, new.get("project") or {}
    if _clean(old_project.get("about")) != _clean(new_project.get("about")):
        changes.append(_item("set", "O projekcie", "opis zmieniony"))
    if _clean(old_project.get("responsibilities")) != _clean(
        new_project.get("responsibilities")
    ):
        changes.append(_item("set", "Obowiązki", "lista zmieniona"))
    old_client, new_client = old.get("client") or {}, new.get("client") or {}
    if _clean(old_client.get("selling_points")) != _clean(
        new_client.get("selling_points")
    ):
        changes.append(_item("set", "Co powiedzieć kandydatowi", "zmienione"))
    changes += _client_question_changes(
        old.get("insights") or [], new.get("insights") or []
    )
    return changes
