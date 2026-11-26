"""Odbiorcy powiadomień i maili: wzorzec (rodzaj × persona) z kodu produkcyjnego.

Bliźniak ``tests/_authz_matrix.py``: tam bramki tras, tu odbiorcy. Persony są
te same (``PERSONAS``, polityka produkcji), więc oba wzorce mówią o tych
samych kontach. Pliki leżą w ``tests/data/notify_golden/``:

* ``bell_roles.json`` — brama dzwonka: kto z person w ogóle może dostać dany
  typ (``notification_access.user_can_receive_notification``, ta sama bramka
  przy zapisie w ``emit``, liście, liczniku, mailu i dymku). Każdy
  ``NotificationType``; typy kontekstowe w wariantach (czat rekrutacji albo
  kandydata, link wzmianki).
* ``mail_roles.json`` — brama maila: ``notification_email_prefs.APPLIES``
  (każdy rodzaj z ``notification_delivery.CATALOG``) przy modułach „Ludzi”
  włączonych jak na produkcji.
* ``relations.json`` — wybór odbiorców liczony bez bazy (reguła „rekruter
  rekrutacji”, nadawca maila Rady, ważne ogłoszenie).
* ``relations_db.json`` — wybór odbiorców liczony zapytaniami: obsada
  fikcyjnych kont i obiektów w Postgresie, wołana funkcja producenta i bramka
  dzwonka (``test_notify_golden_db.py``).

Brama mówi, kto MOŻE dostać; producent wybiera, kto dostaje. Dzwonek trafia
do części wspólnej obu. Stąd dwie warstwy: rozszerzenie producenta zatrzyma
dopiero brama, a rozszerzenie bramy jest widoczne, zanim producent z niego
skorzysta.

Przegenerowanie (diff idzie do PR-a jako lista zmian odbiorców):

    cd backend && NOTIFY_GOLDEN_WRITE=1 python -m pytest \\
        tests/test_notify_golden.py tests/test_notify_golden_db.py
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.notification import NotificationType
from app.models.user import User
from tests._authz_matrix import PERSONAS, Persona, build_user

GOLDEN_DIR = Path(__file__).parent / "data" / "notify_golden"
WRITE_ENV = "NOTIFY_GOLDEN_WRITE"
REGENERATE = (
    "cd backend && NOTIFY_GOLDEN_WRITE=1 python -m pytest "
    "tests/test_notify_golden.py tests/test_notify_golden_db.py"
)

#: Typy kontekstowe (``notification_access.CONTEXTUAL_NOTIFICATION_TYPES``):
#: sekcję wyznacza wiersz, więc każdy wariant ma osobny wpis wzorca.
CONTEXT_VARIANTS: dict[NotificationType, tuple[tuple[str, dict[str, str]], ...]] = {
    NotificationType.job_chat_message: (
        ("czat rekrutacji", {"related_entity_type": "job_chat_message"}),
        ("czat kandydata", {"related_entity_type": "candidate_chat_message"}),
    ),
    NotificationType.job_chat_mention: (
        ("czat rekrutacji", {"related_entity_type": "job_chat_message"}),
        ("czat kandydata", {"related_entity_type": "candidate_chat_message"}),
    ),
    NotificationType.note_mention: (
        ("link /candidates", {"link": "/candidates/1"}),
        ("link /jobs", {"link": "/jobs/1"}),
        ("link /clients", {"link": "/clients/1"}),
        ("link /insights", {"link": "/insights"}),
        ("link /finance", {"link": "/finance"}),
        ("link poza sekcjami", {"link": "/settings"}),
    ),
    NotificationType.pending_verification: (
        ("link /jobs", {"link": "/jobs/1"}),
        ("link poza /jobs", {"link": "/admin/requests"}),
    ),
}

#: Rodzaje, które dziś idą do ról szerszych, niż mówi reguła albo historia.
#: Wzorzec zapisuje stan kodu; tu jest powód, dla którego trzeba o nim
#: zdecydować. Klucz: ``(plik wzorca, rodzaj)``. Wpis przeżywa przegenerowanie.
TO_DECIDE: dict[tuple[str, str], str] = {
    ("bell_roles", "board_krs_entry"): (
        "Brama wpuszcza każde konto z odczytem Insights (sekcja w "
        "NOTIFICATION_SECTION_BY_TYPE), a reguła Rady mówi: tylko Rada i "
        "admini. Dziś trzyma to sam producent (board/notify.recipient_ids). "
        "Tak powstał wyciek 02.11.2026: odbiorców wyznaczało uprawnienie, "
        "a nie rola."
    ),
    ("bell_roles", "board_meeting_pack"): (
        "Jak board_krs_entry: brama = odczyt Insights, reguła = Rada i admini."
    ),
    ("bell_roles", "board_vote"): (
        "Jak board_krs_entry: brama = odczyt Insights, reguła = Rada i admini; "
        "projekt uchwały idzie do składu z wysyłki (board_member_ids)."
    ),
}


@dataclass(frozen=True)
class Kind:
    """Jeden wpis wzorca relacji: funkcja producenta, obsada i kto dostaje.

    ``cast`` to nazwa obsady z ``"obsady"`` pliku — lista kont scenariusza
    stoi tam raz, a „nie dostaje” znaczy „jest w obsadzie, a nie w odbiorcach”.
    """

    source: str
    cast: str
    recipients: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {
            "zrodlo": self.source,
            "obsada": self.cast,
            "odbiorcy": sorted(self.recipients),
        }


def persona_users() -> list[tuple[Persona, User]]:
    """Konta person z dołączoną polityką produkcji (jak w ``_authz_matrix``)."""

    return [
        (persona, build_user(persona, user_id=910_000 + index))
        for index, persona in enumerate(PERSONAS)
    ]


def bell_kinds() -> Iterator[tuple[str, NotificationType, dict[str, str]]]:
    for ntype in sorted(NotificationType, key=lambda value: value.value):
        variants = CONTEXT_VARIANTS.get(ntype)
        if not variants:
            yield ntype.value, ntype, {}
            continue
        for label, context in variants:
            yield f"{ntype.value} [{label}]", ntype, context


def bell_matrix(users: list[tuple[Persona, User]]) -> dict[str, list[str]]:
    """``{rodzaj: [persony, które brama dzwonka przepuszcza]}``."""

    from app.services.notification_access import user_can_receive_notification

    return {
        key: sorted(
            persona.key
            for persona, user in users
            if user_can_receive_notification(user, ntype, **context)
        )
        for key, ntype, context in bell_kinds()
    }


def mail_matrix(
    users: list[tuple[Persona, User]],
) -> tuple[dict[str, list[str]], dict[str, str]]:
    """``({rodzaj maila: [persony]}, {rodzaj poza regułą konta: dlaczego})``.

    Reguła ``APPLIES`` to „czy mail w ogóle może trafić do konta” — ta sama,
    którą widzi osoba w „Maile do Ciebie” i którą nadawca ma odbijać.
    Wołający włącza program „Ludzie” jak na produkcji
    (``settings.HR_PROGRAM_ENABLED = True``); moduły są tu wszystkie włączone.
    """

    from app.services import notification_email_prefs as prefs
    from app.services.hr_foundation_schema import HR_MODULE_KEYS
    from app.services.notification_delivery import CATALOG, SECURITY_CATALOG

    context = prefs._Context(hr_modules={key: True for key in HR_MODULE_KEYS})
    matrix: dict[str, list[str]] = {}
    outside: dict[str, str] = {}
    for spec in CATALOG:
        kind = spec["id"]
        if kind in prefs._NOT_AN_ACCOUNT_EMAIL:
            outside[kind] = "mail do kandydata, nie do konta"
            continue
        rule = prefs.APPLIES[kind]
        matrix[kind] = sorted(
            persona.key for persona, user in users if rule(user, context)
        )
    for spec in SECURITY_CATALOG:
        outside[spec["id"]] = "mail bezpieczeństwa do właściciela konta"
    return matrix, outside


# ── Zapis i porównanie ───────────────────────────────────────────────────────


def _path(name: str) -> Path:
    return GOLDEN_DIR / f"{name}.json"


def _decisions(name: str, kinds: Iterable[str]) -> dict[str, str]:
    known = set(kinds)
    return {
        kind: reason
        for (file, kind), reason in sorted(TO_DECIDE.items())
        if file == name and kind in known
    }


def write_golden(
    name: str,
    kinds: Mapping[str, Any],
    *,
    description: str,
    extra: Mapping[str, Any] | None = None,
) -> None:
    """Jeden plik wzorca: rodzaj na klucz, wartości posortowane (mały diff)."""

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "opis": description,
        "przegeneruj": REGENERATE,
        "rodzaje": dict(kinds),
        "do_decyzji": _decisions(name, kinds),
    }
    if extra:
        payload.update(extra)
    _path(name).write_text(
        json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_golden(name: str) -> dict[str, Any]:
    path = _path(name)
    if not path.exists():
        raise AssertionError(
            f"Brak wzorca {path.relative_to(GOLDEN_DIR.parent.parent.parent)} — "
            f"nagraj go: {REGENERATE}"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _recipients_of(value: Any) -> set[str]:
    return set(value["odbiorcy"] if isinstance(value, dict) else value)


def differences(
    name: str, golden: Mapping[str, Any], actual: Mapping[str, Any]
) -> list[str]:
    """Zmiany odbiorców: rodzaj, persona, było/jest — w kolejności rodzajów."""

    lines: list[str] = []
    for kind in sorted(set(golden) | set(actual)):
        if kind not in golden:
            lines.append(f"{name}: {kind} — nowy rodzaj, wzorzec go nie zna")
            continue
        if kind not in actual:
            lines.append(f"{name}: {kind} — rodzaju nie ma już w kodzie")
            continue
        before, after = golden[kind], actual[kind]
        old, new = _recipients_of(before), _recipients_of(after)
        changes = [f"+{who} (było: nie dostaje, jest: dostaje)" for who in new - old]
        changes += [f"-{who} (było: dostaje, jest: nie dostaje)" for who in old - new]
        if isinstance(before, dict) and isinstance(after, dict):
            if before.get("obsada") != after.get("obsada"):
                changes.append(f"obsada {before.get('obsada')} → {after.get('obsada')}")
            if before.get("zrodlo") != after.get("zrodlo"):
                changes.append(f"źródło {before.get('zrodlo')} → {after.get('zrodlo')}")
        if changes:
            lines.append(f"{name}: {kind}: " + "; ".join(sorted(changes)))
    return lines


def failure_message(lines: list[str]) -> str:
    return (
        f"Zmienili się odbiorcy powiadomień ({len(lines)}):\n  "
        + "\n  ".join(lines[:80])
        + ("\n  …" if len(lines) > 80 else "")
        + "\n\nJeśli to zamierzona zmiana odbiorców, przegeneruj wzorzec i dołącz "
        f"jego diff do PR-a do przeglądu:\n  {REGENERATE}"
    )


def check_or_write(
    name: str,
    actual: Mapping[str, Any],
    *,
    write: bool,
    description: str,
    extra: Mapping[str, Any] | None = None,
) -> list[str]:
    """Zapisz wzorzec (``write``) albo zwróć różnice względem zapisanego."""

    if write:
        write_golden(name, actual, description=description, extra=extra)
        return []
    golden = load_golden(name)
    lines = differences(name, golden["rodzaje"], actual)
    for key, value in (extra or {}).items():
        if golden.get(key) != value:
            lines.append(f"{name}: {key} — było {golden.get(key)!r}, jest {value!r}")
    return lines


def labelled(ids: Iterable[int | None], labels: Mapping[int, str]) -> tuple[str, ...]:
    """Odbiorcy z obsady scenariusza (konta spoza niej — z innych testów — pomija)."""

    return tuple(sorted({labels[uid] for uid in ids if uid in labels}))


def source_name(source: Callable[..., Any] | str) -> str:
    if isinstance(source, str):
        return source
    return f"{source.__module__}.{source.__qualname__}"


def kind(
    source: Callable[..., Any] | str,
    cast: str,
    labels: Mapping[int, str],
    ids: Iterable[int | None],
) -> Kind:
    return Kind(source=source_name(source), cast=cast, recipients=labelled(ids, labels))
