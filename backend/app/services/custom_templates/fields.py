"""Pola wzoru własnego: definicja, walidacja wartości i kontekst renderu.

Klucz pola jest ścieżką w szablonie (``partner.nip`` → ``{{ partner.nip }}``,
najwyżej trzy człony). Wartości przychodzą płasko (``{"partner.nip": "…"}``),
kontekst renderu buduje z nich zagnieżdżone słowniki — wyłącznie z pól z listy.

Co liczy kod, a nie człowiek ani model (decyzja Artura 25.11.2026):

* ``company.*`` — dane B2B.net (``company_party``), ``document_place``,
* pole ``money`` ``X`` → ``{{ X }}`` jako „6 200,00” i ``{{ X_words }}`` słownie,
* pole ``date`` → „DD.MM.RRRR”,
* pole ``gender`` → formy rodzajowe ``{{ g.* }}`` (``g.g_pan`` = „Panem/Panią”,
  także bez przedrostka: ``g.pan``).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from app.services.b2b_contract_generator.formatting import pl_date
from app.services.b2b_contract_generator.gender import _FORMS_M, gender_forms
from app.services.b2b_contract_generator.number_words import pln_words_with_fraction
from app.services.b2b_documents.company_party import COMPANY_PL, company_party

FieldKind = Literal[
    "text", "textarea", "date", "money", "bool", "select", "email", "gender", "list"
]
FieldSource = Literal["candidate", "ceidg", "clients", "manual"]

KINDS: tuple[str, ...] = (
    "text",
    "textarea",
    "date",
    "money",
    "bool",
    "select",
    "email",
    "gender",
    "list",
)
SOURCES: tuple[str, ...] = ("candidate", "ceidg", "clients", "manual")
SOURCE_LABELS: dict[str, str] = {
    "candidate": "kandydat",
    "ceidg": "CEIDG",
    "clients": "lista klientów",
    "manual": "ręcznie",
}

#: Nazwy, które wypełnia kod — pole o takim pierwszym członie jest błędem.
RESERVED_ROOTS: frozenset[str] = frozenset({"company", "g", "document_place", "loop"})
MONEY_WORDS_SUFFIX = "_words"

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}(\.[a-z][a-z0-9_]{0,39}){0,2}$")
ITEM_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")

MAX_FIELDS = 80
MAX_LABEL = 120
MAX_GROUP = 40
MAX_HELP = 300
MAX_OPTIONS = 30
MAX_LIST_ITEMS = 30
MAX_ITEM_KEYS = 6
MAX_TEXT = 2000
MAX_TEXTAREA = 8000
MONEY_MAX = Decimal("10000000")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

#: Formy rodzajowe dostępne w szablonie — z przedrostkiem (jak w umowie B2B)
#: i bez (jak we wzorze umowy szkoleniowej).
GENDER_FORM_KEYS: tuple[str, ...] = tuple(
    sorted({*_FORMS_M, *(k.removeprefix("g_") for k in _FORMS_M)})
)


class FieldsError(ValueError):
    """Lista pól nie da się zapisać — komunikat dla człowieka."""


@dataclass(frozen=True)
class ItemKey:
    key: str
    label: str


@dataclass(frozen=True)
class CustomField:
    key: str
    label: str
    kind: str = "text"
    group: str = "Dokument"
    source: str = "manual"
    required: bool = False
    sensitive: bool = False
    help: str | None = None
    options: tuple[tuple[str, str], ...] = ()
    #: Pole ``list``: klucze pozycji (``{% for m in agenda %}{{ m.text }}``);
    #: pusto = lista samych napisów (``{{ m }}``).
    item_keys: tuple[ItemKey, ...] = ()

    def to_public(self) -> dict[str, Any]:
        data = asdict(self)
        data["options"] = [list(o) for o in self.options]
        data["item_keys"] = [asdict(i) for i in self.item_keys]
        data["source_label"] = SOURCE_LABELS.get(self.source, self.source)
        return data


def _text(value: object, limit: int) -> str:
    return str(value or "").strip()[:limit]


def parse_fields(raw: object) -> list[CustomField]:
    """Lista pól z JSON-a (zapis w bazie albo z formularza). Odrzuca złe klucze,
    powtórki i zastrzeżone nazwy — ``FieldsError`` z opisem."""
    if not isinstance(raw, list):
        raise FieldsError("Lista pól musi być listą.")
    if len(raw) > MAX_FIELDS:
        raise FieldsError(f"Wzór może mieć najwyżej {MAX_FIELDS} pól.")
    out: list[CustomField] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise FieldsError("Każde pole musi mieć klucz i etykietę.")
        key = str(item.get("key") or "").strip()
        if not KEY_RE.match(key):
            raise FieldsError(
                f"Klucz pola „{key[:60]}” jest niepoprawny: małe litery, cyfry, "
                "podkreślenia, najwyżej dwie kropki."
            )
        if key.split(".")[0] in RESERVED_ROOTS:
            raise FieldsError(f"Pole „{key}” wypełnia NEXUS — wybierz inną nazwę.")
        if key in seen:
            raise FieldsError(f"Pole „{key}” jest na liście dwa razy.")
        seen.add(key)
        kind = str(item.get("kind") or "text")
        if kind not in KINDS:
            raise FieldsError(f"Pole „{key}”: nieznany rodzaj „{kind}”.")
        source = str(item.get("source") or "manual")
        if source not in SOURCES:
            source = "manual"
        options = tuple(
            (_text(o[0], 80), _text(o[1], MAX_LABEL))
            for o in (item.get("options") or [])[:MAX_OPTIONS]
            if isinstance(o, (list, tuple)) and len(o) == 2 and str(o[0]).strip()
        )
        if kind == "select" and not options:
            raise FieldsError(f"Pole wyboru „{key}” nie ma opcji.")
        item_keys: list[ItemKey] = []
        if kind == "list":
            for sub in (item.get("item_keys") or [])[:MAX_ITEM_KEYS]:
                sub_key = str((sub or {}).get("key") or "").strip()
                if not ITEM_KEY_RE.match(sub_key):
                    raise FieldsError(f"Lista „{key}”: niepoprawny klucz pozycji.")
                item_keys.append(
                    ItemKey(sub_key, _text(sub.get("label"), MAX_LABEL) or sub_key)
                )
        out.append(
            CustomField(
                key=key,
                label=_text(item.get("label"), MAX_LABEL) or key,
                kind=kind,
                group=_text(item.get("group"), MAX_GROUP) or "Dokument",
                source=source,
                required=bool(item.get("required")),
                sensitive=bool(item.get("sensitive")),
                help=_text(item.get("help"), MAX_HELP) or None,
                options=options,
                item_keys=tuple(item_keys),
            )
        )
    # Ścieżka nie może być jednocześnie polem i „katalogiem” innego pola
    # (``partner`` obok ``partner.nip``) — kontekst miałby dwa znaczenia.
    prefixes = {
        ".".join(k.split(".")[:n]) for k in seen for n in range(1, k.count(".") + 1)
    }
    clash = sorted(prefixes & seen)
    if clash:
        raise FieldsError(f"Pole „{clash[0]}” koliduje z polami „{clash[0]}.*”.")
    return out


def fields_to_json(fields: list[CustomField]) -> list[dict[str, Any]]:
    return [
        {k: v for k, v in f.to_public().items() if k != "source_label"} for f in fields
    ]


# ── Ścieżki dozwolone w szablonie ───────────────────────────────────────────


@dataclass(frozen=True)
class AllowedPaths:
    """Co szablon może przeczytać: pola skalarne, listy z kluczami pozycji
    i to, co liczy kod (``company.*``, ``g.*``, słownie kwot)."""

    scalars: frozenset[str]
    lists: dict[str, frozenset[str]] = field(default_factory=dict)
    #: Pola, które człowiek wypełnia (bez tego, co liczy kod) — do raportu
    #: „pole nieużyte w treści”.
    inputs: frozenset[str] = frozenset()


def allowed_paths(fields: list[CustomField]) -> AllowedPaths:
    scalars: set[str] = {f"company.{k}" for k in COMPANY_PL} | {"document_place"}
    lists: dict[str, frozenset[str]] = {}
    has_gender = False
    for f in fields:
        if f.kind == "list":
            lists[f.key] = frozenset(i.key for i in f.item_keys)
            continue
        scalars.add(f.key)
        if f.kind == "money":
            scalars.add(f.key + MONEY_WORDS_SUFFIX)
        if f.kind == "gender":
            has_gender = True
    if has_gender:
        scalars |= {f"g.{k}" for k in GENDER_FORM_KEYS}
    # „Katalogi” (``partner``) — szablon może zapytać ``{% if partner.phone %}``,
    # ale nie wypisać całego słownika; dlatego tylko pełne ścieżki.
    return AllowedPaths(
        scalars=frozenset(scalars),
        lists=lists,
        inputs=frozenset(f.key for f in fields),
    )


# ── Wartości ────────────────────────────────────────────────────────────────


def parse_money(raw: object) -> Decimal | None:
    if raw is None or raw == "":
        return None
    text = re.sub(r"[\s ]", "", str(raw)).replace("zł", "").replace(",", ".")
    try:
        value = Decimal(text)
    except InvalidOperation:
        return None
    if not value.is_finite() or value < 0 or value > MONEY_MAX:
        return None
    return value.quantize(Decimal("0.01"))


def parse_day(raw: object) -> date | None:
    if isinstance(raw, date):
        return raw
    try:
        return date.fromisoformat(str(raw or "")[:10])
    except ValueError:
        return None


def format_money(value: Decimal) -> str:
    """6200 → „6 200,00” (jak umowa szkoleniowa)."""
    return f"{value:,.2f}".replace(",", " ").replace(".", ",")


def _filled(value: object) -> bool:
    if isinstance(value, list):
        return bool(value)
    if isinstance(value, bool):
        return True
    return value is not None and str(value).strip() != ""


def value_problems(fields: list[CustomField], values: dict[str, Any]) -> list[str]:
    """Braki i złe wartości — etykiety pól dla człowieka (puste = w porządku)."""
    problems: list[str] = []
    for f in fields:
        value = values.get(f.key)
        if not _filled(value):
            if f.required:
                problems.append(f"{f.label}: wymagane")
            continue
        if f.kind == "money" and parse_money(value) is None:
            problems.append(f"{f.label}: niepoprawna kwota")
        elif f.kind == "date" and parse_day(value) is None:
            problems.append(f"{f.label}: niepoprawna data")
        elif f.kind == "email" and not _EMAIL.match(str(value).strip()):
            problems.append(f"{f.label}: niepoprawny adres e-mail")
        elif f.kind == "select" and str(value) not in {o[0] for o in f.options}:
            problems.append(f"{f.label}: wartość spoza listy")
        elif f.kind == "list":
            if not isinstance(value, list) or len(value) > MAX_LIST_ITEMS:
                problems.append(f"{f.label}: najwyżej {MAX_LIST_ITEMS} pozycji")
        elif f.kind in ("text", "gender") and len(str(value)) > MAX_TEXT:
            problems.append(f"{f.label}: za długi tekst")
        elif f.kind == "textarea" and len(str(value)) > MAX_TEXTAREA:
            problems.append(f"{f.label}: za długi tekst")
    return problems


def _scalar(f: CustomField, value: object) -> object:
    if not _filled(value):
        return False if f.kind == "bool" else ""
    if f.kind == "money":
        amount = parse_money(value)
        return format_money(amount) if amount is not None else ""
    if f.kind == "date":
        return pl_date(parse_day(value))
    if f.kind == "bool":
        return bool(value) and str(value).lower() not in ("false", "0", "nie")
    if f.kind == "select":
        return dict(f.options).get(str(value), "")
    limit = MAX_TEXTAREA if f.kind == "textarea" else MAX_TEXT
    return str(value)[:limit]


def _list_items(f: CustomField, value: object) -> list[object]:
    items = value if isinstance(value, list) else []
    keys = [i.key for i in f.item_keys]
    out: list[object] = []
    for item in items[:MAX_LIST_ITEMS]:
        if not keys:
            out.append(str(item if not isinstance(item, dict) else "")[:MAX_TEXT])
            continue
        row = item if isinstance(item, dict) else {}
        out.append({k: str(row.get(k) or "")[:MAX_TEXT] for k in keys})
    return out


def _put(ctx: dict[str, Any], key: str, value: object) -> None:
    *parents, leaf = key.split(".")
    node = ctx
    for part in parents:
        node = node.setdefault(part, {})
    node[leaf] = value


def build_context(
    fields: list[CustomField], values: dict[str, Any], *, language: str = "pl"
) -> dict[str, Any]:
    """Kontekst renderu: same napisy, listy i słowniki — nic poza polami
    z listy i tym, co liczy kod. Brak wartości pola opcjonalnego = pusty napis."""
    ctx: dict[str, Any] = {
        "company": company_party(language),
        "document_place": company_party(language)["place"],
    }
    gender_value: object = None
    for f in fields:
        value = values.get(f.key)
        if f.kind == "list":
            _put(ctx, f.key, _list_items(f, value))
            continue
        _put(ctx, f.key, _scalar(f, value))
        if f.kind == "money":
            amount = parse_money(value)
            words = pln_words_with_fraction(float(amount)) if amount is not None else ""
            _put(ctx, f.key + MONEY_WORDS_SUFFIX, words)
        if f.kind == "gender" and gender_value is None:
            gender_value = value
    if any(f.kind == "gender" for f in fields):
        forms = gender_forms(str(gender_value or ""))
        ctx["g"] = {**forms, **{k.removeprefix("g_"): v for k, v in forms.items()}}
    return ctx


def strip_sensitive(
    fields: list[CustomField], values: dict[str, Any]
) -> dict[str, Any]:
    """Wartości do zapisu w rejestrze — bez pól wrażliwych i spoza listy."""
    keep = {f.key for f in fields if not f.sensitive}
    return {k: v for k, v in values.items() if k in keep}


# ── Dane fikcyjne do „Próbny dokument” ──────────────────────────────────────

_SAMPLE_TEXT: dict[str, str] = {
    "partner.name": "Jan Przykładowy",
    "partner.name_instrumental": "Janem Przykładowym",
    "partner.legal_name": "Przykładowa Firma Jan Przykładowy",
    "partner.company": "Przykładowa Firma Jan Przykładowy",
    "partner.nip": "0000000000",
    "partner.regon": "000000000",
    "partner.business_address": "ul. Testowa 1, 00-001 Warszawa",
    "partner.address": "ul. Testowa 1",
    "partner.postal_city": "00-001 Warszawa",
    "partner.email": "jan.przykladowy@example.com",
    "partner.phone": "+48 500 000 000",
    "client.name": "Klient Przykładowy sp. z o.o.",
}


def sample_values(fields: list[CustomField]) -> dict[str, Any]:
    """Wypełnienie wszystkich pól danymi fikcyjnymi (repo i logi są publiczne)."""
    values: dict[str, Any] = {}
    for f in fields:
        if f.kind == "money":
            values[f.key] = "1234.50"
        elif f.kind == "date":
            values[f.key] = "2026-01-15"
        elif f.kind == "bool":
            values[f.key] = True
        elif f.kind == "gender":
            values[f.key] = "male"
        elif f.kind == "select":
            values[f.key] = f.options[0][0] if f.options else ""
        elif f.kind == "email":
            values[f.key] = "osoba@example.com"
        elif f.kind == "list":
            values[f.key] = [
                {i.key: f"{i.label} {row}" for i in f.item_keys}
                if f.item_keys
                else f"Pozycja {row}"
                for row in (1, 2)
            ]
        else:
            values[f.key] = _SAMPLE_TEXT.get(f.key) or f"[{f.label}]"
    return values
