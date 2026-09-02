"""Deklaracje polityk odczytu PDF zamówienia per klient.

Każdy wpis mówi trzy rzeczy: *u kogo* (bramka po ``client_id`` z env, opcjonalnie
plus kanoniczne ID produkcyjne), *jak zmienia wywołanie parsera* (dokument
jednoosobowy bez nazwiska, domyślna jednostka stawki) i *co robi z wynikiem*
(funkcja z ``order_pdf_parser``). Kolejność i wykluczenia są tu danymi, a nie
kolejnością ``if``-ów w routerze.

Bramka po ID, nie po nazwie — powód powtarza się przy każdej polityce, więc
zapisany raz: ``Client.name`` nadpisuje import z Traffita, a klient bywa
RODZINĄ rekordów (BNP: „BNP Paribas S.A. Oddział w Polsce" i „BNP Paribas Bank
Polska" to dwa podmioty z dwoma NIP-ami, patrz ``GET /api/admin/client-mixups``)
albo ma duplikat wiersza (e-Zdrowie). Podciąg „nordea bank abp" w wolnym tekście
przestawał trafiać po jednej edycji nazwy u źródła — a wtedy parser zwracał numer
umowy ramowej jako numer zamówienia, czyli dokładnie to, przed czym reguła
chroni, tylko bez żadnego sygnału. Odwrotnie też: dowolny nowy klient z tym
podciągiem w ``legal_name`` dostawałby politykę bez niczyjej decyzji.

Env czytane z ``os.environ`` przy KAŻDYM wywołaniu, nie z ``Settings`` i nie przy
imporcie: to bramka jednego routera, a nie kontrakt współdzielony z frontem
(tamte listy — ``MULTI_CONSULTANT_ORDER_CLIENT_IDS``, ``COST_ORDER_CLIENT_IDS`` —
wychodzą do UI przez ``ClientSafeResponse``), a testy przełączają ją
``monkeypatch.setenv`` między wywołaniami.

**Pusta lista = polityka wyłączona dla każdego klienta (fail-closed).** Wyjątek:
Orlen i PFRON mają kanoniczne ID produkcyjne zweryfikowane w rejestrze przed
wdrożeniem — env pozwala dopisać kontrolowany duplikat w innym środowisku, nie
rozlewa heurystyki na klientów o podobnej nazwie.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.services import order_pdf_parser as parser
from app.services.order_pdf_parser import OrderExtraction


@dataclass(frozen=True)
class PolicyContext:
    """To, co polityka może potrzebować poza samym wynikiem odczytu."""

    document_text: str
    target_consultant: Optional[str] = None
    target_given_names: Optional[str] = None


PolicyFn = Callable[[OrderExtraction, PolicyContext], OrderExtraction]


@dataclass(frozen=True)
class OrderClientPolicy:
    """Jedna reguła klientowa: bramka + wpływ na parser + transformacja wyniku."""

    key: str
    #: Nazwa, którą widzi operator w ``client_policy`` odpowiedzi. Testy pinują
    #: te stringi — zmiana nazwy jest zmianą kontraktu API.
    display_name: str
    #: CSV ``client_id`` w Coolify. Pusta → polityka nieaktywna (fail-closed).
    env_var: str
    apply: PolicyFn
    #: Kolejność stosowania (rosnąco). Erste ma najwyższą, bo przelicza kwotę
    #: ustaloną przez polityki wyżej — odwrotna kolejność po cichu nie
    #: przeliczyłaby nic.
    order: int
    #: Produkcyjne ID, które są objęte polityką niezależnie od env (Orlen, PFRON).
    canonical_client_ids: frozenset[int] = frozenset()
    #: Dokument jest z definicji JEDNOOSOBOWY i nie zawiera nazwiska — parser
    #: dostaje sam tekst (bez osoby docelowej), a bramka bezpieczeństwa matchera
    #: jest pomijana, bo cały dokument JEST pozycją jednej osoby (BNP).
    single_consultant_document: bool = False
    #: Klient deklaruje stawkę zawsze w tej jednostce. Podawane matcherowi już
    #: przy parsowaniu: inaczej fail-closed matcher wyczyściłby poprawną kwotę,
    #: gdy model odczytał wiersz osoby, ale pominął sam token jednostki.
    rate_unit_default: Optional[str] = None
    #: Polityka działa wyłącznie po matcherze, bo nie może zgadywać tożsamości
    #: konsultanta (Orlen: dwie pozycje tej samej osoby tylko przy identycznej
    #: stawce). Bez osoby docelowej nie jest stosowana ani raportowana.
    requires_target: bool = False
    #: Klucze polityk AKTYWNYCH u klienta, które wyłączają tę (Erste ustępuje
    #: PFRON-owi, bo PFRON sam wykonuje brutto→netto).
    suppressed_by: frozenset[str] = field(default_factory=frozenset)


def client_ids_from_env(env_name: str) -> frozenset[int]:
    """CSV ``client_id`` ze zmiennej środowiskowej bramki polityki.

    Wpisy nienumeryczne są POMIJANE, nie wysadzają requestu: literówka w
    zmiennej środowiskowej ma wyłączyć politykę jednemu klientowi, a nie
    położyć odczyt PDF-a wszystkim.
    """
    ids: set[int] = set()
    for chunk in os.environ.get(env_name, "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            continue
    return frozenset(ids)


# ── Adaptery na istniejące ciała polityk ─────────────────────────────────────
# Ciała zostają w ``order_pdf_parser`` (razem z ich testami jednostkowymi);
# adaptery tylko ujednolicają sygnaturę do ``(result, ctx)``.


def _nordea(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.enforce_nordea_order_number(result, ctx.document_text)


def _bank_pocztowy(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_bank_pocztowy_order_policy(result, ctx.document_text)


def _credit_agricole(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_credit_agricole_order_policy(result, ctx.document_text)


def _bnp(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_bnp_order_policy(result, ctx.document_text)


def _orlen(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_orlen_order_policy(
        result,
        ctx.document_text,
        consultant_name=ctx.target_consultant,
        consultant_given_names=ctx.target_given_names,
    )


def _pfron(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_pfron_order_policy(result, ctx.document_text)


def _erste(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_erste_order_policy(result, ctx.document_text)


# ── Rejestr ──────────────────────────────────────────────────────────────────

POLICIES: tuple[OrderClientPolicy, ...] = (
    OrderClientPolicy(
        key="nordea",
        display_name="Nordea",
        env_var="NORDEA_ORDER_NUMBER_CLIENT_IDS",
        apply=_nordea,
        order=10,
    ),
    OrderClientPolicy(
        key="bank_pocztowy",
        display_name="Bank Pocztowy",
        env_var="BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_bank_pocztowy,
        order=20,
    ),
    OrderClientPolicy(
        key="credit_agricole",
        display_name="Credit Agricole",
        env_var="CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_credit_agricole,
        order=30,
    ),
    OrderClientPolicy(
        key="bnp",
        display_name="BNP",
        env_var="BNP_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_bnp,
        order=40,
        single_consultant_document=True,
    ),
    OrderClientPolicy(
        key="orlen",
        display_name="Orlen",
        env_var="ORLEN_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_orlen,
        order=50,
        canonical_client_ids=frozenset({35}),
        requires_target=True,
    ),
    OrderClientPolicy(
        key="pfron",
        display_name="PFRON",
        env_var="PFRON_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_pfron,
        order=60,
        canonical_client_ids=frozenset({122}),
        rate_unit_default="hour",
    ),
    OrderClientPolicy(
        key="erste",
        display_name="Erste Bank Polska",
        env_var="ERSTE_GROSS_RATE_CLIENT_IDS",
        apply=_erste,
        order=70,
        rate_unit_default="hour",
        suppressed_by=frozenset({"pfron"}),
    ),
)

_BY_KEY: dict[str, OrderClientPolicy] = {p.key: p for p in POLICIES}


def policy_by_key(key: str) -> OrderClientPolicy:
    return _BY_KEY[key]


def is_client_in_policy(key: str, client_id: Optional[int]) -> bool:
    """Czy klient jest objęty polityką ``key`` (kanoniczne ID ∪ env)."""
    if client_id is None:
        return False
    policy = _BY_KEY[key]
    return client_id in (
        policy.canonical_client_ids | client_ids_from_env(policy.env_var)
    )


def active_policies(client_id: Optional[int]) -> list[OrderClientPolicy]:
    """Polityki, których bramka wpuszcza tego klienta — w kolejności stosowania."""
    return sorted(
        (p for p in POLICIES if is_client_in_policy(p.key, client_id)),
        key=lambda p: p.order,
    )


@dataclass(frozen=True)
class ParsePlan:
    """Jak aktywne polityki kształtują wywołanie ``parse_order_document``."""

    single_consultant_document: bool = False
    rate_unit_default: Optional[str] = None


def parse_plan(policies: list[OrderClientPolicy]) -> ParsePlan:
    single = any(p.single_consultant_document for p in policies)
    unit = next((p.rate_unit_default for p in policies if p.rate_unit_default), None)
    return ParsePlan(single_consultant_document=single, rate_unit_default=unit)


def apply_policies(
    result: OrderExtraction,
    ctx: PolicyContext,
    policies: list[OrderClientPolicy],
) -> tuple[OrderExtraction, list[str]]:
    """Zastosuj polityki po kolei; zwróć wynik i nazwy tych, które zadziałały.

    Nazwy jadą do odpowiedzi jako ``client_policy``. Bez tego niewłączona bramka
    klienta jest NIEWIDOCZNA: odczyt „działa" (model coś wypełnia), a jedynym
    objawem jest numer zamówienia wzięty z niewłaściwego pola — dokładnie objaw
    zgłoszony dla Nordei. Nazwa polityki zamienia cichą różnicę w zdanie, które
    operator widzi przy odczycie.

    ``suppressed_by`` patrzy na polityki AKTYWNE u klienta, nie na te, które
    faktycznie zadziałały: PFRON wyłącza Erste dlatego, że jest włączony u tego
    klienta, a nie dlatego, że akurat coś zmienił w tym dokumencie.
    """
    active_keys = {p.key for p in policies}
    applied: list[str] = []
    for policy in sorted(policies, key=lambda p: p.order):
        if policy.requires_target and not ctx.target_consultant:
            continue
        if policy.suppressed_by & active_keys:
            continue
        applied.append(policy.display_name)
        result = policy.apply(result, ctx)
    return result, applied
