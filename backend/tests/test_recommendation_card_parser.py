"""Parser karty rekomendacji — czysta reguła, dane fikcyjne.

Układy kart odtwarzają to, co rekruterzy wpisują w Traffit i w NEXUSIE
(próba na produkcji 03.10.2026); nazwiska, firmy i treści są zmyślone.
"""

from __future__ import annotations

import time

import pytest

from app.services.recommendation_card_parser import (
    AI_HIDDEN_FIELDS,
    CV_HIDDEN_FIELDS,
    PARSER_VERSION,
    parse_availability,
    parse_card,
    parse_english,
    parse_rate,
    parse_red_flags,
    parse_work_mode,
    parse_worked_at_client,
    redact_card_text,
    to_text,
)

NEW_TEMPLATE_HTML = (
    "<div><p>@Marta Testowa</p>"
    "<p><strong>Imię i nazwisko: </strong>Tomasz Wzorcowy</p>"
    "<p><strong>Stawka</strong>: 135 zł/h netto B2B</p>"
    "<p>Dostępność: 1 miesiąc wypowiedzenia</p>"
    "<p>Tryb pracy: hybrydowo, 2 dni w tygodniu z biura w Łodzi</p>"
    "<p>Lokalizacja: Łódź</p><p>Narodowość: polska</p>"
    "<p>Czy pracował u Klienta? (Jeśli tak, na B2B czy UoP): NIE</p>"
    "<p>Angielski: C1</p><p>Req:</p><p>· ZOB-1234 Senior Java</p>"
    "<p>Nazwa pliku CV: Wzorcowy_Tomasz_B2B.docx</p>"
    "<p>E-mail: tomasz@example.com</p><p>Telefon: 500 000 000</p>"
    "<p>P1: Jakie masz doświadczenie z Javą 17?<br>"
    "Odpowiedź: Java 21 w systemie kredytowym.</p>"
    "<p>P2: Kafka? Tak, do zdarzeń kredytowych od trzech lat w projekcie.</p>"
    "<p>Red flags: brak</p><p>Notatka: Mocny senior z bankowości.</p>"
    "<p>Motywacja: chce pracować z Javą 21.</p></div>"
)

OLD_NORDEA_TEMPLATE = """@Marta Testowa
Imię i nazwisko – Jan Fikcyjny
Stawka. –90zl/h
Dostępność. – miesięczny okres wypowiedzenia
Częstotliwość pracy z biura. – 3x/tyg Gdańsk
Narodowość. – polska
Informacja czy kandydat pracował wcześniej dla Nordea. – Nie
Lokalizacja. – Gdańsk
Request. - NORDEA: Senior Tester (40610)
Numer telefonu i e-mail. – 500 000 000, jan@example.com
Uwagi:
10+ years of testing.
Strong REST API skills.
@Anna Testowa"""


def test_new_template_from_traffit_html():
    card = parse_card(NEW_TEMPLATE_HTML)

    assert card.is_card
    assert card.fields["name"] == {"raw": "Tomasz Wzorcowy"}
    assert card.fields["rate"]["value"] == 135.0
    assert card.fields["availability"]["notice"] == {"value": 1, "unit": "months"}
    assert card.fields["work_mode"] == {
        "raw": "hybrydowo, 2 dni w tygodniu z biura w Łodzi",
        "onsite_days_per_week": 2,
        "mode": "hybrid",
        "office_city": "Łódź",
    }
    assert card.fields["nationality"] == {"raw": "polska"}
    assert card.fields["worked_at_client"]["value"] == "no"
    assert card.fields["english"]["level"] == "C1"
    assert card.fields["project"] == {"raw": "ZOB-1234 Senior Java"}
    assert card.fields["cv_filename"] == {"raw": "Wzorcowy_Tomasz_B2B.docx"}
    assert card.fields["red_flags"] == {"raw": "brak", "none": True}
    assert card.fields["recommendation"] == {"raw": "Mocny senior z bankowości."}
    assert card.fields["motivation"] == {"raw": "chce pracować z Javą 21."}
    assert [(a["number"], a["question"], a["answer"]) for a in card.answers] == [
        (1, "Jakie masz doświadczenie z Javą 17?", "Java 21 w systemie kredytowym."),
        (2, "Kafka?", "Tak, do zdarzeń kredytowych od trzech lat w projekcie."),
    ]


def test_contact_details_never_reach_the_result():
    dumped = str(parse_card(NEW_TEMPLATE_HTML).as_dict())
    dumped += str(parse_card(OLD_NORDEA_TEMPLATE).as_dict())

    assert "example.com" not in dumped
    assert "500 000 000" not in dumped


@pytest.mark.parametrize(
    "text",
    [
        "Stawka: 135\nUwagi: dobry\nMail: jan@example.com\nKontakt: +48 500 000 000",
        "Stawka: 135\nUwagi: dobry\njan.fikcyjny@example.com\n+48 500 000 000",
        "Stawka: 135\nUwagi: dobry\nE-mail prywatny: jan@example.com\nPhone: 500000000",
        "Stawka: 135\nP1: Co robił? Odpowiedź: dobry\nKontakt: 500 000 000",
        "Stawka: 135\nUwagi: dobry\nlinkedin.com/in/jan-fikcyjny-000",
    ],
)
def test_contact_lines_do_not_leak_into_neighbouring_values(text):
    card = parse_card(text)
    values = [value["raw"] for value in card.fields.values()]
    values += [answer["answer"] for answer in card.answers]

    assert "dobry" in values
    assert not any(
        marker in value
        for value in values
        for marker in ("@", "500", "linkedin", "Mail", "Kontakt", "Phone")
    )


@pytest.mark.parametrize(
    "text, key, expected",
    [
        (
            "Stawka: 120\nDostępność: Miesiąc wypowiedzeniaTel: 500 000 000",
            "availability",
            "Miesiąc wypowiedzenia",
        ),
        (
            "Stawka: 120\nNazwa projektu: Analityk\nNumer telefonu i e-mail. 500000000, jan@example.com",
            "project",
            "Analityk",
        ),
        (
            "Stawka: 120\nNazwa projektu: [Bank Fikcyjny] - Analityk",
            "project",
            "[Bank Fikcyjny] - Analityk",
        ),
        ("Stawka: [kwota B2B netto /h]: 110\nDostępność: ASAP", "rate", "110"),
        ("Stawka: 120\nDostępność: ASAPTel: 500 000 000", "availability", "ASAP"),
        (
            "Stawka: 120\nNazwa projektu: Tester (40001)\nTel. + 48 500 000 000",
            "project",
            "Tester (40001)",
        ),
        (
            "Stawka: 120\nNazwa projektu: Tester\nT: 500000000,\nE: jan@example.com",
            "project",
            "Tester",
        ),
        (
            "Stawka: 120\nNazwa projektu: Tester\nE-mal: jan@example.com",
            "project",
            "Tester",
        ),
        (
            "Stawka: 120\nNazwa projektu: Portal Gmail jan@example.com",
            "project",
            "Portal Gmail",
        ),
    ],
)
def test_leftovers_around_the_value(text, key, expected):
    assert parse_card(text).fields[key]["raw"] == expected


def test_contact_written_after_the_name_is_cut():
    card = parse_card(
        "Stawka: 135\nImię i nazwisko: Jan Fikcyjny jan@example.com +48 500 000 000"
    )

    assert card.fields["name"] == {"raw": "Jan Fikcyjny"}


def test_old_template_with_dot_and_dash_separator():
    card = parse_card(OLD_NORDEA_TEMPLATE)

    assert card.fields["name"] == {"raw": "Jan Fikcyjny"}
    assert card.fields["rate"]["value"] == 90.0
    assert card.fields["availability"]["notice"] == {"value": 1, "unit": "months"}
    assert card.fields["work_mode"]["onsite_days_per_week"] == 3
    assert card.fields["work_mode"]["office_city"] == "Gdańsk"
    assert card.fields["worked_at_client"] == {"raw": "Nie", "value": "no"}
    assert card.fields["project"] == {"raw": "NORDEA: Senior Tester (40610)"}
    assert card.fields["recommendation"] == {
        "raw": "10+ years of testing.\nStrong REST API skills."
    }


def test_line_breaks_with_attributes_split_the_fields():
    card = parse_card(
        '<div><p data-start="0"><strong>Stawka:</strong> 130 PLN/h'
        '<br data-start="21" data-end="24"><strong>Dostępność:</strong> dwa tygodnie'
        '<br data-x="1">Angielski: B2</p></div>'
    )

    assert card.fields["rate"]["raw"] == "130 PLN/h"
    assert card.fields["availability"]["notice"] == {"value": 2, "unit": "weeks"}
    assert card.fields["english"]["level"] == "B2"


def test_label_with_a_remark_in_brackets():
    card = parse_card(
        "Imię i Nazwisko: Jan Fikcyjny (po zmianie nazwiska)\n"
        "Narodowość:\n"
        "Lokalizacja (notatka po angielsku o wymiarze hybrydy): Kraków, raz w tygodniu\n"
        "Uwagi (po angielsku):\nExperienced engineer."
    )

    assert card.fields["name"] == {"raw": "Jan Fikcyjny"}
    assert "nationality" not in card.fields
    assert card.fields["location"] == {"raw": "Kraków, raz w tygodniu"}
    assert card.fields["recommendation"] == {"raw": "Experienced engineer."}


def test_empty_label_does_not_take_the_next_unknown_label():
    card = parse_card(
        "Stawka: 120\nNarodowość:\nProfil: Analityk SOC\nLokalizacja: Lublin"
    )

    assert "nationality" not in card.fields
    assert card.fields["location"] == {"raw": "Lublin"}


def test_template_placeholders_are_not_values():
    card = parse_card(
        "Stawka: 130 zł\nNotatka: [dlaczego Kandydat?]\nRed flags: [brak / opis]"
    )

    assert set(card.fields) == {"rate"}


def test_template_hint_before_the_value_is_dropped():
    card = parse_card(
        "Stawka: 120\n"
        "Tryb pracy: [remote/hybrid/onsite, ile dni z biura (Warszawa, Gdynia)] zdalnie"
    )

    assert card.fields["work_mode"] == {"raw": "zdalnie", "mode": "remote"}


def test_numbered_list_of_fields():
    card = parse_card(
        "1. Motywacja – koniec projektu.\n"
        "2. Języki – polski C2, angielski B2.\n"
        "3. Technologia – Python, AWS.\n"
        "5. Miejsce pracy – zdalnie.\n"
        "6. Dostępność – od zaraz.\n"
        "7. Wymiar pracy – pełen etat.\n"
        "8. Oczekiwania finansowe – 90/100zł netto/h"
    )

    assert card.fields["motivation"] == {"raw": "koniec projektu."}
    assert card.fields["english"]["level"] == "B2"
    assert card.fields["work_mode"]["mode"] == "remote"
    assert card.fields["availability"] == {"raw": "od zaraz.", "asap": True}
    assert card.fields["rate"]["value"] == 90.0
    assert card.fields["rate"]["value_max"] == 100.0
    assert card.answers == ()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Pytanie 1\nOpowiedz o projekcie CRM.\nPracowałam przy kilku wdrożeniach.",
            [(1, "Opowiedz o projekcie CRM.", "Pracowałam przy kilku wdrożeniach.")],
        ),
        (
            "Pytanie 1:\nKandydat zna Pythona.\nPytanie 2:\nKandydat zna SQL.",
            [(1, "", "Kandydat zna Pythona."), (2, "", "Kandydat zna SQL.")],
        ),
        (
            "P1: Doświadczenie w testach API\nKandydat ma osiem lat doświadczenia.",
            [
                (
                    1,
                    "Doświadczenie w testach API",
                    "Kandydat ma osiem lat doświadczenia.",
                )
            ],
        ),
        (
            "Pytanie 1: Jakie masz doświadczenie z chmurą?\nPrzy jakich aplikacjach?\n"
            "- Najwięcej AWS i Azure.\nPyt. 2: Kafka?\nOdp.: Tak, trzy lata.",
            [
                (
                    1,
                    "Jakie masz doświadczenie z chmurą? Przy jakich aplikacjach?",
                    "Najwięcej AWS i Azure.",
                ),
                (2, "Kafka?", "Tak, trzy lata."),
            ],
        ),
        (
            "Uwagi:\nSolid backend developer.\n"
            "1. Opowiedz o REST API. Jakie praktyki stosujesz\n- Projektowałem API.\n"
            "2. Czy pisałeś testy w Cucumber?\nTak, integracyjne.",
            [
                (
                    1,
                    "Opowiedz o REST API. Jakie praktyki stosujesz",
                    "Projektowałem API.",
                ),
                (2, "Czy pisałeś testy w Cucumber?", "Tak, integracyjne."),
            ],
        ),
        (
            "Stawka: 90 zł\n"
            "Czy tworzyłeś przypadki testowe od zera na podstawie wymagań?\n"
            "Tak, w ostatnim projekcie.\n"
            "Jakie integracje testowałeś i jak je weryfikowałeś?\nSAP z bazą klientów.",
            [
                (
                    1,
                    "Czy tworzyłeś przypadki testowe od zera na podstawie wymagań?",
                    "Tak, w ostatnim projekcie.",
                ),
                (
                    2,
                    "Jakie integracje testowałeś i jak je weryfikowałeś?",
                    "SAP z bazą klientów.",
                ),
            ],
        ),
    ],
)
def test_question_layouts(text, expected):
    answers = parse_card(text).answers

    assert [(a["number"], a["question"], a["answer"]) for a in answers] == expected


def test_numbered_questions_end_the_recommendation():
    card = parse_card(
        "Uwagi:\nSolid backend developer.\n"
        "1. Opowiedz o REST API.\n- Projektowałem API.\n"
        "2. Czy pisałeś testy?\nTak."
    )

    assert card.fields["recommendation"] == {"raw": "Solid backend developer."}


def test_plain_numbered_list_is_not_a_set_of_questions():
    card = parse_card(
        "Feedback po teście:\n1. Co to jest wzorzec?\n2. Czy volatile jest wymagane?\n"
        "3. Co robi fixed?"
    )

    assert card.answers == ()
    assert not card.is_card


def test_motivation_stops_at_the_next_labelled_line():
    card = parse_card(
        "motywacja: koniec projektu\nprojekty: backend, tech lead\nstawka: 140"
    )

    assert card.fields["motivation"] == {"raw": "koniec projektu"}
    assert card.fields["rate"]["value"] == 140.0


@pytest.mark.parametrize(
    ("raw", "value", "value_max"),
    [
        ("135 zł/h netto B2B", 135.0, None),
        ("125", 125.0, None),
        ("90zl/h", 90.0, None),
        ("87,50", 87.5, None),
        ("120-130", 120.0, 130.0),
        ("90/100zł netto/h", 90.0, 100.0),
        ("140+; do negocjacji", 140.0, None),
        ("120 zł/h (końcowo chce mieć 20 000 po odjęciu składek)", 120.0, None),
        ("125 netto+VAT (+ 2000 na budżet relokacyjny)", 125.0, None),
        ("140 zł/h netto, wcześniej na UoP", 140.0, None),
        ("168,75 (1350 MD)", 168.75, None),
        ("70-100zł/h/brutto", 70.0, 100.0),
    ],
)
def test_hourly_rate_is_read(raw, value, value_max):
    rate = parse_rate(raw)

    assert rate["value"] == value
    assert rate.get("value_max") == value_max
    assert (rate["currency"], rate["period"]) == ("PLN", "h")


@pytest.mark.parametrize(
    "raw",
    [
        "14 000 zł netto",
        "17000 brutto do negocjacji",
        "5500 zł brutto na UoPie (32,78zł/h)",
        "30 000 netto miesięcznie na fakturze",
        "ok. 9 tys miesięcznie na rękę",
        "1200 zł/MD",
        "900/MD",
        "450 EUR/MD",
        "obecnie 220 €/dzień",
        "8 000 - 9000",
        "20-25",
        "35-40 tys. zł",
        "40-45k",
        "35,5k",
        "450 PLN za dzień",
        "400 zł netto za MD",
        "130 na UoP",
        "min. 160h miesięcznie",
        "do ustalenia",
    ],
)
def test_rate_that_would_need_guessing_stays_raw(raw):
    assert parse_rate(raw) == {"raw": raw}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("ASAP", {"asap": True}),
        ("od zaraz", {"asap": True}),
        ("ASAP (wakacje w październiku tydzień)", {"asap": True}),
        ("1 msc", {"notice": {"value": 1, "unit": "months"}}),
        ("2 tygodnie na b2b", {"notice": {"value": 2, "unit": "weeks"}}),
        ("dwa tygodnie", {"notice": {"value": 2, "unit": "weeks"}}),
        ("tydzień od decyzji", {"notice": {"value": 1, "unit": "weeks"}}),
        ("miesięczny okres wypowiedzenia", {"notice": {"value": 1, "unit": "months"}}),
        ("30 dni", {"notice": {"value": 30, "unit": "days"}}),
        (
            "MIESIĄC – MOŻE KRÓCEJ / 2 TYGODNIE",
            {"notice": {"value": 1, "unit": "months"}},
        ),
        ("od 1.07", {"date_text": "1.07"}),
        ("od lutego", {}),
        ("1.5 miesiąca", {"notice": {"value": 6, "unit": "weeks"}}),
        ("1,5 mies", {"notice": {"value": 6, "unit": "weeks"}}),
        ("koniec miesiąca", {}),
        ("półtora miesiąca", {"notice": {"value": 6, "unit": "weeks"}}),
        ("ok. 1–1,5 miesiąca", {"notice": {"value": 6, "unit": "weeks"}}),
        ("2,5 miesiąca", {"notice": {"value": 10, "unit": "weeks"}}),
        ("Gotowy do startu od 02.01.2026", {"date_text": "02.01.2026"}),
        ("od października 1.10", {"date_text": "1.10"}),
        ("od połowy września (czyli od 15.09)", {"date_text": "15.09"}),
        ("spoko rozpocząć 2.01.2026", {"date_text": "2.01.2026"}),
        ("Może rozpocząć od 18 sierpnia (po urlopie do 17.08)", {}),
        ("już zwolniony, formalnie do 31.01", {}),
        ("od połowy stycznia, bo termin porodu na 10.01", {}),
        ("po wakacjach (od 12.07 urlop)", {}),
        (
            "1,5-2 tyg. absolutne minimum tydzień",
            {"notice": {"value": 2, "unit": "weeks"}},
        ),
        ("13 października (28.10 wyjazd na 2,5 tygodnia)", {}),
        ("do końca miesiąca ma wypowiedzenie", {}),
    ],
)
def test_availability(raw, expected):
    assert parse_availability(raw) == {"raw": raw, **expected}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("zdalnie", {"mode": "remote"}),
        ("zdalnie, odbiór sprzętu Wrocław", {"mode": "remote"}),
        ("hybryda ok", {"mode": "hybrid"}),
        (
            "3x/tyg Warszawa",
            {"onsite_days_per_week": 3, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        ("1-2x w tygodniu", {"onsite_days_per_week": 2, "mode": "hybrid"}),
        (
            "2 dni tygodniowo w Warszawie",
            {"onsite_days_per_week": 2, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        ("2 dni z biura", {"onsite_days_per_week": 2, "mode": "hybrid"}),
        ("3 dni onsite", {"onsite_days_per_week": 3, "mode": "hybrid"}),
        (
            "4-6/miesiąc Warszawa",
            {"onsite_days_per_month": 6, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        (
            "2 razy na miesiąc w biurze w Gdyni",
            {"onsite_days_per_month": 2, "mode": "hybrid", "office_city": "Gdynia"},
        ),
        (
            "100% w biurze przez pierwsze 3 tygodnie. Później 1-2 miesięcznie",
            {"onsite_days_per_month": 2, "mode": "hybrid"},
        ),
        ("stacjonarnie, Łódź", {"mode": "onsite", "office_city": "Łódź"}),
        ("według oczekiwań klienta", {}),
        ("hybryda 12 dni w miesiącu", {"onsite_days_per_month": 12, "mode": "hybrid"}),
        ("hybryda 10 dni w miesiącu", {"onsite_days_per_month": 10, "mode": "hybrid"}),
        ("zdalnie, 14 dni w roku w biurze", {"mode": "remote"}),
        (
            "6 dni stacjonarnie - Kraków",
            {"onsite_days_per_month": 6, "mode": "hybrid", "office_city": "Kraków"},
        ),
        (
            "4-6 dni/Warszawa",
            {"onsite_days_per_month": 6, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        ("6 dni w tygodniu z biura w Warszawie", {"office_city": "Warszawa"}),
        ("hybryda, 36 dni on-site / 204 dni off-site", {"mode": "hybrid"}),
        ("Hybryda 23 dni z biura OK", {"mode": "hybrid"}),
        ("10 dni zdalnie, reszta dowolnie", {"mode": "remote"}),
        (
            "Hybryda w przypadku 1/2 spotkań w miesiącu lub remote",
            {"onsite_days_per_month": 2, "mode": "hybrid"},
        ),
        ("hybrydowo (3-2 w biurze)", {"onsite_days_per_week": 3, "mode": "hybrid"}),
        (
            "hybryda: 3 dni zdalnie, 2 w biurze",
            {"onsite_days_per_week": 2, "mode": "hybrid"},
        ),
        ("zdalnie 5 dni w tygodniu", {"mode": "remote"}),
        ("remote, 5 days a week", {"mode": "remote"}),
        ("hybryda 4 dni w tygodniu zdalnie", {"mode": "hybrid"}),
        (
            "zdalnie lub hybrydowo 2 dni w tygodniu",
            {"onsite_days_per_week": 2, "mode": "hybrid"},
        ),
        (
            "100% zdalnie, ewentualnie 1x w miesiącu",
            {"onsite_days_per_month": 1, "mode": "hybrid"},
        ),
        ("zdalnie + 1-2x/miesiąc", {"onsite_days_per_month": 2, "mode": "hybrid"}),
        ("zdalny, max 2 dni w tygodniu", {"onsite_days_per_week": 2, "mode": "hybrid"}),
        ("1 dzień, najchętniej zdalnie", {"onsite_days_per_week": 1, "mode": "hybrid"}),
        (
            "Warszawa 1 w tygodniu max/zdalnie",
            {"onsite_days_per_week": 1, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        (
            "2,3 dni w tyg/Warszawa",
            {"onsite_days_per_week": 3, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        (
            "sporadycznie dojedzie do Warszawy np.1 w msc.",
            {"onsite_days_per_month": 1, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        (
            "6x msc w biurze w Warszawie",
            {"onsite_days_per_month": 6, "mode": "hybrid", "office_city": "Warszawa"},
        ),
        ("hybrydowo (1-3 w biurze)", {"onsite_days_per_week": 3, "mode": "hybrid"}),
        ("zdalna (4-5 dni raz na kwartał z Niemiec)", {"mode": "remote"}),
        ("hybrydowo, ok. 50 dni pracy z biura w trakcie projektu", {"mode": "hybrid"}),
        ("hybrydowo: 36 dni on-site / 204 dni off-site", {"mode": "hybrid"}),
    ],
)
def test_work_mode(raw, expected):
    assert parse_work_mode(raw) == {"raw": raw, **expected}


@pytest.mark.parametrize(
    ("raw", "level"),
    [
        ("C1", "C1"),
        ("b2", "B2"),
        ("B2+", "B2"),
        ("C1/C2 – bardzo dobra komunikacja", "C1"),
        ("polski C2, angielski B2.", "B2"),
        ("polski C2", None),
        ("native", "native"),
        ("fluent", None),
    ],
)
def test_english_level(raw, level):
    assert parse_english(raw).get("level") == level


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("NIE", "no"),
        ("Nie pracował u klienta", "no"),
        ("Tak, B2B, manager z Gdyni", "b2b"),
        ("Pracował na UoP, nie pamięta nazwiska managera", "uop"),
        ("Tak", "yes"),
        ("bezpośrednio nie, przez dostawcę", None),
        ("Nie.", "no"),
        ("nie wiem", None),
        ("Brak informacji", None),
        ("Nie, aktualnie pracuje u klienta na B2B", None),
        ("Nie, ale w UoP tak", None),
        ("Nie – ale kandydat pracował na uop w tym banku", None),
        ("Tak, nie na etacie, tylko B2B", "b2b"),
        ("Tak, najpierw na UoP, potem B2B", "uop"),
        ("Pracował u klienta na UoP, teraz szuka B2B", "uop"),
        ("brak doświadczenia u klienta", "no"),
        ("Na B2B, nie pamięta nazwiska przełożonego", "b2b"),
        ("na UOP", "uop"),
        ("Nigdy", "no"),
        ("nie, ale bardzo by chciał", "no"),
        ("nie (ale żona tam pracuje)", "no"),
        ("nie, był podwykonawcą przez inną firmę", None),
        ("Na jakim poziomie?", None),
    ],
)
def test_worked_at_client(raw, value):
    assert parse_worked_at_client(raw).get("value") == value


@pytest.mark.parametrize(
    ("raw", "none"),
    [
        ("brak", True),
        ("Brak.", True),
        ("-", True),
        ("x", None),
        ("Słaby angielski", None),
    ],
)
def test_red_flags(raw, none):
    assert parse_red_flags(raw).get("none") is none


def test_dash_only_red_flags_line_means_none():
    card = parse_card("Stawka: 110\nRed flags: -\nAngielski: fluent")

    assert card.fields["red_flags"] == {"raw": "-", "none": True}


def test_question_about_past_work_is_not_the_client_field():
    card = parse_card(
        "Stawka: 100\nPytanie 1: Czy pracowałeś z szablonami YAML? Około roku: głównie Helm."
    )

    assert "worked_at_client" not in card.fields
    assert len(card.answers) == 1


def test_free_note_is_not_a_card():
    card = parse_card("<p>Nie odbiera, spróbuję jutro po 16.</p>")

    assert not card.is_card
    assert card.as_dict() == {
        "fields": {},
        "answers": [],
        "labels": [],
        "parser_version": PARSER_VERSION,
    }


def test_to_text_keeps_one_field_per_line():
    assert to_text("<ul><li>Stawka: 100</li><li>Lok:&nbsp;Gdynia</li></ul>") == (
        "Stawka: 100\nLok: Gdynia"
    )


@pytest.mark.parametrize(
    "text",
    [
        "<p " * 6000,
        "czy pracował u klienta? " * 800,
        "Stawka (" * 2500,
        "@" + "a " * 10000,
        "Stawka: 1\n@a" + "." * 19000 + "@",
        "Stawka: 1\n@a b" + "." * 19000 + "@",
        "Uwagi: " + "a" * 19000 + "@",
        "Uwagi: " + "1 " * 9000,
        "1 x " * 5000,
        "\n".join("%d. abc def" % (i % 9 + 1) for i in range(1500)),
    ],
)
def test_hostile_text_is_parsed_quickly(text):
    """Parser pobiegnie w żądaniu zapisu notatki — czas ma zostać liniowy."""
    started = time.perf_counter()
    parse_card(text)

    assert time.perf_counter() - started < 1.0


# ── wejście dla modeli: karta bez pól, których model nie czyta ───────────────


_CARD_FOR_AI = (
    "<p>Imię i nazwisko: Tomasz Wzorcowy</p><p>Stawka: 135 zł/h</p>"
    "<p>Dostępność: 1 miesiąc</p><p>Narodowość: polska</p>"
    "<p>Angielski: C1</p><p>Red flags: długo bez projektu</p>"
    "<p>Notatka: mocny w Springu</p><p>Motywacja: szuka większego projektu</p>"
    "<p>Projekty: bank, telekom</p>"
)


def test_no_model_reads_the_nationality_line():
    text = redact_card_text(_CARD_FOR_AI, AI_HIDDEN_FIELDS)

    assert "Narodowość" not in text and "polska" not in text
    assert "Stawka: 135 zł/h" in text
    assert "Angielski: C1" in text
    assert "Red flags: długo bez projektu" in text


def test_cv_generator_does_not_read_rate_flags_or_motivation():
    text = redact_card_text(_CARD_FOR_AI, CV_HIDDEN_FIELDS)

    for hidden in ("135", "Stawka", "polska", "długo bez projektu", "większego"):
        assert hidden not in text
    assert "Dostępność: 1 miesiąc" in text
    assert "Notatka: mocny w Springu" in text
    # Wiersz z własną etykietą po motywacji to już inne pole — zostaje.
    assert "Projekty: bank, telekom" in text


def test_note_without_hidden_fields_is_returned_unchanged():
    note = "<p>dzwoniłem, zna Javę 21 i Kafkę</p>"
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == note
    assert redact_card_text(None, CV_HIDDEN_FIELDS) == ""


def test_free_text_after_a_single_line_field_survives():
    text = redact_card_text(
        "Stawka: 150\nPracował 5 lat w Javie, ostatnio Spring Boot 3.\nZna Kafkę.",
        CV_HIDDEN_FIELDS,
    )
    assert text == "Pracował 5 lat w Javie, ostatnio Spring Boot 3.\nZna Kafkę."


def test_value_written_under_the_label_is_cut_too():
    text = redact_card_text(
        "Dostępność: ASAP\nNarodowość:\nukraińska\nAngielski: B2", AI_HIDDEN_FIELDS
    )
    assert text == "Dostępność: ASAP\nAngielski: B2"


def test_every_repeated_hidden_label_is_cut():
    text = redact_card_text(
        "Stawka: 150\nDostępność: ASAP\nStawka: 160 po negocjacji", CV_HIDDEN_FIELDS
    )
    assert text == "Dostępność: ASAP"


def test_redaction_is_linear_on_hostile_text():
    hostile = "Stawka: 1\n" + "Narodowość: x\n" * 1500 + "a" * 3000
    started = time.perf_counter()
    redact_card_text(hostile, CV_HIDDEN_FIELDS)
    assert time.perf_counter() - started < 1.0


def test_motivation_does_not_swallow_the_following_dash_labelled_lines():
    note = (
        "Motywacja – projekt jest mało rozwojowy\n"
        "Mocne technologie – Python, PySpark, Databricks\n"
        "Tryb pracy – zdalnie\n"
        "Finanse – 130 PLN do negocjacji"
    )
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == (
        "Mocne technologie – Python, PySpark, Databricks\nTryb pracy – zdalnie"
    )
    assert parse_card(note).fields["motivation"]["raw"] == "projekt jest mało rozwojowy"


def test_hidden_field_in_a_bullet_list_takes_only_its_own_bullet():
    note = (
        "- data scientist i automation\n"
        "- motywacja: ciekawość, nowe technologie\n"
        "- pracuje aktualnie na B2B\n"
        "- zna Pythona i SQL"
    )
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == (
        "- data scientist i automation\n- pracuje aktualnie na B2B\n- zna Pythona i SQL"
    )


def test_red_flags_listed_as_bullets_under_the_label_are_cut():
    note = (
        "Dostępność: ASAP\nRed flags:\n- długo bez projektu\n- częste zmiany pracy\n"
        "Notatka: mocny w Springu"
    )
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == (
        "Dostępność: ASAP\nNotatka: mocny w Springu"
    )


def test_only_the_value_line_is_cut_so_facts_below_survive():
    note = "Motywacja: szuka zmiany\nZna Javę 21 i Kafkę, 5 lat w bankowości."
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == (
        "Zna Javę 21 i Kafkę, 5 lat w bankowości."
    )


@pytest.mark.parametrize(
    "note",
    [
        "Nationality: Ukrainian\nAngielski: C1",
        "Citizenship: UA\nAngielski: C1",
        "Narodowość kandydata: ukraińska\nAngielski: C1",
        "Narodowość ukraińska\nAngielski: C1",
        "<p>Narodowość</p><p>polska</p><p>Angielski: C1</p>",
        "Narodowość/obywatelstwo: polskie\nAngielski: C1",
        "Obywatelstwo:\npolskie\nAngielski: C1",
    ],
)
def test_nationality_is_cut_in_any_spelling(note):
    assert redact_card_text(note, AI_HIDDEN_FIELDS) == "Angielski: C1"


@pytest.mark.parametrize(
    "note",
    [
        "Red flags - nie odbiera\nDostępność: ASAP",
        "Red flags – długo bez projektu\nDostępność: ASAP",
        "Red-flags: brak\nDostępność: ASAP",
        "Motywacja\nszuka zmiany\nDostępność: ASAP",
        "Stawka B2B netto: 140\nDostępność: ASAP",
        "Stawka do klienta: 150\nRate: 140\nExpected rate: 140\nDostępność: ASAP",
        "Stawka kandydata:\n140 zł/h\nDostępność: ASAP",
        "- stawka 150 zł/h, do negocjacji\nDostępność: ASAP",
        "Finanse – 130 PLN\nDostępność: ASAP",
        "Punkty ryzyka: długo bez projektu\nDostępność: ASAP",
    ],
)
def test_commercial_lines_are_cut_in_any_spelling(note):
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == "Dostępność: ASAP"


def test_lines_that_only_mention_the_words_in_prose_survive():
    note = (
        "Pracował w dziale finanse i bankowość – 5 lat\n"
        "Zna rate limiting i międzynarodowy zespół mu nie przeszkadza\n"
        "Projekt: stawki celne w systemie logistycznym"
    )
    assert redact_card_text(note, CV_HIDDEN_FIELDS) == note


def test_hidden_label_beyond_the_parser_window_is_still_cut():
    note = "słowo " * 4000 + "\nNarodowość: polska\nKONIEC"
    text = redact_card_text(note, AI_HIDDEN_FIELDS)
    assert "polska" not in text
    assert text.endswith("KONIEC")


def test_text_after_a_hidden_field_in_a_long_note_is_kept():
    note = "Stawka: 1\n" + "słowo " * 5000 + "\nKONIEC_WAZNY"
    assert redact_card_text(note, CV_HIDDEN_FIELDS).endswith("KONIEC_WAZNY")


def test_redaction_never_raises_on_odd_input():
    assert redact_card_text(123, CV_HIDDEN_FIELDS) == ""  # type: ignore[arg-type]
    assert redact_card_text("", CV_HIDDEN_FIELDS) == ""


@pytest.mark.parametrize(
    "hostile",
    [
        "narodowo" * 2500 + "!",
        "Stawka" + " x" * 9000,
        "\n".join(["Motywacja"] * 3000),
        "- " * 9000 + "narodowość",
    ],
)
def test_line_filters_are_linear_on_hostile_text(hostile):
    started = time.perf_counter()
    redact_card_text(hostile, CV_HIDDEN_FIELDS)
    assert time.perf_counter() - started < 1.0


def test_label_inside_a_paragraph_takes_only_its_sentence():
    note = (
        "Kandydatka z mocnym doświadczeniem w MS SQL i Oracle SQL, dwa lata jako "
        "analityk marketingowy, zainteresowana chmurą, biegle zna angielski. "
        "Oczekiwania finansowe: 28k/msc net. (166 PLN/h net). Projekt może "
        "potraktować jako dodatkowy, zależnie od harmonogramu wdrożenia."
    )
    text = redact_card_text(note, CV_HIDDEN_FIELDS)

    assert "28k" not in text and "166" not in text
    assert text.startswith("Kandydatka z mocnym doświadczeniem w MS SQL")
    assert "Projekt może potraktować jako dodatkowy" in text


def test_rate_at_the_end_of_a_paragraph_does_not_remove_the_paragraph():
    note = (
        "Ponad 10 lat w PHP, pracował przy dużych projektach w branży edukacyjnej "
        "i motoryzacyjnej, zna też Next.js, dostępny od zaraz, lokalizacja Wrocław. "
        "Stawka: 110 zł/h netto, negocjowalne\nAngielski: B1"
    )
    text = redact_card_text(note, CV_HIDDEN_FIELDS)

    assert "110" not in text
    assert text.startswith("Ponad 10 lat w PHP")
    assert text.endswith("Angielski: B1")


def test_nationality_word_in_a_long_paragraph_removes_one_sentence():
    note = (
        "Dużo nie pytali, rozmawiali o doświadczeniu i o tym, jak dokumentowała "
        "ocenę ryzyka w poprzednich projektach dla banku. Z jakimi narodowościami "
        "pracowała. Szukają kogoś z dobrym rozumieniem infrastruktury i chmury."
    )
    text = redact_card_text(note, AI_HIDDEN_FIELDS)

    assert "narodowo" not in text
    assert text.startswith("Dużo nie pytali")
    assert text.endswith("infrastruktury i chmury.")


def test_short_word_before_the_label_goes_with_it():
    assert (
        redact_card_text(
            "Punkty ryzyka: długo bez projektu\nLokalizacja: Warszawa", CV_HIDDEN_FIELDS
        )
        == "Lokalizacja: Warszawa"
    )


# ── Parser v2 (07.10.2026) ─────────────────────────────────────────────────


def test_parser_version_is_two():
    # Zmiana wersji zmienia odcisk notatek — pętla importu przelicza karty.
    assert PARSER_VERSION == 2


@pytest.mark.parametrize(
    ("raw", "value"),
    [
        ("160/115", 115.0),
        ("160 / 115 zł/h", 115.0),
        ("Stawka 150/120 netto", 120.0),
    ],
)
def test_higher_first_slash_pair_is_client_rate_then_candidate(raw, value):
    rate = parse_rate(raw)

    assert rate["value"] == value
    assert "value_max" not in rate
    assert (rate["currency"], rate["period"]) == ("PLN", "h")


def test_higher_first_pair_in_a_card_reads_the_candidate_rate():
    card = parse_card("Stawka: 160/115\nDostępność: ASAP")

    assert card.fields["rate"]["value"] == 115.0


def test_dash_range_written_higher_first_keeps_v1_reading():
    # Myślnik to widełki, nie para „klient/kandydat” — v1 bez zmian.
    assert parse_rate("140-120")["value"] == 140.0


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            "Pytanie 1: Czy znasz Kafkę? Tak\n"
            "Pytanie 2: Czy znasz Kubernetes? Nie",
            [
                (1, "Czy znasz Kafkę?", "Tak"),
                (2, "Czy znasz Kubernetes?", "Nie"),
            ],
        ),
        (
            "1. Czy używasz Kafki? tak, 2 lata\n"
            "2. Ile lat pracujesz z Javą? 8",
            [
                (1, "Czy używasz Kafki?", "tak, 2 lata"),
                (2, "Ile lat pracujesz z Javą?", "8"),
            ],
        ),
        (
            "1. Jak wygląda Twoje doświadczenie\n"
            "z testami automatycznymi w projekcie?\n"
            "Selenium i Playwright.\n"
            "2. Czy pracowałeś w metodyce Scrum?\n"
            "Tak, cztery lata.",
            [
                (
                    1,
                    "Jak wygląda Twoje doświadczenie "
                    "z testami automatycznymi w projekcie?",
                    "Selenium i Playwright.",
                ),
                (2, "Czy pracowałeś w metodyce Scrum?", "Tak, cztery lata."),
            ],
        ),
    ],
)
def test_v2_question_layouts(text, expected):
    answers = parse_card(text).answers

    assert [(a["number"], a["question"], a["answer"]) for a in answers] == expected


def test_bare_questions_wrapped_over_two_lines_are_glued():
    answers = parse_card(
        "Stawka: 120\n"
        "Jak oceniasz swoje doświadczenie z testami\n"
        "wydajnościowymi w JMeter?\n"
        "Dobrze, dwa projekty.\n"
        "Czy pracowałeś z bazami danych Oracle na produkcji?\n"
        "Tak, w banku."
    ).answers

    assert [(a["question"], a["answer"]) for a in answers] == [
        (
            "Jak oceniasz swoje doświadczenie z testami wydajnościowymi w JMeter?",
            "Dobrze, dwa projekty.",
        ),
        (
            "Czy pracowałeś z bazami danych Oracle na produkcji?",
            "Tak, w banku.",
        ),
    ]


def test_note_after_question_mark_is_not_an_answer():
    answers = parse_card(
        "Pytanie 1: Czy znasz Kafkę? (wymagane)\nPytanie 2: Opisz projekt? Jakie role"
    ).answers

    assert [a["answer"] for a in answers] == ["", ""]
