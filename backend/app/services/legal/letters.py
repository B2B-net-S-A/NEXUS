"""Pismo na stronie kontraktu (asystent prawny, część F) — czyste funkcje.

Decyzje Artura 25.11.2026 (``docs/asystent-prawny-plan.md``): asystent działa
w tle strony kontraktu, nic nie wychodzi samo, każdy cytat sprawdza kod,
terminy, daty, kwoty słownie i formy Pan/Pani liczy kod, a dane osób idą do
modelu wyłącznie jako znaczniki.

Rodzaje pisma (``LETTER_KINDS``):

* **wzór** — wypowiedzenie przez nas, porozumienie o rozwiązaniu, cofnięcie
  wypowiedzenia: kod wypełnia istniejący wzór Generatora
  (``templates/documents/<typ>_pl``), model nie pisze ani zdania;
* **model** — odpowiedź na wypowiedzenie Partnera, nota/wezwanie do zapłaty
  kary umownej, pismo do klienta: zdania pisze ``assistant.draft``
  (``legal_assistant``, F56) ze znacznikami, nagłówek, adresata, daty
  i podpis składa kod.

Termin liczy ``deadlines`` z reguły PODPISANEJ umowy (``termination_terms``
z Dokumentów kontraktu), nigdy ze wzoru. Reguła: ``docs/claude/asystent-prawny/``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional, Sequence

from app.services.b2b_contract_generator.gender import is_female
from app.services.contract_document_text.termination import (
    DELIVERY_EMAIL,
    DELIVERY_IN_PERSON,
    DELIVERY_POST,
    FORM_DOCUMENTARY,
    FORM_ELECTRONIC,
    FORM_WRITTEN,
    PERIOD_DAYS,
    PERIOD_END_OF_MONTH,
    PERIOD_FROM_NEXT_MONTH,
)
from app.services.legal import deadlines
from app.services.legal.pseudonymize import Entity

SOURCE_TEMPLATE = "template"
SOURCE_MODEL = "model"

KIND_NOTICE_REPLY = "notice_reply"
KIND_TERMINATION_NOTICE = "termination_notice"
KIND_TERMINATION_AGREEMENT = "termination_agreement"
KIND_NOTICE_WITHDRAWAL = "notice_withdrawal"
KIND_PENALTY_NOTE = "penalty_note"
KIND_CLIENT_LETTER = "client_letter"


@dataclass(frozen=True)
class LetterKind:
    key: str
    label: str
    source: Literal["template", "model"]
    recipient: Literal["partner", "client"]
    #: Rodzaj szkicu fundamentu (``assistant.KINDS``) dla pism modelu.
    draft_kind: Optional[str] = None
    #: Typ dokumentu z rejestru Generatora (``b2b_documents.registry``) dla wzoru.
    template: Optional[str] = None
    #: Pismo ma sens tylko po wypowiedzeniu złożonym przez Partnera.
    needs_partner_notice: bool = False
    #: Czy zatwierdzenie zamyka zadanie „szkic odpowiedzi na wypowiedzenie czeka”.
    closes_notice_task: bool = False


LETTER_KINDS: tuple[LetterKind, ...] = (
    LetterKind(
        KIND_NOTICE_REPLY,
        "Odpowiedź na wypowiedzenie Partnera",
        SOURCE_MODEL,
        "partner",
        draft_kind="reply",
        needs_partner_notice=True,
        closes_notice_task=True,
    ),
    LetterKind(
        KIND_TERMINATION_NOTICE,
        "Wypowiedzenie umowy przez B2B.net",
        SOURCE_TEMPLATE,
        "partner",
        template="termination_notice",
    ),
    LetterKind(
        KIND_TERMINATION_AGREEMENT,
        "Porozumienie o rozwiązaniu umowy",
        SOURCE_TEMPLATE,
        "partner",
        template="termination_agreement",
        closes_notice_task=True,
    ),
    LetterKind(
        KIND_NOTICE_WITHDRAWAL,
        "Cofnięcie wypowiedzenia",
        SOURCE_TEMPLATE,
        "partner",
        template="notice_withdrawal",
        needs_partner_notice=True,
        closes_notice_task=True,
    ),
    LetterKind(
        KIND_PENALTY_NOTE,
        "Nota / wezwanie do zapłaty kary umownej",
        SOURCE_MODEL,
        "partner",
        draft_kind="letter",
    ),
    LetterKind(
        KIND_CLIENT_LETTER,
        "Pismo do klienta",
        SOURCE_MODEL,
        "client",
        draft_kind="letter",
    ),
)
KINDS_BY_KEY: dict[str, LetterKind] = {kind.key: kind for kind in LETTER_KINDS}
LETTER_KIND_KEYS: tuple[str, ...] = tuple(KINDS_BY_KEY)

#: Domyślny termin zapłaty kary w nocie (dni od daty pisma, art. 115 KC).
PENALTY_PAYMENT_DAYS = 7


# ── termin z reguły podpisanej umowy ────────────────────────────────────────


@dataclass(frozen=True)
class NoticeRule:
    """Część reguły wypowiedzenia z ``TerminationTerms`` potrzebna pismu."""

    period_kind: str
    period_months: Optional[int]
    period_days: Optional[int]
    forms: tuple[str, ...] = ()
    under_nullity: bool = False
    delivery: tuple[str, ...] = ()
    #: Oznaczenie zapisu o okresie („§ 8 ust. 2”) i całe odwołanie ze źródła.
    period_ref: Optional[str] = None
    period_source_ref: Optional[str] = None
    form_source_ref: Optional[str] = None


def notice_deadline(
    rule: NoticeRule, delivered_on: date
) -> tuple[Optional[deadlines.Deadline], Optional[str]]:
    """Dzień rozwiązania umowy z reguły podpisanej umowy albo powód, czemu go nie liczymy."""
    months, days = rule.period_months, rule.period_days
    if rule.period_kind == PERIOD_END_OF_MONTH:
        if months:
            return deadlines.notice_end_of_month(delivered_on, months), None
        if days:
            return deadlines.notice_days_end_of_month(delivered_on, days), None
    if rule.period_kind == PERIOD_FROM_NEXT_MONTH and months:
        return deadlines.notice_from_next_month(delivered_on, months), None
    if rule.period_kind == PERIOD_DAYS and days:
        return deadlines.term_end(delivered_on, days, deadlines.UNIT_DAYS), None
    return None, (
        "Umowa podaje okres, którego NEXUS nie umie policzyć pewnie — dzień "
        "rozwiązania wpisz sam."
    )


_GENITIVE = {
    1: "jednego",
    2: "dwóch",
    3: "trzech",
    4: "czterech",
    5: "pięciu",
    6: "sześciu",
}


def period_label(rule: NoticeRule) -> str:
    """Okres po polsku do pisma i nagłówka: „1 miesiąc, liczony od kolejnego miesiąca”."""
    if rule.period_months:
        length = deadlines.months_word(rule.period_months)
    elif rule.period_days:
        length = f"{rule.period_days} dni"
    else:
        return "okres z umowy"
    if rule.period_kind == PERIOD_END_OF_MONTH:
        return f"{length} ze skutkiem na koniec miesiąca kalendarzowego"
    if rule.period_kind == PERIOD_FROM_NEXT_MONTH:
        return f"{length}, liczony od kolejnego miesiąca"
    return length


def period_genitive(rule: NoticeRule) -> Optional[str]:
    """Okres w dopełniaczu do wzoru wypowiedzenia („z zachowaniem okresu wypowiedzenia …”)."""
    if rule.period_months:
        months = rule.period_months
        word = _GENITIVE.get(months)
        unit = "miesiąca" if months == 1 else "miesięcy"
        length = f"{months} ({word}) {unit}" if word else f"{months} {unit}"
    elif rule.period_days:
        length = f"{rule.period_days} dni"
    else:
        return None
    if rule.period_kind == PERIOD_END_OF_MONTH:
        return f"{length} ze skutkiem na koniec miesiąca kalendarzowego"
    if rule.period_kind == PERIOD_FROM_NEXT_MONTH:
        return f"{length} liczonego od kolejnego miesiąca"
    return length


_SECTION_REF = re.compile(r"§\s*\d+[A-Za-z]?(?:\s+(?:ust\.|pkt|lit\.)\s*\S+)*\s*$")


def bare_ref(source_ref: Optional[str]) -> Optional[str]:
    """„umowa 12/2025 § 8 ust. 2” → „§ 8 ust. 2” (do zdania „zgodnie z § 8 ust. 2 umowy”)."""
    match = _SECTION_REF.search(source_ref or "")
    return match.group(0).strip() if match else None


# ── forma wypowiedzenia ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class FormWarning:
    """Ostrzeżenie o formie: pytanie (blokuje zatwierdzenie) albo informacja."""

    level: Literal["question", "info"]
    title: str
    message: str
    clause_ref: Optional[str] = None
    document_name: Optional[str] = None
    actions: tuple[str, ...] = ()


def strict_form(rule: NoticeRule) -> bool:
    """Umowa wymaga oryginału: forma pisemna bez dokumentowej albo doręczenie bez maila."""
    written_only = (
        FORM_WRITTEN in rule.forms
        and FORM_DOCUMENTARY not in rule.forms
        and FORM_ELECTRONIC not in rule.forms
    )
    paper_delivery = bool(rule.delivery) and DELIVERY_EMAIL not in rule.delivery
    return written_only or paper_delivery


def _form_phrase(rule: NoticeRule) -> str:
    parts = []
    if FORM_WRITTEN in rule.forms:
        parts.append("na piśmie")
    if rule.under_nullity:
        parts.append("pod rygorem nieważności")
    ways = {
        DELIVERY_IN_PERSON: "osobiście",
        DELIVERY_POST: "pocztą",
        DELIVERY_EMAIL: "mailem",
    }
    delivery = [ways[w] for w in rule.delivery if w in ways]
    if delivery:
        parts.append("doręczonego " + " albo ".join(delivery))
    return ", ".join(parts) or "w formie z umowy"


def form_warning(
    kind: str,
    rule: Optional[NoticeRule],
    *,
    notice_document: Optional[tuple[str, date]] = None,
    original_confirmed: bool = False,
) -> Optional[FormWarning]:
    """Ostrzeżenie o formie dla rodzaju pisma (``None`` = umowa nie wymaga oryginału).

    Odpowiedź na wypowiedzenie Partnera: gdy umowa wymaga formy pisemnej albo
    doręczenia osobiście lub pocztą, a wypowiedzenie jest tylko plikiem
    w Dokumentach — pytanie o oryginał lub podpis kwalifikowany i propozycja
    porozumienia z tą samą datą. Do odpowiedzi pytanie blokuje „Zatwierdzam”.
    """
    if rule is None or not strict_form(rule):
        return None
    clause = rule.form_source_ref or rule.period_source_ref
    if kind == KIND_NOTICE_REPLY:
        if original_confirmed:
            return None
        if notice_document is not None:
            name, added = notice_document
            seen = (
                f"W Dokumentach jest plik „{name}” z {added:%d.%m.%Y}. Jeśli to skan "
                "albo mail, a nie oryginał ani dokument z kwalifikowanym podpisem "
                "elektronicznym, wypowiedzenie może być nieskuteczne"
            )
        else:
            name = None
            seen = (
                "W Dokumentach kontraktu nie ma pliku wypowiedzenia. Jeśli Partner "
                "przysłał je tylko mailem, wypowiedzenie może być nieskuteczne"
            )
        return FormWarning(
            level="question",
            title="Zanim wyślesz: forma wypowiedzenia",
            message=(
                f"Umowa wymaga wypowiedzenia {_form_phrase(rule)}"
                + (f" ({clause})" if clause else "")
                + f". {seen} — bezpieczniej zawrzeć porozumienie o rozwiązaniu "
                "z tą samą datą."
            ),
            clause_ref=clause,
            document_name=name,
            actions=("confirm_original", "switch_to_agreement"),
        )
    if kind == KIND_TERMINATION_NOTICE:
        return FormWarning(
            level="info",
            title="Forma wypowiedzenia",
            message=(
                f"Umowa wymaga wypowiedzenia {_form_phrase(rule)}"
                + (f" ({clause})" if clause else "")
                + ". Mail z plikiem nie wystarczy: wyślij podpisany oryginał albo "
                "dokument z kwalifikowanym podpisem elektronicznym."
            ),
            clause_ref=clause,
        )
    return None


# ── formy Pan/Pani i dane do znaczników ─────────────────────────────────────

_MALE_A = frozenset({"kuba", "barnaba", "bonawentura", "kosma", "jarema", "dyzma"})


def partner_female(gender: Optional[str], full_name: str) -> bool:
    """Płeć z umowy B2B z Generatora, a bez niej z imienia (jak umowa szkolenia)."""
    if (gender or "").strip():
        return is_female(gender)
    words = (full_name or "").split()
    first = words[0].lower() if words else ""
    return first.endswith("a") and first not in _MALE_A


def courtesy_entities(female: bool) -> list[Entity]:
    """Zwrot i formy Pan/Pani jako znaczniki — model ich nie odmienia, liczy je kod."""
    forms = (
        ("Szanowna Pani", "Pani", "Pani", "Pani", "Panią")
        if female
        else ("Szanowny Panie", "Pan", "Pana", "Panu", "Panem")
    )
    labels = (
        "ZWROT",
        "PAN_MIANOWNIK",
        "PAN_DOPELNIACZ",
        "PAN_CELOWNIK",
        "PAN_NARZEDNIK",
    )
    return [Entity(label, value) for label, value in zip(labels, forms)]


CLIENT_COURTESY: tuple[Entity, ...] = (Entity("ZWROT", "Szanowni Państwo"),)


def amount_text(amount: float, words: str) -> str:
    """„5 000,00 zł (słownie: pięć tysięcy złotych)”."""
    whole = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{whole} zł (słownie: {words})"


# ── polecenia dla modelu (piszę kod, wartości tylko jako znaczniki) ─────────


def _token_rules(to_partner: bool) -> str:
    address = (
        "Do adresata zwracaj się wyłącznie znacznikami form grzecznościowych "
        "z listy (PAN_MIANOWNIK, PAN_DOPELNIACZ, PAN_CELOWNIK, PAN_NARZEDNIK) — "
        "nigdy „Pan”, „Pani” ani samodzielnie odmienionym nazwiskiem."
        if to_partner
        else "Do adresata zwracaj się formą „Państwo”."
    )
    return (
        f"Zacznij od znacznika [ZWROT] i przecinka. {address} Daty, okres "
        "i kwoty wyłącznie znacznikami z listy. Bez miejsca, daty, adresata, "
        "tematu i podpisu — dopisze je NEXUS."
    )


def model_instruction(
    kind: str,
    *,
    has_end: bool,
    has_period: bool,
    user_text: str = "",
) -> str:
    """Polecenie dla ``assistant.draft`` — zdania o faktach ze znacznikami."""
    extra = (user_text or "").strip()
    if kind == KIND_NOTICE_REPLY:
        lines = [
            "Napisz do Partnera potwierdzenie otrzymania jego wypowiedzenia umowy "
            "o współpracy B2B, złożonego [DATA_ZLOZENIA].",
        ]
        if has_period and has_end:
            lines.append(
                "Napisz, że zgodnie z postanowieniem umowy o okresie wypowiedzenia "
                "(podaj jego oznaczenie ze źródeł) okres wynosi [OKRES_WYPOWIEDZENIA], "
                "więc umowa rozwiąże się z dniem [DATA_ROZWIAZANIA]."
            )
        else:
            lines.append(
                "Dnia rozwiązania nie podawaj — NEXUS nie policzył go z umowy; "
                "napisz, że potwierdzimy go osobno."
            )
        lines.append(
            "Poproś o świadczenie usług do dnia rozwiązania na dotychczasowych "
            "zasadach i o zwrot powierzonego sprzętu, jeśli umowa albo umowa "
            "ramowa klienta w źródłach o tym mówi. Podziękuj za współpracę."
        )
    elif kind == KIND_PENALTY_NOTE:
        lines = [
            "Napisz do Partnera notę obciążeniową z wezwaniem do zapłaty kary "
            "umownej w kwocie [KWOTA_KARY] w terminie do [TERMIN_ZAPLATY].",
            "Podstawę podaj wyłącznie z postanowienia umowy o karze umownej ze "
            "źródeł (z jego oznaczeniem). Gdy w źródłach nie ma takiego "
            "postanowienia, napisz zdanie bez podstawy.",
        ]
    elif kind == KIND_CLIENT_LETTER:
        lines = [
            "Napisz pismo do klienta [KLIENT] w sprawie współpracy konsultanta "
            "[PARTNER] (umowa B2B nr [NUMER_UMOWY]).",
            "Powołuj się na umowę ramową klienta i przepisy tylko ze źródeł.",
        ]
    else:
        raise ValueError(f"Rodzaj {kind!r} wypełnia wzór, nie model.")
    lines.append(_token_rules(kind != KIND_CLIENT_LETTER))
    if extra:
        lines.append(f"Prośba osoby piszącej: {extra}")
    return "\n".join(lines)


# ── tekst pisma ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Recipient:
    kind: Literal["partner", "client"]
    name: str
    lines: tuple[str, ...] = ()
    email: Optional[str] = None
    candidate_id: Optional[int] = None


def compose_letter(
    *,
    place: str,
    on_date: date,
    recipient: Recipient,
    subject: str,
    body: str,
    signature: str,
) -> str:
    """Pismo zwykłym tekstem: miejsce i data, adresat, „Dotyczy”, treść, podpis."""
    head = [f"{place}, {deadlines.polish_date(on_date)}", ""]
    address = [line for line in (recipient.name, *recipient.lines) if line]
    parts = [
        *head,
        *address,
        "",
        f"Dotyczy: {subject}",
        "",
        body.strip(),
        "",
        "Z poważaniem",
        signature,
    ]
    return "\n".join(parts).strip() + "\n"


_BLOCK_TAGS = re.compile(r"</?(?:p|h1|h2|h3|li|div|br|tr)\b[^>]*>", re.I)
_TAGS = re.compile(r"<[^>]+>")
_ENTITIES = {"&nbsp;": " ", "&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"'}


def html_to_text(html: str) -> str:
    """Podgląd HTML wzoru → zwykły tekst akapitami (do panelu i okna maila)."""
    text = _BLOCK_TAGS.sub("\n", html or "")
    text = _TAGS.sub("", text)
    for entity, value in _ENTITIES.items():
        text = text.replace(entity, value)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    paragraphs = [line for line in lines if line]
    return "\n\n".join(paragraphs) + ("\n" if paragraphs else "")


def placeholder_issues(text: str) -> list[str]:
    """Wzór z „…” w miejscu danych: czego brakuje, zanim pismo da się zatwierdzić."""
    count = text.count("…")
    if not count:
        return []
    return [
        f"We wzorze brakuje danych ({count} × „…”) — uzupełnij je na profilu "
        "kandydata albo w Generatorze, zanim zatwierdzisz pismo."
    ]


@dataclass(frozen=True)
class Fact:
    label: str
    value: str
    note: Optional[str] = None
    tone: Literal["ok", "warn", "plain"] = "plain"


@dataclass(frozen=True)
class DeadlineFacts:
    facts: tuple[Fact, ...]
    steps: tuple[str, ...]
    end: Optional[date]
    reason: Optional[str] = None


def deadline_facts(
    rule: Optional[NoticeRule],
    delivered_on: Optional[date],
    *,
    recorded_last_day: Optional[date] = None,
    rule_reason: Optional[str] = None,
) -> DeadlineFacts:
    """Fakty do nagłówka panelu: złożone, okres, rozwiązanie (z porównaniem z NEXUSEM)."""
    facts: list[Fact] = []
    if delivered_on is not None:
        facts.append(Fact("Złożone", f"{delivered_on:%d.%m.%Y}"))
    if rule is None:
        return DeadlineFacts(
            tuple(facts),
            (),
            None,
            rule_reason
            or "Nie odczytano okresu wypowiedzenia z podpisanej umowy — termin policzy człowiek.",
        )
    facts.append(Fact("Okres", period_label(rule), rule.period_source_ref))
    if delivered_on is None:
        return DeadlineFacts(
            tuple(facts), (), None, "Podaj dzień złożenia wypowiedzenia."
        )
    deadline, reason = notice_deadline(rule, delivered_on)
    if deadline is None:
        return DeadlineFacts(tuple(facts), (), None, reason)
    note: Optional[str] = None
    tone: Literal["ok", "warn", "plain"] = "plain"
    if recorded_last_day is not None:
        if recorded_last_day == deadline.end:
            note, tone = "zgodne z NEXUSEM", "ok"
        else:
            note = f"w NEXUSIE zapisano {recorded_last_day:%d.%m.%Y}"
            tone = "warn"
    facts.append(Fact("Rozwiązanie", f"{deadline.end:%d.%m.%Y}", note, tone))
    return DeadlineFacts(tuple(facts), deadline.steps, deadline.end)


@dataclass(frozen=True)
class ApprovalState:
    blocked: bool
    reasons: tuple[str, ...] = field(default_factory=tuple)


def approval_state(
    *,
    check_statuses: Sequence[str],
    issues: Sequence[str],
    warning: Optional[FormWarning],
    has_text: bool,
) -> ApprovalState:
    """Czy „Zatwierdzam” jest zablokowane i dlaczego (cytat bez pokrycia, pytanie o formę …)."""
    reasons: list[str] = []
    bad = sum(1 for status in check_statuses if status != "ok")
    if bad:
        reasons.append(
            f"{bad} {'cytat nie ma' if bad == 1 else 'cytaty nie mają'} pokrycia w źródłach."
        )
    reasons.extend(issues)
    if warning is not None and warning.level == "question":
        reasons.append("Odpowiedz na pytanie o formę wypowiedzenia.")
    if not has_text:
        reasons.append("Pismo nie ma treści.")
    return ApprovalState(bool(reasons), tuple(reasons))
