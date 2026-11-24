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
    #: Reguła „włącz / wyłącz” bez poziomu: na ekranie przełącznik, w bazie
    #: ``block`` (włączona) albo ``off``.
    switch: bool = False


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
            Rule(
                "proof.accept_has_hours",
                "Prośba o akceptację podaje liczbę godzin lub MD za miesiąc",
                "off",
                "E6.1",
                hint="Liczba musi być w treści maila do akceptującego. Przy prośbach "
                "nadpisywanych co miesiąc liczy się akceptacja za rozliczany miesiąc; "
                "akceptować może ktoś inny niż koordynator.",
            ),
            Rule(
                "report.consultant_declaration",
                "Deklaracja konsultanta w treści maila wystarcza jako raport",
                "off",
                "E6.7",
                hint="Klient bez pliku godzin: „We wrześniu nie miałam dni wolnych” "
                "z adresu konsultanta daje MD = dni robocze miesiąca, „miałam 2 dni "
                "wolnego” — dni robocze minus 2. Zdanie bez nazwy miesiąca, za inny "
                "miesiąc albo bez liczby dni idzie do Finansów. Wystarczy włączyć; "
                "poziom nie zmienia odczytu.",
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
                "order.auto_accept_clean",
                "Przyjmuj RCP bez uwag automatycznie",
                "off",
                "F1",
                {"workday": "3"},
                (ParamField("workday", "od", "dnia roboczego następnego miesiąca"),),
                "Co rano w dzień roboczy NEXUS przyjmuje RCP „Bez uwag” tak jak "
                "„Przyjmij RCP bez uwag”. RCP po „Do poprawy” zostaje dla Finansów.",
                switch=True,
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
            Rule(
                "fields.md_month_limit",
                "MD osoby w miesiącu nie więcej niż dni robocze",
                "warn",
                "E6.2",
                hint="Więcej MD to zwykle zapis za dwóch klientów. Wyłącz, gdy osoba "
                "realizuje u klienta kilka projektów i miesięczny limit nie obowiązuje.",
            ),
        ),
    ),
    Section(
        "extra",
        "Nadgodziny i dyżury",
        (
            Rule(
                "extra.mail_accept",
                "Mail akceptujący nadgodziny",
                "block",
                "E2",
                {"domain": ""},
                (ParamField("domain", "z domeny", "np. bnpparibas.pl"),),
                "Domena nadawcy zgody — dokładnie, bez poddomen; kilka po przecinku.",
            ),
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
        "Delegacje i koszty dodatkowe",
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
            Rule(
                "travel.extra_costs_confirm",
                "Koszty dodatkowe potwierdza osoba rozliczająca klienta",
                "warn",
                "E6.3",
                hint="Nie blokuje automatycznie: zanim NEXUS oznaczy koszt dodatkowy "
                "jako błąd albo go odrzuci, potwierdza to osoba rozliczająca klienta.",
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
            Rule(
                "ci.sale_date",
                "Data sprzedaży = ostatni dzień rozliczanego miesiąca",
                "off",
                "E6.6",
                hint="Z treści faktury w KSeF (P_6 albo koniec okresu; bez P_6 data "
                "wystawienia). Treść NEXUS pobiera po przypięciu faktury do kontraktu, "
                "zwykle w ciągu godziny; do tego czasu „nie sprawdzono”.",
            ),
            Rule(
                "ci.item_month",
                "Nazwa pozycji bez innego miesiąca niż rozliczany",
                "off",
                "E6.6",
                hint="Szuka nazw miesięcy i zapisów 10.2026 / 2026-10 w nazwach pozycji. "
                "Nazwa bez miesiąca przechodzi.",
            ),
            Rule(
                "ci.payment_form",
                "Płatność przelewem, faktura bez „Zapłacono”",
                "off",
                "E6.6",
                hint="Błąd: znacznik zapłaty, forma inna niż przelew (gotówka, karta…) "
                "albo brak formy płatności i numeru rachunku.",
            ),
        ),
    ),
    Section(
        "payment",
        "Zapłata kontraktorowi",
        (
            Rule(
                "pay.after_client_signature",
                "Zapłata po podpisie klienta na dokumencie osoby",
                "off",
                "E6.3",
            ),
            Rule(
                "pay.mail_accept_fallback",
                "Mail z akceptacją zastępuje podpis, gdy podpisujący jest nieobecny",
                "off",
                "E6.3",
                hint="Tylko gdy nie ma zastępstwa; podpisany dokument sprawdzamy później. "
                "Finanse zaznaczają to na karcie osoby.",
            ),
            Rule(
                "pay.per_person",
                "Zapłata po podpisanym dokumencie osoby, bez czekania na pozostałe",
                "off",
                "E6.2",
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
                {"months": "12", "deadline": ""},
                (
                    ParamField("months", "miesiące", "np. 12"),
                    ParamField("deadline", "plan do", "np. 04.12"),
                ),
                "Plan przyjmujemy po przyjęciu poprzedniego miesiąca, nie ponad resztę puli; "
                "mniej przepracowane schodzi na kolejnej fakturze.",
            ),
            Rule(
                "cl.extra_costs_on_invoice",
                "Koszty dodatkowe na fakturze głównej",
                "off",
                "E6.3",
                {"item": ""},
                (ParamField("item", "osobna pozycja"),),
                "Puste = doliczone do pozycji głównej, nazwa = osobna pozycja.",
            ),
            Rule(
                "cl.client_document",
                "Dokument do podpisu klienta z NEXUS-a",
                "off",
                "E6.2",
                {"kind": "", "per": "", "from": "", "header": ""},
                (
                    ParamField(
                        "kind", "rodzaj", "np. protokół, arkusz, potwierdzenie usług"
                    ),
                    ParamField("per", "na", "projekt / podpisujący / cały miesiąc"),
                    ParamField("from", "od miesiąca", "RRRR-MM"),
                    ParamField("header", "nagłówek", "np. załącznik do umowy"),
                ),
                "Każdy dokument do pobrania osobno, żeby wysłać go od razu, gdy jest gotowy. "
                "„Podpisujący”: arkusz zbiorczy na osobę podpisującą u klienta (menedżer "
                "u klienta z kontraktu). „Cały miesiąc”: jeden protokół na wszystkie osoby.",
            ),
            Rule(
                "cl.protocol_amount",
                "Kwota do faktury taka jak w protokole klienta",
                "off",
                "E6",
                hint="Protokół klienta z kwotą netto (Orlen): kwota rozliczenia, która idzie "
                "na fakturę (MD × stawka z zamówienia), musi być równa kwocie z protokołu. "
                "Finanse Orlenu odsyłają fakturę z inną kwotą do korekty albo do nowego PO.",
            ),
            Rule(
                "cl.copyright_statement",
                "Oświadczenie o prawach autorskich za miesiąc przed fakturą",
                "off",
                "E6",
                hint="Centrum e-Zdrowia: każda osoba co miesiąc, osobno na każdą umowę "
                "wykonawczą, oświadczenie o przeniesieniu autorskich praw majątkowych na "
                "wzorze CeZ, z okresem od 01.MM do 30/31.MM, podpisane po końcu miesiąca. "
                "Plik rozpoznajemy po nazwie albo treści; brak, inny okres, podpis przed "
                "końcem miesiąca i nagłówek „Wzór” dają uwagę.",
            ),
            Rule(
                "cl.cost_mail_block",
                "Blok kosztów projektu do maila do automatu klienta",
                "off",
                "E6",
                {"vendor": ""},
                (ParamField("vendor", "dostawca", "nazwa jak w mailu klienta"),),
                "Przy dokumencie na projekt: „Kopiuj blok ESP” z etapem, projektem, "
                "zamówieniem, miesiącem, MD i kwotą netto w walucie faktury.",
            ),
            Rule(
                "cl.after_signed_document",
                "Faktura do klienta po podpisanym dokumencie",
                "off",
                "E6.3",
                hint="KEŚU (E6.3): „Do faktury” dopiero po drugim podpisie w odesłanym "
                "pliku. PKO (E6.1): po podpisanym zbiorczym protokole, Velo (E6.2): po "
                "podpisanych arkuszach wszystkich osób. Dokument na cały miesiąc czeka "
                "na wszystkie osoby. Wstrzymuje też szkic w „Wystaw za miesiąc” "
                "(faktura z NEXUSA).",
            ),
            Rule(
                "cl.send_to",
                "Adres wysyłki paczki do klienta",
                "off",
                "E6.1",
                {"email": ""},
                (ParamField("email", "adres"),),
                "Dokument z podpisami, dowody pracy i akceptacje w jednym mailu.",
            ),
            Rule(
                "cl.client_acceptance",
                "Klient akceptuje dowody pracy mailem po zbiorczej wysyłce",
                "off",
                "E6.5",
                {"email": "", "subject": "KCP B2Bnetwork {miesiac} {rok}"},
                (
                    ParamField("email", "adres klienta"),
                    ParamField("subject", "temat", "{miesiac} {rok}"),
                ),
                "Bank Pocztowy: KCP zbieramy i wysyłamy paczką; odpowiedź z domeny adresu "
                "w wątku paczki akceptuje wysłane osoby poza wymienionymi jako brakujące. "
                "Z „Faktura do klienta po podpisanym dokumencie” faktura osoby czeka na "
                "jej akceptację.",
            ),
            Rule(
                "cl.item_name",
                "Opis pozycji faktury do klienta według wzoru",
                "off",
                "E6.5",
                {"template": ""},
                (ParamField("template", "wzór", "{zamowienie}, {osoba}"),),
                "Wygrywa z nazwą z poprzedniej faktury. Pola: {zamowienie} — numer "
                "zamówienia, {osoba} — imię i nazwisko, {rola} — tytuł pozycji "
                "zamówienia (stanowisko), {usluga} — nazwa usługi z ustawień "
                "wystawiania, {miesiac} — miesiąc usługi. Działa też w szkicu "
                "faktury z NEXUSA.",
            ),
            Rule(
                "cl.orders_together",
                "Kilka zamówień na jednej fakturze z NEXUSA",
                "off",
                "F2",
                hint="„Wystaw za miesiąc”: zaznaczone zamówienia klienta w tej samej "
                "walucie idą jedną fakturą, każda osoba osobną pozycją z numerem "
                "swojego zamówienia, a wszystkie numery trafiają do KSeF "
                "(NrZamowienia). Inna waluta albo inny nabywca = osobna faktura.",
                switch=True,
            ),
            Rule(
                "cl.ksef_contract",
                "Numer umowy w KSeF (NrUmowy)",
                "off",
                "F2",
                {"number": "", "date": ""},
                (
                    ParamField("number", "numer umowy"),
                    ParamField("date", "z dnia", "RRRR-MM-DD, można pominąć"),
                ),
                "Trafia do warunków transakcji każdej faktury z NEXUSA.",
                switch=True,
            ),
            Rule(
                "cl.ksef_fields",
                "Pola dodatkowe w KSeF (DodatkowyOpis)",
                "off",
                "F2",
                {"key": "", "value": "", "key2": "", "value2": ""},
                (
                    ParamField("key", "klucz", "np. OSOBA"),
                    ParamField("value", "wartość", "tekst albo {zamowienie}"),
                    ParamField("key2", "klucz 2"),
                    ParamField("value2", "wartość 2"),
                ),
                "Para klucz–wartość w fakturze z NEXUSA, obok „Uwagi” ze szkicu. "
                "{zamowienie} = numery zamówień faktury. Pusta wartość = pole pominięte.",
                switch=True,
            ),
            Rule(
                "cl.item_must_contain",
                "Opis każdej pozycji faktury zawiera tekst",
                "off",
                "F2",
                {"text": ""},
                (ParamField("text", "tekst", "np. JIRA"),),
                "Sprawdza szkic faktury z NEXUSA: „blokuje” wstrzymuje wysyłkę do "
                "KSeF, „ostrzega” tylko pokazuje uwagę. Numery (np. zgłoszeń JIRA) "
                "dopisuje się w opisie pozycji szkicu.",
            ),
            Rule(
                "cl.invoice_mail",
                "Faktura mailem do klienta obok KSeF",
                "off",
                "F2",
                {
                    "email": "",
                    "subject": "",
                    "email_eu": "",
                    "subject_eu": "",
                    "attach": "PDF faktury",
                },
                (
                    ParamField("email", "adres"),
                    ParamField("subject", "temat", "{numer} {ksef} {m} {mm} {rrrr}"),
                    ParamField("email_eu", "adres dla serii UE"),
                    ParamField("subject_eu", "temat dla serii UE"),
                    ParamField("attach", "załącz", "np. PDF faktury, TS"),
                ),
                "Karta faktury z NEXUSA podaje adres i gotowy temat: {numer} — numer "
                "faktury, {ksef} — numer KSeF, {m}/{mm}/{rrrr} — miesiąc usługi, "
                "{zamowienie} — numery zamówień. Seria UE bierze adres i temat UE, gdy "
                "są wpisane. Maila wysyła osoba z Finansów.",
                switch=True,
            ),
            Rule(
                "cl.bzone_order",
                "Faktura tylko ze zleceniem B-ZONE na okres",
                "off",
                "F2",
                hint="ERSTE: każdy dzień roboczy pracy osoby w miesiącu faktury musi "
                "być w okresie zamówienia klienta z numerem K/RRRR/nr/inicjały/nr/kod "
                "(zlecenie miesięczne albo kwartalne, może być kilka). Bez zlecenia "
                "„Wystaw za miesiąc” nie tworzy szkicu, a szkic nie idzie do KSeF.",
                switch=True,
            ),
            Rule(
                "cl.client_protocol",
                "Ostrzeżenie: faktura przed protokołem odbioru od klienta",
                "off",
                "F2",
                hint="Centrum e-Zdrowia: szkic faktury ostrzega, gdy wśród dokumentów "
                "miesiąca osoby nie ma protokołu odbioru od klienta (PDF z domeny klienta "
                "albo odesłany przez PM-a w wątku z klientem) z tym miesiącem i umową "
                "osoby w treści. Fakturę można wysłać mimo ostrzeżenia.",
                switch=True,
            ),
        ),
    ),
    Section(
        "client_report",
        "Raport klienta (T4T)",
        (
            Rule(
                "report.time_for_teams",
                "Raport godzin od klienta (Time for Teams) porównany z fakturą kontraktora",
                "off",
                "N1",
                {"warn_days": "5"},
                (
                    ParamField(
                        "warn_days",
                        "ostrzeżenie",
                        "dni przed terminem faktury (15. dnia następnego miesiąca)",
                    ),
                ),
                hint="Włączona daje podzakładkę „Raport klienta (T4T)”: wersje raportu od "
                "klienta, kartoteka numerów osób i status każdej osoby w miesiącu. "
                "Liczą się tylko godziny w statusie 2 (Approved). „Do faktury dla "
                "klienta” bierze godziny zatwierdzone w ostatniej wersji raportu, "
                "a godziny niezatwierdzone wstrzymują pozycję osoby.",
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
                    "switch": rule.switch,
                }
                for rule in section.rules
            ],
        }
        for section in SECTIONS
    ]
