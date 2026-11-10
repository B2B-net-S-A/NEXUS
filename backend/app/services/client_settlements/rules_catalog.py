"""Stały katalog reguł rozliczenia (roadmapa E1.2).

Każdy klient ma te same rodzaje reguł; Finanse ustawiają poziom (``block`` —
blokuje przyjęcie, ``warn`` — ostrzega, ``off`` — wyłączona) i parametry.
Wartości klienta leżą w ``client_settlement_rule_sets.rules`` jako
``{klucz: {"level": …, "params": {…}}}``. Nieznany klucz w bazie pomijamy
(reguła wycofana z katalogu), brakujący bierze wartości domyślne katalogu.

Etap, w którym reguła zaczyna działać w silniku, stoi przy niej (``stage``):
reguła z późniejszego etapu daje się ustawić, ale silnik E1 jej nie sprawdza.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

LEVELS: tuple[str, ...] = ("block", "warn", "off")
PARAM_MAX = 200


@dataclass(frozen=True)
class ParamField:
    key: str
    label: str
    suffix: str | None = None


@dataclass(frozen=True)
class Rule:
    key: str
    name: str
    level: str
    stage: str
    params: Mapping[str, str] = field(default_factory=dict)
    fields: tuple[ParamField, ...] = ()
    hint: str | None = None


@dataclass(frozen=True)
class Section:
    key: str
    title: str
    rules: tuple[Rule, ...]


SECTIONS: tuple[Section, ...] = (
    Section(
        "proof",
        "Dowód pracy",
        (
            Rule(
                "proof.signed_pdf",
                "PDF z podpisem elektronicznym klienta",
                "block",
                "E2",
                {"issuer": ""},
                (ParamField("issuer", "wystawca certyfikatu"),),
            ),
            Rule(
                "proof.excel_with_mail",
                "Excel z mailem akceptującym usługi, gdy brak podpisu",
                "warn",
                "E2",
                {"domain": ""},
                (ParamField("domain", "domena"),),
            ),
            Rule("proof.month", "RCP za rozliczany miesiąc", "block", "E2"),
            Rule(
                "proof.name_match",
                "Nazwisko na RCP i fakturze takie jak w kontrakcie",
                "warn",
                "E2",
            ),
        ),
    ),
    Section(
        "order",
        "Zamówienie i MD",
        (
            Rule(
                "order.no_md_holds_invoice",
                "Brak MD na zamówieniu wstrzymuje fakturę",
                "block",
                "E1",
            ),
            Rule(
                "order.md_visible",
                "Zużycie MD widoczne w panelu konsultanta",
                "warn",
                "E3",
            ),
            Rule(
                "order.charge_on_accept",
                "Zejście z zamówienia po przyjęciu RCP",
                "block",
                "E1",
            ),
            Rule(
                "order.onboarding_md",
                "MD wdrożeniowe nowego konsultanta",
                "off",
                "E1",
                {"md": "2", "item": "_onbording"},
                (ParamField("md", "", "MD za 0 zł"), ParamField("item", "pozycja")),
                "Nie schodzą z zamówienia; reszta przechodzi na kolejny miesiąc.",
            ),
            Rule(
                "order.pool",
                "Pula nowego zamówienia",
                "off",
                "E5",
                {"md": ""},
                (ParamField("md", "", "MD na rok"),),
                "Proporcjonalnie przy starcie w trakcie roku.",
            ),
        ),
    ),
    Section(
        "fields",
        "Pola i sumy",
        (
            Rule(
                "fields.product_id",
                "Product ID",
                "off",
                "E2",
                {"allowed": ""},
                (ParamField("allowed", "dozwolone też"),),
            ),
            Rule("fields.cmdb", "Kod CMDB", "off", "E2"),
            Rule(
                "fields.md_hours",
                "Sumy MD zgodne z godzinami",
                "block",
                "E2",
                {"hours": "8"},
                (ParamField("hours", "1 MD =", "h"),),
            ),
            Rule(
                "fields.day_limit",
                "Limit godzin w jednym dniu",
                "block",
                "E2",
                {"hours": "24"},
                (ParamField("hours", "", "h z nadgodzinami i dyżurem"),),
            ),
        ),
    ),
    Section(
        "extra",
        "Nadgodziny i dyżury",
        (
            Rule("extra.mail_accept", "Mail akceptujący nadgodziny", "block", "E2"),
            Rule("extra.mail_before", "Mail wysłany przed pracą", "warn", "E2"),
            Rule(
                "extra.multiplier",
                "Mnożnik w fakturze i zużyciu MD",
                "warn",
                "E1",
                {"pct": "100"},
                (ParamField("pct", "", "%"),),
                "Konsultant nie widzi mnożnika.",
            ),
            Rule("extra.on_call", "Dyżur", "off", "E2"),
        ),
    ),
    Section(
        "travel",
        "Delegacje",
        (
            Rule(
                "travel.mail_before",
                "Mail przed wyjazdem: miejsce, termin, koszt",
                "off",
                "E2",
            ),
            Rule(
                "travel.cities",
                "Miasta klienta",
                "off",
                "E2",
                {"cities": ""},
                (ParamField("cities", ""),),
            ),
            Rule(
                "travel.cost_invoices",
                "Faktury kosztów zgodne z kwotami w RCP",
                "off",
                "E2",
            ),
        ),
    ),
    Section(
        "contractor_invoice",
        "Faktura kontraktora",
        (
            Rule("ci.ksef", "Przez KSeF, data wpływu = numer KSeF", "block", "E4"),
            Rule(
                "ci.buyer_nip",
                "NIP nabywcy",
                "block",
                "E4",
                {"nip": ""},
                (ParamField("nip", ""),),
            ),
            Rule(
                "ci.amount",
                "Kwota równa wyliczeniu z RCP",
                "block",
                "E4",
                {"tolerance": "0,00"},
                (ParamField("tolerance", "tolerancja", "zł"),),
            ),
            Rule(
                "ci.payment_days",
                "Termin płatności",
                "warn",
                "E3",
                {"days": "14"},
                (ParamField("days", "", "dni od numeru KSeF"),),
            ),
        ),
    ),
    Section(
        "client_invoice",
        "Faktura do klienta",
        (
            Rule(
                "cl.attachment_name",
                "RCP nazwane numerem KSeF faktury, reszta w tym samym mailu",
                "off",
                "E5",
            ),
            Rule(
                "cl.integration_costs",
                "Koszty integracji na koszt B2B, zgoda DL",
                "off",
                "E5",
                {"limit": ""},
                (ParamField("limit", "do", "zł na konsultanta na rok"),),
            ),
            Rule(
                "cl.overtime_item",
                "Nadgodziny osobną pozycją",
                "off",
                "E5",
                {"suffix": "_nadgodziny"},
                (ParamField("suffix", "przyrostek"),),
            ),
            Rule(
                "cl.estimate",
                "Estymacja: RCP z planem dni przed końcem miesiąca",
                "off",
                "E5",
                {"months": "12"},
                (ParamField("months", "miesiące", "np. 12"),),
                "Plan przyjmujemy po przyjęciu poprzedniego miesiąca, nie ponad resztę puli; "
                "mniej przepracowane schodzi na kolejnej fakturze.",
            ),
        ),
    ),
)

RULES: dict[str, Rule] = {
    rule.key: rule for section in SECTIONS for rule in section.rules
}


class RulesError(ValueError):
    """Zapis reguł z niepoprawną wartością (komunikat po polsku dla Finansów)."""


def effective(stored: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
    """Reguły klienta na miesiąc: katalog z nadpisaniami z bazy.

    ``stored is None`` (klient bez reguł) = wszystko wyłączone: NEXUS przyjmuje
    pliki bez kontroli, a silnik liczy tylko MD i kwoty.
    """

    result: dict[str, dict[str, Any]] = {}
    for key, rule in RULES.items():
        if stored is None:
            result[key] = {"level": "off", "params": dict(rule.params)}
            continue
        raw = stored.get(key) if isinstance(stored, Mapping) else None
        level = raw.get("level") if isinstance(raw, Mapping) else None
        params = raw.get("params") if isinstance(raw, Mapping) else None
        merged = dict(rule.params)
        if isinstance(params, Mapping):
            merged.update({k: str(v) for k, v in params.items() if k in rule.params})
        result[key] = {
            "level": level if level in LEVELS else rule.level,
            "params": merged,
        }
    return result


def clean_for_save(items: list[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Wejście z ekranu → słownik do zapisu. Nieznany klucz albo poziom = błąd."""

    out: dict[str, dict[str, Any]] = {}
    for item in items:
        key = item.get("key")
        rule = RULES.get(key) if isinstance(key, str) else None
        if rule is None:
            raise RulesError("Nieznana reguła rozliczenia.")
        level = item.get("level")
        if level not in LEVELS:
            raise RulesError(f"Nieznany poziom reguły „{rule.name}”.")
        params_in = item.get("params") or {}
        if not isinstance(params_in, Mapping):
            raise RulesError(f"Parametry reguły „{rule.name}” mają zły format.")
        params: dict[str, str] = {}
        for name in rule.params:
            value = (
                str(params_in.get(name, rule.params[name])).replace("\x00", "").strip()
            )
            if len(value) > PARAM_MAX:
                raise RulesError(f"Za długa wartość w regule „{rule.name}”.")
            params[name] = value
        out[rule.key] = {"level": level, "params": params}
    return out


def as_screen(rules: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Sekcje dla ekranu „Reguły klienta”."""

    return [
        {
            "key": section.key,
            "title": section.title,
            "rules": [
                {
                    "key": rule.key,
                    "name": rule.name,
                    "level": rules[rule.key]["level"],
                    "params": dict(rules[rule.key]["params"]),
                    "param_fields": [
                        {"key": f.key, "label": f.label, "suffix": f.suffix}
                        for f in rule.fields
                    ],
                    "hint": rule.hint,
                    "stage": rule.stage,
                }
                for rule in section.rules
            ],
        }
        for section in SECTIONS
    ]
