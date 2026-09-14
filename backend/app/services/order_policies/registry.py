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
from app.services.order_pdf_parser import ConsultantOrderRow, OrderExtraction
from app.services.order_policies import (
    alior,
    bank_pocztowy,
    bik,
    cardif,
    credit_agricole,
    kir,
    mleasing,
    nordea,
    pko_bp,
    polkomtel,
    velobank,
)


@dataclass(frozen=True)
class PolicyContext:
    """To, co polityka może potrzebować poza samym wynikiem odczytu."""

    document_text: str
    target_consultant: Optional[str] = None
    target_given_names: Optional[str] = None
    filename: Optional[str] = None
    #: Reguła działa ponownie na ZAPISANYM odczycie („Przelicz plan"), a nie na
    #: świeżej odpowiedzi modelu — wiersze wejściowe mogą być jej własnym wynikiem.
    reapplied: bool = False


PolicyFn = Callable[[OrderExtraction, PolicyContext], OrderExtraction]
RowsFn = Callable[[str], list[ConsultantOrderRow]]
RateRulesFn = Callable[[OrderExtraction, str], Optional[OrderExtraction]]


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
    #: Deterministyczny ekstraktor wierszy osób z tekstu (bez modelu). Bramka
    #: automatu porównuje z nim wiersze modelu; harness korpusu używa go jako
    #: źródła wierszy w trybie bez LLM. Brak = klient bez tabeli osób.
    extract_rows: Optional[RowsFn] = None
    #: Zamówienie klienta jest z definicji BEZTERMINOWE (BIK): brak daty końca
    #: jest poprawnym odczytem, a nie niepełnym okresem. Bramka automatu nie
    #: odsyła go do kolejki, a formularze dostają jawne „bezterminowo".
    open_ended_period: bool = False
    #: Zamówienie MD klienta kończy się WYŁĄCZNIE wyczerpaniem limitów MD
    #: wszystkich konsultantów (``order_md_exhaustion``), nie datą.
    closes_on_md_exhaustion: bool = False
    #: Ręczny odczyt oddaje całą tabelę osób (``consultant_rows``) — formularz
    #: zamówienia wieloosobowego pokazuje ją i uzupełnia z niej linie.
    exposes_consultant_rows: bool = False
    #: Tabela osób z PDF-a jest źródłem prawdy w KAŻDEJ ścieżce (Nordea, Alior):
    #: formularze czytają wszystkie osoby tak jak mail (parser all-rows, osobę
    #: wybiera polityka), a „Przelicz plan" stosuje regułę ponownie na zapisanym
    #: odczycie — inaczej dokument sprzed poprawki reguły zostawałby w kolejce
    #: z powodami, których reguła już nie generuje.
    table_authoritative: bool = False
    #: „Przelicz plan" stosuje regułę klienta ponownie na zapisanym odczycie,
    #: BEZ przełączania parsera w tryb all-rows (to robi ``table_authoritative``
    #: i zmienia formularze). PKO BP: reguła prostuje nazwisko z doklejonym
    #: profilem w odczycie zapisanym przed poprawką.
    reapply_on_refresh: bool = False
    #: Reguła rodzaju stawki klienta w miejsce uniwersalnego rozpoznania
    #: brutto/netto z dokumentu (Nordea: netto/h, Alior: netto, jawne „brutto" →
    #: weryfikacja; BIK: netto z nagłówka tabeli). Reguła może oddać decyzję
    #: (``None``) — wtedy, jak u klienta bez reguły, rozstrzyga oznaczenie w PDF-ie.
    rate_rules: Optional[RateRulesFn] = None
    #: Wersja reguły odczytu. Dokument zapamiętuje wersje, którymi go przeczytano
    #: (``document_meta["rule_versions"]``); po jej zmianie dokumenty klienta
    #: czekające w kolejce przeliczają się SAME, raz, przy najbliższym biegu
    #: skrzynki (``order_mail_ingest.replan_outdated_documents``). Bez tego
    #: poprawka reguły działała wyłącznie dla nowych maili, a wpis sprzed
    #: wdrożenia wisiał ze starymi powodami do ręcznego „Przelicz plan" (Alior,
    #: 09.2026). ZMIEŃ wersję przy każdej zmianie reguły, która może zmienić
    #: werdykt dokumentu; ``None`` = bez automatycznego przeliczania.
    rule_version: Optional[str] = None


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
    text = nordea.order_text_only(ctx.document_text)
    result = parser.enforce_nordea_order_number(result, text)
    return nordea.apply_nordea_layout(
        result,
        text,
        target_consultant=ctx.target_consultant,
        target_given_names=ctx.target_given_names,
    )


def _bank_pocztowy(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    result = parser.apply_bank_pocztowy_order_policy(result, ctx.document_text)
    return bank_pocztowy.apply_bank_pocztowy_layout(result, ctx.document_text)


def _credit_agricole(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    result = parser.apply_credit_agricole_order_policy(result, ctx.document_text)
    return credit_agricole.apply_credit_agricole_layout(result, ctx.document_text)


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
    return parser.apply_pfron_order_policy(
        result, ctx.document_text, filename=ctx.filename
    )


def _erste(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return parser.apply_erste_order_policy(result, ctx.document_text)


def _pko_bp(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return pko_bp.apply_pko_bp_order_policy(result, ctx.document_text)


def _kir(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return kir.apply_kir_order_policy(result, ctx.document_text)


def _mleasing(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return mleasing.apply_mleasing_order_policy(result, ctx.document_text)


def _velobank(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return velobank.apply_velobank_order_policy(result, ctx.document_text)


def _alior(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return alior.apply_alior_order_policy(
        result,
        ctx.document_text,
        target_consultant=ctx.target_consultant,
        target_given_names=ctx.target_given_names,
        reapplied=ctx.reapplied,
    )


def _polkomtel(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return polkomtel.apply_polkomtel_order_policy(
        result,
        ctx.document_text,
        target_consultant=ctx.target_consultant,
        target_given_names=ctx.target_given_names,
    )


def _cyfrowy_polsat(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return polkomtel.apply_cyfrowy_polsat_order_number(result, ctx.document_text)


def _nordea_rate_rules(result: OrderExtraction, text: str) -> OrderExtraction:
    return nordea.apply_rate_rules(result)


def _cardif(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return cardif.apply_cardif_order_policy(result, ctx.document_text)


def _bik(result: OrderExtraction, ctx: PolicyContext) -> OrderExtraction:
    return bik.apply_bik_order_policy(
        result,
        ctx.document_text,
        target_consultant=ctx.target_consultant,
        target_given_names=ctx.target_given_names,
    )


# ── Rejestr ──────────────────────────────────────────────────────────────────

POLICIES: tuple[OrderClientPolicy, ...] = (
    OrderClientPolicy(
        key="nordea",
        display_name="Nordea",
        env_var="NORDEA_ORDER_NUMBER_CLIENT_IDS",
        apply=_nordea,
        order=10,
        rate_unit_default="hour",
        extract_rows=nordea.extract_rows,
        exposes_consultant_rows=True,
        table_authoritative=True,
        rate_rules=_nordea_rate_rules,
    ),
    OrderClientPolicy(
        key="bank_pocztowy",
        display_name="Bank Pocztowy",
        env_var="BANK_POCZTOWY_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_bank_pocztowy,
        order=20,
        extract_rows=bank_pocztowy.extract_rows,
    ),
    OrderClientPolicy(
        key="credit_agricole",
        display_name="Credit Agricole",
        env_var="CREDIT_AGRICOLE_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_credit_agricole,
        order=30,
        extract_rows=credit_agricole.extract_rows,
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
        extract_rows=parser.pfron_extract_rows,
        rate_unit_default="hour",
    ),
    OrderClientPolicy(
        key="erste",
        display_name="Erste Bank Polska",
        env_var="ERSTE_GROSS_RATE_CLIENT_IDS",
        apply=_erste,
        order=70,
        # Dzienna, nie godzinowa — „23,00 dni roboczych x 1 426,80 PLN BRUTTO".
        rate_unit_default="day",
        suppressed_by=frozenset({"pfron"}),
        extract_rows=parser.erste_extract_rows,
    ),
    # ── Polityki z korpusu 09.2026 (ticket mailowy) ──────────────────────
    OrderClientPolicy(
        key="pko_bp",
        display_name="PKO BP",
        env_var="PKO_BP_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_pko_bp,
        order=110,
        rate_unit_default="day",
        extract_rows=pko_bp.extract_rows,
        rate_rules=pko_bp.apply_rate_rules,
        reapply_on_refresh=True,
        # 09.2026: nazwisko bez doklejonego profilu, stawka zawsze netto.
        rule_version="2026-09-14",
    ),
    OrderClientPolicy(
        key="kir",
        display_name="KIR",
        env_var="KIR_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_kir,
        order=120,
        rate_unit_default="hour",
        extract_rows=kir.extract_rows,
    ),
    OrderClientPolicy(
        key="mleasing",
        display_name="mLeasing",
        env_var="MLEASING_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_mleasing,
        order=130,
        extract_rows=mleasing.extract_rows,
    ),
    OrderClientPolicy(
        key="velobank",
        display_name="VeloBank",
        env_var="VELOBANK_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_velobank,
        order=140,
        rate_unit_default="day",
        extract_rows=velobank.extract_rows,
    ),
    OrderClientPolicy(
        key="alior",
        display_name="Alior",
        env_var="ALIOR_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_alior,
        order=150,
        rate_unit_default="day",
        extract_rows=alior.extract_rows,
        table_authoritative=True,
        rate_rules=alior.apply_rate_rules,
        # 09.2026: cztery pola z PDF, netto z definicji, zapisany odczyt modelu.
        rule_version="2026-09-10",
    ),
    OrderClientPolicy(
        key="cardif",
        display_name="Cardif",
        env_var="CARDIF_ORDER_EXTRACTION_CLIENT_IDS",
        apply=_cardif,
        order=160,
        rate_unit_default="day",
        extract_rows=cardif.extract_rows,
    ),
    # Kanoniczne ID 18 = BIK z ticketu korekty 29.08.2026 (to samo, które
    # przypina ``order_types._PINNED_ALLOWED_ORDER_TYPES``). Env dopisuje
    # kontrolowany duplikat w innym środowisku.
    OrderClientPolicy(
        key="bik",
        display_name="BIK",
        env_var=bik.CLIENT_IDS_ENV,
        apply=_bik,
        order=170,
        canonical_client_ids=bik.CANONICAL_CLIENT_IDS,
        rate_unit_default="day",
        extract_rows=bik.extract_rows,
        open_ended_period=True,
        closes_on_md_exhaustion=True,
        exposes_consultant_rows=True,
        rate_rules=bik.apply_rate_rules,
    ),
    # Kanoniczne ID 15 = Polkomtel (``finance_order_matching.POLKOMTEL_CLIENT_ID``).
    # Zamówienie kosztowe albo MD, zawsze bezterminowe: koniec wyznacza
    # wyczerpanie kwoty (kosztowe) albo MD (per osoba lub wspólnej puli).
    OrderClientPolicy(
        key="polkomtel",
        display_name="Polkomtel",
        env_var=polkomtel.CLIENT_IDS_ENV,
        apply=_polkomtel,
        order=180,
        canonical_client_ids=polkomtel.CANONICAL_CLIENT_IDS,
        rate_unit_default="day",
        extract_rows=polkomtel.extract_rows,
        open_ended_period=True,
        closes_on_md_exhaustion=True,
        exposes_consultant_rows=True,
        rate_rules=polkomtel.apply_rate_rules,
    ),
    # Ten sam szablon „Zlecenie wykonawcze nr CP … / rok" — wyłącznie reguła
    # numeru. Cyfrowy Polsat ma też zamówienia okresowe, więc okres i stawki
    # zostają przy odczycie ogólnym.
    OrderClientPolicy(
        key="cyfrowy_polsat",
        display_name="Cyfrowy Polsat",
        env_var=polkomtel.CYFROWY_POLSAT_CLIENT_IDS_ENV,
        apply=_cyfrowy_polsat,
        order=190,
        canonical_client_ids=polkomtel.CYFROWY_POLSAT_CANONICAL_CLIENT_IDS,
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
    all_rows: bool = False


def parse_plan(policies: list[OrderClientPolicy]) -> ParsePlan:
    single = any(p.single_consultant_document for p in policies)
    # Tie-break: pierwsza polityka w kolejności ``order`` wygrywa. Gdyby PFRON
    # (60) i Erste (70) były aktywne u jednego klienta, obowiązuje jednostka
    # PFRON-u — spójnie z ``suppressed_by``, przez które PFRON wyłącza Erste.
    ordered = sorted(policies, key=lambda p: p.order)
    unit = next((p.rate_unit_default for p in ordered if p.rate_unit_default), None)
    return ParsePlan(
        single_consultant_document=single,
        rate_unit_default=unit,
        all_rows=any(p.table_authoritative for p in policies),
    )


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

    Lista jest sortowana TUTAJ, choć ``active_policies`` już ją sortuje: funkcja
    jest publiczna i dostaje listy także spoza niej (harness korpusu, ścieżka
    mailowa po rozpoznaniu klienta). Kontrakt „kolejność = ``order``" ma
    trzymać się niezależnie od tego, kto zbudował listę.
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


def prepare_document_text(text: str, policies: list[OrderClientPolicy]) -> str:
    """Zakres dokumentu wspólny dla modelu, reguł i kontroli deterministycznej."""
    if any(p.key == "nordea" for p in policies):
        return nordea.order_text_only(text)
    return text


def apply_rate_kind(
    result: OrderExtraction, text: str, policies: list[OrderClientPolicy]
) -> OrderExtraction:
    """Klient z własną regułą rodzaju stawki jej używa; reszta — dowodu z PDF-a.

    Nordea: zawsze netto za godzinę. Alior: netto z definicji, jawne „brutto" →
    weryfikacja. PKO BP: kolumna „Stawka PLN/MD netto" — zawsze netto. BIK dowodzi netto nagłówkiem tabeli („Wart.netto" / „netto bez
    VAT") — ogólne rozpoznanie szuka etykiety przy KWOCIE stawki, a w sklejonym
    tekście z SAP-a („1.200,00", „wynosi1200,-zł/MD") jej nie widzi i oznaczało
    każdą pozycję jako niepewną; bez tego nagłówka BIK oddaje decyzję (``None``).
    """
    for policy in sorted(policies, key=lambda p: p.order):
        if policy.rate_rules is not None:
            ruled = policy.rate_rules(result, text)
            if ruled is not None:
                return ruled
    return parser.apply_document_rate_kind(result, text)


def reapplies_on_refresh(policies: list[OrderClientPolicy]) -> bool:
    """Czy „Przelicz plan" stosuje reguły klienta ponownie na zapisanym odczycie."""
    return any(p.table_authoritative or p.reapply_on_refresh for p in policies)


def rule_versions(policies: list[OrderClientPolicy]) -> dict[str, str]:
    """Wersje reguł odczytu aktywnych u klienta — znacznik zapisywany na dokumencie."""
    return {p.key: p.rule_version for p in policies if p.rule_version}


def closes_on_md_exhaustion(client_id: Optional[int]) -> bool:
    """Czy zamówienia MD klienta kończy wyczerpanie limitów, a nie data (BIK)."""
    return any(p.closes_on_md_exhaustion for p in active_policies(client_id))


def md_exhaustion_client_ids() -> frozenset[int]:
    """Wszyscy klienci, których zamówienia MD kończy wyczerpanie limitów."""
    ids: set[int] = set()
    for policy in POLICIES:
        if policy.closes_on_md_exhaustion:
            ids |= policy.canonical_client_ids | client_ids_from_env(policy.env_var)
    return frozenset(ids)


def open_ended_period(policies: list[OrderClientPolicy]) -> bool:
    """Czy brak daty końca jest u tego klienta poprawnym odczytem."""
    return any(p.open_ended_period for p in policies)


def prepare_parser_text(text: str, policies: list[OrderClientPolicy]) -> str:
    """Kolumny ignorowane przez klienta nie są przekazywane do modelu."""
    if any(p.key == "nordea" for p in policies):
        return nordea.parser_text(text)
    return text
